"""DCS-derived awareness: attrition tracking, objective capture, contact tracks.

This module turns raw DCS observations into campaign-relevant facts. It never
issues orders; the generals and the service read its output.
"""

from collections import deque
import math
from typing import Any


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    latitude = math.radians((lat1 + lat2) / 2)
    return math.hypot((lat2 - lat1) * 111_320.0,
                      (lon2 - lon1) * 111_320.0 * math.cos(latitude))


class Awareness:
    """Tracks deployment attrition, objective presence, and contact trails."""

    def __init__(self, track_seconds: float = 600.0):
        self.track_seconds = track_seconds
        self._tracks: dict[str, deque] = {}
        self._last_kill_id = 0

    def state_dict(self) -> dict[str, Any]:
        return {
            "tracks": {name: list(points) for name, points in self._tracks.items()},
            "last_kill_id": self._last_kill_id,
        }

    def restore(self, data: dict[str, Any]) -> None:
        self._tracks = {
            name: deque((tuple(point) for point in points), maxlen=self._capacity())
            for name, points in data.get("tracks", {}).items()
        }
        self._last_kill_id = int(data.get("last_kill_id", 0))

    def _capacity(self) -> int:
        # 5 s poll cadence; keep a little headroom above the window.
        return int(self.track_seconds / 5) + 8

    def update_tracks(self, snapshot: dict[str, Any]) -> None:
        """Record observed positions for every unit, keyed by group name."""
        mission_time = float(snapshot.get("mission_time", 0))
        capacity = self._capacity()
        for group in snapshot.get("groups", []):
            name = group.get("name")
            if not name or not group.get("units"):
                continue
            track = self._tracks.setdefault(name, deque(maxlen=capacity))
            for unit in group["units"]:
                if not (NumberOk(unit.get("lat")) and NumberOk(unit.get("lon"))):
                    continue
                track.append((
                    mission_time,
                    float(unit["lat"]),
                    float(unit["lon"]),
                    float(unit.get("speed_mps", 0) or 0),
                ))
                break  # one sample per group (the lead unit) is enough
        # Drop tracks for groups that no longer exist.
        live = {group.get("name") for group in snapshot.get("groups", [])}
        for name in list(self._tracks):
            if name not in live:
                del self._tracks[name]

    def new_kill_reports(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Kill reports not yet consumed, in order."""
        reports = [report for report in snapshot.get("kill_reports", [])
                   if int(report.get("id", 0)) > self._last_kill_id]
        if reports:
            self._last_kill_id = max(int(report["id"]) for report in reports)
        return reports

    def deployment_losses(self, deployment_names: set[str],
                          snapshot: dict[str, Any]) -> dict[str, int]:
        """Units lost per deployment name, derived from kill reports."""
        live_units: dict[str, int] = {}
        for group in snapshot.get("groups", []):
            name = group.get("name")
            if name in deployment_names:
                live_units[name] = len(group.get("units", []))
        return live_units

    def objective_presence(self, scenario, snapshot: dict[str, Any]) -> dict[str, dict[str, int]]:
        """Count ground units of each coalition near each objective."""
        presence: dict[str, dict[str, int]] = {
            objective_id: {1: 0, 2: 0} for objective_id in scenario.objectives}
        radius = 3500.0
        for group in snapshot.get("groups", []):
            if group.get("category") != 2:  # ground units only
                continue
            units = group.get("units", [])
            if not units:
                continue
            lead = units[0]
            if not (NumberOk(lead.get("lat")) and NumberOk(lead.get("lon"))):
                continue
            for objective_id, objective in scenario.objectives.items():
                if distance_m(lead["lat"], lead["lon"],
                              objective.lat, objective.lon) <= radius:
                    coalition = group.get("coalition")
                    if coalition in (1, 2):
                        presence[objective_id][coalition] += len(units)
                    break
        return presence


def NumberOk(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
