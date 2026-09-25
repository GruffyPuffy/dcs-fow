"""Typed view of state observed from the DCS bridge."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DcsSnapshot:
    mission_id: str
    mission_time: float
    groups: tuple[dict[str, Any], ...]
    statics: tuple[dict[str, Any], ...]
    airbases: tuple[dict[str, Any], ...]
    kill_reports: tuple[dict[str, Any], ...]
    awacs_reports: tuple[dict[str, Any], ...]
    awacs_sensor_errors: int

    @classmethod
    def from_reply(cls, reply: dict[str, Any]) -> "DcsSnapshot":
        if reply.get("ok") is not True:
            raise ValueError("DCS status reply was not successful")
        mission_id = reply.get("mission_id")
        mission_time = reply.get("time")
        if not isinstance(mission_id, str) or not mission_id:
            raise ValueError("DCS status has no mission ID")
        if not isinstance(mission_time, (int, float)) or isinstance(mission_time, bool):
            raise ValueError("DCS status has invalid mission time")
        return cls(
            mission_id=mission_id,
            mission_time=float(mission_time),
            groups=tuple(reply.get("groups", [])),
            statics=tuple(reply.get("statics", [])),
            airbases=tuple(reply.get("airbases", [])),
            kill_reports=tuple(reply.get("kill_reports", [])),
            awacs_reports=tuple(reply.get("awacs_reports", [])),
            awacs_sensor_errors=int(reply.get("awacs_sensor_errors", 0)),
        )

    def summary(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_time": self.mission_time,
            "groups": len(self.groups),
            "units": sum(len(group.get("units", [])) for group in self.groups),
            "airbases": len(self.airbases),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_time": self.mission_time,
            "groups": list(self.groups),
            "statics": list(self.statics),
            "airbases": list(self.airbases),
            "kill_reports": list(self.kill_reports),
            "awacs_reports": list(self.awacs_reports),
            "awacs_sensor_errors": self.awacs_sensor_errors,
        }