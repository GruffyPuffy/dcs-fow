# Manual commander prototype

The local FoW server polls the DCS bridge every 10 seconds and serves a map at `http://127.0.0.1:8765/`. It records manual orders, observed units, and sampled group positions in `data/fow.sqlite3` (ignored by Git). The database survives a FoW server restart within the same DCS mission run. On mission reload or DCS restart, the next status response clears old orders, tracks, aliases, ROE, and observed units. `scripts/fow-viewer.py` remains as a compatibility launcher; prefer `./scripts/fow-server.py`.

## Start and test

Refresh the menu from the installed DCS country database, then build and deploy:

```bash
./scripts/refresh-unit-catalog.py
./scripts/build-mission.sh
./scripts/dcs.sh missions
./scripts/dcs.sh bridge
```

The hook needs a **DCS process restart**. Then load or restart `fow.miz` in the DCS dashboard. Start the FoW server:

```bash
./scripts/fow-server.py
```

Open `http://127.0.0.1:8765/` on Ubuntu. From Windows, tunnel it with `ssh -L 8765:127.0.0.1:8765 USER@UBUNTU_HOST`, then open the same URL on Windows. Stop the FoW server with Ctrl+C. It needs Python 3 and the existing local bridge, with no Python package installation.

### Strategic-base trial

The map labels Batumi and Gudauta as Blue and Red home bases and shows the coalition DCS currently assigns to every airbase. Kobuleti, Senaki-Kolkhi, Kutaisi and Sukhumi-Babushara are configured as attackable objectives.

On **Spawn**, choose **Attack base** to launch one randomized combined-arms package from a configured approach roughly 5 km from the objective. DCS receives the group and its route; DCS combat and native airbase capture determine the outcome. Each side may have two active assaults.

Enable **Quick trial** to move the same configured approach to roughly 2.3 km from the airbase, just outside the nominal DCS capture radius. This is a local testing aid for observing movement, contention and capture without waiting for the full approach.

Choose **Defend base** to add a randomized defense package at a strategic base DCS currently reports as owned. Alternatively choose a specific **Base defense package**, stage a point within 8 km of an owned strategic base, and spawn it there. Each base may have three active spawned defense packages. Spawned assault and defense units are capped at 80 per coalition, and active aircraft at 12 per coalition.

For the first live test, attack Kobuleti from Blue, confirm the force appears on the configured southern approach, and watch whether it reaches the airfield and changes native DCS ownership. Then try a Red assault or player intervention. Automatic CAP/CAS/SEAD support is intentionally deferred until the ground capture loop is proven.

1. Choose **Blue commander**. On **Orders**, left-click `FoW Blue Ground` on the map or in Groups. Right-click a nearby land point, review the staged line, then click **Send order to DCS**. The order should appear in the history and its target as a dashed line. Later observed movement appears as a solid line.
2. With a ground group selected, choose **Hold position** to cancel movement or **Set fire permission** for Open Fire, Return Fire, or Weapon Hold. These do not need a map point.
3. Click an existing group, edit **Display name**, and save it. This changes only its name in the FoW viewer. DCS retains its original group identifier for orders.
4. On **Spawn**, choose **Ground group or vehicle**, stage a land point within 50 km of a friendly ground group, and search or choose a curated group or installed unit. Some single units are components that need other units to function; use the curated site for a working SAM test. Leave **New group name** empty for a descriptive DCS name, or enter your own. A duplicate DCS name is rejected. The mission attempts to set new groups to Open Fire and reports the result. A complete Hawk site shows an approximate 45 km circle.
5. Switch to **Red commander**. Its response contains Red groups and Red orders only. Enemy contacts are currently empty because DCS detection reports are not wired in. **Admin** shows raw DCS truth for debugging.
6. On **Spawn**, choose **AI aircraft**, then right-click a point 5–150 km from Batumi or Gudauta respectively. Select the aircraft preset and click **Spawn at staged point**. The preset is one unarmed aircraft at 5 km altitude with that point as its waypoint. A Blue Hornet was observed turning toward the selected point in DCS; the Red preset was seen heading toward landing.
7. On **Orders**, left-click an aircraft marker or group, then right-click a point 2–300 km from it. The available order is **Fly to staged point**; choose an altitude in metres MSL and click **Send order to DCS**. This replaces its current route. Player-controlled aircraft cannot be redirected. A live Blue Hornet test confirmed a turn after redirect; altitude changes still need a live test. The dashed line shows FoW's latest requested point; the solid line is the observed track. DCS's internal route is not read back.

Aircraft and helicopters use [milsymbol](https://github.com/spatialillusions/milsymbol) symbols. Ground units use local SVG silhouettes for tanks, armored vehicles, trucks, fuel trucks, air defense, radar, artillery, and infantry; ships and trains also have silhouettes. These represent vehicle families, not exact models. Ground families are inferred from DCS type names, with a generic vehicle fallback for unrecognized types. Vehicle labels show the DCS type (such as `BMP-2`); aircraft labels show the custom group name, callsign, or unit name. Labels are small and pale beneath the icon; click for full unit and group details. Coalition colors remain Blue, Red, and Neutral. Aircraft symbols load pinned milsymbol 2.2.0 from a CDN, with fallback markers if unavailable; vehicle icons need no external library. The sidebar has **Orders**, **Spawn**, and **Groups** tabs; the Groups tab contains the list, recent orders, and raw status. Clicking a group takes you to its Orders tab. Fields change with the selected group or spawn type. Only ground and airplane navigation commands are implemented so far. Helicopters, ships, combat roles, and logistics orders need separate DCS command support.

If an order times out, its state is `unknown`: DCS may have applied it. Check a fresh status before resending. A missing unit means it was absent from a snapshot; this is not a confirmed casualty. Each mission reload or DCS restart begins a fresh ledger with no prior orders or tracks.

## Current boundaries

This is a local single-user prototype. The side selector is **not authentication**: anyone who can reach the local HTTP API can ask for Admin truth or choose either side. Keep the bind address at `127.0.0.1`; the SSH tunnel above is for personal access. Add login and server-enforced roles before exposing it or using it for competitive play.

The map uses Leaflet and OpenStreetMap Standard raster tiles. Place names in those tiles are baked in and cannot be switched to English client-side. We will test a vector basemap with English name fields after the manual command loop is stable. DCS terrain may differ from real-world OSM roads and coastline, so a map click is approximate. The dashed SAM circles are reference weapon ranges, not actual coverage. The 10-second poll is a test cadence, not a final simulation rate.

See [manual commander design](MANUAL_COMMANDER.md) for the command catalog and next data work.

Hover over a unit to highlight all members of its group and show the group display name above that unit. Clicking a unit or selecting its group in the sidebar keeps the group highlighted with a thin gold ring until another group is selected. Hovering another group temporarily highlights its members while preserving the selection. Selection highlighting is restored after each status refresh.

Selecting a parked alert flight offers **Scramble CAP — start parked flight** in Orders. This starts its configured DCS CAP route without a staged destination. Once the scramble is accepted, the normal aircraft orders become available. The Spawn tab retains its ready-aircraft controls. Unsupported unit types show an explicit disabled order option.

SAM reference ranges have a faint coalition-colored fill beneath other map overlays and ignore pointer events. Clicking the map, including inside a range circle, clears the group selection and closes its popup.

AI AWACS radar contacts are now collected for each coalition. Current range-resolved detections of opposing aircraft/helicopters appear as contact diamonds; identification is shown only when DCS reports the type known. Click for reporting AWACS units, radar provenance, reported altitude, and observation age. Lost detections remain at the last observed position, faded, for five mission minutes. No enemy group names, callsigns, fuel, or live hidden positions are included. Reports are shared across the observing coalition as a FoW rule, not an exact simulation of cockpit Link 16. Human aircraft sensors and bearing-only reports are not included. Contact memory resets on FoW server restart or DCS mission change/time reset. A disconnected server's entire picture is stale; check the connection indicator.

Activation: rebuild with `./scripts/build-mission.sh`, deploy with `./scripts/dcs.sh missions`, reload the mission in DCS, and restart the FoW server. Older missions show “AWACS contacts unavailable”. Live acceptance: spawn an AI AWACS and an opposing aircraft, confirm only the observing side gets a contact; remove radar detection and verify position freezes and the contact expires after five mission minutes. Verify unknown types remain unidentified and mission reload clears contact memory. DCS radar API behavior still needs this live validation. Admin raw status includes `awacs_sensor_errors` to diagnose failed sensor calls.

Aircraft spawning accepts an optional **Spawn altitude (ft MSL)** between 3,281 and 39,370 ft. Leave it blank for the selected preset default. The altitude applies to the initial aircraft position, first waypoint, and mission waypoint/task. This is altitude above mean sea level, not terrain clearance.

Ground groups default explicitly to **Open Fire**. The mission bridge applies this once per group, including initial groups, late activations, and spawned units. Subsequent **Return Fire** or **Weapons Hold** orders are preserved. The displayed ROE reflects the last setting applied by FoW, not an independent readback of DCS controller options. Radar alarm state and engagement conditions remain controlled by DCS.

Confirmed kills are recorded from DCS `S_EVENT_KILL`, independently of radar contact loss. **Groups → Confirmed kills** shows the latest 30 reports with attacker group, target type, mission time, and weapon when available. The summary and group roster show kill counts. Reports also appear as structured `kills` records in the side-filtered status API for future commanders. Each side receives enemy kills credited to its forces, even if the attacker no longer exists. This is shared DCS-confirmed information, not simulated pilot visual confirmation. Admin can additionally see friendly fire and unattributed events. Enemy target names and internal target IDs are not exposed in coalition reports.

A matching coalition contact is labeled **destroyed** for up to 60 mission seconds at its last reported position; the kill report remains in the ledger. Reports persist across FoW restarts and clear with a new mission. The bridge retains the latest 200 events between polls; a longer outage with more than 200 kills can lose older uncollected reports. Events that occurred before the updated bridge was loaded cannot be reconstructed. Missing attacker/weapon information is recorded as unknown, never inferred from radar loss. Deploy/reload the rebuilt mission and restart FoW to activate collection. Live validation: cause one enemy kill, verify exactly one report and matching group count, then check persistence after a FoW restart and isolation in the opposing side view.

Admin view hides radar-contact overlays and their summary because it already displays actual units. Blue and Red views retain their coalition contact picture.

In every view, nearby aircraft of the same type within a group share one marker with a count badge. The marker stays at a representative aircraft’s actual position, and its popup lists the grouped aircraft. Zooming in separates the markers as their map spacing increases. Ground-unit markers remain individual.
