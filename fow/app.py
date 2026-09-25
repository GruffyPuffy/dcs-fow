#!/usr/bin/env python3
"""Run the second-generation FoW campaign service and web shell."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from urllib.parse import urlsplit

from .campaign import CampaignEngine, CampaignState, load_scenario
from .dcs import DcsClient, DcsGateway, ManualOperations


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DEFAULT_SCENARIO = ROOT / "scenarios" / "caucasus_pve.json"


class FoWService:
    def __init__(self, scenario_path: Path, dcs_gateway: DcsGateway):
        self.scenario = load_scenario(scenario_path)
        self.engine = CampaignEngine(self.scenario)
        self.dcs = dcs_gateway
        self.manual = ManualOperations(dcs_gateway)
        self._lock = Lock()
        self._campaign: CampaignState | None = None

    def new_game(self) -> dict[str, Any]:
        with self._lock:
            self._campaign = self.engine.new_game()
            return self._campaign.as_dict()

    def overview(self) -> dict[str, Any]:
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
        return {
            "campaign": campaign,
            "scenario": self.scenario.as_public_dict(),
            "legal_actions": legal_actions,
            "dcs": self.dcs.public_status(),
            "persistence": {"enabled": False, "status": "planned"},
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
                if request not in ({}, {"scenario": service.scenario.id}):
                    self.send_json(400, {"ok": False, "error": "Unknown scenario"})
                    return
                self.send_json(201, {"ok": True, "campaign": service.new_game()})
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
    args = parser.parse_args()

    gateway = DcsGateway(DcsClient(args.bridge_host, args.bridge_port))
    service = FoWService(args.scenario, gateway)
    stop = Event()

    def poll_dcs() -> None:
        while not stop.is_set():
            gateway.refresh()
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