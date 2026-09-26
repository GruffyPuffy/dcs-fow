#!/usr/bin/env python3
"""Run the second-generation FoW campaign service and web shell."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
from threading import Event, Lock, Thread
import time
from typing import Any
from urllib.parse import urlsplit

from .campaign import ActionPlan, AlgorithmicGeneral, CampaignEngine, CampaignState, Side, load_scenario
from .dcs import CampaignExecutor, DcsClient, DcsGateway, ManualOperations
from .dcs.awareness import Awareness, distance_m
from scripts import dcs_structures
from .runtime import RuntimeCheckpoint


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DEFAULT_SCENARIO = ROOT / "scenarios" / "caucasus_pve.json"
DEFAULT_CHECKPOINT = ROOT.parent / "data" / "fow-runtime.json"
SLOT_CATALOG = ROOT / "assets" / "slot_catalog.json"


class FoWService:
    def __init__(self, scenario_path: Path, dcs_gateway: DcsGateway,
                 clock=time.monotonic, wall_clock=time.time,
                 checkpoint_path: Path | None = None):
        self.scenario = load_scenario(scenario_path)
        self.engine = CampaignEngine(self.scenario)
        self.dcs = dcs_gateway
        self.manual = ManualOperations(dcs_gateway)
        self.executor = CampaignExecutor(self.scenario, dcs_gateway)
        self.awareness = Awareness()
        self._clock = clock
        self._wall_clock = wall_clock
        self._checkpoint = RuntimeCheckpoint(checkpoint_path) if checkpoint_path else None
        self._lock = Lock()
        self._campaign: CampaignState | None = None
        self._generals = self._new_generals()
        self._deployments: list[dict[str, Any]] = []
        self._income_interval = self.scenario.economy.income_interval_seconds
        self._next_income_at: float | None = None
        self._next_decision_at: float | None = None
        self._last_dcs_mission_id: str | None = None
        # Player requests from the F10 radio menu, awaiting the general's
        # approval. Each entry: {id, side, action, target, requested_at}.
        self._player_requests: list[dict[str, Any]] = []
        self._last_menu_event_id = 0
        # Intel messages already sent to Blue (dedup by key).
        self._sent_intel: set[str] = set()
        self._restore()

    def _new_generals(self) -> dict[Side, AlgorithmicGeneral]:
        economy = self.scenario.economy
        return {
            side: AlgorithmicGeneral(
                side, self.engine, economy.general_seed, economy.general_reserve,
                opening_endowment=(
                    economy.red_opening_endowment if side == Side.RED else 0))
            for side in Side
        }

    def slot_unlocks(self) -> dict[str, str]:
        """Base name -> controlling objective id for catalog slots."""
        return self.scenario.mission_slot_unlocks()

    def catalog_slot_names(self) -> dict[str, list[str]]:
        """Slot names per base from the universal slot catalog."""
        catalog = json.loads(SLOT_CATALOG.read_text())
        names = {}
        for base in catalog["bases"]:
            entries = []
            for entry in catalog["fixed_wing"] + catalog["helicopters"]:
                for index, start in enumerate(entry["starts"]):
                    name = f"FoW {base['name']} {entry['label']} {start.title()}"
                    if index:
                        name = f"{name} {index + 1}"
                    entries.append(name)
            names[base["name"]] = entries
        return names

    def _apply_slot_access(self) -> None:
        """Open catalog slots at bases whose controlling objective is Blue-owned."""
        if self._campaign is None:
            return
        unlocks = self.slot_unlocks()
        names = self.catalog_slot_names()
        enabled = []
        for base, objective_id in unlocks.items():
            objective_state = self._campaign.objectives.get(objective_id)
            if objective_state and objective_state.owner == Side.BLUE:
                enabled.extend(names.get(base, []))
        if enabled:
            self.dcs.set_slot_access(enabled, True)

    def new_game(self, income_interval_seconds: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._campaign is not None:
                return self._campaign.as_dict()
            # Optional per-campaign override of the scenario's income interval,
            # mainly for faster testing rounds.
            self._income_interval = (max(30, int(income_interval_seconds))
                                     if income_interval_seconds
                                     else self.scenario.economy.income_interval_seconds)
            self._campaign = self.engine.new_game()
            self._generals = self._new_generals()
            self._deployments = []
            jobs = []
            for side in Side:
                for choice in self._generals[side].opening_actions(self._campaign):
                    plan = self.engine.apply_action(
                        self._campaign, side, choice.action, choice.target)
                    sequence = len(self._campaign.events)
                    jobs.append((plan, sequence))
                    self._deployments.append(self._deployment(plan, sequence))
            self._next_income_at = self._clock() + self._income_interval
            self._next_decision_at = self._clock() + AlgorithmicGeneral.decision_interval_seconds
            self.engine.settle_opening_endowment(self._campaign)
            self._save_locked()
        self._execute_jobs(jobs)
        self._apply_slot_access()
        self._register_radio_menu()
        with self._lock:
            return self._campaign.as_dict()

    def _register_radio_menu(self) -> None:
        """Add the FoW F10 menu for Blue: request JTAC support per objective."""
        try:
            for objective in self.scenario.objectives.values():
                if objective.kind != "zone":
                    continue
                self.dcs.add_radio_command(
                    2, f"Request JTAC - {objective.label}",
                    ["FoW"], f"jtac:{objective.id}")
        except (OSError, RuntimeError, ValueError):
            pass  # DCS offline; retried on next campaign start

    def tick(self, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        self._reconcile_deployments()
        self._update_awareness()
        jobs = []
        with self._lock:
            if self._campaign is None or self._next_income_at is None:
                return
            changed = False
            # Income still accrues on the (configurable) income interval.
            while now >= self._next_income_at:
                changed = True
                self.engine.collect_income(self._campaign)
                self._next_income_at += self._income_interval
            # Generals decide on their own minute cadence, rate-limited by the
            # spending bucket, so they can burst on reactions but must pace
            # themselves afterwards.
            if self._next_decision_at is None:
                self._next_decision_at = now + AlgorithmicGeneral.decision_interval_seconds
            while now >= self._next_decision_at:
                elapsed = AlgorithmicGeneral.decision_interval_seconds
                for side in Side:
                    general = self._generals[side]
                    general.accrue(elapsed)
                    # Hand pending player requests to the general for approval.
                    general.pending_requests = [
                        request for request in self._player_requests
                        if request["side"] == side.value and request["status"] == "pending"]
                    choice = self._generals[side].choose_action(self._campaign)
                    if choice:
                        plan = self.engine.apply_action(
                            self._campaign, side, choice.action, choice.target)
                        # A CAP bought as a free AWACS escort is doctrine, not
                        # an expense: refund the cost immediately.
                        if general.free_escort and choice.action == "cap":
                            self._campaign.resources[side] += plan.cost
                            general.free_escort = False
                        sequence = len(self._campaign.events)
                        jobs.append((plan, sequence))
                        self._deployments.append(self._deployment(plan, sequence))
                        # Tactical comms: announce Blue orders to Blue players.
                        if side == Side.BLUE:
                            self._announce_order(plan)
                        # Mark matching player requests as approved.
                        for request in self._player_requests:
                            if (request["side"] == side.value
                                    and request["status"] == "pending"
                                    and request["action"] == choice.action
                                    and request["target"] == choice.target):
                                request["status"] = "approved"
                self._next_decision_at += AlgorithmicGeneral.decision_interval_seconds
                changed = True
            if changed:
                self._save_locked()
        self._execute_jobs(jobs)

    def _update_awareness(self) -> None:
        """Consume the latest DCS snapshot: tracks, kills, capture flips."""
        snapshot = self.dcs.public_snapshot()
        if snapshot is None:
            return
        self.awareness.update_tracks(snapshot)
        with self._lock:
            if self._campaign is None:
                return
            # Consume F10 menu selections into the player request queue.
            for event in snapshot.get("menu_events", []):
                event_id = int(event.get("id", 0))
                if event_id <= self._last_menu_event_id:
                    continue
                self._last_menu_event_id = event_id
                command_id = str(event.get("command_id", ""))
                if command_id.startswith("jtac:"):
                    objective_id = command_id.split(":", 1)[1]
                    if objective_id in self.scenario.objectives:
                        self._player_requests.append({
                            "id": event_id,
                            "side": "blue",
                            "action": "jtac",
                            "target": objective_id,
                            "status": "pending",
                        })
            # Report live support flights (AWACS/tanker) to each general so it
            # can replace losses and escort the AWACS, plus live ground group
            # counts for the force cap.
            for side in Side:
                # A support flight counts as live only while AIRBORNE. A
                # landed AWACS (station time over, shot on approach) sitting
                # on the ramp must not block its replacement.
                airborne_names = {
                    group.get("name") for group in snapshot.get("groups", [])
                    if group.get("units") and any(
                        (unit.get("y") or 0) > 100 for unit in group["units"])}
                self._generals[side].live_support = {
                    deployment["action"] for deployment in self._deployments
                    if deployment["side"] == side.value
                    and deployment["action"] in ("awacs", "tanker", "cap")
                    and deployment["status"] == "active"
                    and set(deployment.get("names", [deployment["name"]]))
                    & airborne_names
                }
                self._generals[side].live_ground_groups = sum(
                    1 for group in snapshot.get("groups", [])
                    if group.get("coalition") == (1 if side == Side.RED else 2)
                    and group.get("category") == 2 and group.get("units")
                    # Only offensive groups count against the cap; garrisons
                    # are the opening posture, not runaway spawning.
                    and " Assault " in str(group.get("name", "")))
                # Objectives this side is already assaulting (active assault
                # deployments) - blocks stacking a second package on one zone.
                self._generals[side].live_assault_targets = {
                    deployment["target"] for deployment in self._deployments
                    if deployment["side"] == side.value
                    and deployment["action"] == "assault"
                    and deployment["status"] == "active"
                    and deployment["target"] in self.scenario.objectives}
                # Live air deployment counts for the air caps: total and per
                # type. Only deployments whose groups still exist in DCS count.
                air_deployments = [
                    deployment for deployment in self._deployments
                    if deployment["side"] == side.value
                    and deployment["action"] in ("cap", "cas", "sead", "strike",
                                                 "awacs", "tanker")
                    and deployment["status"] == "active"
                    and set(deployment.get("names", [deployment["name"]])) & airborne_names]
                self._generals[side].live_air_total = len(air_deployments)
                self._generals[side].live_air_by_type = {
                    action: sum(1 for d in air_deployments
                                if d["action"] == action)
                    for action in ("cap", "cas", "sead", "strike", "awacs", "tanker")}
            presence = self.awareness.objective_presence(self.scenario, snapshot)
            coalition_of = {Side.RED: 1, Side.BLUE: 2}
            enemy = {Side.BLUE: Side.RED, Side.RED: Side.BLUE}
            for side in Side:
                self._generals[side].confirmed_enemy_troops = {
                    objective_id for objective_id, counts in presence.items()
                    if counts.get(coalition_of[enemy[side]], 0) > 0}

            flips = self.engine.evaluate_capture(self._campaign, presence)
            # Reactive triggers: an objective we own with enemy ground present
            # is threatened; one we just lost is a counter-attack target.
            # Presence counts are keyed by DCS coalition id (1=red, 2=blue).
            enemy = {Side.BLUE: Side.RED, Side.RED: Side.BLUE}
            coalition_of = {Side.RED: 1, Side.BLUE: 2}
            enemy = {Side.BLUE: Side.RED, Side.RED: Side.BLUE}
            for side in Side:
                general = self._generals[side]
                enemy_coalition = coalition_of[enemy[side]]
                general.threatened = {
                    objective_id for objective_id, counts in presence.items()
                    if self._campaign.objectives[objective_id].owner == side
                    and counts.get(enemy_coalition, 0) > 0}
                general.lost = {
                    flip["objective"] for flip in flips if flip["to"] == enemy[side].value}
                # Enemy assaults in progress drive counter-doctrine - but
                # only what this side can SEE. An assault is visible when its
                # target has confirmed enemy ground presence (the fight is
                # observable). Reacting to the enemy's order the same round
                # it was issued would be omniscience, not command.
                observable = {objective_id for objective_id, counts in
                              presence.items()
                              if counts.get(coalition_of[enemy[side]], 0) > 0}
                general.enemy_assaults = {
                    deployment["target"] for deployment in self._deployments
                    if deployment["side"] == enemy[side].value
                    and deployment["action"] == "assault"
                    and deployment["status"] == "active"
                    and deployment["target"] in self.scenario.objectives
                    and deployment["target"] in observable}
            if flips:
                self._apply_slot_access()
                self._reposition_support(flips)
                self._save_locked()
            self._strike_confirmed_troops(snapshot, presence)
            self._retask_close_aircraft(snapshot, presence)
            self._send_intel(flips, presence)
            self._announce_takeoffs(snapshot)

    def _announce_takeoffs(self, snapshot: dict) -> None:
        """Tactical comms: announce Blue flights as they take off (first seen
        airborne with altitude). One message per deployment."""
        for deployment in self._deployments:
            if (deployment["side"] != "blue"
                    or deployment["action"] not in ("cap", "cas", "sead",
                                                    "strike", "awacs", "tanker")
                    or deployment.get("announced_takeoff")):
                continue
            for group in snapshot.get("groups", []):
                if group.get("name") not in deployment.get("names", []):
                    continue
                unit = next((u for u in group.get("units", [])
                             if (u.get("y") or 0) > 100), None)
                if unit is None:
                    continue
                deployment["announced_takeoff"] = True
                objective = self.scenario.objectives[deployment["target"]]
                try:
                    self.dcs.message(
                        f"[FoW] {deployment['action'].upper()} airborne - "
                        f"tasking: {objective.label}", 2, 15)
                except (OSError, RuntimeError, ValueError):
                    pass
                break

    def _reposition_support(self, flips: list[dict]) -> None:
        """AWACS controller: when territory near a support racetrack changes
        hands, reposition the flight away from the front. The racetrack is
        shifted toward the side's home objective."""
        snapshot = self.dcs.public_snapshot()
        if snapshot is None:
            return
        live = {group.get("name"): group for group in snapshot.get("groups", [])
                if group.get("units")}
        for deployment in self._deployments:
            if (deployment["action"] not in ("awacs", "tanker")
                    or deployment["status"] != "active"):
                continue
            if not any(name in live for name in deployment.get("names", [])):
                continue
            station = self.scenario.air_stations.get(
                Side(deployment["side"]), {}).get(deployment["action"])
            if not station:
                continue
            # If any flipped objective is within 60 km of the racetrack,
            # pull the station 40 km toward the side's home objective.
            home = next((obj for obj in self.scenario.objectives.values()
                         if obj.initial_owner == Side(deployment["side"])), None)
            if home is None:
                continue
            for flip in flips:
                objective = self.scenario.objectives[flip["objective"]]
                near = any(
                    distance_m(objective.lat, objective.lon, wp[0], wp[1]) < 60_000
                    for wp in station.waypoints)
                if not near:
                    continue
                # Shift both waypoints 40 km toward home.
                shifted = []
                for wp in station.waypoints:
                    bearing = dcs_structures.initial_bearing(
                        wp[0], wp[1], home.lat, home.lon)
                    shifted.append(dcs_structures.offset_position(
                        wp[0], wp[1], 40_000 * math.cos(bearing),
                        40_000 * math.sin(bearing)))
                group_name = next(
                    name for name in deployment.get("names", []) if name in live)
                lead = live[group_name]["units"][0]
                route = dcs_structures.build_racetrack_route(
                    lead["lat"], lead["lon"], shifted[0], shifted[1],
                    9000 if deployment["action"] == "awacs" else 8000, 180,
                    "AWACS" if deployment["action"] == "awacs" else "tanker")
                try:
                    self.dcs.set_route(group_name, route)
                except (OSError, RuntimeError, ValueError):
                    pass  # DCS offline or group gone; next flip retries
                break

    def _strike_confirmed_troops(self, snapshot: dict, presence: dict) -> None:
        """Put arriving strike/CAS flights onto real targets: when a flight
        is near its tasked objective and enemy troops are confirmed there,
        task an AttackGroup on the nearest live enemy group (re-attacks until
        destroyed or weapons/fuel out). Bombing the zone center does nothing
        when the defenders are 1 km from the point."""
        for deployment in self._deployments:
            if (deployment["action"] not in ("cas", "strike")
                    or deployment["status"] != "active"
                    or deployment.get("strike_tasked")):
                continue
            names = [n for n in deployment.get("names", [deployment["name"]])
                     if n in {g.get("name") for g in snapshot.get("groups", [])
                              if g.get("units")}]
            if not names:
                continue
            flight = next((g for g in snapshot["groups"] if g["name"] == names[0]), None)
            if flight is None or not flight.get("units"):
                continue
            lead = flight["units"][0]
            objective = self.scenario.objectives[deployment["target"]]
            if distance_m(lead.get("lat", 0), lead.get("lon", 0),
                          objective.lat, objective.lon) > 4000:
                continue  # not arrived yet
            enemy_coalition = 1 if deployment["side"] == "blue" else 2
            enemy_groups = [
                g for g in snapshot.get("groups", [])
                if g.get("coalition") == enemy_coalition
                and g.get("category") == 2 and g.get("units")
                and distance_m(g["units"][0].get("lat", 0),
                               g["units"][0].get("lon", 0),
                               objective.lat, objective.lon) <= 3500]
            if not enemy_groups:
                continue  # nothing confirmed yet; try again next tick
            target = min(
                enemy_groups,
                key=lambda g: distance_m(
                    g["units"][0].get("lat", 0), g["units"][0].get("lon", 0),
                    objective.lat, objective.lon))
            task = dcs_structures.build_strike_task(
                objective.lat, objective.lon, target["name"])
            try:
                self.dcs.set_task(names[0], task)
            except (OSError, RuntimeError, ValueError):
                continue
            deployment["strike_tasked"] = target["name"]
            try:
                self.dcs.message(
                    f"[FoW] {deployment['name']} engaging troops at "
                    f"{objective.label}", 2, 15)
            except (OSError, RuntimeError, ValueError):
                pass

    def _retask_close_aircraft(self, snapshot: dict, presence: dict) -> None:
        """Dynamic battlefield response: when an objective has confirmed enemy
        troops, redirect nearby CAS/strike flights (with ground-attack
        weapons) to orbit it. Urgent targets beat the original tasking - a
        flight already in the air is the fastest fire support available."""
        from scripts.dcs_structures import build_route_update
        hot = {objective_id for objective_id, counts in presence.items()
               if counts.get(1, 0) > 0 or counts.get(2, 0) > 0}
        if not hot:
            return
        for deployment in self._deployments:
            if (deployment["action"] not in ("cas", "strike")
                    or deployment["status"] != "active"
                    or deployment.get("retasked_for") == deployment["target"]):
                continue
            names = [n for n in deployment.get("names", [deployment["name"]])
                     if n in {g.get("name") for g in snapshot.get("groups", [])
                              if g.get("units")}]
            if not names:
                continue
            # Find a hot objective closer than the current target.
            flight = next((g for g in snapshot["groups"] if g["name"] == names[0]), None)
            if flight is None or not flight.get("units"):
                continue
            lead = flight["units"][0]
            current = self.scenario.objectives[deployment["target"]]
            current_distance = distance_m(lead.get("lat", 0), lead.get("lon", 0),
                                          current.lat, current.lon)
            best = None
            for objective_id in hot:
                if objective_id == deployment["target"]:
                    continue
                objective = self.scenario.objectives[objective_id]
                d = distance_m(lead.get("lat", 0), lead.get("lon", 0),
                               objective.lat, objective.lon)
                if d < current_distance * 0.7 and (best is None or d < best[1]):
                    best = (objective_id, d)
            if best is None:
                continue
            objective_id, _ = best
            objective = self.scenario.objectives[objective_id]
            # Real strike tasking: attack the confirmed enemy group nearest
            # the hot objective (AttackGroup re-attacks until the target is
            # destroyed or weapons/fuel run out); Bombing on the coordinates
            # as fallback when no live group is mapped.
            enemy_groups = [
                g for g in snapshot.get("groups", [])
                if g.get("coalition") == (1 if deployment["side"] == "blue" else 2)
                and g.get("category") == 2 and g.get("units")
                and distance_m(g["units"][0].get("lat", 0),
                               g["units"][0].get("lon", 0),
                               objective.lat, objective.lon) <= 3500]
            target_group = None
            if enemy_groups:
                target_group = min(
                    enemy_groups,
                    key=lambda g: distance_m(
                        g["units"][0].get("lat", 0), g["units"][0].get("lon", 0),
                        objective.lat, objective.lon))["name"]
            task = dcs_structures.build_strike_task(
                objective.lat, objective.lon, target_group)
            try:
                self.dcs.set_task(names[0], task)
            except (OSError, RuntimeError, ValueError):
                continue
            deployment["retasked_for"] = objective_id
            try:
                self.dcs.message(
                    f"[FoW] {deployment['name']} redirected - troops at "
                    f"{objective.label}", 2, 15)
            except (OSError, RuntimeError, ValueError):
                pass

    def _send_intel(self, flips: list[dict], presence: dict) -> None:
        """Balanced intel to Blue players: what Blue's own forces do, plus
        enemy activity only where Blue could plausibly see it (its own
        objectives under attack, lost ground). Never full enemy truth."""
        def tell(key: str, text: str) -> None:
            if key in self._sent_intel:
                return
            self._sent_intel.add(key)
            try:
                self.dcs.message(text, 2, 20)
            except (OSError, RuntimeError, ValueError):
                pass
        for flip in flips:
            objective = self.scenario.objectives[flip["objective"]]
            if flip["to"] == "blue":
                tell(f"capture:{flip['objective']}",
                     f"[FoW] {objective.label} captured. Slots opened.")
            else:
                tell(f"lost:{flip['objective']}",
                     f"[FoW] We lost {objective.label}! Enemy counter-attack likely.")
        # Blue's own objectives with enemy ground = visible contact.
        for objective_id in self._generals[Side.BLUE].threatened:
            objective = self.scenario.objectives[objective_id]
            tell(f"threat:{objective_id}",
                 f"[FoW] Enemy ground forces at {objective.label}!")
        # Contested objectives: the fight for a base is on - hold or lose it.
        contested = {objective_id: state for objective_id, state
                     in self._campaign.objectives.items()
                     if state.contested_since is not None}
        for objective_id in contested:
            objective = self.scenario.objectives[objective_id]
            tell(f"contested:{objective_id}",
                 f"[FoW] {objective.label} is CONTESTED - fight for control!")
        # Red assaults are only reported when Blue has eyes on the target
        # (its own adjacent objective is threatened) - not every Red move.
        for deployment in self._deployments:
            if (deployment["side"] != "red" or deployment["action"] != "assault"
                    or deployment["status"] != "active"):
                continue
            target = deployment["target"]
            if target in self._generals[Side.BLUE].threatened:
                objective = self.scenario.objectives[target]
                tell(f"assault:{deployment['sequence']}",
                     f"[FoW] Intel: Red assault on {objective.label} in progress!")

    def _deployment(self, plan, sequence: int) -> dict[str, Any]:
        return {
            "name": self.executor.name_for(plan, sequence),
            "names": self.executor.names_for(plan, sequence),
            "status": "waiting",
            "error": "Awaiting DCS reconciliation",
            "side": plan.side.value,
            "action": plan.action,
            "target": plan.target,
            "sequence": sequence,
            "waypoints": self._mission_waypoints(plan.side, plan.action, plan.target),
        }

    def _mission_waypoints(self, side: Side, action: str, target: str) -> list[dict[str, Any]]:
        if action == "reinforce":
            return []
        objective = self.scenario.objectives[target]
        station = self.scenario.air_stations.get(side, {}).get(action)
        if station:
            # Strike/SEAD/CAS orbit the TARGET, not a fixed map racetrack -
            # the same rule the executor uses. The displayed route matches
            # where the flight actually goes.
            if action in ("strike", "sead", "cas"):
                positions = [(objective.lat, objective.lon)]
            else:
                positions = station.waypoints
            # Final leg: RTB to the launch base (nearest friendly airbase),
            # labeled with the base name - the flight lands there, not at
            # the target.
            launch = self.dcs.public_snapshot()
            base_name, base_pos = None, None
            if launch:
                coalition = 2 if side == Side.BLUE else 1
                candidates = [ab for ab in launch.get("airbases", [])
                              if ab.get("coalition") == coalition]
                if candidates:
                    base = min(candidates, key=lambda ab: distance_m(
                        ab.get("lat", 0), ab.get("lon", 0),
                        objective.lat, objective.lon))
                    base_name, base_pos = base.get("name"), (base.get("lat"), base.get("lon"))
            # Flight-plan naming like a real kneeboard: WP 1, WP 2, TGT 3,
            # RTB 4 (the landing base).
            waypoints = [
                {"lat": position[0], "lon": position[1],
                 "label": f"WP {index + 1}"}
                for index, position in enumerate(positions)
            ]
            if base_pos:
                waypoints.append({"lat": base_pos[0], "lon": base_pos[1],
                                  "label": f"RTB {base_name}"})
            else:
                waypoints.append({"lat": objective.lat, "lon": objective.lon,
                                  "label": f"RTB {objective.label}"})
            return waypoints
        return [{
            "lat": objective.lat,
            "lon": objective.lon,
            "label": f"{objective.label} {action.upper()}",
        }]

    def _announce_order(self, plan) -> None:
        """Tactical comms: tell Blue players what their general just ordered."""
        objective = self.scenario.objectives[plan.target]
        labels = {
            "assault": f"Ground assault launched on {objective.label}.",
            "reinforce": f"Reinforcements moving to {objective.label}.",
            "cap": f"CAP flight scrambling - {objective.label}.",
            "cas": f"CAS flight inbound - {objective.label}.",
            "sead": f"SEAD flight inbound - {objective.label}.",
            "strike": f"Strike flight inbound - {objective.label}.",
            "awacs": f"AWACS launching - {objective.label}.",
            "tanker": f"Tanker launching - {objective.label}.",
            "jtac": f"JTAC team deploying to {objective.label}.",
        }
        text = labels.get(plan.action)
        if text:
            try:
                self.dcs.message(f"[FoW] {text}", 2, 15)
            except (OSError, RuntimeError, ValueError):
                pass

    def _execute_jobs(self, jobs: list[tuple]) -> None:
        for plan, sequence in jobs:
            with self._lock:
                state = self._campaign
            if state is None:
                return
            result = self.executor.execute(plan, sequence, state)
            result.update({
                "side": plan.side.value,
                "action": plan.action,
                "target": plan.target,
                "sequence": sequence,
            })
            with self._lock:
                existing = next((item for item in self._deployments
                                 if item["sequence"] == sequence), None)
                if existing is None:
                    self._deployments.append(result)
                else:
                    existing.update(result)
                # A failed deployment wasted the credits it cost (DCS could
                # not place the groups). Refund so a bad spawn spot does not
                # silently burn the general's budget.
                if result.get("status") == "failed":
                    self._campaign.resources[plan.side] += plan.cost
                snapshot = self.dcs.public_snapshot()
                if snapshot:
                    self._last_dcs_mission_id = snapshot["mission_id"]
                self._save_locked()

    def _reconcile_deployments(self) -> None:
        snapshot = self.dcs.public_snapshot()
        if snapshot is None:
            return
        mission_id = snapshot["mission_id"]
        groups = {group.get("name") for group in snapshot.get("groups", [])
                  if group.get("units")}
        with self._lock:
            mission_changed = (self._last_dcs_mission_id is not None
                               and self._last_dcs_mission_id != mission_id)
            changed = self._last_dcs_mission_id != mission_id
            jobs = []
            for deployment in self._deployments:
                expected = set(deployment.get("names", [deployment["name"]]))
                if expected <= groups:
                    if deployment["status"] != "active" or deployment.get("error") is not None:
                        deployment.update(status="active", error=None)
                        changed = True
                elif deployment["status"] == "waiting" or mission_changed:
                    action = self.scenario.actions[deployment["action"]]
                    plan = ActionPlan(
                        deployment["action"], Side(deployment["side"]),
                        deployment["target"], action.cost, action.package)
                    deployment.update(status="waiting", error="Rehydrating in DCS")
                    jobs.append((plan, deployment["sequence"]))
                    changed = True
                elif deployment["action"] in ("cap", "cas", "sead", "strike",
                                              "awacs", "tanker"):
                    # Air cycle: a flight that was active and is now gone was
                    # shot down or landed after its station time. Relaunch it
                    # from its base so the air war keeps running.
                    action = self.scenario.actions[deployment["action"]]
                    plan = ActionPlan(
                        deployment["action"], Side(deployment["side"]),
                        deployment["target"], action.cost, action.package)
                    deployment.update(status="waiting", error="Relaunching air cycle")
                    jobs.append((plan, deployment["sequence"]))
                    changed = True
            self._last_dcs_mission_id = mission_id
            if changed:
                self._save_locked()
        self._execute_jobs(jobs)

    def _restore(self) -> None:
        if self._checkpoint is None:
            return
        data = self._checkpoint.load()
        if data is None:
            return
        if data.get("scenario_id") != self.scenario.id:
            raise ValueError("Runtime checkpoint belongs to a different scenario")
        self._campaign = CampaignState.from_dict(data["campaign"])
        if set(self._campaign.objectives) != set(self.scenario.objectives):
            raise ValueError("Runtime checkpoint objectives do not match the scenario")
        self._deployments = list(data.get("deployments", []))
        for deployment in self._deployments:
            deployment["waypoints"] = self._mission_waypoints(
                Side(deployment["side"]), deployment["action"], deployment["target"])
        self._last_dcs_mission_id = data.get("last_dcs_mission_id")
        if isinstance(data.get("awareness"), dict):
            self.awareness.restore(data["awareness"])
        self._next_income_at = self._clock() + max(
            0, float(data["next_income_at_epoch"]) - self._wall_clock())
        for side, general in self._generals.items():
            general.restore(data["generals"][side.value])

    def _save_locked(self) -> None:
        if self._checkpoint is None or self._campaign is None:
            return
        remaining = max(0, (self._next_income_at or self._clock()) - self._clock())
        self._checkpoint.save({
            "scenario_id": self.scenario.id,
            "campaign": self._campaign.as_dict(),
            "generals": {
                side.value: general.state_dict()
                for side, general in self._generals.items()
            },
            "deployments": self._deployments,
            "next_income_at_epoch": self._wall_clock() + remaining,
            "last_dcs_mission_id": self._last_dcs_mission_id,
            "awareness": self.awareness.state_dict(),
        })

    def overview(self) -> dict[str, Any]:
        snapshot = self.dcs.public_snapshot()
        with self._lock:
            campaign = self._campaign.as_dict() if self._campaign else None
            legal_actions = {
                side.value: [
                    {
                        "action": plan.action,
                        "target": plan.target,
                        "cost": plan.cost,
                        "package": plan.package,
                    }
                    for plan in self.engine.legal_actions(self._campaign, side)
                ]
                for side in self._campaign.resources
            } if self._campaign else {"blue": [], "red": []}
            presence = (self.awareness.objective_presence(self.scenario, snapshot)
                        if snapshot and self._campaign else None)
        return {
            "campaign": campaign,
            "scenario": self.scenario.as_public_dict(),
            "legal_actions": legal_actions,
            "dcs": self.dcs.public_status(),
            "presence": presence,
            "generals": {
                "policy": "seeded_algorithm",
                "reserve": self.scenario.economy.general_reserve,
                "income_interval_seconds": self._income_interval,
                "next_income_seconds": max(0, round(self._next_income_at - self._clock()))
                if self._next_income_at is not None else None,
                "decisions": {
                    side.value: general.decision_log[-20:]
                    for side, general in self._generals.items()
                },
            },
            "deployments": list(self._deployments),
            "player_requests": list(self._player_requests),
            "persistence": {
                "enabled": self._checkpoint is not None,
                "status": "runtime checkpoint" if self._checkpoint else "disabled",
            },
        }

    def debug_status(self) -> dict[str, Any]:
        return {
            **self.dcs.public_status(),
            "snapshot": self.dcs.public_snapshot(),
        }

    def debug_catalogs(self) -> dict[str, Any]:
        return self.manual.catalogs()

    def debug_spawn(self, kind: str, request: dict) -> dict[str, Any]:
        result = (self.manual.spawn_air(request) if kind == "air"
                  else self.manual.spawn_ground(request))
        if result["reply"].get("ok") is not True:
            raise RuntimeError(result["reply"].get("error", "DCS rejected spawn"))
        return {"ok": True, **result}

    def debug_order(self, request: dict) -> dict[str, Any]:
        result = self.manual.order(request)
        if result["reply"].get("ok") is not True:
            raise RuntimeError(result["reply"].get("error", "DCS rejected order"))
        return {"ok": True, **result}


def make_handler(service: FoWService):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            files = {
                "/": (WEB / "index.html", "text/html; charset=utf-8"),
                "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
                "/styles.css": (WEB / "styles.css", "text/css; charset=utf-8"),
            }
            if path == "/api/overview":
                self.send_json(200, service.overview())
                return
            if path in ("/api/status", "/api/debug/status"):
                self.send_json(200, service.debug_status())
                return
            if path == "/api/catalog":
                self.send_json(200, service.debug_catalogs()["ground"])
                return
            if path == "/api/air-catalog":
                self.send_json(200, service.debug_catalogs()["air"])
                return
            if path not in files:
                self.send_error(404)
                return
            file_path, content_type = files[path]
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path not in ("/api/campaign/new", "/api/spawn", "/api/spawn-air", "/api/orders"):
                self.send_error(404)
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.send_json(415, {"ok": False, "error": "Expected JSON"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                self.send_json(413, {"ok": False, "error": "Request too large"})
                return
            request = {}
            if length:
                try:
                    request = json.loads(self.rfile.read(length))
                except json.JSONDecodeError:
                    self.send_json(400, {"ok": False, "error": "Invalid JSON"})
                    return
            if path == "/api/campaign/new":
                interval = request.get("income_interval_seconds")
                if request not in ({}, {"scenario": service.scenario.id}) and interval is None:
                    self.send_json(400, {"ok": False, "error": "Unknown scenario"})
                    return
                if interval is not None and (not isinstance(interval, (int, float))
                                             or isinstance(interval, bool) or interval < 30):
                    self.send_json(400, {"ok": False, "error": "income_interval_seconds must be >= 30"})
                    return
                self.send_json(201, {"ok": True,
                                     "campaign": service.new_game(
                                         income_interval_seconds=interval)})
                return
            try:
                result = (service.debug_order(request) if path == "/api/orders" else
                          service.debug_spawn("air" if path == "/api/spawn-air" else "ground", request))
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                self.send_json(400, {"ok": False, "error": str(error)})
                return
            self.send_json(201, result)

        def log_message(self, format: str, *values: object) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=10309)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_CHECKPOINT)
    args = parser.parse_args()

    gateway = DcsGateway(DcsClient(args.bridge_host, args.bridge_port))
    service = FoWService(args.scenario, gateway, checkpoint_path=args.state_file)
    stop = Event()

    def poll_dcs() -> None:
        while not stop.is_set():
            gateway.refresh()
            service.tick()
            stop.wait(5)

    Thread(target=poll_dcs, daemon=True).start()
    server = ThreadingHTTPServer((args.listen, args.port), make_handler(service))
    print(f"FoW campaign service: http://{args.listen}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()