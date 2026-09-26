"""Small, serializable campaign domain types."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Side(str, Enum):
    RED = "red"
    BLUE = "blue"


class CampaignPhase(str, Enum):
    STOPPED = "stopped"
    ACTIVE = "active"
    ENDED = "ended"


@dataclass(frozen=True)
class ObjectiveState:
    owner: Side | None
    defense_level: int = 0
    # Epoch timestamp when an attacker first held exclusive presence. Capture
    # requires holding through a contest window - a walk-in does not take a
    # base; the defender gets time to reinforce and fight for it.
    contested_since: float | None = None


@dataclass(frozen=True)
class CampaignEvent:
    sequence: int
    kind: str
    side: Side | None
    detail: dict[str, Any]


@dataclass(frozen=True)
class ActionPlan:
    action: str
    side: Side
    target: str
    cost: int
    package: str | None


@dataclass
class CampaignState:
    scenario_id: str
    phase: CampaignPhase
    resources: dict[Side, int]
    objectives: dict[str, ObjectiveState]
    events: list[CampaignEvent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CampaignState":
        return cls(
            scenario_id=data["scenario_id"],
            phase=CampaignPhase(data["phase"]),
            resources={Side(side): int(value) for side, value in data["resources"].items()},
            objectives={
                objective_id: ObjectiveState(
                    owner=Side(value["owner"]) if value.get("owner") else None,
                    defense_level=int(value.get("defense_level", 0)),                    contested_since=value.get("contested_since"),                )
                for objective_id, value in data["objectives"].items()
            },
            events=[
                CampaignEvent(
                    sequence=int(event["sequence"]),
                    kind=event["kind"],
                    side=Side(event["side"]) if event.get("side") else None,
                    detail=dict(event.get("detail", {})),
                )
                for event in data.get("events", [])
            ],
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "phase": self.phase.value,
            "resources": {side.value: value for side, value in self.resources.items()},
            "objectives": {
                objective_id: {
                    "owner": objective.owner.value if objective.owner else None,
                    "defense_level": objective.defense_level,
                    "contested_since": objective.contested_since,
                }
                for objective_id, objective in self.objectives.items()
            },
            "events": [
                {
                    **asdict(event),
                    "side": event.side.value if event.side else None,
                }
                for event in self.events
            ],
        }