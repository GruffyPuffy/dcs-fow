# AGENTS.md — Guidance for AI coding agents

This repo is **DCS Fog of War**: a persistent DCS World campaign where two AI
commanders (Red/Blue) run a live war while human players join PvE on Blue.
Python owns campaign rules and decisions; a small generic Lua bridge connects
to a DCS dedicated server running in Docker. The end goal is local LLM
generals (qwen) replacing the current algorithmic ones — the interfaces for
that already exist.

## Non-negotiable rules of engagement

1. **NEVER start, stop, or restart services.** The user runs everything
   themselves: `python3 -m fow.app`, the DCS docker container
   (`./scripts/dcs.sh ...`), mission reloads. Do not kill processes, do not
   `nohup` anything, do not touch docker, do not list or inspect running
   processes. If a change needs a restart, tell the user and stop.
2. **Do not over-test.** Run the test suite ONCE after a change. If it fails,
   read the failure, fix, and run once more. Never loop test runs, never run
   the same debug command repeatedly hoping for different output. Diagnose by
   *reading code*, not by probing a running system.
3. **Ask when instructions are ambiguous.** The user has been burned by an
   agent "helpfully" removing Red's opening AWACS/tanker while implementing
   something else. Side effects of your changes are your responsibility —
   check what a change touches beyond the literal request, and ask if unsure.
4. **No scripting gameplay.** Behavior must be emergent from doctrine +
   economy, not scripted sequences. Example: the user rejected "scripted
   opening assaults"; the accepted pattern is giving a side budget so its
   normal decision rolls *likely* produce the desired behavior.
5. **Minimal changes to DCS/miz.** The mission shell (`fow-shell.miz`) is
   deliberately thin. Campaign logic lives in Python; the Lua bridge
   (`missions/fow_bridge_generic.lua`) stays generic and stateless. Never put
   campaign rules in Lua.

## Documentation map — read what your task touches

**Game rules live in docs, not in this file.** When a change alters a game
rule, update the corresponding doc in the same commit — this file points to
them and stays stable.

| Doc | Contents | Update when |
| --- | --- | --- |
| [](docs/DOCTRINE.md) | Economy, capture, actions, limits, general doctrine, intel, callsigns, roadmap | Any gameplay rule or scenario value changes |
| [](docs/BRIDGE.md) | JSON bridge protocol, ops, handshake | Bridge op added/changed |
| [](docs/GENERIC_BRIDGE.md) | Bridge design principles (generic, stateless) | Bridge architecture changes |
| [](docs/MANUAL_COMMANDER.md) | Manual commander orders API | Manual order set changes |
| [](docs/AIR_COMMANDS.md) | Air tasking commands | Air command set changes |
| [](docs/VIEWER.md) | Web viewer (Leaflet) features | Viewer UI changes |
| [](docs/LOGISTICS.md) | Logistics/transport plans | Logistics work starts |
| [](docs/PLAN.md) | Project plan, staged gates | Milestones reached |
| [](docs/adr/README.md) | Architecture decision records | Significant design decisions |

## Workflow facts

- User restarts DCS + service themselves and deletes `data/fow-runtime.json`
  between scenario changes. A fresh campaign is required for scenario economy
  changes to take effect (the scenario is reloaded from disk at service
  start, but campaign state is not).
- Rebuild + deploy mission after editing the Lua bridge:
  `./scripts/build-fow-shell.sh && ./scripts/dcs.sh shell-mission`
  (the user runs this; the build script embeds the bridge into the miz).
- Tests: `python3 -m unittest discover -s tests` — 52 tests, all must pass.
  Test expectations encode gameplay doctrine; update them deliberately and
  say why.
- The user live-tests every change in DCS and reports back. Expect an
  iterative loop: implement → minimal test → user tests → diagnose from
  decision logs / runtime state → fix.

## Architecture map

```
fow/
  app.py                 FoWService (port 8770): tick loop, awareness, intel,
                         radio menus, deployment reconciliation, persistence
  campaign/
    engine.py            CampaignEngine: legal actions, apply_action,
                         evaluate_capture (contested capture), income
    general.py           AlgorithmicGeneral: token-bucket economy, doctrine,
                         reactive triggers, decision_log (LLM slot later)
    scenario.py          Scenario/Economy/AssetPackage models + loader
    models.py            CampaignState, ObjectiveState (owner, defense_level,
                         contested_since)
  dcs/
    campaign.py          CampaignExecutor: turns plans into DCS spawns/routes
    client.py            DcsGateway: JSON ops to the Lua bridge
    awareness.py         track history, objective_presence (3.5 km radius)
    snapshot.py          public snapshot (fog-of-war filtered)
    manual.py            manual commander orders
  scenarios/caucasus_pve.json   THE scenario: objectives graph, economy,
                         actions, air stations, asset packages
  web/                   Leaflet viewer (app.js, index.html, styles.css)
missions/fow_bridge_generic.lua  generic stateless bridge (ops: status,
                         ground_position, spawn_group, set_route, set_task,
                         set_command, set_option, add_radio_command, smoke,
                         mark, message)
scripts/
  dcs_structures.py      builders: spawn data, base-start, racetrack, ROE
  dcs.sh                 docker/deploy helpers (user runs these)
data/fow-runtime.json    live campaign checkpoint (user deletes for reset)
```

## Hard-won DCS facts (do not relearn these)

- **DCS controllers have NO `getOption`** — only `setOption`. Live ROE read is
  impossible. The bridge tracks ROE per category (`ground_roe`/`air_roe`
  tables), defaults air to `open_fire`, records `set_option` changes. Never
  call `getOption` again.
- **Base-start spawns need `airdromeId`** on the takeoff route point:
  `{'__ref': 'airbase_id', 'name': base}` — otherwise DCS silently drops the
  spawn (accepted but never appears).
- Ground ROE and Air ROE enums have **different numeric values** and some
  entries are nil in this DCS version — build enum maps with `pairs()`, never
  explicit constructors (nil key = "table index is nil" mission error).
- DCS coordinates: Transverse Mercator, lon0=33, k0=0.9996,
  FE=-99516.9999999732, FN=-4998114.999999984; y=easting, x=northing. The
  bridge resolves `__geo = {lat, lon}` via `coord.LLtoLO` and `__ref` refs.
- Presence counts in awareness are keyed by DCS coalition id (1=red, 2=blue),
  NOT the Side enum.
- Reinforce spawns near own airbases are legitimate (Anapa garrison is 236 m
  from the runway) — reinforce uses 300 m airbase clearance, other ground
  actions 1200 m.

## Conventions

- Scenario JSON is the single source of truth for economy/actions/stations —
  tune there, not in code.
- Decision log: `general.decision_log` (last 50 in checkpoint), shown on the
  web Generals page — the primary diagnosis tool for "why did the general
  do X".
- Callsigns and current doctrine values: see
  [`docs/DOCTRINE.md`](docs/DOCTRINE.md).
