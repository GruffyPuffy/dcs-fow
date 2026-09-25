# FoW campaign service

This folder contains the second-generation implementation. The legacy scripts,
viewer, and generated mission remain unchanged as a working reference.

## Boundaries

- `campaign/` owns symmetric Red/Blue rules, resources, objectives, and legal actions.
- `dcs/` owns the bridge protocol and typed observations. Campaign code does not import it.
- `web/` is the operational shell and debug command surface.
- `scenarios/caucasus_pve.json` defines one shared action catalog with side-specific asset
  variants. Only Blue player slots are included in the initial PvE mission shell.
- `assets/foothold_pve_slots.json` records Foothold's 107-slot Blue PvE roster separately
  from placement. Its Anapa/Krymsk/FARP/carrier layout still needs mapping to this scenario.
- `data/fow-runtime.json` is an atomic runtime checkpoint for the current campaign. It stores
  strategic state and deployment intent, not DCS positions.

## Run the web shell

```bash
python3 -m fow.app
```

Open `http://127.0.0.1:8770/`. The service can run while DCS is offline and reports bridge
connection state separately.

Starting a campaign lets both seeded generals buy one opening garrison while preserving their
configured reserve. Restarting the service restores `data/fow-runtime.json` and adopts existing
DCS groups by deterministic name instead of spawning them again. If DCS restarted with a new
mission ID, the service rehydrates missing managed deployments once.

To deliberately discard the current campaign, stop the service and remove the checkpoint before
starting it again:

```bash
rm data/fow-runtime.json
python3 -m fow.app
```

Use `--state-file PATH` to keep the runtime checkpoint elsewhere.

## Build the minimal mission

The shell contains home-base ownership, Blue client slots, the generic bridge, and a small slot
guard. Each slot names an `unlock_objective`; the FoW server decides access and Lua only enforces
the supplied allow/deny state. The shell contains no initial AI groups or campaign rules.

Build with pinned pydcs 0.15.0 inside the running DCS container, then upload it beside the legacy
mission:

```bash
./scripts/build-fow-shell.sh
./scripts/dcs.sh shell-mission
```

The builder writes and validates `fow/missions/fow-shell.miz`. Deployment atomically updates
`fow-shell.miz` in DCS Saved Games without replacing the legacy `fow.miz`. Select
`fow-shell.miz` in the DCS WebGUI and restart the mission.

During shell-builder development, the Python entry point can also be run directly in an
environment containing pydcs 0.15.0:

```bash
python3 -m fow.dcs.build_shell_mission
```