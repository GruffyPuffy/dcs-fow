# Generic Bridge Architecture

## Overview

The bridge is now **completely generic** - it validates DCS physics constraints and applies data structures, but has **zero mission logic**. All knowledge of DCS formats, mission types, tasks, and behaviors lives in the server.

## Benefits

1. **Bridge never changes** for new mission types (CAS, SEAD, Strike, Transport, etc.)
2. **Fast iteration** - change CAP parameters, add missions, tweak loadouts server-side
3. **No mission rebuild** needed for logic changes
4. **Testable** - DCS structures built in Python can be unit tested
5. **AI-ready** - Server interface perfect for LLM commanders

## Architecture

### Bridge Responsibilities (DCS-specific)

- Validate group exists/doesn't exist
- Validate category (aircraft, ground, etc.)
- Check player-controlled
- Validate land surface (`land.getSurfaceType`)
- Convert lat/lon to DCS x/z (`coord.LLtoLO`, `coord.LOtoLL`)
- Validate coalitions and friendly proximity
- Apply server-built data to DCS APIs

### Server Responsibilities (Mission logic)

- Build complete `coalition.addGroup()` tables
- Build route structures with waypoints and tasks
- Know DCS task formats (CAP, Orbit, Land, etc.)
- Choose loadouts, altitudes, speeds
- Validate mission requests against catalog
- Record orders and flight plans

## Operations

### `spawn_group` - Spawn any unit type

Server sends:
```json
{
  "op": "spawn_group",
  "country_id": 2,
  "category": 0,
  "group_data": { /* complete DCS group table */ },
  "spawn_coords": {"lat": 42.0, "lon": 41.5},
  "mission_coords": {"lat": 42.2, "lon": 41.7}
}
```

Bridge:
- Converts coordinates
- Validates land, friendly proximity (ground), name collision
- Updates group_data with DCS x/z
- Calls `coalition.addGroup()`
- Returns accepted/rejected

### `set_route` - Update group route

Server sends:
```json
{
  "op": "set_route",
  "group_name": "FoW Blue F/A-18C CAP 001",
  "route_data": { /* complete DCS route with waypoints and tasks */ },
  "current_coords": {"lat": 42.0, "lon": 41.5},
  "mission_coords": {"lat": 42.2, "lon": 41.7}
}
```

Bridge:
- Validates group exists, not player-controlled
- Converts coordinates
- Updates route_data with DCS x/z
- Calls `group:getController():setTask({id='Mission', params={route=...}})`

### `set_task` - Apply controller task

Server sends:
```json
{
  "op": "set_task",
  "group_name": "FoW Blue F/A-18C CAP 001",
  "task_data": {
    "task_type": "land",
    "airbase": "Batumi"
  }
}
```

Bridge handles:
- `land` - RTB to airbase
- `hold` - Hold position

### `set_option` - Set controller option

Server sends:
```json
{
  "op": "set_option",
  "group_name": "FoW Blue Ground",
  "option_id": 0,
  "value": 2
}
```

For ROE, alarm state, etc.

## Server DCS Structure Building

Module: `scripts/dcs_structures.py`

### Functions

**`build_air_spawn_data()`** - Complete air spawn with mission
- Inputs: side, preset config, group template, coordinates, name
- Returns: Ready-to-send spawn_group request
- Handles: CAP task, Orbit task, waypoint building

**`build_route_update()`** - Mission change for existing aircraft
- Inputs: mission type, coordinates, altitude, speed
- Returns: Ready-to-send set_route request

**`build_rtb_task()`** - RTB order
- Inputs: airbase name
- Returns: set_task request for landing

**`build_ground_move()`** - Ground unit movement
- Inputs: destination coordinates
- Returns: set_route request for ground group

**`build_roe_option()`** - ROE setting
- Inputs: ROE mode string
- Returns: set_option request with DCS option IDs

## DCS Task Structures

### CAP Task
```lua
{
  id = 'ComboTask',
  params = {
    tasks = {
      [1] = {
        id = 'CAP',
        params = {
          x = destination.x,
          y = destination.z,
          alt = 7000,
          speed = 250,
          pattern = 'Circle',
          priority = 0
        }
      }
    }
  }
}
```

### Patrol (Orbit) Task
```lua
{
  id = 'ComboTask',
  params = {
    tasks = {
      [1] = {
        id = 'Orbit',
        params = {
          pattern = 'Circle',
          speed = 210,
          altitude = 5000
        }
      }
    }
  }
}
```

### Land (RTB) Task
```lua
{
  id = 'Land',
  params = {
    durationFlag = false,
    airdromeId = airbase:getID()
  }
}
```

## Migration Path

1. ✅ Create `dcs_structures.py` module
2. ✅ Create `fow_bridge_generic.lua`
3. ✅ Update server to use `dcs_structures` and new operations:
   - `/api/spawn-air` → uses `build_air_spawn_data()` + `spawn_group` op
   - `/api/set-mission` → uses `build_route_update()` + `set_route` op
   - `/api/rtb` → uses `build_rtb_task()` + `set_task` op
   - `/api/spawn` (ground) → uses `spawn_group` op
  - `/api/move` (ground) → uses `build_ground_route()` + `set_route` op
   - `/api/set-roe` → uses `build_roe_option()` + `set_option` op
4. ✅ Update `build_mission.py` to use `fow_bridge_generic.lua`
5. Test all operations
6. ✅ Remove old bridge code

## Testing

With generic bridge, you can:
- Change CAP engagement range without mission rebuild
- Add new mission types (SEAD, CAS) server-side only
- Tweak orbit patterns, speeds, altitudes instantly
- Test different loadout assignments
- Experiment with DCS task parameters

The bridge is now **stable infrastructure** - changes happen in testable Python code.

## Future Extensions

Easy to add server-side:
- **SEAD missions** - build EngageTargets task for air defense
- **CAS missions** - build Attack/CAS task with target coordinates
- **Strike missions** - build Bombing task with map points
- **Transport missions** - build Transport task with pickup/dropoff
- **Escort missions** - build Escort task following another group
- **Custom patrol patterns** - racetrack, figure-8, etc.
- **Advanced engagement rules** - altitude bands, max range, weapon restrictions

All without touching the bridge!
