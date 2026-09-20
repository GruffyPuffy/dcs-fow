"""Build the single Caucasus FoW mission (requires pydcs 0.15.0).

Run: python build_mission.py fow.miz
Keep one mission and add or change client slots here as the project develops.
"""

from pathlib import Path
import json
import sys

import dcs


def client(group: dcs.unitgroup.FlyingGroup, name: str) -> None:
    group.units[0].skill = dcs.unit.Skill.Client
    group.units[0].name = name


def lua_literal(value):
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return "{" + ",".join("[" + lua_literal(k) + "]=" + lua_literal(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "{" + ",".join(lua_literal(v) for v in value) + "}"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise ValueError(f"Unsupported catalog value: {value!r}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python build_mission.py OUTPUT.miz")

    output = Path(sys.argv[1])
    mission = dcs.Mission()
    usa = mission.country("USA")
    batumi = mission.terrain.airports["Batumi"]
    # pydcs leaves every airfield neutral by default. Ground client slots at
    # Batumi belong to Blue, so the airfield warehouse must belong to Blue too.
    batumi.set_blue()
    hornet = dcs.planes.FA_18C_hornet
    catalog = json.loads(Path(__file__).with_name("spawn_catalog.json").read_text())
    unit_catalog = json.loads(Path(__file__).with_name("unit_catalog.json").read_text())
    for side in ("blue", "red"):
        overlap = set(catalog[side]) & set(unit_catalog[side])
        if overlap:
            raise ValueError(f"Duplicate spawn IDs for {side}: {overlap}")
        catalog[side].update(unit_catalog[side])

    client(
        mission.flight_group_inflight(
            country=usa,
            name="FoW Hornet Air",
            aircraft_type=hornet,
            position=dcs.Point(
                batumi.position.x - 10000,
                batumi.position.y + 5000,
                mission.terrain,
            ),
            altitude=3000,
            speed=200,
            group_size=1,
        ),
        "FoW Hornet Air",
    )
    client(
        mission.flight_group_from_airport(
            country=usa,
            name="FoW Hornet Runway",
            aircraft_type=hornet,
            airport=batumi,
            start_type=dcs.mission.StartType.Runway,
            group_size=1,
        ),
        "FoW Hornet Runway",
    )
    stand_10 = next(slot for slot in batumi.parking_slots if slot.slot_name == "10")
    client(
        mission.flight_group_from_airport(
            country=usa,
            name="FoW Hornet Ramp",
            aircraft_type=hornet,
            airport=batumi,
            start_type=dcs.mission.StartType.Cold,
            group_size=1,
            parking_slots=[stand_10],
        ),
        "FoW Hornet Ramp",
    )

    # One harmless vehicle per side, far apart. Test orders use these groups.
    gudauta = mission.terrain.airports["Gudauta"]
    mission.vehicle_group(
        country=usa,
        name="FoW Blue Ground",
        _type=dcs.vehicles.Unarmed.M_818,
        position=dcs.Point(batumi.position.x + 2500, batumi.position.y + 2500, mission.terrain),
    )
    mission.vehicle_group(
        country=mission.country("Russia"),
        name="FoW Red Ground",
        _type=dcs.vehicles.Unarmed.Ural_375,
        position=dcs.Point(gudauta.position.x + 2500, gudauta.position.y + 2500, mission.terrain),
    )

    # Capture valid pydcs AI flight data, then remove the template groups. The
    # mission Lua clones these known-good tables for the manual air-start trial.
    air_catalog = {}
    air_config = json.loads(Path(__file__).with_name("air_trial.json").read_text())
    for side, country, airport, aircraft in (
        ("blue", usa, batumi, dcs.planes.FA_18C_hornet),
        ("red", mission.country("Russia"), gudauta, dcs.planes.MiG_29S),
    ):
        group = mission.flight_group_inflight(
            country=country, name=f"FoW {side} air template", aircraft_type=aircraft,
            position=dcs.Point(airport.position.x - 15000, airport.position.y + 5000, mission.terrain),
            altitude=5000, speed=750, maintask=dcs.task.Nothing, group_size=1,
        )
        group.units[0].skill = dcs.unit.Skill.High
        data = group.dict()
        data.pop("groupId", None)
        for unit in data["units"].values():
            unit.pop("unitId", None)
        for waypoint in data["route"]["points"].values():
            waypoint["task"] = {"id": "ComboTask", "params": {"tasks": {}}}
        if not mission.remove_plane_group(group):
            raise RuntimeError("Could not remove temporary AI flight template")
        air_catalog[side] = {"test_flight": {"label": air_config[side]["test_flight"]["label"], "group": data}}

    mission.init_script = ("FoWAirCatalog = " + lua_literal(air_catalog) + "\n" +
                           "FoWSpawnCatalog = " + lua_literal(catalog) + "\n" +
                           Path(__file__).with_name("fow_bridge.lua").read_text())

    output.parent.mkdir(parents=True, exist_ok=True)
    mission.save(str(output))
    print(output)


if __name__ == "__main__":
    main()
