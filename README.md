# DCS Fog of War

Prototype for a persistent DCS mission in which two local AI commanders eventually give operational orders to Red and Blue forces. Each commander should see its own forces and only the enemy information its side has earned. A player can join as a pilot.

**Current state:** A DCS dedicated server runs in the Aterfax Wine container on Ubuntu 24.04. A Windows client joined and spawned in the Caucasus `fow.miz` mission. The project-owned JSON socket bridge now returns live active-group status, accepts ground movement orders, and rejects a missing group; Blue reached its test destination. A web service, fog of war, AI commanders and LLM integration remain unbuilt.

See the [plan](docs/PLAN.md), [ADRs](docs/adr/README.md), [server setup and mission build instructions](deploy/dcs/README.md), [JSON bridge guide](docs/BRIDGE.md), and [local viewer](docs/VIEWER.md). The viewer is ready for a live map trial after a mission restart. The next bridge work is to test a richer mission, reconnect and restart behavior, then integrate a small FoW service.
