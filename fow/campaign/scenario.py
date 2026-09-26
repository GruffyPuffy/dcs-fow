"""Load and validate campaign scenarios independently of DCS."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Literal

from .models import Side


TargetOwnership = Literal["friendly", "not_friendly"]


ObjectiveKind = Literal["zone", "carrier"]
Difficulty = Literal["easy", "normal", "hard"]


@dataclass(frozen=True)
class Objective:
    id: str
    label: str
    lat: float
    lon: float
    connections: tuple[str, ...]
    initial_owner: Side | None
    income: int
    defense_positions: tuple[tuple[float, float], ...]
    kind: ObjectiveKind = "zone"
    difficulty: Difficulty = "normal"


@dataclass(frozen=True)
class ActionRule:
    id: str
    label: str
    cost: int
    target_ownership: TargetOwnership
    requires_connection: bool
    package: str | None


@dataclass(frozen=True)
class AssetPackage:
    id: str
    label: str
    variants: dict[Side, str]
    # Optional per-difficulty template overrides for garrison-style packages,
    # so easy objectives spawn lighter defenses than hard ones.
    tiers: dict[str, dict[Side, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Economy:
    income_interval_seconds: int
    general_reserve: int
    general_seed: int
    red_opening_endowment: int = 0


@dataclass(frozen=True)
class AirStation:
    waypoints: tuple[tuple[float, float], tuple[float, float]]
    on_station_seconds: int


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    map: str
    starting_resources: int
    objectives: dict[str, Objective]
    actions: dict[str, ActionRule]
    assets: dict[str, AssetPackage]
    air_stations: dict[Side, dict[str, AirStation]]
    economy: Economy
    slot_unlocks: dict[str, str] = field(default_factory=dict)

    def mission_slot_unlocks(self) -> dict[str, str]:
        """Base name -> controlling objective id, from the mission section."""
        return dict(self.slot_unlocks)

    def as_public_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "map": self.map,
            "starting_resources": self.starting_resources,
            "air_stations": {
                side.value: {
                    role: {
                        "waypoints": [
                            {"lat": position[0], "lon": position[1]}
                            for position in station.waypoints
                        ],
                        "on_station_seconds": station.on_station_seconds,
                    }
                    for role, station in stations.items()
                }
                for side, stations in self.air_stations.items()
            },
            "economy": {
                "income_interval_seconds": self.economy.income_interval_seconds,
                "general_reserve": self.economy.general_reserve,
            },
            "objectives": [
                {
                    "id": objective.id,
                    "label": objective.label,
                    "lat": objective.lat,
                    "lon": objective.lon,
                    "connections": list(objective.connections),
                    "initial_owner": objective.initial_owner.value if objective.initial_owner else None,
                    "income": objective.income,
                    "defense_positions": [list(position) for position in objective.defense_positions],
                    "kind": objective.kind,
                    "difficulty": objective.difficulty,
                }
                for objective in self.objectives.values()
            ],
            "actions": [
                {
                    "id": action.id,
                    "label": action.label,
                    "cost": action.cost,
                    "target_ownership": action.target_ownership,
                    "requires_connection": action.requires_connection,
                    "package": action.package,
                }
                for action in self.actions.values()
            ],
        }


def load_scenario(path: Path) -> Scenario:
    data = json.loads(path.read_text())
    objective_data = data["objectives"]
    objectives = {
        objective_id: Objective(
            id=objective_id,
            label=value["label"],
            lat=float(value["lat"]),
            lon=float(value["lon"]),
            connections=tuple(value.get("connections", [])),
            initial_owner=Side(value["initial_owner"]) if value.get("initial_owner") else None,
            income=int(value.get("income", 0)),
            kind=value.get("kind", "zone"),
            difficulty=value.get("difficulty", "normal"),
            defense_positions=tuple(
                (float(position["lat"]), float(position["lon"]))
                for position in value.get("defense_positions", [])
            ),
        )
        for objective_id, value in objective_data.items()
    }
    assets = {
        asset_id: AssetPackage(
            id=asset_id,
            label=value["label"],
            variants={Side(side): variant for side, variant in value["variants"].items()},
            tiers={
                difficulty: {Side(side): variant for side, variant in variants.items()}
                for difficulty, variants in value.get("tiers", {}).items()
            },
        )
        for asset_id, value in data["assets"].items()
    }
    actions = {
        action_id: ActionRule(
            id=action_id,
            label=value["label"],
            cost=int(value["cost"]),
            target_ownership=value["target_ownership"],
            requires_connection=bool(value.get("requires_connection", False)),
            package=value.get("package"),
        )
        for action_id, value in data["actions"].items()
    }
    economy_data = data["economy"]
    scenario = Scenario(
        id=data["id"],
        name=data["name"],
        map=data["map"],
        starting_resources=int(data["starting_resources"]),
        objectives=objectives,
        actions=actions,
        assets=assets,
        air_stations={
            Side(side): {
                role: AirStation(
                    waypoints=tuple(
                        (float(position["lat"]), float(position["lon"]))
                        for position in station["waypoints"]
                    ),
                    on_station_seconds=int(station["on_station_seconds"]),
                )
                for role, station in stations.items()
            }
            for side, stations in data.get("air_stations", {}).items()
        },
        economy=Economy(
            income_interval_seconds=int(economy_data["income_interval_seconds"]),
            general_reserve=int(economy_data["general_reserve"]),
            general_seed=int(economy_data["general_seed"]),
            red_opening_endowment=int(economy_data.get("red_opening_endowment", 0)),
        ),
        slot_unlocks=dict(data.get("mission", {}).get("slot_unlocks", {})),
    )
    _validate(scenario)
    return scenario


def _validate(scenario: Scenario) -> None:
    if scenario.starting_resources < 0:
        raise ValueError("Starting resources cannot be negative")
    if scenario.economy.income_interval_seconds <= 0:
        raise ValueError("Income interval must be positive")
    if not 0 <= scenario.economy.general_reserve <= scenario.starting_resources:
        raise ValueError("General reserve must fit within starting resources")
    homes = {side: 0 for side in Side}
    for objective in scenario.objectives.values():
        if objective.initial_owner:
            homes[objective.initial_owner] += 1
        if not objective.defense_positions:
            raise ValueError(f"Objective {objective.id} needs defense positions")
        if objective.kind not in ("zone", "carrier"):
            raise ValueError(f"Objective {objective.id} has unknown kind {objective.kind}")
        if objective.difficulty not in ("easy", "normal", "hard"):
            raise ValueError(f"Objective {objective.id} has unknown difficulty {objective.difficulty}")
        for neighbor in objective.connections:
            if neighbor not in scenario.objectives:
                raise ValueError(f"Objective {objective.id} connects to unknown objective {neighbor}")
            if objective.id not in scenario.objectives[neighbor].connections:
                raise ValueError(f"Connection {objective.id}-{neighbor} is not bidirectional")
    if any(count == 0 for count in homes.values()):
        raise ValueError("Each side needs at least one initially owned objective")
    for side in Side:
        stations = scenario.air_stations.get(side, {})
        for role in ("awacs", "tanker"):
            if role not in stations:
                raise ValueError(f"{side.value.title()} needs an {role} station")
            station = stations[role]
            if len(station.waypoints) != 2:
                raise ValueError(f"{side.value.title()} {role} station needs two waypoints")
            if station.on_station_seconds <= 0:
                raise ValueError(f"{side.value.title()} {role} station duration must be positive")
    for action in scenario.actions.values():
        if action.cost < 0:
            raise ValueError(f"Action {action.id} has a negative cost")
        if action.target_ownership not in ("friendly", "not_friendly"):
            raise ValueError(f"Action {action.id} has invalid target ownership")
        if action.package and action.package not in scenario.assets:
            raise ValueError(f"Action {action.id} uses unknown package {action.package}")
    for asset in scenario.assets.values():
        if set(asset.variants) != set(Side):
            raise ValueError(f"Asset {asset.id} must define symmetric Red and Blue variants")