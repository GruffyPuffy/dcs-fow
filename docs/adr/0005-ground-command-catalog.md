# ADR 0005: Ground-unit catalog and commander metadata

Date: 2026-09-20  
Status: Proposed; live validation pending

## Context

A fixed spawn catalog made a truck and Hawk site appear in DCS, but the resulting `FoW Spawn blue 2` name did not tell a commander what it was. One hardcoded list also misses changes in the installed DCS unit set. SAM range graphics and firing permission are distinct: a reference range is useful on the map, while DCS ROE controls whether a ground group may engage.

## Proposed decision

Keep multi-unit groups as curated templates in `missions/spawn_catalog.json`. Generate single-unit choices from the installed DCS `Scripts/Database/db_countries.lua` USA and Russia ground lists with `scripts/refresh-unit-catalog.py`. Embed the merged catalog in `fow.miz` at build time. The FoW server serves the same merged menu; the mission accepts only an embedded catalog ID and validates side, land, distance, and group-name uniqueness.

Before spawn, allow a custom DCS group name; otherwise use a side and template based name. For groups already spawned, retain the DCS identifier and allow a separate FoW display alias in SQLite. Make ground ROE an explicit command. Show range circles only for recognized complete SAM templates, labeled as reference values.

## Alternatives

- A free-form unit type and Lua group table would cover more cases but make validation and reproducibility harder.
- Editing the installed DCS database would create an update-sensitive dependency.
- Treating a drawn circle as actual engagement coverage would misstate terrain, altitude, radar, ammo and ROE effects.

## Consequences and validation

Refresh and rebuild the mission after DCS updates to change available units. The parser currently covers the core country file, not every third-party module. A listed unit may still need supporting components or live validation to operate. Test a custom name, one generated single unit, duplicate-name rejection, all three ROE values, range circle behavior, and mission restart. Confirm no untrusted request text becomes a DCS type or task table without catalog validation. Air spawning has a separate [trial plan](../AIR_COMMANDS.md).

Sources: [DCS coalition and group APIs](https://www.digitalcombatsimulator.com/es/support/faq/1646/), [DCS Controller ROE options](https://www.digitalcombatsimulator.com/en/support/faq/1267/).
