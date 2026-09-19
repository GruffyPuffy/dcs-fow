# DCS Fog of War

Prototype for a persistent DCS mission in which two local AI commanders eventually give operational orders to Red and Blue forces. Each commander should see its own forces and only the enemy information its side has earned. A player can join as a pilot.

**Current state:** A DCS dedicated server runs in the Aterfax Wine container on Ubuntu 24.04. The Windows client can join the single Caucasus `fow.miz` mission and spawn. The mission has F/A-18C air, runway and ramp Client slots. Ground spawning worked after Batumi was assigned to Blue. There is no live Lua bridge, fog-of-war service, AI commander or local LLM integration yet.

See the [plan](docs/PLAN.md), [ADRs](docs/adr/README.md), [server setup and mission build instructions](deploy/dcs/README.md), and [first experiment](docs/experiments/0001-linux-server-client-join.md). The next milestone is a minimal live state and command round trip with one AI group.
