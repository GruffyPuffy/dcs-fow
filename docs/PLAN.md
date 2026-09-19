# Project plan

Status: server baseline proven; live bridge is next. Updated 2026-09-19.

## Intended experience

A DCS dedicated server runs a persistent scenario on an Ubuntu 24.04 machine. Red and Blue AI commanders continue making bounded, high-level choices when no human is present. A player can join the same mission. DCS remains responsible for flying, movement, combat, and simulation; the external service chooses objectives and submits validated orders.

## Working architecture

```text
                    Ubuntu 24.04 host
  +------------------------------------------------------+
  | DCS dedicated server via Aterfax Docker/Wine          |
  |   mission Lua / bridge <----> Python orchestrator     |
  |                                | state & rules         |
  |                                +--> Red local LLM      |
  |                                +--> Blue local LLM     |
  +------------------------------------------------------+
                      ^ player joins over LAN
```

The proposed loop is: collect authoritative mission state; maintain side-specific intelligence; give each commander its own brief, available order catalog and observed state; validate each structured order; translate accepted orders into DCS tasks; observe the result. A nominal 60-second decision interval is a starting parameter, not a requirement or performance promise. The two commanders may share one model process while keeping separate context and memory.

## Boundaries and principles

- Start with a single mission and a few ground groups. Add air operations, spawning, logistics, and campaign continuity after live control is reliable.
- The LLM outputs **intent** using a small catalog of named orders, not Lua or arbitrary coordinates. Deterministic code resolves zones, groups, task parameters, cooldowns, and resource limits.
- Own a small Lua bridge in this project. Keep DCS API reads, task execution and acknowledgements bounded; keep intelligence, planning, validation and LLM calls in Python. The bridge must also reject unknown groups, stale commands, out-of-bounds destinations and orders affecting player-controlled units.
- Fog of war is enforced before prompts are built. Raw omniscient DCS state stays inside the state processor. Unknown contacts and stale sightings remain explicitly uncertain.
- Keep enough event and decision history to explain a command, recover after restart, and avoid repeated oscillating orders. Define persistence and mission reload behavior before promising a continuous campaign.
- Prefer reproducible, reversible experiments. Record DCS version, Wine/container version, mission, timings, logs, and actual behavior for each trial.

## Staged work and acceptance gates

| Stage | Work | Evidence required before expanding |
| --- | --- | --- |
| 0. Align | Choose the first map, host and client setup. | **Done for the server trial:** Ubuntu 24.04, Caucasus, F/A-18C Windows client. Broader FoW scope remains open. |
| 1. Host feasibility | Run [Experiment 0001](experiments/0001-linux-server-client-join.md): host one repo-owned Caucasus mission and join from Windows. | **Working:** server install, auto start, LAN join, air and ground spawn. Resource measurements and reboot test remain useful operational follow-up. |
| 2. Live bridge | Use one mission and one group to export a small state record and accept a single safe order. Evaluate DCS mission Lua versus a server hook and transport without assuming mission file/socket access. | A command changes the group as intended; disconnect/restart/invalid-order cases are recorded. |
| 3. Deterministic battle | Add fixed zones, objectives, two sides, basic detection filtering, action validation and scripted commanders. | Both sides act independently without an LLM; hidden units remain absent from enemy views. |
| 4. Local LLM trial | Add separate Red/Blue briefs and structured output behind the same validator. Replay recorded states and compare decisions. | Valid order rate, inference latency, strategic continuity and failure behavior measured on the actual host. |
| 5. Living mission | Add player interaction, broader orders, reinforcements and persistence only where evidence supports them. | An unattended session evolves coherently; a human can join and affect later decisions. |
| 6. Packaging | Write Ubuntu 24.04 installer/operations scripts from the proven setup. | Repeatable installation on a clean environment with documented upgrades and backups. |

Agree on each new experiment before implementing it. The first server trial is complete enough to begin designing Stage 2; the later stages remain proposals.

## Open design questions

1. What is the smallest state record and one safe AI order for the live bridge test?
2. Should bridge transport use a server hook, mission Lua with a narrow socket, or another supported path?
3. Must war state survive mission/server restarts in the first playable version?
4. Should the Blue commander issue suggestions to the player or treat the player as autonomous at first?

## Known research limits

- The [Aterfax container](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker) works for this host's basic server and client trial. DCS updates and later Lua integration still need testing.
- The [DCS controller API](https://www.digitalcombatsimulator.com/en/support/faq/1267/) supports AI tasks, but task behavior varies by unit type and situation. A broad phrase such as “hold the river” still needs explicit translation and live testing.
- The [mission scripting environment](https://www.digitalcombatsimulator.com/en/support/faq/1253/) is isolated. File and socket examples in the pasted discussion should not be treated as working bridge code. The bridge mechanism is an early experiment.
- [pydcs](https://github.com/pydcs/dcs) generated the repo's `fow.miz`. It is not the live command channel. Its default neutral airfield ownership blocked ground slots until Batumi was set to Blue.
- The pasted model latency, memory and hardware estimates are unverified for this machine. Measure them before choosing model and deployment method.
