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

    # Capture airbases for RTB catalog
    airbase_catalog = {"blue": {}, "red": {}}
    for airport in mission.terrain.airport_list():
        latlng = airport.position.latlng()
        if airport.is_blue():
            airbase_catalog["blue"][airport.name] = {
                "label": airport.name,
                "lat": round(latlng.lat, 6),
                "lon": round(latlng.lng, 6)
            }
        elif airport.is_red():
            airbase_catalog["red"][airport.name] = {
                "label": airport.name,
                "lat": round(latlng.lat, 6),
                "lon": round(latlng.lng, 6)
            }

    # Capture valid pydcs AI flight data, then remove the template groups. The
    # mission Lua clones these known-good tables for the manual air-start trial.
    air_catalog = {"presets": {}, "loadouts": {}}
    air_config = json.loads(Path(__file__).with_name("air_trial.json").read_text())
    air_catalog["loadouts"] = air_config["loadouts"]
    
    for side, country, airport, aircraft in (
        ("blue", usa, batumi, dcs.planes.FA_18C_hornet),
        ("red", mission.country("Russia"), gudauta, dcs.planes.MiG_29S),
    ):
        air_catalog["presets"][side] = {}
        for preset_name, preset_config in air_config["presets"][side].items():
            group = mission.flight_group_inflight(
                country=country, name=f"FoW {side} {preset_name} template", aircraft_type=aircraft,
                position=dcs.Point(airport.position.x - 15000, airport.position.y + 5000, mission.terrain),
                altitude=preset_config["altitude_m"], speed=preset_config["speed_mps"],
                maintask=dcs.task.Nothing, group_size=1,
            )
            group.units[0].skill = dcs.unit.Skill.High
            
            # Apply loadout if specified
            loadout_name = preset_config.get("loadout")
            if loadout_name and loadout_name in air_config["loadouts"][side]:
                loadout = air_config["loadouts"][side][loadout_name]
                for pylon_data in loadout["pylons"].values():
                    # pydcs load_pylon expects (weapon_clsid, pylon_number)
                    group.units[0].pylons[pylon_data["num"]] = {"CLSID": pylon_data["CLSID"]}
            
            data = group.dict()
            data.pop("groupId", None)
            for unit in data["units"].values():
                unit.pop("unitId", None)
            for waypoint in data["route"]["points"].values():
                waypoint["task"] = {"id": "ComboTask", "params": {"tasks": {}}}
            if not mission.remove_plane_group(group):
                raise RuntimeError("Could not remove temporary AI flight template")
            
            air_catalog["presets"][side][preset_name] = {
                "label": preset_config["label"],
                "mission_type": preset_config["mission_type"],
                "altitude_m": preset_config["altitude_m"],
                "speed_mps": preset_config["speed_mps"],
                "loadout": loadout_name,
                "default_rtb_base": preset_config["default_rtb_base"],
                "orbit_radius_m": preset_config.get("orbit_radius_m"),
                "group": data
            }

    mission.init_script = ("FoWAirCatalog = " + lua_literal(air_catalog) + "\n" +
                           "FoWAirbaseCatalog = " + lua_literal(airbase_catalog) + "\n" +
                           "FoWSpawnCatalog = " + lua_literal(catalog) + "\n" +
                           Path(__file__).with_name("fow_bridge_generic.lua").read_text())

    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_name("air_templates.json").write_text(json.dumps(air_catalog["presets"], indent=2))
    mission.save(str(output))
    print(output)


if __name__ == "__main__":
    main()
