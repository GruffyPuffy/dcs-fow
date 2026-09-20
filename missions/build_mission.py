"""Build a configured FoW mission (requires pydcs 0.15.0).

Run: python build_mission.py SCENARIO.json OUTPUT.miz
"""

from pathlib import Path
import json
import sys

import dcs


def client(group: dcs.unitgroup.FlyingGroup, name: str) -> None:
    group.units[0].skill = dcs.unit.Skill.Client
    group.units[0].name = name


def aircraft_type(name: str):
    aircraft = getattr(dcs.planes, name, None) or dcs.planes.plane_map.get(name)
    if aircraft is None:
        raise ValueError(f"Unknown aircraft type: {name}")
    return aircraft


def set_flight_callsign(group: dcs.unitgroup.FlyingGroup, country,
                        configured: dict) -> None:
    callsign = configured.get("callsign")
    if callsign is None:
        return
    if "number" in callsign:
        number = callsign["number"]
        if not isinstance(number, int) or not 1 <= number <= 999:
            raise ValueError("Numeric callsign must be 1-999")
        if number + len(group.units) - 1 > 999:
            raise ValueError("Numeric callsign exceeds 999 for flight members")
        for member, unit in enumerate(group.units):
            unit.callsign = number + member
        return
    if not isinstance(country.callsign, dict):
        raise ValueError(f"{country.name} uses numeric callsigns")
    category = group.units[0].unit_type.category
    if category == "Interceptor":
        category = "Air"
    available = country.callsign.get(category, [])
    name = callsign["name"]
    flight = callsign.get("flight", 1)
    if name not in available:
        raise ValueError(
            f"Callsign {name!r} is not available for {country.name} {category}"
        )
    if not isinstance(flight, int) or not 1 <= flight <= 999:
        raise ValueError("Callsign flight number must be 1-999")
    callsign_id = available.index(name) + 1
    for member, unit in enumerate(group.units, 1):
        unit.callsign = None
        unit.callsign_dict = {
            1: callsign_id,
            2: flight,
            3: member,
            "name": f"{name}{flight}{member}",
        }


def offset_point(mission: dcs.Mission, airport, offset: list[float]) -> dcs.Point:
    return dcs.Point(
        airport.position.x + offset[0],
        airport.position.y + offset[1],
        mission.terrain,
    )


def add_client_slots(mission: dcs.Mission, scenario: dict,
                     countries: dict, airports: dict) -> None:
    start_types = {
        "runway": dcs.mission.StartType.Runway,
        "hot": dcs.mission.StartType.Warm,
        "cold": dcs.mission.StartType.Cold,
    }
    for slot in scenario["client_slots"]:
        country = countries[slot["side"]]
        airport = airports[slot["base"]]
        aircraft = aircraft_type(slot["aircraft"])
        if slot["start"] == "air":
            group = mission.flight_group_inflight(
                country=country, name=slot["name"], aircraft_type=aircraft,
                position=offset_point(mission, airport, slot.get("offset_m", [0, 0])),
                altitude=slot["altitude_m"], speed=slot["speed_mps"], group_size=1,
            )
        else:
            parking_slots = None
            if slot.get("parking"):
                parking_slots = [next(
                    parking for parking in airport.parking_slots
                    if parking.slot_name == slot["parking"]
                )]
            group = mission.flight_group_from_airport(
                country=country, name=slot["name"], aircraft_type=aircraft,
                airport=airport, start_type=start_types[slot["start"]],
                group_size=1, parking_slots=parking_slots,
            )
        client(group, slot["name"])


def add_initial_groups(mission: dcs.Mission, scenario: dict,
                       countries: dict, airports: dict, catalog: dict) -> None:
    for configured in scenario["initial_groups"]:
        package = catalog[configured["side"]][configured["package"]]
        if not package["units"]:
            raise ValueError(f"Initial group {configured['name']} has no units")
        position = offset_point(mission, airports[configured["base"]],
                                configured.get("offset_m", [0, 0]))
        group = mission.vehicle_group_platoon(
            country=countries[configured["side"]],
            name=configured["name"],
            types=[dcs.vehicles.vehicle_map[unit["type"]] for unit in package["units"]],
            position=position,
        )
        for unit, unit_config in zip(group.units, package["units"]):
            unit.position = offset_point(
                mission, airports[configured["base"]],
                [configured.get("offset_m", [0, 0])[0] + unit_config.get("dx", 0),
                 configured.get("offset_m", [0, 0])[1] + unit_config.get("dy", 0)],
            )


def add_initial_flights(mission: dcs.Mission, scenario: dict,
                        countries: dict, airports: dict) -> None:
    for configured in scenario.get("initial_flights", []):
        country = countries[configured["side"]]
        airport = airports[configured["base"]]
        aircraft = aircraft_type(configured["aircraft"])
        role = configured["role"]
        if role in ("awacs", "tanker"):
            position = offset_point(mission, airport, configured["track_offset_m"])
            common = {
                "country": country,
                "name": configured["name"],
                "plane_type": aircraft,
                "airport": None,
                "position": position,
                "race_distance": configured["track_length_m"],
                "heading": configured["heading_deg"],
                "altitude": configured["altitude_m"],
                "speed": configured["speed_kph"],
                "frequency": configured["frequency_mhz"],
            }
            if role == "awacs":
                group = mission.awacs_flight(**common)
            else:
                group = mission.refuel_flight(
                    **common, tacanchannel=configured["tacan"])
        elif role == "cap":
            point1 = offset_point(mission, airport, configured["track_offsets_m"][0])
            point2 = offset_point(mission, airport, configured["track_offsets_m"][1])
            group = mission.patrol_flight(
                country=country, name=configured["name"], patrol_type=aircraft,
                airport=None, pos1=point1, pos2=point2,
                speed=configured["speed_kph"], altitude=configured["altitude_m"],
                max_engage_distance=configured["engage_range_m"],
                group_size=configured.get("group_size", 2),
            )
        else:
            raise ValueError(f"Unknown initial flight role: {role}")
        group.set_skill(dcs.unit.Skill.High)
        set_flight_callsign(group, country, configured)


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
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python build_mission.py SCENARIO.json OUTPUT.miz")

    scenario = json.loads(Path(sys.argv[1]).read_text())
    output = Path(sys.argv[2])
    if scenario.get("map") != "Caucasus":
        raise ValueError("Only the Caucasus terrain is currently supported")
    mission = dcs.Mission()
    countries = {
        side: mission.country(config["country"])
        for side, config in scenario["coalitions"].items()
    }
    airports = mission.terrain.airports
    for side, config in scenario["coalitions"].items():
        for airbase_name in config["airbases"]:
            getattr(airports[airbase_name], f"set_{side}")()

    catalog = json.loads(Path(__file__).with_name("spawn_catalog.json").read_text())
    unit_catalog = json.loads(Path(__file__).with_name("unit_catalog.json").read_text())
    for side in ("blue", "red"):
        overlap = set(catalog[side]) & set(unit_catalog[side])
        if overlap:
            raise ValueError(f"Duplicate spawn IDs for {side}: {overlap}")
        catalog[side].update(unit_catalog[side])

    add_client_slots(mission, scenario, countries, airports)
    add_initial_groups(mission, scenario, countries, airports, catalog)
    add_initial_flights(mission, scenario, countries, airports)

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
    
    for side, country in countries.items():
        airport = airports[scenario["coalitions"][side]["airbases"][0]]
        air_catalog["presets"][side] = {}
        for preset_name, preset_config in air_config["presets"][side].items():
            aircraft = aircraft_type(preset_config["aircraft"])
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
    output.with_name("airbase_catalog.json").write_text(json.dumps(airbase_catalog, indent=2))
    output.with_name("scenario_manifest.json").write_text(json.dumps({
        "scenario": scenario,
        "airbases": airbase_catalog,
    }, indent=2))
    mission.save(str(output))
    print(output)


if __name__ == "__main__":
    main()
