"""Translate accepted campaign ground plans into idempotent DCS commands."""

import json
from pathlib import Path

from scripts import dcs_structures

from ..campaign.models import ActionPlan, CampaignState
from ..campaign.scenario import Scenario
from .client import DcsGateway


MISSIONS = Path(__file__).resolve().parents[2] / "missions"
CATALOG = MISSIONS / "spawn_catalog.json"
AIR_CATALOG = MISSIONS / "air_trial.json"
AIR_TEMPLATES = MISSIONS / "air_templates.json"


class CampaignExecutor:
    def __init__(self, scenario: Scenario, gateway: DcsGateway):
        self.scenario = scenario
        self.gateway = gateway
        self.catalog = json.loads(CATALOG.read_text())
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
        snapshot = self.gateway.public_snapshot()
        if snapshot is None:
            return {"name": name, "status": "waiting", "error": "DCS status is unavailable"}
        active_names = {group.get("name") for group in snapshot.get("groups", []) if group.get("units")}
        if set(names) <= active_names:
            return {"name": self.name_for(plan, sequence), "names": names, "status": "active", "error": None}
        asset = self.scenario.assets[plan.package]
        template_id = asset.variants[plan.side]
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
            spawn_lat, spawn_lon = dcs_structures.offset_position(
                origin.lat, origin.lon, north_m, east_m)
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