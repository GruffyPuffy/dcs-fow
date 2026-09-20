# Experiment 0003: Visible ground move with rollback

Status: live command and position test passed on 2026-09-20. Visual observation in a DCS client is still unverified.

## Commit checkpoint

This experiment adds a reversible ground-movement candidate. Commit the source and documentation, not the generated `.miz` or any server data:

| Project file | Purpose |
| --- | --- |
| `missions/fow_move_candidate.lua` | Implements one fixed Blue ground-group move and reports accepted, completed, or failed. |
| `missions/build_mission.py`, `scripts/build-mission.sh` | Build the candidate mission when `--candidate` is requested. |
| `bridge/fow_hook_move.lua` | Allows the move command in the Saved Games hook; the baseline hook is preserved. |
| `scripts/dcs.sh` | Adds candidate mission and hook deployment commands. |
| `scripts/fow-command.sh` | Allows queuing the fixed move command. |
| `.gitignore` | Excludes the generated candidate `.miz`. |
| `docs/experiments/0003-visible-ground-move.md` | Records the procedure, result, limits, and restore path. |

The deployed `fow-move-candidate.miz` and hook under `/data/dcs-fow` are runtime copies. The tracked baseline `missions/fow.miz`, `missions/fow_bridge.lua`, and `bridge/fow_hook.lua` were not changed for this experiment. This checkpoint does not promote the candidate command to the baseline bridge.

## Baseline preserved

The repo and deployed `fow.miz` remain the working baseline. The move-test mission is built as Git-ignored `missions/.fow-move-candidate.miz` and deployed under a different server filename. The baseline hook remains in `bridge/fow_hook.lua`; `bridge/fow_hook_move.lua` adds one fixed token. No DCS installation file is edited.

## Candidate and run sequence

1. `./scripts/build-mission.sh --candidate`
2. `./scripts/dcs.sh mission-move-test`
3. `./scripts/dcs.sh bridge-move-test`, then restart the DCS process to load that hook.
4. Select `fow-move-candidate.miz` in DCS WebGUI and unpause it. Confirm `FOW_MOVE_CANDIDATE_READY` and both `FOW_STATUS` groups in `dcs.log`.
5. Run `./scripts/fow-command.sh BLUE_MOVE_TEST` once. It requests a 150 m northeast off-road move from the Blue truck's current position, after checking the target is land. Look for `FOW_RESULT;BLUE_MOVE_TEST;accepted`, changing Blue coordinates in later `FOW_STATUS` lines, then `FOW_RESULT;BLUE_MOVE_TEST;completed`.

The 150 m point is a test offset, not a vetted road route. If the truck does not move or gets stuck, record the result rather than sending repeated orders.

## Restore

Select the original `fow.miz` in DCS WebGUI. Run `./scripts/dcs.sh bridge` and restart the DCS process to restore the baseline hook. The candidate mission can be removed from the DCS mission list and Saved Games after evaluation; the working repo `fow.miz` is unaffected.

## Pass criterion

One command is accepted, the Blue group's reported position changes, and the truck reaches the target or a bounded failure is recorded. The Red group and all pilot slots remain available.

## Live result (2026-09-20)

The candidate mission logged `FOW_MOVE_CANDIDATE_READY` and both ground groups alive. One `BLUE_MOVE_TEST` command was accepted with target `x=-353160.7, z=620036.2`. Blue moved from `x=-353310.7, z=619886.2` through several reported positions to `x=-353173.3, z=620028.3`, then logged `FOW_RESULT;BLUE_MOVE_TEST;completed`. Red stayed at `x=-194210.1, z=518951.7` in the status reports. This confirms the command changed the simulated group's position and the completion check fired. The hook's acknowledgement was `DISPATCHED_NO_RETURN`, so the mission log and changing coordinates are the evidence of execution. A client-side visual check and pilot-slot check have not yet been performed for this candidate.

## Next check

Join the candidate mission from a DCS client and visually check the Blue truck and pilot slots. Decide afterward whether to generalize movement commands in the baseline bridge or keep the candidate isolated.
