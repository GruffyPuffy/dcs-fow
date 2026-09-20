#!/usr/bin/env python3
"""Local read-only map viewer for live FoW bridge status."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

from fowctl import exchange


PAGE = Path(__file__).resolve().parent.parent / "viewer" / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=10309)
    parser.add_argument("--interval", type=int, default=10, help="DCS poll interval in seconds")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be positive")

    lock = threading.Lock()
    state = {"snapshot": None, "received_at": None, "error": "Waiting for first DCS response"}
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            try:
                result = exchange(args.bridge_host, args.bridge_port, "status")
                if not result.get("ok"):
                    raise RuntimeError(result.get("error") or result.get("result") or "DCS rejected status")
                with lock:
                    state.update(snapshot=result, received_at=time.time(), error=None)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                with lock:
                    state["error"] = str(error)
            stop.wait(args.interval)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                body = PAGE.read_bytes()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/status":
                with lock:
                    payload = state.copy()
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

        def log_message(self, format: str, *values: object) -> None:
            pass

    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((args.listen, args.port), Handler)
    print(f"FoW viewer: http://{args.listen}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
