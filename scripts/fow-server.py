#!/usr/bin/env python3
"""Local manual FoW server: DCS status, orders, and observation history."""

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import random
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from fowctl import exchange
from fow_store import Store
import dcs_structures


PAGE = Path(__file__).resolve().parent.parent / "viewer" / "index.html"
CATALOG = Path(__file__).resolve().parent.parent / "missions" / "spawn_catalog.json"
UNIT_CATALOG = CATALOG.with_name("unit_catalog.json")
AIR_CATALOG = CATALOG.with_name("air_trial.json")
AIR_TEMPLATES = CATALOG.with_name("air_templates.json")
AIRBASE_CATALOG = CATALOG.with_name("airbase_catalog.json")
SCENARIO_MANIFEST = CATALOG.with_name("scenario_manifest.json")


def load_catalog() -> dict:
    catalog = json.loads(CATALOG.read_text())
    units = json.loads(UNIT_CATALOG.read_text())
    for side in ("blue", "red"):
        catalog[side].update(units[side])
    return catalog


def scenario_aliases() -> dict:
    if not SCENARIO_MANIFEST.exists():
        return {}
    scenario = json.loads(SCENARIO_MANIFEST.read_text()).get("scenario", {})
    configured = scenario.get("client_slots", []) + scenario.get("initial_groups", []) \
        + scenario.get("initial_flights", []) + scenario.get("alert_flights", [])
    return {
        item["name"]: item["display_name"]
        for item in configured if item.get("display_name")
    }


def scenario_rules() -> tuple[dict, dict]:
    scenario = json.loads(SCENARIO_MANIFEST.read_text()).get("scenario", {})
    return scenario.get("strategic_bases", {}), scenario.get("commander_rules", {})


def scenario_alert_flights() -> list[dict]:
    scenario = json.loads(SCENARIO_MANIFEST.read_text()).get("scenario", {})
    return scenario.get("alert_flights", [])


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2
    a += math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(min(1, math.sqrt(a)))


def range_rings(snapshot: dict | None, catalog: dict) -> dict:
    if not snapshot:
        return {}
    rings = {}
    for group in snapshot.get("groups", []):
        side = {1: "red", 2: "blue"}.get(group.get("coalition"))
        if not side:
            continue
        actual = Counter(unit.get("type") for unit in group.get("units", []))
        for entry in catalog[side].values():
            if entry.get("range_m") and actual == Counter(unit["type"] for unit in entry["units"]):
                rings[group["name"]] = {"range_m": entry["range_m"], "label": entry["label"]}
                break
    return rings


def side_view(payload: dict, side: str) -> dict:
    """Filter on the server so a coalition view never receives enemy truth."""
    if side == "admin":
        return payload
    coalition = {"red": 1, "blue": 2}[side]
    snapshot = payload.get("snapshot")
    if snapshot:
        own_groups = [g for g in snapshot.get("groups", []) if g.get("coalition") == coalition]
        names = {g["name"] for g in own_groups}
        payload["snapshot"] = {**snapshot, "groups": own_groups,
                               "statics": [s for s in snapshot.get("statics", []) if s.get("coalition") == coalition],
                               "contacts": []}
        payload["orders"] = [o for o in payload["orders"] if o["group_name"] in names]
        payload["tracks"] = {name: points for name, points in payload["tracks"].items() if name in names}
        payload["range_rings"] = {name: ring for name, ring in payload["range_rings"].items() if name in names}
        payload["aliases"] = {name: alias for name, alias in payload["aliases"].items() if name in names}
        payload["roe"] = {name: mode for name, mode in payload["roe"].items() if name in names}
    else:
        payload["orders"] = []
        payload["tracks"] = {}
        payload["range_rings"] = {}
        payload["aliases"] = {}
        payload["roe"] = {}
    counts = payload["roster"]["by_coalition"].get(str(coalition), {"seen": 0, "present": 0, "missing": 0})
    payload["roster"] = {**counts, "by_coalition": {str(coalition): counts}}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=10309)
    parser.add_argument("--interval", type=int, default=10, help="DCS poll interval in seconds")
    parser.add_argument("--db", type=Path, default=PAGE.parent.parent / "data" / "fow.sqlite3")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be positive")

    store = Store(args.db)
    lock = threading.Lock()
    state = {"snapshot": None, "received_at": None, "error": "Waiting for first DCS response"}
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            try:
                result = exchange(args.bridge_host, args.bridge_port, "status")
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or result.get("result") or "DCS rejected status")
                store.record_snapshot(result)
                with lock:
                    state.update(snapshot=result, received_at=time.time(), error=None)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                with lock:
                    state["error"] = str(error)
            stop.wait(args.interval)

    class Handler(BaseHTTPRequestHandler):
        def json_response(self, status: int, data: dict) -> None:
            body = json.dumps(data, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path)
            if path.path == "/":
                body = PAGE.read_bytes()
                content_type = "text/html; charset=utf-8"
            elif path.path == "/api/catalog":
                body = json.dumps(load_catalog(), separators=(",", ":")).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif path.path == "/api/air-catalog":
                body = AIR_CATALOG.read_bytes()
                content_type = "application/json; charset=utf-8"
            elif path.path == "/api/airbase-catalog":
                body = AIRBASE_CATALOG.read_bytes()
                content_type = "application/json; charset=utf-8"
            elif path.path == "/api/objectives":
                strategic_bases, commander_rules = scenario_rules()
                body = json.dumps({"bases": strategic_bases, "rules": commander_rules,
                                   "alert_flights": scenario_alert_flights()},
                                  separators=(",", ":")).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif path.path == "/api/status":
                sides = parse_qs(path.query).get("side", ["blue"])
                if len(sides) != 1 or sides[0] not in ("blue", "red", "admin"):
                    self.send_error(400)
                    return
                with lock:
                    payload = state.copy()
                payload.update(store.dashboard())
                payload["aliases"] = {**scenario_aliases(), **payload["aliases"]}
                payload["range_rings"] = range_rings(payload["snapshot"], load_catalog())
                payload = side_view(payload, sides[0])
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if path.path == "/api/status" else "public, max-age=60")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path not in ("/api/orders", "/api/move", "/api/spawn", "/api/spawn-air", "/api/alias", "/api/set-mission", "/api/rtb", "/api/attack-base", "/api/defend-base", "/api/scramble"):
                self.send_error(404)
                return
            # JSON plus a custom header prevents a cross-site HTML form from
            # issuing orders to a viewer running on the user's localhost.
            origin = self.headers.get("Origin")
            if (origin and origin != "http://" + self.headers.get("Host", "")) or \
                    self.headers.get("X-FoW-Viewer") != "1" or \
                    self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.json_response(403, {"ok": False, "error": "Invalid request origin or content type"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 512:
                    raise ValueError("Request size out of range")
                request = json.loads(self.rfile.read(length))
                side = request.get("side", "blue")
                if side not in ("blue", "red", "admin"):
                    raise ValueError("Invalid commander side")
                if self.path == "/api/scramble":
                    if side == "admin":
                        raise ValueError("Choose Blue or Red before scrambling aircraft")
                    name = request.get("group")
                    configured_alert = next((flight for flight in scenario_alert_flights()
                                             if flight.get("name") == name and flight.get("side") == side), None)
                    if configured_alert is None:
                        raise ValueError("Choose a configured ready flight for this side")
                    op = "scramble"
                elif self.path in ("/api/attack-base", "/api/defend-base"):
                    if side == "admin":
                        raise ValueError("Choose Blue or Red before deploying a force")
                    target_base = request.get("base")
                    strategic_bases, commander_rules = scenario_rules()
                    target_config = strategic_bases.get(target_base)
                    if not isinstance(target_base, str) or not target_config:
                        raise ValueError("Choose a configured strategic base")
                    if self.path == "/api/attack-base":
                        if target_config.get("kind") != "objective":
                            raise ValueError("Home bases are not assault objectives")
                        op, name = "attack_base", f"Assault on {target_base}"
                        quick_trial = request.get("quick_trial", False)
                        if not isinstance(quick_trial, bool):
                            raise ValueError("Invalid quick-trial option")
                    else:
                        op, name = "defend_base", f"Defense of {target_base}"
                elif self.path == "/api/alias":
                    op, name = "alias", request["group"]
                    alias = request["alias"]
                    if not isinstance(alias, str) or not 1 <= len(alias) <= 80 or \
                            alias.strip() != alias or not all(c.isprintable() for c in alias):
                        raise ValueError("Display name must be 1–80 printable characters")
                    if not isinstance(name, str) or not name or len(name) > 128:
                        raise ValueError("Invalid group")
                elif self.path in ("/api/spawn", "/api/spawn-air"):
                    if side == "admin":
                        raise ValueError("Choose Blue or Red before spawning")
                    if self.path == "/api/spawn-air":
                        template = request["preset"]
                        catalog = json.loads(AIR_CATALOG.read_text())
                        op = "spawn_air"
                        if not isinstance(template, str) or template not in catalog.get("presets", {}).get(side, {}):
                            raise ValueError("Unknown spawn preset")
                    else:
                        template = request["template"]
                        catalog = load_catalog()
                        op = "spawn"
                        if not isinstance(template, str) or template not in catalog[side]:
                            raise ValueError("Unknown spawn preset")
                    custom_name = request.get("name")
                    if custom_name is not None and (
                            not isinstance(custom_name, str) or
                            not 3 <= len(custom_name) <= 60 or
                            not all(c.isascii() and (c.isalnum() or c in " _-") for c in custom_name) or
                            custom_name.strip() != custom_name):
                        raise ValueError("Name must be 3–60 ASCII letters, digits, spaces, _ or -")
                    name = template
                elif self.path == "/api/set-mission":
                    name = request["group"]
                    op = "set_mission"
                    if not isinstance(name, str) or not name or len(name) > 128:
                        raise ValueError("Invalid group")
                    mission_type = request.get("mission_type")
                    if mission_type not in ("patrol", "CAP", "CAS", "AWACS", "tanker"):
                        raise ValueError("Invalid mission type")
                elif self.path == "/api/rtb":
                    name = request["group"]
                    op = "rtb"
                    if not isinstance(name, str) or not name or len(name) > 128:
                        raise ValueError("Invalid group")
                    rtb_base = request.get("airbase")
                    if not isinstance(rtb_base, str) or not rtb_base or len(rtb_base) > 64:
                        raise ValueError("Invalid airbase")
                else:
                    name = request["group"]
                    op = request.get("op", "move" if self.path == "/api/move" else None)
                    if op not in ("move", "hold", "set_roe", "air_move"):
                        raise ValueError("Unknown order")
                    if not isinstance(name, str) or not name or len(name) > 128:
                        raise ValueError("Invalid group")
                    if op == "set_roe":
                        mode = request.get("mode")
                        if mode not in ("open_fire", "return_fire", "weapon_hold"):
                            raise ValueError("Invalid rules of engagement")
                lat = lon = None
                if op in ("move", "spawn", "spawn_air", "air_move", "set_mission"):
                    lat, lon = request["lat"], request["lon"]
                    if (not isinstance(lat, (int, float)) or isinstance(lat, bool) or
                        not isinstance(lon, (int, float)) or isinstance(lon, bool) or
                        not math.isfinite(lat) or not math.isfinite(lon) or
                        abs(lat) > 90 or abs(lon) > 180):
                        raise ValueError("Invalid map coordinates")
                altitude_m = None
                mission_type_val = None
                loadout_val = None
                rtb_base_val = None
                if op == "air_move":
                    altitude_m = request.get("altitude_m", 5000)
                    if (not isinstance(altitude_m, (int, float)) or isinstance(altitude_m, bool) or
                            not math.isfinite(altitude_m) or not 1000 <= altitude_m <= 12000):
                        raise ValueError("Aircraft altitude must be 1000–12000 m")
                elif op == "spawn_air":
                    preset_data = catalog["presets"][side][template]
                    altitude_m = preset_data["altitude_m"]
                    mission_type_val = preset_data["mission_type"]
                    loadout_val = preset_data.get("loadout")
                    rtb_base_val = preset_data.get("default_rtb_base")
                elif op == "set_mission":
                    altitude_m = request.get("altitude_m", 5000)
                    if (not isinstance(altitude_m, (int, float)) or isinstance(altitude_m, bool) or
                            not math.isfinite(altitude_m) or not 1000 <= altitude_m <= 12000):
                        raise ValueError("Aircraft altitude must be 1000–12000 m")
                    mission_type_val = mission_type
                elif op == "rtb":
                    rtb_base_val = rtb_base
            except (ValueError, KeyError, TypeError) as error:
                self.json_response(400, {"ok": False, "error": str(error)})
                return
            with lock:
                snapshot = state["snapshot"]
                received_at = state["received_at"]
                bridge_error = state["error"]
            if bridge_error or not snapshot or not received_at or time.time() - received_at > 30:
                self.json_response(503, {"ok": False, "error": "DCS status is stale"})
                return
            if op in ("attack_base", "defend_base"):
                coalition = {"red": 1, "blue": 2}[side]
                airbase = next((base for base in snapshot.get("airbases", [])
                                if base.get("name") == target_base), None)
                if not airbase:
                    self.json_response(400, {"ok": False, "error": "Target airbase is absent from DCS status"})
                    return
            if op == "scramble":
                coalition = {"red": 1, "blue": 2}[side]
                home = next((base for base in snapshot.get("airbases", [])
                             if base.get("name") == configured_alert["base"]), None)
                if not home or home.get("coalition") != coalition:
                    self.json_response(400, {"ok": False,
                                             "error": "DCS does not show the alert base as owned by this side"})
                    return
                if op == "attack_base" and airbase.get("coalition") == coalition:
                    self.json_response(400, {"ok": False, "error": "That airbase is already owned by this side"})
                    return
                if op == "defend_base" and airbase.get("coalition") != coalition:
                    self.json_response(400, {"ok": False, "error": "DCS does not show that base as owned by this side"})
                    return
            if op == "attack_base":
                approaches = target_config.get("approaches", {}).get(side, [])
                if not approaches:
                    self.json_response(400, {"ok": False, "error": "No validated approach for this side"})
                    return
                prefix = f"FoW {side.title()} Assault "
                active_assaults = sum(1 for group in snapshot.get("groups", [])
                                      if group.get("name", "").startswith(prefix) and group.get("units"))
                maximum = int(commander_rules.get("maximum_active_assaults_per_side", 2))
                if active_assaults >= maximum:
                    self.json_response(400, {"ok": False,
                                             "error": f"Active assault limit reached ({maximum})"})
                    return
                package_ids = commander_rules.get("assault_packages", [])
                catalog = load_catalog()
                package_ids = [package for package in package_ids if package in catalog[side]]
                if not package_ids:
                    self.json_response(500, {"ok": False, "error": "No assault packages configured"})
                    return
                template = random.choice(package_ids)
                approach = random.choice(approaches)
                lat, lon = airbase["lat"], airbase["lon"]
                if quick_trial:
                    configured_distance = distance_m(
                        lat, lon, approach["lat"], approach["lon"])
                    if configured_distance > 2300:
                        fraction = 2300 / configured_distance
                        approach = {
                            "lat": lat + (approach["lat"] - lat) * fraction,
                            "lon": lon + (approach["lon"] - lon) * fraction,
                        }
                approach_distance = distance_m(lat, lon, approach["lat"], approach["lon"])
                stop_distance = min(1200, approach_distance * 0.5)
                stop_fraction = stop_distance / approach_distance if approach_distance else 0
                assault_destination = (
                    lat + (approach["lat"] - lat) * stop_fraction,
                    lon + (approach["lon"] - lon) * stop_fraction,
                )
            elif op == "defend_base":
                positions = target_config.get("defense_positions", [])
                if not positions:
                    self.json_response(400, {"ok": False, "error": "No validated defense position for this base"})
                    return
                prefix = f"FoW {side.title()} Defense {target_base} "
                active_defenses = sum(1 for group in snapshot.get("groups", [])
                                      if group.get("name", "").startswith(prefix) and group.get("units"))
                maximum = int(commander_rules.get("maximum_defense_packages_per_base", 3))
                if active_defenses >= maximum:
                    self.json_response(400, {"ok": False,
                                             "error": f"Defense limit reached for {target_base} ({maximum})"})
                    return
                package_ids = commander_rules.get(
                    "automatic_defense_packages", commander_rules.get("defense_packages", []))
                catalog = load_catalog()
                package_ids = [package for package in package_ids if package in catalog[side]]
                if not package_ids:
                    self.json_response(500, {"ok": False, "error": "No defense packages configured"})
                    return
                template = random.choice(package_ids)
                approach = random.choice(positions)
                lat, lon = approach["lat"], approach["lon"]
            elif op == "spawn":
                strategic_bases, commander_rules = scenario_rules()
                defense_packages = commander_rules.get("defense_packages", [])
                if template not in defense_packages:
                    self.json_response(400, {"ok": False,
                                             "error": "Commanders may manually place only curated defense packages"})
                    return
                coalition = {"red": 1, "blue": 2}[side]
                radius = int(commander_rules.get("defense_spawn_radius_m", 8000))
                owned = [base for base in snapshot.get("airbases", [])
                         if base.get("coalition") == coalition and base.get("name") in strategic_bases]
                nearby = [(distance_m(lat, lon, base["lat"], base["lon"]), base) for base in owned]
                nearby = [(distance, base) for distance, base in nearby if distance <= radius]
                if not nearby:
                    self.json_response(400, {"ok": False,
                                             "error": f"Place defenses within {radius // 1000} km of an owned strategic base"})
                    return
                defense_base = min(nearby, key=lambda item: item[0])[1]
                prefix = f"FoW {side.title()} Defense {defense_base['name']} "
                active_defenses = sum(1 for group in snapshot.get("groups", [])
                                      if group.get("name", "").startswith(prefix) and group.get("units"))
                maximum = int(commander_rules.get("maximum_defense_packages_per_base", 3))
                if active_defenses >= maximum:
                    self.json_response(400, {"ok": False,
                                             "error": f"Defense limit reached for {defense_base['name']} ({maximum})"})
                    return
            if op in ("spawn", "attack_base", "defend_base"):
                coalition = {"red": 1, "blue": 2}[side]
                prefix = f"FoW {side.title()} "
                active_units = sum(len(group.get("units", [])) for group in snapshot.get("groups", [])
                                   if group.get("coalition") == coalition and
                                   group.get("category") == 2 and
                                   group.get("name", "").startswith(prefix) and
                                   (" Assault " in group["name"] or " Defense " in group["name"]))
                requested_units = len(catalog[side][template]["units"])
                maximum_units = int(commander_rules.get("maximum_dynamic_ground_units_per_side", 80))
                if active_units + requested_units > maximum_units:
                    self.json_response(400, {"ok": False,
                                             "error": f"Dynamic ground unit limit reached ({maximum_units})"})
                    return
            elif op == "spawn_air":
                coalition = {"red": 1, "blue": 2}[side]
                active_aircraft = sum(len(group.get("units", [])) for group in snapshot.get("groups", [])
                                      if group.get("coalition") == coalition and
                                      group.get("category") == 0)
                maximum_aircraft = int(scenario_rules()[1].get("maximum_active_aircraft_per_side", 12))
                if active_aircraft >= maximum_aircraft:
                    self.json_response(400, {"ok": False,
                                             "error": f"Active aircraft limit reached ({maximum_aircraft})"})
                    return
            if op not in ("spawn", "spawn_air", "attack_base", "defend_base"):
                groups = snapshot.get("groups", [])
                allowed = {"blue": 2, "red": 1, "admin": None}[side]
                required_category = 0 if op in ("air_move", "set_mission", "rtb", "scramble") else 2
                matching_groups = [g for g in groups
                                   if g.get("name") == name
                                   and (op == "alias" or g.get("category") == required_category)
                                   and g.get("coalition") in (1, 2)
                                   and (allowed is None or g.get("coalition") == allowed)
                                   and g.get("units")]
                if not matching_groups:
                    self.json_response(400, {"ok": False, "error": "Choose an active group on this side"})
                    return
                active_group = matching_groups[0]
                alert_names = {flight.get("name") for flight in scenario_alert_flights()}
                if name in alert_names:
                    was_scrambled = any(
                        order.get("group_name") == name and
                        order.get("op") == "scramble" and
                        order.get("state") == "accepted"
                        for order in store.dashboard()["orders"]
                    )
                    if op == "scramble" and was_scrambled:
                        self.json_response(400, {"ok": False,
                                                 "error": "That alert flight has already been scrambled"})
                        return
                    if op in ("air_move", "set_mission", "rtb") and not was_scrambled:
                        self.json_response(400, {"ok": False,
                                                 "error": "Scramble this parked alert flight before assigning another order"})
                        return
            if op == "alias":
                store.set_alias(name, alias)
                self.json_response(200, {"ok": True, "group": name, "alias": alias})
                return
            # Validate all catalog-dependent choices before recording or sending an order.
            try:
                if op in ("air_move", "set_mission", "rtb"):
                    lead = active_group["units"][0]
                    air_config = json.loads(AIR_CATALOG.read_text())
                    matching = [p for presets in air_config["presets"].values() for p in presets.values()
                                if p["dcs_type"] == lead["type"]]
                    speed_mps = matching[0]["speed_mps"] if matching else 210
                    if op == "set_mission" and mission_type != "patrol" and not any(
                            p["mission_type"] == mission_type for p in matching):
                        raise ValueError("Aircraft does not support that mission")
                    if op == "rtb":
                        group_side = {1: "red", 2: "blue"}[active_group["coalition"]]
                        group_coalition = {"red": 1, "blue": 2}[group_side]
                        airbase = next((base for base in snapshot.get("airbases", [])
                                        if base.get("name") == rtb_base and
                                        base.get("coalition") == group_coalition), None)
                        if airbase is None:
                            raise ValueError("Choose a friendly recovery base")
                elif op == "spawn_air":
                    group_template = json.loads(AIR_TEMPLATES.read_text()).get(side, {}).get(template, {}).get("group")
                    if group_template is None:
                        raise ValueError("Aircraft template missing; run scripts/build-air-catalog.sh")
            except (ValueError, KeyError) as error:
                self.json_response(400, {"ok": False, "error": str(error)})
                return
            order_id = uuid.uuid4().hex
            store.create_order(order_id, op, name, lat, lon, altitude_m, mission_type_val, loadout_val, rtb_base_val)
            try:
                if op in ("attack_base", "defend_base"):
                    template_config = catalog[side][template]
                    role = "Assault" if op == "attack_base" else "Defense"
                    actual_name = f"FoW {side.title()} {role} {target_base} {order_id[:3]}"
                    spawn_data = dcs_structures.build_ground_spawn_data(
                        side, template_config, actual_name,
                        approach["lat"], approach["lon"],
                        assault_destination if op == "attack_base" else None)
                    result = exchange(args.bridge_host, args.bridge_port, "spawn_group",
                                      request_id=order_id, **spawn_data)
                    if result.get("ok"):
                        store.rename_order_group(order_id, actual_name)
                elif op == "spawn_air":
                    air_catalog_data = json.loads(AIR_CATALOG.read_text())
                    preset_config = air_catalog_data["presets"][side][template]
                    actual_name = custom_name if custom_name else f"FoW {side.title()} {preset_config['label']} {order_id[:3]}"
                    spawn_lat, spawn_lon = dcs_structures.air_start_position(lat, lon)

                    spawn_data = dcs_structures.build_air_spawn_data(
                        side=side,
                        preset_config=preset_config,
                        group_template=group_template,
                        spawn_lat=spawn_lat,
                        spawn_lon=spawn_lon,
                        mission_lat=lat,
                        mission_lon=lon,
                        group_name=actual_name
                    )
                    result = exchange(args.bridge_host, args.bridge_port, "spawn_group",
                                    request_id=order_id, **spawn_data)
                    if result.get("ok"):
                        store.rename_order_group(order_id, actual_name)
                elif op == "spawn":
                    template_config = catalog[side][template]
                    actual_name = f"FoW {side.title()} Defense {defense_base['name']} {order_id[:3]}"
                    spawn_data = dcs_structures.build_ground_spawn_data(
                        side, template_config, actual_name, lat, lon)
                    result = exchange(args.bridge_host, args.bridge_port, "spawn_group",
                                      request_id=order_id, **spawn_data)
                    if result.get("ok"):
                        store.rename_order_group(order_id, actual_name)
                        if custom_name:
                            store.set_alias(actual_name, custom_name)
                else:
                    lead = active_group["units"][0]
                    if op == "scramble":
                        result = exchange(args.bridge_host, args.bridge_port, "set_command",
                                          request_id=order_id, group_name=name,
                                          command_data=dcs_structures.build_start_command())
                    elif op == "move":
                        route_data = dcs_structures.build_ground_route(
                            lead["lat"], lead["lon"], lat, lon)
                        result = exchange(args.bridge_host, args.bridge_port, "set_route",
                                          request_id=order_id, group_name=name,
                                          route_data=route_data)
                    elif op in ("air_move", "set_mission"):
                        selected_mission = mission_type if op == "set_mission" else "transit"
                        route = dcs_structures.build_route_update(
                            selected_mission, lead["lat"], lead["lon"], lat, lon,
                            altitude_m, speed_mps)
                        result = exchange(args.bridge_host, args.bridge_port, "set_route",
                                          request_id=order_id, group_name=name, **route)
                    elif op == "rtb":
                        result = exchange(args.bridge_host, args.bridge_port, "set_task",
                                          request_id=order_id, group_name=name,
                                          task_data=dcs_structures.build_rtb_task(
                                              rtb_base, airbase["lat"], airbase["lon"],
                                              lead["lat"], lead["lon"], lead["y"],
                                              min(180, speed_mps)))
                    elif op == "hold":
                        result = exchange(args.bridge_host, args.bridge_port, "set_task",
                                          request_id=order_id, group_name=name,
                                          task_data={"id": "Hold", "params": {}})
                    else:
                        option = dcs_structures.build_roe_option(mode)
                        result = exchange(args.bridge_host, args.bridge_port, "set_option",
                                          request_id=order_id, group_name=name, **option)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                store.finish_order(order_id, "unknown", str(error))
                self.json_response(502, {"ok": False, "error": str(error), "order_id": order_id, "state": "unknown"})
                return
            order_state = "accepted" if result.get("ok") else "rejected"
            if op in ("spawn", "attack_base", "defend_base") and result.get("ok") and result.get("result", "").startswith("SPAWN_ACCEPTED:"):
                group_name = result["result"].split(":", 1)[1].split(";", 1)[0]
                store.rename_order_group(order_id, group_name)
                if result["result"].endswith(";ROE=OPEN_FIRE"):
                    store.set_roe(group_name, "open_fire")
            if op == "spawn_air" and result.get("ok") and result.get("result", "").startswith("SPAWN_ACCEPTED:"):
                # Generic bridge returns SPAWN_ACCEPTED, name already set above
                pass
            if op == "set_roe" and result.get("ok"):
                store.set_roe(name, mode)
            store.finish_order(order_id, order_state, result.get("result") or result.get("error") or "No detail")
            self.json_response(200 if result.get("ok") else 400,
                               {**result, "order_id": order_id, "state": order_state})

        def log_message(self, format: str, *values: object) -> None:
            pass

    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((args.listen, args.port), Handler)
    print(f"FoW server: http://{args.listen}:{args.port}/ (database: {args.db})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
