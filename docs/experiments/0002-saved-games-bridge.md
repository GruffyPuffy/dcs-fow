# Experiment 0002: Minimal Saved Games bridge

Status: Basic handoff verified on 2026-09-20; visible movement remains untested.

## Scope

`fow.miz` contains one Blue and one Red unarmed ground group and an embedded Lua probe. The probe logs group positions every ten simulation seconds and accepts only `PING`, `BLUE_HOLD`, and `RED_HOLD`. The project-owned `bridge/fow_hook.lua` lives under DCS Saved Games `Scripts/Hooks`; no DCS installation file is edited. The hook reads one command token from Saved Games `FoW/command.txt` and appends its result to `FoW/ack.txt`.

## Run

1. Build and deploy the mission: `./scripts/build-mission.sh` then `./scripts/dcs.sh missions`.
2. Install the hook: `./scripts/dcs.sh bridge`. Restart the DCS process to load a new hook.
3. In DCS WebGUI, select and start `fow.miz`. It must be unpaused for simulation-frame callbacks to run.
4. Check DCS Saved Games `Logs/dcs.log` for `FOW_BRIDGE_READY`, `FOW_STATUS` and `hook loaded`.
5. Run `./scripts/fow-command.sh PING`. Check `FoW/ack.txt` and `dcs.log` for acknowledgement. Then try `BLUE_HOLD` and `RED_HOLD`.

The Hold command is intentionally small: it changes the AI group's current task, but a stationary group may show no visible movement. A later experiment should use a visible, validated move command and observe the position change.

## Observed result

With `fow.miz` running, DCS logged `hook loaded`, `FOW_BRIDGE_READY`, and a `FOW_STATUS` line with both groups alive and positioned. `./scripts/fow-command.sh PING` produced `FOW_ACK;PING` in the mission log. `BLUE_HOLD` produced `FOW_ACK;BLUE_HOLD`, so the hook reached the mission and the mission's ground-group `Hold` call returned without an error. The hook's `net.dostring_in` call returned an empty string even though the mission executed the command; the original `ack.txt` entries therefore have empty result fields. The hook source now labels that case `DISPATCHED_NO_RETURN`, which will take effect after the hook is redeployed and DCS restarts. The mission log is the execution receipt in this trial.

## Open checks

- Confirm the original F/A-18C client slots still work.
- Test a visible ground movement command and verify a changed position in later status records.
- Improve acknowledgements so the host can distinguish dispatch from actual execution without parsing DCS logs.
