# Local mission viewer

Status: viewer implemented; right-click move awaits a DCS process and mission restart with the updated hook and `fow.miz`.

The viewer is a small Python HTTP server. It asks the FoW/DCS JSON bridge for a snapshot every 10 seconds and serves the latest result to a browser. Browser refreshes read a cache, so opening another tab does not increase DCS polling. Selecting an active ground group and right-clicking the map offers a confirmed move order. It binds to `127.0.0.1:8765` by default; the bridge remains on `127.0.0.1:10309`.

## Start

Build and deploy the current mission if needed:

```bash
./scripts/build-mission.sh
./scripts/dcs.sh missions
./scripts/dcs.sh bridge
```

Fully restart the DCS process to load the updated hook, then select/restart `fow.miz` in the DCS WebGUI and unpause it. Then run:

```bash
./scripts/fow-viewer.py
```

Open `http://127.0.0.1:8765/` on the Ubuntu host. To view from a Windows machine, use an SSH tunnel such as `ssh -L 8765:127.0.0.1:8765 USER@UBUNTU_HOST`, then open the same address in a browser on Windows. Stop the viewer with Ctrl+C. Python 3 and the existing FoW bridge are the only server-side dependencies.

## What it shows

The map plots every active unit and static object returned by `status` using coordinates converted by DCS from its local `x/z` coordinates to latitude/longitude. Group markers use simple Blue, Red and Neutral military-style frames with category icons; they are not certified APP-6 symbols. The sidebar lists active groups and lets you center on one. The viewer retains the last snapshot and shows a stale warning if DCS stops responding.

To test movement, click the Blue ground group in the sidebar (or its map marker), right-click a nearby land point, and confirm **Send move order**. The viewer sends `move_geo`; DCS converts the clicked latitude/longitude to local mission coordinates and checks the land surface and 50 km range. The response acknowledges task acceptance, and later position refreshes show whether the unit moved. A rejected order is shown in the sidebar. The viewer refuses to send while its snapshot is stale.

The browser loads Leaflet 1.9.4 and [OpenStreetMap Standard tiles](https://operations.osmfoundation.org/policies/tiles/) over the internet. OSM attribution is displayed on the map. Tiles are fetched only for the visible viewport; normal browser caching applies. DCS Caucasus roads, buildings and coastline may differ from the real-world OSM map. This prototype is for seeing positions and movement, not for precise route planning. A later version could use licensed DCS-aligned tiles or a self-hosted map layer.

The viewer displays the raw, omniscient bridge state and can send test orders. Keep it local while fog-of-war filtering and login are not implemented. The 10-second poll is a trial setting, not a planned final simulation cadence. It can be changed with `--interval`.
