# DCS Fog of War

Prototype for a persistent DCS mission in which two local AI commanders eventually give operational orders to Red and Blue forces. Each commander should see its own forces and only the enemy information its side has earned. A player can join as a pilot.

**Current state:** A DCS dedicated server runs in the Aterfax Wine container on Ubuntu 24.04. A Windows client joined and spawned in the Caucasus `fow.miz` mission. An isolated candidate mission and Saved Games hook now exchange live ground-group status and a fixed move order over a localhost socket; the Blue group reached its test destination. The original mission and hook remain available. A web service, fog of war, AI commanders and LLM integration remain unbuilt.

See the [plan](docs/PLAN.md), [ADRs](docs/adr/README.md), [server setup and mission build instructions](deploy/dcs/README.md), and [socket experiment](docs/experiments/0004-hook-socket.md). The next bridge work is to test restart and failure behavior, then define a bounded protocol for the FoW service.
