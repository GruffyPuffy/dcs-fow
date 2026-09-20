# Flight Plan Feature Testing Guide

## Implementation Summary

Added named flight plan presets for spawning fighters with Patrol and CAP missions. The implementation keeps flight plan logic server-side while minimizing changes to the `.miz` and bridge.

## Changes Made

### 1. Air Catalog Structure (`missions/air_trial.json`)
- Restructured to include `loadouts` and `presets` sections
- **Loadouts**: Weapon configurations per side (cap_light, patrol_clean)
  - Blue: AIM-120C + AIM-9X for CAP, fuel tanks for patrol
  - Red: R-27R + R-73 for CAP, fuel tanks for patrol
- **Presets**: Named mission configurations
  - `hornet_cap` / `hornet_patrol` for Blue F/A-18C
  - `mig29_cap` / `mig29_patrol` for Red MiG-29S
- Each preset includes: aircraft type, mission_type (CAP/patrol), altitude, speed, loadout reference, default RTB base, orbit radius (for future use)

### 2. Mission Builder (`missions/build_mission.py`)
- Added airbase enumeration from terrain
- Embeds `FoWAirbaseCatalog` with Blue/Red airbases (name, lat, lon)
- Generates multiple aircraft templates per side based on presets
- Applies loadouts using pydcs `load_pylon()` before capturing group data
- Stores preset metadata (mission_type, altitude, speed, etc.) alongside group data

### 3. Mission Bridge (`missions/fow_bridge_generic.lua`)
- Resolves server-provided geographic coordinates with DCS `coord.LLtoLO`
- Resolves server-provided airbase references to DCS IDs
- Applies only generic spawn, route, task, and option operations
- Contains no CAP, patrol, RTB, ground-placement, or ROE policy

### 4. Server (`scripts/fow-server.py`)
- **Updated `/api/spawn-air`**: Validates against new preset catalog structure
  - Extracts mission_type, loadout, rtb_base from preset
  - Stores flight plan details in database
- **New `/api/set-mission`**: Changes mission type for existing aircraft
  - Validates mission_type (patrol/CAP), altitude, waypoint
  - Requires aircraft group (category 0)
- **New `/api/rtb`**: Orders aircraft to land
  - Validates airbase name from catalog
  - Requires aircraft group
- **New `/api/airbase-catalog`**: Returns available airbases (placeholder for now)

### 5. Database (`scripts/fow_store.py`)
- Extended `orders` table with columns: `mission_type`, `loadout`, `rtb_base`
- Updated `create_order()` to accept and store flight plan parameters
- Auto-migration adds new columns if missing

## Testing Workflow

### Prerequisites
```bash
./scripts/refresh-unit-catalog.py
./scripts/build-mission.sh
./scripts/dcs.sh missions
./scripts/dcs.sh bridge
```

Restart DCS process to load the hook, then load and unpause `fow.miz`.

### Test 1: Spawn Hornet with Patrol Mission
**Objective**: Verify aircraft spawns at air start and flies to waypoint at specified altitude

Expected catalog call:
```json
{
  "side": "blue",
  "preset": "hornet_patrol",
  "lat": 42.0,
  "lon": 41.5
}
```

Expected behavior:
- Hornet spawns near Batumi at 5000m altitude
- Flies toward specified waypoint at 210 m/s
- No engagement behavior (simple waypoint)
- Database shows mission_type='patrol', loadout='patrol_clean', rtb_base='Batumi'

### Test 2: Spawn Hornet with CAP Mission
**Objective**: Verify CAP task is applied with engagement rules

Expected catalog call:
```json
{
  "side": "blue",
  "preset": "hornet_cap",
  "lat": 42.2,
  "lon": 41.7
}
```

Expected behavior:
- Hornet spawns near Batumi at 7000m altitude
- Flies to waypoint at 250 m/s
- Will attempt to engage aircraft within ~40nm if detected
- Database shows mission_type='CAP', loadout='cap_light'

### Test 3: Change Mission Type
**Objective**: Update existing aircraft from patrol to CAP

Expected API call to `/api/set-mission`:
```json
{
  "side": "blue",
  "group": "FoW Blue F/A-18C Patrol 001",
  "mission_type": "CAP",
  "lat": 42.1,
  "lon": 41.6,
  "altitude_m": 7000
}
```

Expected behavior:
- Aircraft routes to new waypoint at new altitude
- Engagement task is added
- Status updates show new mission point

### Test 4: RTB Command
**Objective**: Order aircraft to land at Batumi

Expected API call to `/api/rtb`:
```json
{
  "side": "blue",
  "group": "FoW Blue F/A-18C CAP 001",
  "airbase": "Batumi"
}
```

Expected behavior:
- Aircraft routes to Batumi
- Attempts landing approach
- Bridge returns RTB_ACCEPTED

### Test 5: Database Verification
```sql
SELECT group_name, mission_type, loadout, rtb_base, state 
FROM orders 
WHERE op IN ('spawn_air', 'set_mission', 'rtb')
ORDER BY created_at DESC 
LIMIT 10;
```

Expected: All flight plan details are recorded and persist across spawns/commands

## Known Limitations (First Version)

- **Single aircraft only**: Multi-ship formations deferred
- **Air start only**: Runway/ramp starts not implemented
- **Simple orbit**: Orbit radius in catalog but pattern not implemented
- **No automatic RTB**: Fuel-based RTB requires fuel reporting in bridge status
- **Default engagement rules**: CAP uses DCS defaults, no altitude bands or range customization yet
- **No CAS/SEAD**: Ground attack missions deferred pending target designation

## Future Enhancements

1. **Patrol patterns**: Use orbit_radius_m for racetrack or circular patterns
2. **Flight formations**: Support 2-ship and 4-ship with proper spacing
3. **Runway starts**: Validate parking and airbase ownership
4. **Automatic RTB**: Monitor fuel levels and trigger landing
5. **Advanced CAP parameters**: Altitude bands, max engage range
6. **Ground attack**: CAS and SEAD with target designation and loadout validation
7. **Red aircraft testing**: MiG-29S with opposing missions

## Error Messages Reference

Bridge errors:
- `UNKNOWN_AIR_PRESET`: Preset not found in catalog
- `AIR_WAYPOINT_RANGE`: Waypoint <5km or >150km from spawn
- `INVALID_NAME` / `NAME_IN_USE`: Custom name validation failed
- `AIR_SPAWN_FAILED`: DCS rejected coalition.addGroup
- `MISSION_SET_FAILED`: DCS rejected setTask for mission change
- `RTB_FAILED`: DCS rejected Land task
- `AIRBASE_NOT_FOUND`: Airbase name not found in DCS
- `INVALID_SET_MISSION`: Mission type not patrol/CAP, or invalid altitude
- `INVALID_RTB`: Airbase name validation failed

Server errors:
- `Unknown spawn preset`: Preset not in catalog for that side
- `Invalid mission type`: Not patrol or CAP
- `Invalid airbase`: Name validation failed
- `Choose an active group on this side`: Group not found or wrong category

## Catalog Structure Reference

Air presets (`missions/air_trial.json`):
```json
{
  "loadouts": {
    "blue": {
      "cap_light": { "label": "...", "pylons": {...} },
      "patrol_clean": { "label": "...", "pylons": {...} }
    }
  },
  "presets": {
    "blue": {
      "hornet_cap": {
        "label": "F/A-18C CAP",
        "aircraft": "FA_18C_hornet",
        "mission_type": "CAP",
        "altitude_m": 7000,
        "speed_mps": 250,
        "loadout": "cap_light",
        "default_rtb_base": "Batumi",
        "orbit_radius_m": 18520
      }
    }
  }
}
```

Embedded in mission as `FoWAirCatalog.presets[side][preset_name]` and `FoWAirCatalog.loadouts[side][loadout_name]`.
