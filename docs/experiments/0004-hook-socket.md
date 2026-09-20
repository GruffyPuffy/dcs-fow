# Experiment 0004: Local socket through a Saved Games hook

Status: live socket round trip passed on 2026-09-20 with DCS 2.9.29.27468. Client-side visual observation is pending.

## Goal

Exchange a status record and one fixed command without using `dcs.log` as the transport. The DCS installation files and mission files stay unchanged. This uses the existing `fow-move-candidate.miz` mission and a separate candidate hook.

## Candidate

`bridge/fow_hook_socket.lua` listens on TCP port 10309 inside the DCS container. Docker publishes it as `127.0.0.1:10309` on the Ubuntu host, so it is not exposed on the LAN. The hook handles one short line per connection:

| Request | Expected reply |
| --- | --- |
| `PING` | `OK HOOK_PONG` (tests the socket without touching mission Lua) |
| `STATUS` | The current `FOW_STATUS;...` record from mission Lua |
| `BLUE_MOVE_TEST` | `MOVE_ACCEPTED` if the candidate mission accepts the order |

Unknown or oversized requests return `ERR ...`. Each socket operation in the DCS frame callback is nonblocking; the test client has a three-second timeout. This is a diagnostic protocol, not yet the final FoW service protocol. The mission still emits its existing diagnostic log lines during this test; the success criterion is that the client obtains state and command results directly over the socket.

The hook asks DCS for two return values from mission Lua to probe a reported `a_do_script` single-return issue. If the DCS build still does not return the result, it replies `ERR NO_MISSION_RETURN`; the hook does not invent a successful acknowledgement.

## Run

1. Install the candidate with `./scripts/dcs.sh bridge-socket-test`.
2. Run `./scripts/dcs.sh start` to apply the Compose port change and restart the DCS process. Confirm `socket candidate listening on 10309` in `dcs.log`.
3. Select and unpause `fow-move-candidate.miz` if it did not auto-load.
4. Run `python3 scripts/fow-socket-test.py PING`, then `python3 scripts/fow-socket-test.py STATUS`.
5. Only if `STATUS` returns the expected record, run `python3 scripts/fow-socket-test.py BLUE_MOVE_TEST` once. Check a later `STATUS` for changed Blue coordinates and, if desired, the diagnostic `completed` line in `dcs.log`.

## Restore

Run `./scripts/dcs.sh bridge-move-test` and restart the DCS process to restore the previous move-test hook. `./scripts/dcs.sh bridge` restores the original baseline hook. The extra Compose port mapping is inert without the candidate hook and can be removed after evaluation.

## Open checks

- Measure response time and verify reconnect after mission and process restart.
- Before product use, add message IDs, mission identity, expiry, authentication, and bounded request handling appropriate to the chosen service placement.

## Live result (2026-09-20)

After the DCS process restarted, the hook logged `socket candidate listening on 10309` and the candidate mission logged `FOW_MOVE_CANDIDATE_READY`. A host-side `PING` returned `OK HOOK_PONG`. `STATUS` returned `FOW_STATUS;FoW Blue Ground;alive;-353310.7;619886.2;FoW Red Ground;alive;-194210.1;518951.7` directly through the socket. This confirms the two-value return workaround works on this build for a status string.

One `BLUE_MOVE_TEST` request returned `MOVE_ACCEPTED` through the socket. Subsequent socket `STATUS` calls showed Blue at `-353305.7,619888.8`, then `-353198.4,620007.1`, and finally `-353160.9,620036.2`. Red remained at `-194210.1,518951.7`. The mission diagnostic log also recorded `FOW_RESULT;BLUE_MOVE_TEST;completed`. The log was used to corroborate completion, not to deliver status or the command result to the client.

This validates one local client, short text messages, and the live mission return path. It does not establish behavior after disconnects, concurrent clients, mission restart, larger state records, or a remote FoW service. The current mission still writes its old periodic status log; that can be removed after the socket design is chosen.
