"""Translate accepted campaign ground plans into idempotent DCS commands."""

import json
import math
from pathlib import Path

from scripts import dcs_structures

from ..campaign.models import ActionPlan, CampaignState
from ..campaign.scenario import Scenario
from .client import DcsGateway


MISSIONS = Path(__file__).resolve().parents[2] / "missions"
CATALOG = MISSIONS / "spawn_catalog.json"
UNIT_CATALOG = MISSIONS / "unit_catalog.json"
AIR_CATALOG = MISSIONS / "air_trial.json"
AIR_TEMPLATES = MISSIONS / "air_templates.json"


class CampaignExecutor:
    def __init__(self, scenario: Scenario, gateway: DcsGateway):
        self.scenario = scenario
        self.gateway = gateway
        self.catalog = json.loads(CATALOG.read_text())
        self.unit_catalog = json.loads(UNIT_CATALOG.read_text())
        self.air_catalog = json.loads(AIR_CATALOG.read_text())
        self.air_templates = json.loads(AIR_TEMPLATES.read_text())

    def name_for(self, plan: ActionPlan, sequence: int) -> str:
        objective = self.scenario.objectives[plan.target]
        return f"FoW {plan.side.value.title()} {plan.action.title()} {objective.label} {sequence}"

    def names_for(self, plan: ActionPlan, sequence: int) -> list[str]:
        root = self.name_for(plan, sequence)
        return [f"{root} {index}" for index in range(1, 5)] if plan.action == "reinforce" else [root]

    def execute(self, plan: ActionPlan, sequence: int, state: CampaignState) -> dict:
        side = plan.side.value
        objective = self.scenario.objectives[plan.target]
        names = self.names_for(plan, sequence)
        name = names[0]
        if plan.action == "jtac":
            return self._execute_jtac(plan, sequence, objective)
        if objective.kind == "carrier" and plan.action not in ("cap", "awacs", "tanker"):
            return {"name": name, "names": names, "status": "failed",
                    "error": "Carrier objectives only host air actions"}
        snapshot = self.gateway.public_snapshot()
        if snapshot is None:
            return {"name": name, "status": "waiting", "error": "DCS status is unavailable"}
        active_names = {group.get("name") for group in snapshot.get("groups", []) if group.get("units")}
        if set(names) <= active_names:
            return {"name": self.name_for(plan, sequence), "names": names, "status": "active", "error": None}
        asset = self.scenario.assets[plan.package]
        # Garrison-style packages scale with the objective's difficulty tier:
        # easy objectives get infantry, hard ones get armor plus SAMs.
        tier = asset.tiers.get(objective.difficulty)
        template_id = (tier or asset.variants)[plan.side]
        if template_id in self.air_catalog.get("presets", {}).get(side, {}):
            return self._execute_air(plan, sequence, template_id, objective, snapshot)
        template = self.catalog[side].get(template_id)
        if template is None:
            return {"name": name, "names": names, "status": "failed", "error": f"Unknown template {template_id}"}
        north_m = 180 * ((sequence % 3) - 1)
        east_m = 180 * (((sequence // 3) % 3) - 1)
        spawn_lat, spawn_lon = objective.defense_positions[sequence % len(objective.defense_positions)]
        destination = None
        if plan.action == "assault":
            origins = [self.scenario.objectives[neighbor]
                       for neighbor in objective.connections
                       if state.objectives[neighbor].owner == plan.side]
            if not origins:
                return {"name": name, "status": "failed", "error": "No friendly assault origin"}
            origin = sorted(origins, key=lambda item: item.id)[0]
            # Spawn the assault force a short drive from the objective, along
            # the attack line from the friendly origin. Driving the whole
            # distance takes too long; a 5-10 minute approach keeps the push
            # visible and leaves time for a counter-attack.
            approach_m = 4000
            bearing = dcs_structures.initial_bearing(
                objective.lat, objective.lon, origin.lat, origin.lon)
            spawn_lat, spawn_lon = dcs_structures.offset_position(
                objective.lat, objective.lon, approach_m * math.cos(bearing),
                approach_m * math.sin(bearing))
            destination = (objective.lat, objective.lon)
        chunks = [template["units"][index::4] for index in range(4)] if plan.action == "reinforce" else [template["units"]]
        replies = []
        try:
            for index, (group_name, units) in enumerate(zip(names, chunks)):
                if group_name in active_names:
                    continue
                group_template = {**template, "units": units}
                if plan.action == "reinforce":
                    position = objective.defense_positions[index % len(objective.defense_positions)]
                    group_lat, group_lon = dcs_structures.offset_position(
                        position[0], position[1], 250 * (index // 2), 250 * (index % 2))
                else:
                    group_lat, group_lon = spawn_lat, spawn_lon
                group_lat, group_lon = self.gateway.ground_position(
                    group_lat, group_lon,
                    [{"dx": unit.get("dx", 0), "dy": unit.get("dy", 0)} for unit in units])
                spawn_data = dcs_structures.build_ground_spawn_data(
                    side, group_template, group_name, group_lat, group_lon, destination)
                replies.append(self.gateway.spawn_group(spawn_data))
        except (OSError, RuntimeError, ValueError) as error:
            return {"name": self.name_for(plan, sequence), "names": names, "status": "failed", "error": str(error)}
        accepted = all(reply.get("ok") for reply in replies)
        return {
            "name": self.name_for(plan, sequence), "names": names,
            "status": "accepted" if accepted else "failed",
            "error": None if accepted else "DCS rejected one or more groups",
        }

    def _execute_jtac(self, plan, sequence, objective) -> dict:
        """Spawn a JTAC infantry observer near the objective, give it a FAC
        task, drop smoke for visibility, and mark the objective on the F10 map."""
        name = self.name_for(plan, sequence)
        template = self.unit_catalog.get("blue", {}).get("unit_39038408fa35f2b8")
        if template is None:
            return {"name": name, "names": [name], "status": "failed",
                    "error": "JTAC template unavailable"}
        # Stage the JTAC just outside the objective so it observes, not fights.
        lat, lon = objective.defense_positions[sequence % len(objective.defense_positions)]
        lat, lon = dcs_structures.offset_position(lat, lon, 300, 0)
        try:
            lat, lon = self.gateway.ground_position(
                lat, lon, [{"dx": 0, "dy": 0}])
            spawn_data = dcs_structures.build_ground_spawn_data(
                plan.side.value, template, name, lat, lon)
            reply = self.gateway.spawn_group(spawn_data)
            if reply.get("ok") is not True:
                return {"name": name, "names": [name], "status": "failed",
                        "error": reply.get("result", "DCS rejected JTAC spawn")}
            # FAC task: the JTAC lases and calls targets for players.
            self.gateway.set_task(name, {
                "id": "FAC",
                "params": {"targetTypes": ["Ground Units", "Airplanes"],
                           "priority": 0},
            })
            # Orange smoke near the objective for visual reference.
            self.gateway.smoke(objective.lat, objective.lon, 4, 300)
            # F10 map mark for the requesting coalition (Blue).
            self.gateway.mark(objective.lat, objective.lon,
                              f"JTAC on station - {objective.label}", 2)
        except (OSError, RuntimeError, ValueError) as error:
            return {"name": name, "names": [name], "status": "failed", "error": str(error)}
        return {"name": name, "names": [name], "status": "accepted", "error": None}

    def _execute_air(self, plan, sequence, template_id, objective, snapshot):
        side = plan.side.value
        name = self.name_for(plan, sequence)
        preset = self.air_catalog["presets"][side][template_id]
        template = self.air_templates.get(side, {}).get(template_id, {}).get("group")
        if template is None:
            return {"name": name, "names": [name], "status": "failed", "error": f"Missing air template {template_id}"}
        station = self.scenario.air_stations.get(plan.side, {}).get(plan.action)
        mission_lat, mission_lon = station.waypoints[0] if station else (objective.lat, objective.lon)
        spawn_lat, spawn_lon = dcs_structures.air_start_position(mission_lat, mission_lon)
        spawn_data = dcs_structures.build_air_spawn_data(
            side, preset, template, spawn_lat, spawn_lon,
            mission_lat, mission_lon, name,
            racetrack_end=station.waypoints[1] if station else None,
            on_station_seconds=station.on_station_seconds if station else None,
            rtb=(preset["default_rtb_base"], objective.lat, objective.lon) if station else None)
        try:
            reply = self.gateway.spawn_group(spawn_data)
        except (OSError, RuntimeError, ValueError) as error:
            return {"name": name, "names": [name], "status": "failed", "error": str(error)}
        return {"name": name, "names": [name],
                "status": "accepted" if reply.get("ok") else "failed",
                "error": None if reply.get("ok") else reply.get("result", "DCS rejected command")}