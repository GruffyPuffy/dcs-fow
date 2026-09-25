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

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "phase": self.phase.value,
            "resources": {side.value: value for side, value in self.resources.items()},
            "objectives": {
                objective_id: {
                    "owner": objective.owner.value if objective.owner else None,
                    "defense_level": objective.defense_level,
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