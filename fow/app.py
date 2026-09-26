#!/usr/bin/env python3
"""Run the second-generation FoW campaign service and web shell."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Event, Lock, Thread
import time
from typing import Any
from urllib.parse import urlsplit

from .campaign import ActionPlan, AlgorithmicGeneral, CampaignEngine, CampaignState, Side, load_scenario
from .dcs import CampaignExecutor, DcsClient, DcsGateway, ManualOperations
from .dcs.awareness import Awareness
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
                        sequence = len(self._campaign.events)
                        jobs.append((plan, sequence))
                        self._deployments.append(self._deployment(plan, sequence))
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
            # can replace losses and escort the AWACS.
            for side in Side:
                self._generals[side].live_support = {
                    deployment["action"] for deployment in self._deployments
                    if deployment["side"] == side.value
                    and deployment["action"] in ("awacs", "tanker", "cap")
                    and deployment["status"] == "active"
                    and set(deployment.get("names", [deployment["name"]]))
                    & {group.get("name") for group in snapshot.get("groups", [])
                       if group.get("units")}
                }
            presence = self.awareness.objective_presence(self.scenario, snapshot)
            flips = self.engine.evaluate_capture(self._campaign, presence)
            # Reactive triggers: an objective we own with enemy ground present
            # is threatened; one we just lost is a counter-attack target.
            # Presence counts are keyed by DCS coalition id (1=red, 2=blue).
            enemy = {Side.BLUE: Side.RED, Side.RED: Side.BLUE}
            coalition_of = {Side.RED: 1, Side.BLUE: 2}
            for side in Side:
                general = self._generals[side]
                enemy_coalition = coalition_of[enemy[side]]
                general.threatened = {
                    objective_id for objective_id, counts in presence.items()
                    if self._campaign.objectives[objective_id].owner == side
                    and counts.get(enemy_coalition, 0) > 0}
                general.lost = {
                    flip["objective"] for flip in flips if flip["to"] == enemy[side].value}
            if flips:
                self._apply_slot_access()
                self._save_locked()
            self._send_intel(flips, presence)

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
            return [
                {"lat": position[0], "lon": position[1],
                 "label": f"{action.upper()} station {index + 1}"}
                for index, position in enumerate(station.waypoints)
            ] + [{
                "lat": objective.lat,
                "lon": objective.lon,
                "label": f"RTB {objective.label}",
            }]
        return [{
            "lat": objective.lat,
            "lon": objective.lon,
            "label": f"{objective.label} {action.upper()}",
        }]

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