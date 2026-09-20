#!/usr/bin/env python3
"""Local manual FoW server: DCS status, orders, and observation history."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
import uuid

from fowctl import exchange
from fow_store import Store


PAGE = Path(__file__).resolve().parent.parent / "viewer" / "index.html"


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
            if self.path == "/":
                body = PAGE.read_bytes()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/status":
                with lock:
                    payload = state.copy()
                payload.update(store.dashboard())
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if self.path == "/api/status" else "public, max-age=60")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path not in ("/api/orders", "/api/move"):
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
                name = request["group"]
                op = request.get("op", "move" if self.path == "/api/move" else None)
                if op not in ("move", "hold"):
                    raise ValueError("Choose move or hold")
                if not isinstance(name, str) or not name or len(name) > 128:
                    raise ValueError("Invalid group")
                lat = lon = None
                if op == "move":
                    lat, lon = request["lat"], request["lon"]
                    if (not isinstance(lat, (int, float)) or isinstance(lat, bool) or
                        not isinstance(lon, (int, float)) or isinstance(lon, bool) or
                        not math.isfinite(lat) or not math.isfinite(lon) or
                        abs(lat) > 90 or abs(lon) > 180):
                        raise ValueError("Invalid map coordinates")
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
            groups = snapshot.get("groups", [])
            if not any(g.get("name") == name and g.get("category") == 2 and
                       g.get("coalition") in (1, 2) and g.get("units") for g in groups):
                self.json_response(400, {"ok": False, "error": "Choose an active ground group"})
                return
            order_id = uuid.uuid4().hex
            store.create_order(order_id, op, name, lat, lon)
            try:
                fields = {"group": name}
                if op == "move":
                    fields.update(lat=lat, lon=lon)
                result = exchange(args.bridge_host, args.bridge_port,
                                  "move_geo" if op == "move" else "hold",
                                  request_id=order_id, **fields)
            except (OSError, RuntimeError, ValueError) as error:
                store.finish_order(order_id, "unknown", str(error))
                self.json_response(502, {"ok": False, "error": str(error), "order_id": order_id, "state": "unknown"})
                return
            order_state = "accepted" if result.get("ok") else "rejected"
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
