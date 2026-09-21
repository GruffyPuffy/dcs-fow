# Manual air-command trial

Status: first Blue F/A-18C air-start and waypoint path confirmed in a live DCS test. Red MiG-29S remains untested.

The viewer can request one Blue F/A-18C or Red MiG-29S AI aircraft. The aircraft starts in the air near Batumi or Gudauta at 5 km altitude. A right-clicked map point, 5–150 km from that start, becomes its first waypoint. The flight is unarmed. The FoW server validates the preset, side, name, and coordinates; the hook forwards a compact command; mission Lua clones a pydcs-generated aircraft group and asks DCS to spawn it. The server records the accepted order and observed position. A live Blue trial confirmed that the Hornet turned toward the selected waypoint.

The next air trial should add a verified loadout and a CAP route. A human pilot slot stays in `fow.miz` as it is today.

After selecting an aircraft on the map, the viewer offers **Fly to staged point**. It replaces the AI group's route with a single new destination at the chosen altitude (1000–12000 m MSL), using a nominal 210 m/s speed. Targets must be 2–300 km away. DCS rejects player-controlled aircraft. The map shows the most recent FoW requested point and the aircraft's observed trail. It does not read DCS's internal route back. A turn after this order was observed in a live Blue Hornet test; altitude changes still need a live test.

Proposed `spawn_flight` input:

| Field | First trial | Later options |
| --- | --- | --- |
| Side and name | Blue or Red; editable name | Display alias after spawn |
| Aircraft | Fixed, verified AI type | Catalog from installed DCS aircraft list |
| Role | CAP preset | CAS, SEAD, escort, transport |
| Start | Air start at approved point and altitude | Runway, hot ramp, cold ramp; parking validation |
| Flight size | One or two | Larger flights with spacing checks |
| Payload and fuel | Known working preset | Named loadout presets compatible with role and aircraft |
| Route | Two map points, speed and altitude preset | More waypoints, patrol zone, recovery airbase |
| Launch | Immediate | Scheduled time or explicit launch order |

The FoW server should validate the structured request and retain the flight plan and launch state. The mission Lua should only translate a verified preset into DCS group data and report acceptance. An AI general would use this exact command catalog later; it would choose among validated presets and points rather than emit arbitrary DCS task tables.

Acceptance order: air-start CAP flight appears; follows the route; engages according to explicit ROE; returns or lands; server tracks its state. Only then test runway and ramp starts, parking allocation, and delayed launch. [pydcs](https://github.com/pydcs/dcs) supports mission generation with airport start types and task classes, but dynamic live spawning needs its own DCS `coalition.addGroup` validation. The [DCS user manual](https://www.digitalcombatsimulator.com/upload/iblock/ed6/87v22jwd1xh51i3rgki944xsf503istq/DCS_User_Manual_EN_2020.pdf) describes uncontrolled ramp starts and START triggers for delayed AI launch.
# Ready aircraft

The default scenario includes two cold, parked fighters at Batumi and two at
Gudauta. In **Spawn → Ready aircraft**, a commander can issue **Scramble CAP**.
DCS starts the uncontrolled group and then flies its mission-defined CAP route.
The aircraft, route, combat, losses, landing, and base ownership remain DCS
state; FoW only sends the native `Start` command and records that order.
