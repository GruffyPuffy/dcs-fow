# DCS Fog of War

DCS Fog of War is a prototype for running a persistent Caucasus scenario with external Red and Blue commanders. DCS owns the simulation; a Python service observes mission state, validates commander orders, and translates them into DCS tasks through a small generic Lua bridge.

## Current state

- A scenario JSON is compiled into `fow.miz` with pydcs.
- The default scenario includes owned airbases, player Hornet slots, base defenses, logistics, AWACS, tankers, and CAP flights.
- Aircraft use native DCS callsigns, routes, roles, frequencies, and tanker TACAN configuration.
- The live bridge reports groups, positions, speed, altitude, fuel, and callsigns.
- The local commander viewer shows coalition-filtered state, observed tracks, orders, aliases, and reference weapon ranges.
- Manual commanders can move or hold ground forces, set ROE, spawn ground or air units, redirect aircraft, assign Patrol/CAP missions, and order aircraft to return to base.
- Expanded curated ground forces and 21 aircraft types are available in the spawn menu.
- DCS-owned airbases appear on the map; commanders can launch bounded assaults against four neutral objectives or deploy limited defenses at bases DCS says they own.
- SQLite retains observations and orders for the current mission run.

Sensor-derived enemy contacts, authenticated commander roles, campaign persistence, DCS warehouse/cargo observation, automatic fuel/recovery decisions, and automatic air support for base assaults are not implemented yet.

## Run

Build and deploy the mission and bridge:

```bash
./scripts/build-mission.sh
./scripts/dcs.sh missions
./scripts/dcs.sh bridge
```

Restart DCS when the hook changes, load `fow.miz`, then start the local service:

```bash
./scripts/fow-server.py
```

Open `http://127.0.0.1:8765/`.

## Direction

The manual commander is the test harness for a later LLM-based command layer. The plan is to give separate Red and Blue commanders only their side-filtered intelligence and a bounded catalog of structured orders. Deterministic Python code will continue to validate decisions and own all DCS task construction; the LLMs will choose operational intent, not generate Lua or directly control the simulator.

See the [commander note](docs/COMMANDER_NOTE.md), [plan](docs/PLAN.md), [server setup](deploy/dcs/README.md), [bridge guide](docs/BRIDGE.md), [viewer guide](docs/VIEWER.md), [command design](docs/MANUAL_COMMANDER.md), and [ADRs](docs/adr/README.md).

See [curated forces and logistics](docs/LOGISTICS.md) for the new spawn catalog and the intended DCS-owned logistics direction.
