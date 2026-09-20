# DCS Fog of War

Prototype for a persistent DCS mission in which two local AI commanders eventually give operational orders to Red and Blue forces. Each commander should see its own forces and only the enemy information its side has earned. A player can join as a pilot.

**Current state:** A DCS dedicated server runs in the Aterfax Wine container on Ubuntu 24.04. A Windows client joined and spawned in the Caucasus `fow.miz` mission. The JSON bridge and manual commander server report live status, retain orders and movement tracks, and have spawned a truck and a Hawk SAM group in DCS. Descriptive/custom names, editable viewer aliases, ground ROE orders, range overlays, and a DCS-derived single-unit menu are staged for the next live test. Sensor-derived fog of war, AI commanders and LLM integration remain future work.

See the [plan](docs/PLAN.md), [ADRs](docs/adr/README.md), [server setup and mission build instructions](deploy/dcs/README.md), [JSON bridge guide](docs/BRIDGE.md), [manual commander instructions](docs/VIEWER.md), [command design](docs/MANUAL_COMMANDER.md), and [air-command trial](docs/AIR_COMMANDS.md).
