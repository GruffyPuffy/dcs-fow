"""Atomic JSON checkpoint storage for the current FoW runtime."""

import json
import os
from pathlib import Path
from typing import Any


CHECKPOINT_VERSION = 1


class RuntimeCheckpoint:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        if data.get("version") != CHECKPOINT_VERSION:
            raise ValueError(f"Unsupported runtime checkpoint version: {data.get('version')}")
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        payload = json.dumps(
            {"version": CHECKPOINT_VERSION, **data}, indent=2, sort_keys=True) + "\n"
        with temporary.open("w") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)