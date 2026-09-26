"""Build the minimal FoW mission shell (requires pydcs 0.15.0)."""

import argparse
import json
from pathlib import Path

import dcs


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = ROOT / "fow" / "scenarios" / "caucasus_pve.json"
DEFAULT_OUTPUT = ROOT / "fow" / "missions" / "fow-shell.miz"
SLOT_CATALOG = ROOT / "fow" / "assets" / "slot_catalog.json"
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


def helicopter_type(name: str):
    helicopter = getattr(dcs.helicopters, name, None) or dcs.helicopters.helicopter_map.get(name)
    if helicopter is None:
        raise ValueError(f"Unknown helicopter type: {name}")
    return helicopter


def unit_type(name: str):
    return aircraft_type(name) if name in dcs.planes.plane_map else helicopter_type(name)


def start_type_for(start: str):
    starts = {
        "runway": dcs.mission.StartType.Runway,
        "hot": dcs.mission.StartType.Warm,
        "cold": dcs.mission.StartType.Cold,
    }
    if start not in starts:
        raise ValueError(f"Unknown slot start type: {start}")
    return starts[start]


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


def add_catalog_slots(mission: dcs.Mission, catalog: dict, country) -> None:
    """Bake player slots at every catalog base. All start disabled; the FoW
    server opens them at runtime through set_slot_access."""
    used_parking = {}
    placed = {}
    for base in catalog["bases"]:
        airport = mission.terrain.airports[base["name"]]
        limit = int(base.get("parking_limit", 12))
        used = used_parking.setdefault(base["name"], 0)
        big_slots = [slot for slot in airport.parking_slots if slot.length >= 40]
        regular_slots = [slot for slot in airport.parking_slots if slot.length < 40]
        for category in ("fixed_wing", "helicopters"):
            for entry in catalog[category]:
                aircraft = unit_type(entry["aircraft"])
                needs_big = entry.get("requires_big_slot", False)
                for index, start in enumerate(entry["starts"]):
                    if used >= limit:
                        break
                    name = f"FoW {base['name']} {entry['label']} {start.title()}"
                    if index:
                        name = f"{name} {index + 1}"
                    parking_slots = None
                    if start != "runway":
                        pool = big_slots if needs_big else regular_slots
                        if not pool:
                            continue
                        parking_slots = [pool[used % len(pool)]]
                    group = mission.flight_group_from_airport(
                        country=country,
                        name=name,
                        aircraft_type=aircraft,
                        airport=airport,
                        start_type=start_type_for(start),
                        group_size=1,
                        parking_slots=parking_slots,
                    )
                    group.units[0].skill = dcs.unit.Skill.Client
                    group.units[0].name = name
                    used += 1
        placed[base["name"]] = used
    print(f"catalog_slots={sum(placed.values())}")


def build(scenario_path: Path, output: Path) -> None:
    scenario = json.loads(scenario_path.read_text())
    if scenario.get("map") != "Caucasus":
        raise ValueError("Only the Caucasus terrain is currently supported")
    config = scenario["mission"]
    if any(slot["side"] != "blue" for slot in config["client_slots"]):
        raise ValueError("The initial PvE shell supports Blue client slots only")
    catalog = json.loads(SLOT_CATALOG.read_text())

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
    add_catalog_slots(mission, catalog, countries[config["player_side"]])

    player_side = config["player_side"]
    slot_access = {}
    for slot in config["client_slots"]:
        objective_id = slot.get("unlock_objective")
        objective = scenario["objectives"].get(objective_id)
        if not objective:
            raise ValueError(f"Slot {slot['name']} has unknown unlock objective")
        slot_access[slot["name"]] = objective.get("initial_owner") == player_side
    for base in catalog["bases"]:
        for entry in catalog["fixed_wing"] + catalog["helicopters"]:
            for index, start in enumerate(entry["starts"]):
                name = f"FoW {base['name']} {entry['label']} {start.title()}"
                if index:
                    name = f"{name} {index + 1}"
                slot_access[name] = False
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