# FoW ↔ DCS bridge

Status: JSON bridge passed a live round trip on 2026-09-20 with DCS 2.9.29.27468. The earlier fixed-text and log/file experiments have been removed from the repo.

## Boundary

`missions/fow_bridge.lua` is embedded in the repo-owned `fow.miz`. It reads DCS state, validates allowed orders, and applies a small set of DCS tasks. It has no filesystem or socket access. `bridge/fow_hook.lua` is copied to DCS Saved Games `Scripts/Hooks/fow_hook.lua`; it owns the TCP listener, validates the protocol envelope, converts bounded JSON data to a Lua table literal, and calls one mission entry point through `net.dostring_in`. The FoW service owns intelligence filtering, strategy, target choice, retries, and history.

The hook listens on port 10309 inside Docker. Compose publishes that port only on the Ubuntu host's `127.0.0.1`. DCS multiplayer remains on 10308. There are no edits to installed DCS files. The hook's small `a_do_script` return workaround is needed on the tested DCS build; it requests a second sentinel value so a mission string reaches the hook.

## Protocol version 1

One UTF-8 JSON object per TCP connection, followed by `\n`. The response is also one JSON line; the hook closes the connection after sending it. Requests must fit in 4096 bytes. Responses are capped at 1 MiB. The client should time out, correlate `id`, and treat an absent or mismatched response as unknown outcome. An accepted command means DCS accepted the task; it does not mean the group arrived.

| Operation | Request fields | Response |
| --- | --- | --- |
| `ping` | `v:1`, string `id`, `op:"ping"` | `ok:true`, `result:"pong"` |
| `status` | `v:1`, string `id`, `op:"status"` | `ok:true`, `mission_id`, `time`, `groups`, `statics` |
| `hold` | `v:1`, string `id`, `op:"hold"`, `group` | `result:"HOLD_ACCEPTED"` or an error |
| `move` | `v:1`, string `id`, `op:"move"`, `group`, numeric `x`, `z` | `result:"MOVE_ACCEPTED"` or an error |
| `move_geo` | `v:1`, string `id`, `op:"move_geo"`, `group`, numeric `lat`, `lon` | Converts with DCS `coord.LLtoLO`, then applies the same ground move |
| `spawn` | `v:1`, string `id`, `op:"spawn"`, `side`, `template`, numeric `lat`, `lon`, optional `name` | Uses the embedded catalog and returns `SPAWN_ACCEPTED:group_name;ROE=OPEN_FIRE` when explicit ROE succeeds; truck and Hawk site passed live tests, custom names await testing |
| `set_roe` | `v:1`, string `id`, `op:"set_roe"`, `group`, `mode` | Ground AI `open_fire`, `return_fire`, or `weapon_hold`; staged for live test |

Example:

```json
{"v":1,"id":"trial1","op":"status"}
```

The `id` contains 1–64 ASCII letters, digits, `_` or `-`. The hook limits requests to 4096 bytes, scalar strings to 2048 bytes, and nested data to six levels and 256 nodes. It encodes data as literals and never accepts executable Lua. The mission allowlists operations, checks names and coordinates, and rejects player-controlled units for orders. Movement checks land and a 50 km destination radius. Spawn uses curated `missions/spawn_catalog.json` plus the DCS-derived `missions/unit_catalog.json`, both embedded at mission build time. It checks each unit's land point and requires a friendly ground group within 50 km. Custom spawn names are restricted and checked for collisions. This is a prototype boundary, not a complete authorization scheme. Only trusted local processes should have access to port 10309.

`status` enumerates active groups and their existing units for Neutral, Red, and Blue, plus existing static objects from all three coalitions. Groups include DCS ID, name, coalition, category, and units. Units include DCS ID, name, type, DCS `x/y/z` coordinates, latitude/longitude, and horizontal velocity magnitude in `speed_mps`. The viewer derives altitude MSL from `y` and ground speed from that velocity. Statics include name, type, coalition and the same coordinates. Latitude/longitude come from DCS's [`coord.LOtoLL`](https://www.digitalcombatsimulator.com/en/support/faq/1257/), so a map client need not guess the terrain projection. Dead groups that DCS may still return are excluded using `isExist`; units no longer in a group are absent. Empty Client slots are not active units and do not appear until a player spawns. This is an **omniscient raw snapshot**. The local FoW service filters Blue and Red groups for its display, but its Admin endpoint and bridge remain accessible to trusted local processes. Sensor-derived enemy contacts and authentication are not yet implemented. Airbases, scenery, and weapons are outside this first snapshot.

This scan uses DCS's documented [`coalition.getGroups` and `coalition.getStaticObjects`](https://www.digitalcombatsimulator.com/es/support/faq/1646/) and each group's documented [`getUnits`](https://www.digitalcombatsimulator.com/en/support/faq/1266/).

## Build, install and test

From the project root:

```bash
./scripts/refresh-unit-catalog.py
./scripts/build-mission.sh
./scripts/dcs.sh missions
./scripts/dcs.sh bridge
```

Restart the **DCS process once** to load this generic hook. Select and restart `fow.miz` in the DCS WebGUI to load the matching mission; unpause it. After the generic hook passes a live test, later command additions should need only a mission reload and FoW server restart, unless the transport or envelope itself changes. A container restart is not required if DCS itself fully exits and relaunches. The hook logs `JSON bridge listening on 10309`; mission Lua logs `FOW_BRIDGE_READY` once for diagnostics. The log is not the state or command channel.

On the Ubuntu host, outside the DCS container:

```bash
./scripts/fowctl.py ping
./scripts/fowctl.py status
./scripts/fowctl.py move-test
./scripts/fowctl.py status
```

`move-test` reads the current Blue ground group's position, then requests a 150 m northeast off-road move. It is a deliberate test action; use it once per trial. `./scripts/fowctl.py hold 'FoW Blue Ground'`, `./scripts/fowctl.py move 'FoW Blue Ground' X Z`, and `./scripts/fowctl.py move-geo 'FoW Blue Ground' LAT LON` exercise the other operations. The client prints formatted JSON and exits nonzero on a bridge error.

For a client on another machine, keep the Docker port private and tunnel it over SSH to the Ubuntu host:

```bash
ssh -L 10309:127.0.0.1:10309 USER@UBUNTU_HOST
```

Then run the same client against `127.0.0.1:10309` on that machine. Python 3 is the only client dependency. Do not publish the bridge port to the internet.

## Evidence and open work

The earlier fixed-text socket experiment returned live status and completed one Blue move; it has been retired. On 2026-09-20, the consolidated JSON bridge returned `pong`, then reported both active ground groups through `status`. One `move-test` returned `MOVE_ACCEPTED`; subsequent snapshots showed Blue move from `x=-353310.7,z=619886.2` to `x=-353160.9,z=620036.2`, while Red stayed at `x=-194210.1,z=518951.7`. A `hold` order for a nonexistent group returned `ok:false,result:GROUP_MISSING`. No log parsing was used for these results.

The generic hook is staged but awaits a live round trip. Reconnect, process restart, larger snapshots, player joins, and command completion handling also need testing. Before connecting an automated FoW service, add command expiry, replay handling, service authentication as appropriate, and a bounded paging or streaming design if snapshots approach the response limit.
