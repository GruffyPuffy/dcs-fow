# Manual commander design

Status: ground spawn and movement tested live; names, range overlay, ROE, and installed-unit menu are staged for the next live test. Real fog of war remains.

## Ownership of state

- DCS is authoritative for units, positions, mission time, and whether a task or spawn was accepted.
- The FoW server owns the order ledger and sampled positions in SQLite. A solid line is an observed path; a dashed line is the current accepted destination. An acceptance is not proof of arrival.
- The server will later own side-specific intelligence, resources, and campaign history. `missing` is deliberately separate from `destroyed`; a casualty needs a DCS event or other positive evidence.
- The mission Lua remains small: enumerate state, validate and apply a few commands. No files, sockets, model calls, or strategic reasoning run inside mission Lua.

## Command contract

All callers, including a future AI general, should submit the same typed commands to the FoW server. The server validates side, target, active group, catalog entry, and freshness, records an order ID, then forwards only the narrow instruction to DCS. The bridge performs its own safety checks.

| Command | Input | Current behavior |
|---|---|---|
| `move` | Side, ground group, latitude, longitude | Replaces its route; DCS checks land and 50 km range. |
| `hold` | Side, ground group | Sets the ground group to hold. |
| `spawn` | Side, catalog template, latitude, longitude | Creates one named DCS ground group from fixed mission data; DCS checks land and a friendly ground group within 50 km. |
| `set_roe` | Side, ground group, `open_fire` / `return_fire` / `weapon_hold` | Changes ground AI fire permission independently of movement. |

`missions/spawn_catalog.json` contains curated multi-unit templates. `./scripts/refresh-unit-catalog.py` reads the installed DCS `Scripts/Database/db_countries.lua` and generates `missions/unit_catalog.json` with single-unit choices available to USA and Russia in that core list. Both files are embedded in `fow.miz` at build time and served by the FoW menu. Regenerate and rebuild after DCS updates. This first parser does not discover every third-party mod or verify every unit's behavior.

Current curated templates are a truck, four armored vehicles, and a four-unit Hawk/Buk SAM site for each side. These are test templates, not a realistic platoon or logistics model. A custom DCS name can be entered before spawning; an empty name gets a side and template based default. Existing DCS group names cannot be changed in place, so the FoW server also stores editable display aliases for active groups. DCS [coalition.addGroup documentation](https://www.digitalcombatsimulator.com/es/support/faq/1646/) describes its group data and name-collision behavior; the mission rejects a duplicate requested name.

The web map draws 45 km Hawk and 35 km Buk reference weapon-range circles when all four expected components are present. Values come from the installed pydcs 0.15 unit metadata and are **not live engagement envelopes**. DCS terrain, target altitude, radar and ROE state, ammunition, and surviving components affect actual firing. The updated mission attempts to set spawned groups to Open Fire and reports whether that call succeeded; the FoW server displays only ROE it has positively set. Existing groups show ROE `unknown` until commanded. [DCS Controller options](https://www.digitalcombatsimulator.com/en/support/faq/1267/) define the supported ground ROE values.

Map vehicles use silhouettes by vehicle family with their DCS type underneath. Aircraft retain milsymbol symbols and name labels. See the [viewer guide](VIEWER.md) for mapping and fallback behavior. For aircraft, use the separate [manual air trial](AIR_COMMANDS.md).

## Next experiments

1. Live-test custom names, one generated single unit, ROE changes, and the SAM range overlay. If a unit fails, refine the country catalog or template before widening the menu.
2. Add DCS detection reports to the mission status. The server should retain only last known enemy contacts per side, with source, time, and uncertainty. Never infer an enemy contact from Admin raw truth.
3. Add DCS birth/death events and reconcile them with snapshots before counting casualties. Add resources and spawn costs only once the event ledger is trustworthy.
4. Test an English-label vector basemap and check map alignment against DCS. OpenStreetMap raster tile labels cannot be translated after rendering.
5. Add authentication and role-bound views before remote multiplayer use. Today, Blue/Red/Admin are local display modes, not a security boundary.
