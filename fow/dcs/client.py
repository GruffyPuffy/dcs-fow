"""Transport and current-state holder for the generic DCS bridge."""

import json
import socket
from threading import Lock
from typing import Any
import uuid

from .snapshot import DcsSnapshot


class DcsClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 10309,
                 timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(self, operation: str, **fields: object) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        request = {"v": 1, "id": request_id, "op": operation, **fields}
        payload = (json.dumps(request, separators=(",", ":")) + "\n").encode()
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
            connection.settimeout(self.timeout)
            connection.sendall(payload)
            with connection.makefile("rb") as stream:
                line = stream.readline(2 * 1024 * 1024 + 1)
        if not line.endswith(b"\n") or len(line) > 2 * 1024 * 1024:
            raise RuntimeError("No complete response from DCS bridge")
        reply = json.loads(line)
        if not isinstance(reply, dict) or reply.get("v") != 1 or reply.get("id") != request_id:
            raise RuntimeError("Unexpected DCS bridge response")
        return reply

    def status(self) -> DcsSnapshot:
        return DcsSnapshot.from_reply(self.request("status"))


class DcsGateway:
    """Owns the latest raw DCS observation and all future DCS commands."""

    def __init__(self, client: DcsClient):
        self.client = client
        self._lock = Lock()
        self._snapshot: DcsSnapshot | None = None
        self._error: str | None = "Waiting for DCS"

    def refresh(self) -> None:
        try:
            snapshot = self.client.status()
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            with self._lock:
                self._error = str(error)
            return
        with self._lock:
            self._snapshot = snapshot
            self._error = None

    def set_slot_access(self, group_names: list[str], enabled: bool) -> dict[str, Any]:
        if not group_names or any(not isinstance(name, str) or not name for name in group_names):
            raise ValueError("Slot access requires at least one valid group name")
        return self.client.request("set_slot_access", slots=group_names, enabled=enabled)

    def public_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self._snapshot is not None and self._error is None,
                "error": self._error,
                "snapshot": self._snapshot.summary() if self._snapshot else None,
            }