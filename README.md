# DCS Fog of War

Planning workspace for a persistent DCS mission in which two local AI commanders give operational orders to Red and Blue forces. Each commander sees its own forces and only the enemy information its side has earned. A player can join the live war as a pilot.

This repository is at the **planning stage**. The architecture below is a working hypothesis; no server, bridge, or LLM integration has been implemented or tested. The source discussion is the user's pasted concept from 2026-09-19. Its sample code and performance claims are illustrative, not verified instructions.

Start with [the project plan](docs/PLAN.md) and [the decision log](docs/adr/README.md). The first milestone is a small live mission test on Ubuntu 24.04, followed by a measured two commander experiment. The first server trial has [reproducible setup files](deploy/dcs/README.md) and [experiment notes](docs/experiments/0001-linux-server-client-join.md); broader installer and operations work belongs after those tests stabilize.
