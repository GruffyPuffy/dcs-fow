#!/usr/bin/env python3
"""Local manual FoW server: DCS status, orders, and observation history."""

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
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
        + scenario.get("initial_flights", [])
    return {
        item["name"]: item["display_name"]
        for item in configured if item.get("display_name")
    }


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
            if self.path not in ("/api/orders", "/api/move", "/api/spawn", "/api/spawn-air", "/api/alias", "/api/set-mission", "/api/rtb"):
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
                if self.path == "/api/alias":
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
                    if mission_type not in ("patrol", "CAP"):
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
            if op not in ("spawn", "spawn_air"):
                groups = snapshot.get("groups", [])
                allowed = {"blue": 2, "red": 1, "admin": None}[side]
                required_category = 0 if op in ("air_move", "set_mission", "rtb") else 2
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
            if op == "alias":
                store.set_alias(name, alias)
                self.json_response(200, {"ok": True, "group": name, "alias": alias})
                return
            order_id = uuid.uuid4().hex
            store.create_order(order_id, op, name, lat, lon, altitude_m, mission_type_val, loadout_val, rtb_base_val)
            try:
                if op == "spawn_air":
                    air_catalog_data = json.loads(AIR_CATALOG.read_text())
                    preset_config = air_catalog_data["presets"][side][template]
                    group_template = json.loads(AIR_TEMPLATES.read_text())[side][template]["group"]
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
                    actual_name = custom_name if custom_name else f"FoW {side.title()} {template_config['label']} {order_id[:3]}"
                    spawn_data = dcs_structures.build_ground_spawn_data(
                        side, template_config, actual_name, lat, lon)
                    result = exchange(args.bridge_host, args.bridge_port, "spawn_group",
                                      request_id=order_id, **spawn_data)
                    if result.get("ok"):
                        store.rename_order_group(order_id, actual_name)
                else:
                    lead = active_group["units"][0]
                    if op == "move":
                        route_data = dcs_structures.build_ground_route(
                            lead["lat"], lead["lon"], lat, lon)
                        result = exchange(args.bridge_host, args.bridge_port, "set_route",
                                          request_id=order_id, group_name=name,
                                          route_data=route_data)
                    elif op in ("air_move", "set_mission"):
                        selected_mission = mission_type if op == "set_mission" else "patrol"
                        speed_mps = 250 if selected_mission == "CAP" else 210
                        route = dcs_structures.build_route_update(
                            selected_mission, lead["lat"], lead["lon"], lat, lon,
                            altitude_m, speed_mps)
                        result = exchange(args.bridge_host, args.bridge_port, "set_route",
                                          request_id=order_id, group_name=name, **route)
                    elif op == "rtb":
                        airbase = json.loads(AIRBASE_CATALOG.read_text())[side][rtb_base]
                        result = exchange(args.bridge_host, args.bridge_port, "set_task",
                                          request_id=order_id, group_name=name,
                                          task_data=dcs_structures.build_rtb_task(
                                              rtb_base, airbase["lat"], airbase["lon"],
                                              lead["lat"], lead["lon"], lead["y"]))
                    elif op == "hold":
                        result = exchange(args.bridge_host, args.bridge_port, "set_task",
                                          request_id=order_id, group_name=name,
                                          task_data={"id": "Hold", "params": {}})
                    else:
                        option = dcs_structures.build_roe_option(mode)
                        result = exchange(args.bridge_host, args.bridge_port, "set_option",
                                          request_id=order_id, group_name=name, **option)
            except (OSError, RuntimeError, ValueError) as error:
                store.finish_order(order_id, "unknown", str(error))
                self.json_response(502, {"ok": False, "error": str(error), "order_id": order_id, "state": "unknown"})
                return
            order_state = "accepted" if result.get("ok") else "rejected"
            if op == "spawn" and result.get("ok") and result.get("result", "").startswith("SPAWN_ACCEPTED:"):
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
