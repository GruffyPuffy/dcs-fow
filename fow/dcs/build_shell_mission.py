"""Build the minimal FoW mission shell (requires pydcs 0.15.0)."""

import argparse
import json
from pathlib import Path

import dcs


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = ROOT / "fow" / "scenarios" / "caucasus_pve.json"
DEFAULT_OUTPUT = ROOT / "fow" / "missions" / "fow-shell.miz"
BRIDGE = ROOT / "missions" / "fow_bridge_generic.lua"
SLOT_GUARD = ROOT / "fow" / "dcs" / "slot_guard.lua"


def lua_literal(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{" + ",".join(
            "[" + json.dumps(key) + "]=" + lua_literal(item)
            for key, item in value.items()
        ) + "}"
    raise ValueError(f"Unsupported Lua value: {value!r}")


def aircraft_type(name: str):
    aircraft = getattr(dcs.planes, name, None) or dcs.planes.plane_map.get(name)
    if aircraft is None:
        raise ValueError(f"Unknown aircraft type: {name}")
    return aircraft


def offset_point(mission: dcs.Mission, airport, offset: list[float]) -> dcs.Point:
    return dcs.Point(
        airport.position.x + offset[0],
        airport.position.y + offset[1],
        mission.terrain,
    )


def add_client_slots(mission: dcs.Mission, config: dict, countries: dict,
                     airports: dict) -> None:
    starts = {
        "runway": dcs.mission.StartType.Runway,
        "hot": dcs.mission.StartType.Warm,
        "cold": dcs.mission.StartType.Cold,
    }
    for slot in config["client_slots"]:
        country = countries[slot["side"]]
        airport = airports[slot["base"]]
        aircraft = aircraft_type(slot["aircraft"])
        if slot["start"] == "air":
            group = mission.flight_group_inflight(
                country=country,
                name=slot["name"],
                aircraft_type=aircraft,
                position=offset_point(mission, airport, slot.get("offset_m", [0, 0])),
                altitude=slot["altitude_m"],
                speed=slot["speed_mps"],
                group_size=1,
            )
        else:
            parking_slots = None
            if slot.get("parking"):
                parking_slots = [next(
                    parking for parking in airport.parking_slots
                    if parking.slot_name == slot["parking"]
                )]
            group = mission.flight_group_from_airport(
                country=country,
                name=slot["name"],
                aircraft_type=aircraft,
                airport=airport,
                start_type=starts[slot["start"]],
                group_size=1,
                parking_slots=parking_slots,
            )
        group.units[0].skill = dcs.unit.Skill.Client
        group.units[0].name = slot["name"]


def build(scenario_path: Path, output: Path) -> None:
    scenario = json.loads(scenario_path.read_text())
    if scenario.get("map") != "Caucasus":
        raise ValueError("Only the Caucasus terrain is currently supported")
    config = scenario["mission"]
    if any(slot["side"] != "blue" for slot in config["client_slots"]):
        raise ValueError("The initial PvE shell supports Blue client slots only")

    mission = dcs.Mission()
    countries = {
        side: mission.country(value["country"])
        for side, value in config["coalitions"].items()
    }
    airports = mission.terrain.airports
    for side, value in config["coalitions"].items():
        for airbase_name in value["airbases"]:
            getattr(airports[airbase_name], f"set_{side}")()
    add_client_slots(mission, config, countries, airports)

    player_side = config["player_side"]
    slot_access = {}
    for slot in config["client_slots"]:
        objective_id = slot.get("unlock_objective")
        objective = scenario["objectives"].get(objective_id)
        if not objective:
            raise ValueError(f"Slot {slot['name']} has unknown unlock objective")
        slot_access[slot["name"]] = objective.get("initial_owner") == player_side
    mission.init_script = (
        BRIDGE.read_text()
        + "\nFoWSlotAccess = " + lua_literal(slot_access) + "\n"
        + SLOT_GUARD.read_text()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    mission.save(str(output))
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.scenario, args.output)


if __name__ == "__main__":
    main()