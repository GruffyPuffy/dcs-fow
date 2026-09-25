"""Validated manual DCS operations for the debug console."""

import json
import math
from pathlib import Path
import uuid

from scripts import dcs_structures

from .client import DcsGateway


ROOT = Path(__file__).resolve().parents[2]
GROUND_CATALOG = ROOT / "missions" / "spawn_catalog.json"
AIR_CATALOG = ROOT / "missions" / "air_trial.json"
AIR_TEMPLATES = ROOT / "missions" / "air_templates.json"


class ManualOperations:
    def __init__(self, gateway: DcsGateway):
        self.gateway = gateway
        self.ground = json.loads(GROUND_CATALOG.read_text())
        self.air = json.loads(AIR_CATALOG.read_text())
        self.air_templates = json.loads(AIR_TEMPLATES.read_text())

    def catalogs(self) -> dict:
        return {
            "ground": self.ground,
            "air": {
                "presets": self.air.get("presets", {}),
                "loadouts": self.air.get("loadouts", {}),
            },
        }

    def spawn_ground(self, request: dict) -> dict:
        side = self._side(request)
        template_id = request.get("template")
        if not isinstance(template_id, str) or template_id not in self.ground[side]:
            raise ValueError("Unknown ground template")
        lat, lon = self._coordinates(request)
        name = self._name(request, f"FoW Debug {side.title()} {template_id}")
        template = self.ground[side][template_id]
        lat, lon = self.gateway.ground_position(
            lat, lon,
            [{"dx": unit.get("dx", 0), "dy": unit.get("dy", 0)}
             for unit in template["units"]])
        spawn_data = dcs_structures.build_ground_spawn_data(
            side, template, name, lat, lon)
        return {"name": name, "reply": self.gateway.spawn_group(spawn_data)}

    def spawn_air(self, request: dict) -> dict:
        side = self._side(request)
        preset_id = request.get("preset")
        presets = self.air.get("presets", {}).get(side, {})
        if not isinstance(preset_id, str) or preset_id not in presets:
            raise ValueError("Unknown air preset")
        lat, lon = self._coordinates(request)
        preset = dict(presets[preset_id])
        altitude = request.get("altitude_m", preset["altitude_m"])
        if (not isinstance(altitude, (int, float)) or isinstance(altitude, bool)
                or not math.isfinite(altitude) or not 1000 <= altitude <= 12000):
            raise ValueError("Aircraft altitude must be 1000-12000 m")
        preset["altitude_m"] = altitude
        template = self.air_templates.get(side, {}).get(preset_id, {}).get("group")
        if template is None:
            raise ValueError("Aircraft template is unavailable")
        name = self._name(request, f"FoW Debug {side.title()} {preset_id}")
        spawn_lat, spawn_lon = dcs_structures.air_start_position(lat, lon)
        spawn_data = dcs_structures.build_air_spawn_data(
            side, preset, template, spawn_lat, spawn_lon, lat, lon, name)
        return {"name": name, "reply": self.gateway.spawn_group(spawn_data)}

    def order(self, request: dict) -> dict:
        side = self._side(request)
        operation = request.get("op")
        allowed = {"move", "hold", "set_roe", "air_move", "set_mission", "start", "rtb"}
        if operation not in allowed:
            raise ValueError("Unknown order")
        snapshot = self.gateway.public_snapshot()
        if snapshot is None:
            raise ValueError("DCS status is unavailable")
        name = request.get("group")
        coalition = {"red": 1, "blue": 2}[side]
        group = next((entry for entry in snapshot["groups"]
                      if entry.get("name") == name and entry.get("coalition") == coalition
                      and entry.get("units")), None)
        if group is None:
            raise ValueError("Choose an active group on this side")
        air_operation = operation in {"air_move", "set_mission", "start", "rtb"}
        expected_category = 0 if air_operation else 2
        if group.get("category") != expected_category:
            raise ValueError("Order does not match the group category")
        lead = group["units"][0]
        if operation == "move":
            lat, lon = self._coordinates(request)
            reply = self.gateway.set_route(
                name, dcs_structures.build_ground_route(lead["lat"], lead["lon"], lat, lon))
        elif operation == "hold":
            reply = self.gateway.set_task(name, {"id": "Hold", "params": {}})
        elif operation == "set_roe":
            mode = request.get("mode")
            if mode not in ("open_fire", "return_fire", "weapon_hold"):
                raise ValueError("Invalid rules of engagement")
            option = dcs_structures.build_roe_option(mode)
            reply = self.gateway.set_option(name, option["option_id"], option["value"])
        elif operation == "start":
            reply = self.gateway.set_command(name, dcs_structures.build_start_command())
        elif operation == "rtb":
            airbase_name = request.get("airbase")
            airbase = next((entry for entry in snapshot["airbases"]
                            if entry.get("name") == airbase_name
                            and entry.get("coalition") == coalition), None)
            if airbase is None:
                raise ValueError("Choose a friendly recovery base")
            speed = self._air_speed(lead.get("type"))
            task = dcs_structures.build_rtb_task(
                airbase_name, airbase["lat"], airbase["lon"], lead["lat"], lead["lon"],
                lead.get("y", 3000), min(180, speed))
            reply = self.gateway.set_task(name, task)
        else:
            lat, lon = self._coordinates(request)
            altitude = request.get("altitude_m", 5000)
            if (not isinstance(altitude, (int, float)) or isinstance(altitude, bool)
                    or not math.isfinite(altitude) or not 1000 <= altitude <= 12000):
                raise ValueError("Aircraft altitude must be 1000-12000 m")
            mission_type = request.get("mission_type", "transit") if operation == "set_mission" else "transit"
            if mission_type not in ("transit", "patrol", "CAP", "CAS", "AWACS", "tanker"):
                raise ValueError("Invalid mission type")
            route = dcs_structures.build_route_update(
                mission_type, lead["lat"], lead["lon"], lat, lon,
                int(altitude), self._air_speed(lead.get("type")))
            reply = self.gateway.set_route(name, route["route_data"])
        return {"group": name, "operation": operation, "reply": reply}

    def _air_speed(self, dcs_type: str | None) -> int:
        matching = [preset for presets in self.air.get("presets", {}).values()
                    for preset in presets.values() if preset.get("dcs_type") == dcs_type]
        return int(matching[0]["speed_mps"]) if matching else 210

    @staticmethod
    def _side(request: dict) -> str:
        side = request.get("side")
        if side not in ("blue", "red"):
            raise ValueError("Side must be blue or red")
        return side

    @staticmethod
    def _coordinates(request: dict) -> tuple[float, float]:
        lat, lon = request.get("lat"), request.get("lon")
        if (not isinstance(lat, (int, float)) or isinstance(lat, bool)
                or not isinstance(lon, (int, float)) or isinstance(lon, bool)
                or not math.isfinite(lat) or not math.isfinite(lon)
                or abs(lat) > 90 or abs(lon) > 180):
            raise ValueError("Invalid map coordinates")
        return float(lat), float(lon)

    @staticmethod
    def _name(request: dict, prefix: str) -> str:
        name = request.get("name") or f"{prefix} {uuid.uuid4().hex[:6]}"
        if (not isinstance(name, str) or not 3 <= len(name) <= 80
                or name.strip() != name
                or not all(character.isascii() and (
                    character.isalnum() or character in " _-") for character in name)):
            raise ValueError("Name must be 3-80 ASCII letters, digits, spaces, _ or -")
        return name