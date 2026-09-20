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

1. Choose **Blue commander**. On **Orders**, left-click `FoW Blue Ground` on the map or in Groups. Right-click a nearby land point, review the staged line, then click **Send order to DCS**. The order should appear in the history and its target as a dashed line. Later observed movement appears as a solid line.
2. With a ground group selected, choose **Hold position** to cancel movement or **Set fire permission** for Open Fire, Return Fire, or Weapon Hold. These do not need a map point.
3. Click an existing group, edit **Display name**, and save it. This changes only its name in the FoW viewer. DCS retains its original group identifier for orders.
4. On **Spawn**, choose **Ground group or vehicle**, stage a land point within 50 km of a friendly ground group, and search or choose a curated group or installed unit. Some single units are components that need other units to function; use the curated site for a working SAM test. Leave **New group name** empty for a descriptive DCS name, or enter your own. A duplicate DCS name is rejected. The mission attempts to set new groups to Open Fire and reports the result. A complete Hawk site shows an approximate 45 km circle.
5. Switch to **Red commander**. Its response contains Red groups and Red orders only. Enemy contacts are currently empty because DCS detection reports are not wired in. **Admin** shows raw DCS truth for debugging.
6. On **Spawn**, choose **AI aircraft**, then right-click a point 5–150 km from Batumi or Gudauta respectively. Select the aircraft preset and click **Spawn at staged point**. The preset is one unarmed aircraft at 5 km altitude with that point as its waypoint. A Blue Hornet was observed turning toward the selected point in DCS; the Red preset was seen heading toward landing.
7. On **Orders**, left-click an aircraft marker or group, then right-click a point 2–300 km from it. The available order is **Fly to staged point**; choose an altitude in metres MSL and click **Send order to DCS**. This replaces its current route. Player-controlled aircraft cannot be redirected. A live Blue Hornet test confirmed a turn after redirect; altitude changes still need a live test. The dashed line shows FoW's latest requested point; the solid line is the observed track. DCS's internal route is not read back.

Map markers show the DCS unit type, such as `M1A2C`. The sidebar has **Orders**, **Spawn**, and **Groups** tabs; the Groups tab contains the list, recent orders, and raw status. Clicking a group takes you to its Orders tab. Fields change with the selected group or spawn type. Only ground and airplane navigation commands are implemented so far. Helicopters, ships, combat roles, and logistics orders need separate DCS command support.

If an order times out, its state is `unknown`: DCS may have applied it. Check a fresh status before resending. A missing unit means it was absent from a snapshot; this is not a confirmed casualty. Each mission reload or DCS restart begins a fresh ledger with no prior orders or tracks.

## Current boundaries

This is a local single-user prototype. The side selector is **not authentication**: anyone who can reach the local HTTP API can ask for Admin truth or choose either side. Keep the bind address at `127.0.0.1`; the SSH tunnel above is for personal access. Add login and server-enforced roles before exposing it or using it for competitive play.

The map uses Leaflet and OpenStreetMap Standard raster tiles. Place names in those tiles are baked in and cannot be switched to English client-side. We will test a vector basemap with English name fields after the manual command loop is stable. DCS terrain may differ from real-world OSM roads and coastline, so a map click is approximate. The dashed SAM circles are reference weapon ranges, not actual coverage. The 10-second poll is a test cadence, not a final simulation rate.

See [manual commander design](MANUAL_COMMANDER.md) for the command catalog and next data work.
