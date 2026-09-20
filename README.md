# DCS Fog of War

Prototype for a persistent DCS mission in which two local AI commanders eventually give operational orders to Red and Blue forces. Each commander should see its own forces and only the enemy information its side has earned. A player can join as a pilot.

**Current state:** A DCS dedicated server runs in the Aterfax Wine container on Ubuntu 24.04. The Windows client can join the single Caucasus `fow.miz` mission and spawn. The mission has F/A-18C air, runway and ramp Client slots. Ground spawning worked after Batumi was assigned to Blue. An experimental Saved Games hook can dispatch fixed commands to mission Lua; `PING` and `BLUE_HOLD` reached the mission, and both ground groups report status in `dcs.log`. Visible movement, a web service, fog of war, AI commanders and local LLM integration remain untested.

See the [plan](docs/PLAN.md), [ADRs](docs/adr/README.md), [server setup and mission build instructions](deploy/dcs/README.md), and [bridge experiment](docs/experiments/0002-saved-games-bridge.md). The next milestone is a visible, validated group movement command with acknowledgement and observed position change.
