"""Build complete DCS data structures for the mission bridge."""

import math


def build_start_command() -> dict:
    """Return DCS's native command for starting an uncontrolled aircraft group."""
    return {'id': 'Start', 'params': {}}


def air_start_position(lat: float, lon: float, distance_m: float = 25000) -> tuple[float, float]:
    """Return an air-start point west of the selected mission point."""
    earth_radius_m = 6371000
    angular_distance = distance_m / earth_radius_m
    latitude = math.radians(lat)
    longitude = math.radians(lon)
    bearing = math.radians(270)
    spawn_latitude = math.asin(
        math.sin(latitude) * math.cos(angular_distance)
        + math.cos(latitude) * math.sin(angular_distance) * math.cos(bearing)
    )
    spawn_longitude = longitude + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(latitude),
        math.cos(angular_distance) - math.sin(latitude) * math.sin(spawn_latitude),
    )
    return math.degrees(spawn_latitude), math.degrees(spawn_longitude)


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the initial bearing in DCS heading radians."""
    latitude1, latitude2 = math.radians(lat1), math.radians(lat2)
    longitude_delta = math.radians(lon2 - lon1)
    east = math.sin(longitude_delta) * math.cos(latitude2)
    north = math.cos(latitude1) * math.sin(latitude2) \
        - math.sin(latitude1) * math.cos(latitude2) * math.cos(longitude_delta)
    return math.atan2(east, north) % (2 * math.pi)


def offset_position(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    distance = math.hypot(north_m, east_m)
    if distance == 0:
        return lat, lon
    bearing = math.atan2(east_m, north_m)
    earth_radius_m = 6371000
    angular_distance = distance / earth_radius_m
    latitude = math.radians(lat)
    longitude = math.radians(lon)
    result_latitude = math.asin(
        math.sin(latitude) * math.cos(angular_distance)
        + math.cos(latitude) * math.sin(angular_distance) * math.cos(bearing)
    )
    result_longitude = longitude + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(latitude),
        math.cos(angular_distance) - math.sin(latitude) * math.sin(result_latitude),
    )
    return math.degrees(result_latitude), math.degrees(result_longitude)

def build_air_spawn_data(side: str, preset_config: dict, group_template: dict | None, 
                         spawn_lat: float, spawn_lon: float, 
                         mission_lat: float, mission_lon: float,
                         group_name: str) -> dict:
    """Build complete coalition.addGroup data for air spawn.
    
    Args:
        side: 'blue' or 'red'
        preset_config: Preset from air_trial.json (mission_type, altitude, speed, etc)
        group_template: DCS group data from embedded catalog
        spawn_lat/lon: Spawn position (will be converted to x/z by bridge)
        mission_lat/lon: Mission waypoint (will be converted to x/z by bridge)
        group_name: DCS group name
    
    Returns:
        Complete arguments for the bridge's generic spawn operation.
    """
    import copy
    
    # If no template provided, build minimal group structure for air start
    # DCS expects units and route.points as integer-keyed dicts (Lua arrays)
    if group_template is None:
        group_template = {
            'units': [{
                'type': preset_config.get('aircraft', 'FA_18C_hornet'),
                'heading': 0,
                'skill': 'High',
                'alt': preset_config['altitude_m'],
                'speed': preset_config['speed_mps'],
                'alt_type': 'BARO'
            }],
            'route': {
                'points': [
                    {
                        'alt': preset_config['altitude_m'],
                        'speed': preset_config['speed_mps'],
                        'type': 'Turning Point',
                        'action': 'Turning Point',
                        'alt_type': 'BARO',
                        'speed_locked': True,
                        'ETA': 0,
                        'ETA_locked': False,
                        'task': {'id': 'ComboTask', 'params': {'tasks': []}}
                    },
                    {}
                ]
            },
            'x': 0,
            'y': 0,
            'hidden': False,
            'visible': True,
            'start_time': 0,
            'task': 'CAP',
            'modulation': 0,
            'frequency': 124,
            'uncontrolled': False
        }
    
    # Copy template to avoid modifying catalog
    group_data = copy.deepcopy(group_template)
    group_data['name'] = group_name
    group_data['task'] = {'tanker': 'Refueling', 'transport': 'Transport', 'patrol': 'Nothing'}.get(preset_config['mission_type'], preset_config['mission_type'])
    group_data.pop('groupId', None)
    
    # Handle both list and dict formats for units
    units = group_data.get('units', [])
    if isinstance(units, dict):
        # Convert dict to list, sorted by numeric keys
        units = [units[k] for k in sorted(units.keys(), key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else x)]
        group_data['units'] = units
    
    # Update unit name and ensure no ID conflicts
    if units:
        unit = units[0]
        unit['name'] = f"{group_name} Pilot 1"
        unit.pop('unitId', None)
        unit['skill'] = 'High'
        unit['heading'] = initial_bearing(spawn_lat, spawn_lon, mission_lat, mission_lon)
        unit['__geo'] = {'lat': spawn_lat, 'lon': spawn_lon}
    
    # Build mission waypoint task based on mission type
    mission_task = _build_mission_task(
        preset_config['mission_type'],
        preset_config['altitude_m'],
        preset_config['speed_mps']
    )
    
    # Handle both list and dict formats for route points
    points = group_data['route'].get('points', [])
    if isinstance(points, dict):
        # Convert dict to list
        points = [points.get(str(i+1), {}) for i in range(max(int(k) for k in points.keys() if str(k).isdigit()))]
        group_data['route']['points'] = points
    
    # Ensure we have at least 2 points
    while len(points) < 2:
        points.append({})
    
    points[1] = {
        'alt': preset_config['altitude_m'],
        'alt_type': 'BARO',
        'speed': preset_config['speed_mps'],
        'speed_locked': True,
        'ETA': 0,
        'ETA_locked': False,
        'type': 'Turning Point',
        'action': 'Turning Point',
        'name': 'Mission point',
        'task': mission_task,
        '__geo': {'lat': mission_lat, 'lon': mission_lon},
    }
    points[0]['__geo'] = {'lat': spawn_lat, 'lon': spawn_lon}
    group_data['__geo'] = {'lat': spawn_lat, 'lon': spawn_lon}
    
    return {
        'country_id': 2 if side == 'blue' else 0,  # USA=2, Russia=0
        'category': 0,  # AIRPLANE
        'group_data': group_data,
    }


def build_route_update(mission_type: str, current_lat: float, current_lon: float,
                      mission_lat: float, mission_lon: float, 
                      altitude_m: int, speed_mps: int) -> dict:
    """Build route update for existing aircraft group.
    
    Args:
        mission_type: 'CAP' or 'patrol'
        current_lat/lon: Current aircraft position
        mission_lat/lon: New mission waypoint
        altitude_m: Mission altitude MSL
        speed_mps: Mission speed
    
    Returns:
        Complete route arguments for the bridge's generic route operation.
    """
    mission_task = _build_mission_task(mission_type, altitude_m, speed_mps)
    
    return {
        'route_data': {
            'points': [
                {
                    'alt_type': 'BARO',
                    'speed': speed_mps,
                    'type': 'Turning Point',
                    'action': 'Turning Point',
                    'speed_locked': True,
                    'ETA': 0,
                    'ETA_locked': False,
                    'task': {'id': 'ComboTask', 'params': {'tasks': []}},
                    '__geo': {'lat': current_lat, 'lon': current_lon},
                },
                {
                    'alt': altitude_m,
                    'alt_type': 'BARO',
                    'speed': speed_mps,
                    'speed_locked': True,
                    'ETA': 0,
                    'ETA_locked': False,
                    'type': 'Turning Point',
                    'action': 'Turning Point',
                    'name': 'Mission point',
                    'task': mission_task,
                    '__geo': {'lat': mission_lat, 'lon': mission_lon},
                }
            ]
        },
    }


def build_rtb_task(airbase_name: str, airbase_lat: float, airbase_lon: float,
                   current_lat: float, current_lon: float,
                   current_altitude_m: float, speed_mps: float = 180) -> dict:
    """Build a fixed-wing mission route ending at an airbase."""
    return {
        'id': 'Mission',
        'params': {
            'airborne': True,
            'route': {
                'points': [
                    {
                        'alt': max(1000, current_altitude_m),
                        'alt_type': 'BARO',
                        'speed': speed_mps,
                        'speed_locked': True,
                        'ETA': 0,
                        'ETA_locked': False,
                        'type': 'Turning Point',
                        'action': 'Turning Point',
                        'task': {'id': 'ComboTask', 'params': {'tasks': []}},
                        '__geo': {'lat': current_lat, 'lon': current_lon},
                    },
                    {
                        'alt': 0,
                        'alt_type': 'BARO',
                        'speed': min(150, speed_mps),
                        'speed_locked': True,
                        'ETA': 0,
                        'ETA_locked': False,
                        'type': 'Land',
                        'action': 'Landing',
                        'task': {'id': 'ComboTask', 'params': {'tasks': []}},
                        'airdromeId': {'__ref': 'airbase_id', 'name': airbase_name},
                        '__geo': {'lat': airbase_lat, 'lon': airbase_lon},
                    },
                ]
            },
        },
    }


def build_ground_route(current_lat: float, current_lon: float, lat: float, lon: float) -> dict:
    """Build ground unit move order.
    
    Args:
        lat/lon: Destination coordinates
    
    Returns:
        A complete DCS ground route.
    """
    return {'points': [
        {'action': 'Off Road', 'speed': 5, 'speed_locked': True,
         '__geo': {'lat': current_lat, 'lon': current_lon}},
        {'action': 'Off Road', 'speed': 5, 'speed_locked': True,
         '__geo': {'lat': lat, 'lon': lon}},
    ]}


def build_ground_spawn_data(side: str, template: dict, group_name: str,
                            lat: float, lon: float,
                            destination: tuple[float, float] | None = None) -> dict:
    units = []
    for index, entry in enumerate(template['units'], 1):
        unit_lat, unit_lon = offset_position(lat, lon, entry.get('dx', 0), entry.get('dy', 0))
        units.append({
            'type': entry['type'], 'name': f'{group_name} Unit {index}',
            'heading': 0, 'skill': 'Average', 'playerCanDrive': False,
            '__geo': {'lat': unit_lat, 'lon': unit_lon},
        })
    group_data = {
        'name': group_name, 'task': 'Ground Nothing', 'units': units,
        'visible': True, 'hidden': False, 'start_time': 0,
        '__geo': {'lat': lat, 'lon': lon},
    }
    if destination:
        group_data['route'] = build_ground_route(
            lat, lon, destination[0], destination[1])
    return {
        'country_id': 2 if side == 'blue' else 0,
        'category': 2,
        'group_data': group_data,
    }


def build_roe_option(mode: str) -> dict:
    """Build ROE option for ground units.
    
    Args:
        mode: 'open_fire', 'return_fire', or 'weapon_hold'
    
    Returns:
        Dict with DCS option ID and value
    """
    roe_values = {
        'open_fire': 2,  # AI.Option.Ground.val.ROE.OPEN_FIRE
        'return_fire': 3,  # AI.Option.Ground.val.ROE.RETURN_FIRE
        'weapon_hold': 4,  # AI.Option.Ground.val.ROE.WEAPON_HOLD
    }
    return {
        'option_id': 0,  # AI.Option.Ground.id.ROE
        'value': roe_values[mode],
    }


def _build_mission_task(mission_type: str, altitude_m: int, speed_mps: int) -> dict:
    """Build DCS task structure for mission type.
    
    Args:
        mission_type: 'CAP', 'patrol', etc.
        altitude_m: Mission altitude
        speed_mps: Mission speed
    
    Returns:
        DCS task structure
    """
    if mission_type in ('CAS', 'AWACS', 'tanker'):
        task = ({'id': 'EngageTargets', 'params': {'targetTypes': ['Ground Units'], 'priority': 0}}
                if mission_type == 'CAS' else {'id': 'Tanker' if mission_type == 'tanker' else 'AWACS', 'params': {}})
        task.update(number=1, auto=True, enabled=True)
        orbit = _build_mission_task('patrol', altitude_m, speed_mps)['params']['tasks'][0]
        orbit['number'] = 2
        return {'id': 'ComboTask', 'params': {'tasks': [task, orbit]}}
    if mission_type == 'transport':
        return _build_mission_task('patrol', altitude_m, speed_mps)
    if mission_type == 'CAP':
        return {
            'id': 'ComboTask',
            'params': {
                'tasks': [
                    {
                        'id': 'EngageTargets',
                        'key': 'CAP',
                        'number': 1,
                        'auto': True,
                        'enabled': True,
                        'params': {
                            'targetTypes': ['Air'],
                            'priority': 0,
                        }
                    },
                    {
                        'id': 'Orbit',
                        'number': 2,
                        'auto': False,
                        'enabled': True,
                        'params': {
                            'altitude': altitude_m,
                            'pattern': 'Circle',
                            'speed': speed_mps,
                            'speedEdited': True,
                        },
                    }
                ]
            }
        }
    elif mission_type == 'patrol':
        return {
            'id': 'ComboTask',
            'params': {
                'tasks': [
                    {
                        'id': 'Orbit',
                        'number': 1,
                        'auto': False,
                        'enabled': True,
                        'params': {
                            'pattern': 'Circle',
                            'speed': speed_mps,
                            'altitude': altitude_m,
                            'speedEdited': True,
                        }
                    }
                ]
            }
        }
    else:
        # Empty task for simple waypoint
        return {'id': 'ComboTask', 'params': {'tasks': []}}
