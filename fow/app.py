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
from .runtime import RuntimeCheckpoint


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DEFAULT_SCENARIO = ROOT / "scenarios" / "caucasus_pve.json"
DEFAULT_CHECKPOINT = ROOT.parent / "data" / "fow-runtime.json"


class FoWService:
    def __init__(self, scenario_path: Path, dcs_gateway: DcsGateway,
                 clock=time.monotonic, wall_clock=time.time,
                 checkpoint_path: Path | None = None):
        self.scenario = load_scenario(scenario_path)
        self.engine = CampaignEngine(self.scenario)
        self.dcs = dcs_gateway
        self.manual = ManualOperations(dcs_gateway)
        self.executor = CampaignExecutor(self.scenario, dcs_gateway)
        self._clock = clock
        self._wall_clock = wall_clock
        self._checkpoint = RuntimeCheckpoint(checkpoint_path) if checkpoint_path else None
        self._lock = Lock()
        self._campaign: CampaignState | None = None
        self._generals = self._new_generals()
        self._deployments: list[dict[str, Any]] = []
        self._next_income_at: float | None = None
        self._last_dcs_mission_id: str | None = None
        self._restore()

    def _new_generals(self) -> dict[Side, AlgorithmicGeneral]:
        economy = self.scenario.economy
        return {
            side: AlgorithmicGeneral(
                side, self.engine, economy.general_seed, economy.general_reserve)
            for side in Side
        }

    def new_game(self) -> dict[str, Any]:
        with self._lock:
            if self._campaign is not None:
                return self._campaign.as_dict()
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
            self._next_income_at = self._clock() + self.scenario.economy.income_interval_seconds
            self._save_locked()
        self._execute_jobs(jobs)
        with self._lock:
            return self._campaign.as_dict()

    def tick(self, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        self._reconcile_deployments()
        jobs = []
        with self._lock:
            if self._campaign is None or self._next_income_at is None:
                return
            changed = False
            while now >= self._next_income_at:
                changed = True
                self.engine.collect_income(self._campaign)
                for side in Side:
                    choice = self._generals[side].choose_action(self._campaign)
                    if choice:
                        plan = self.engine.apply_action(
                            self._campaign, side, choice.action, choice.target)
                        sequence = len(self._campaign.events)
                        jobs.append((plan, sequence))
                        self._deployments.append(self._deployment(plan, sequence))
                self._next_income_at += self.scenario.economy.income_interval_seconds
            if changed:
                self._save_locked()
        self._execute_jobs(jobs)

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
        })

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
            "generals": {
                "policy": "seeded_algorithm",
                "reserve": self.scenario.economy.general_reserve,
                "income_interval_seconds": self.scenario.economy.income_interval_seconds,
                "next_income_seconds": max(0, round(self._next_income_at - self._clock()))
                if self._next_income_at is not None else None,
            },
            "deployments": list(self._deployments),
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