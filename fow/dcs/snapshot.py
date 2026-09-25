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
        )

    def summary(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission_time": self.mission_time,
            "groups": len(self.groups),
            "units": sum(len(group.get("units", [])) for group in self.groups),
            "airbases": len(self.airbases),
        }