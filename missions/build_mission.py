"""Build the single Caucasus FoW mission (requires pydcs 0.15.0).

Run: python build_mission.py fow.miz
Keep one mission and add or change client slots here as the project develops.
"""

from pathlib import Path
import sys

import dcs


def client(group: dcs.unitgroup.FlyingGroup, name: str) -> None:
    group.units[0].skill = dcs.unit.Skill.Client
    group.units[0].name = name


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

    output.parent.mkdir(parents=True, exist_ok=True)
    mission.save(str(output))
    print(output)


if __name__ == "__main__":
    main()
