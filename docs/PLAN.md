# Project plan

Status: draft for discussion, 2026-09-19.

## Intended experience

A DCS dedicated server runs a persistent scenario on an Ubuntu 24.04 machine. Red and Blue AI commanders continue making bounded, high-level choices when no human is present. A player can join the same mission. DCS remains responsible for flying, movement, combat, and simulation; the external service chooses objectives and submits validated orders.

## Working architecture

```text
                    Ubuntu 24.04 host
  +------------------------------------------------------+
  | DCS dedicated server via Wine (packaging TBD)        |
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
| 0. Align | Agree on first map, available hardware, client access, acceptable operational complexity and MVP behavior. Review ADRs. | Agreed scope and test setup. |
| 1. Host feasibility | Run [Experiment 0001](experiments/0001-linux-server-client-join.md): a minimal Caucasus mission with one F/A-18C client slot on Ubuntu, joined from Windows. | Versioned steps, server logs, a completed client connection, CPU/RAM/disk observations, restart behavior. |
| 2. Live bridge | Use one mission and one group to export a small state record and accept a single safe order. Evaluate DCS mission Lua versus a server hook and transport without assuming mission file/socket access. | A command changes the group as intended; disconnect/restart/invalid-order cases are recorded. |
| 3. Deterministic battle | Add fixed zones, objectives, two sides, basic detection filtering, action validation and scripted commanders. | Both sides act independently without an LLM; hidden units remain absent from enemy views. |
| 4. Local LLM trial | Add separate Red/Blue briefs and structured output behind the same validator. Replay recorded states and compare decisions. | Valid order rate, inference latency, strategic continuity and failure behavior measured on the actual host. |
| 5. Living mission | Add player interaction, broader orders, reinforcements and persistence only where evidence supports them. | An unattended session evolves coherently; a human can join and affect later decisions. |
| 6. Packaging | Write Ubuntu 24.04 installer/operations scripts from the proven setup. | Repeatable installation on a clean environment with documented upgrades and backups. |

Each stage requires agreement on the actual test before implementation. We can revise the sequence as evidence arrives.

## Questions to settle first

1. What are this host's CPU, RAM, GPU/VRAM, free disk and network conditions? Is a DCS client available to join test missions?
2. Which map and DCS modules are available, and should the first mission use only free content?
3. Is the first playable target a continuous single mission that can reset, or must war state survive server/mission restarts?
4. Should the Blue commander issue suggestions to the player, or treat the player as completely autonomous at first?
5. Can the initial experiment use a private LAN only? What DCS account/server administration constraints apply?

## Known research limits

- Eagle Dynamics supplies a [dedicated server installer](https://www.digitalcombatsimulator.com/en/downloads/world/server/); Linux operation currently relies on community Wine approaches such as [Aterfax's container](https://github.com/Aterfax/DCS-World-Dedicated-Server-Docker) or [ActiumDev's direct Wine setup](https://github.com/ActiumDev/dcs-server-wine). These are candidates, not a verified recommendation for this machine.
- The [DCS controller API](https://www.digitalcombatsimulator.com/en/support/faq/1267/) supports AI tasks, but task behavior varies by unit type and situation. A broad phrase such as “hold the river” still needs explicit translation and live testing.
- The [mission scripting environment](https://www.digitalcombatsimulator.com/en/support/faq/1253/) is isolated. File and socket examples in the pasted discussion should not be treated as working bridge code. The bridge mechanism is an early experiment.
- [pydcs](https://github.com/pydcs/dcs) creates and edits mission files. It may help with initial or later generated `.miz` files, but it is not the live command channel.
- The pasted model latency, memory and hardware estimates are unverified for this machine. Measure them before choosing model and deployment method.
