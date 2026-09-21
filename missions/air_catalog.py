"""Generate server-owned aircraft templates using the pinned pydcs definitions."""
import json
from pathlib import Path
import sys
import dcs


def build_templates(config):
    mission = dcs.Mission()
    result = {"blue": {}, "red": {}}
    airport = mission.terrain.airports['Batumi']
    for side, presets in config['presets'].items():
        country = mission.country('USA' if side == 'blue' else 'Russia')
        for name, preset in presets.items():
            aircraft = getattr(dcs.planes, preset['aircraft'])
            if aircraft.id != preset['dcs_type']:
                raise ValueError(f"Aircraft identifier mismatch: {name}")
            group = mission.flight_group_inflight(
                country, f'FoW {side} {name} template', aircraft,
                airport.position, altitude=preset['altitude_m'],
                speed=preset['speed_mps'] * 3.6, maintask=dcs.task.Nothing,
                group_size=1)
            group.units[0].skill = dcs.unit.Skill.High
            group.units[0].pylons = {}
            loadout = config['loadouts'][side][preset['loadout']]
            if loadout['aircraft'] != preset['aircraft']:
                raise ValueError(f"Loadout aircraft mismatch: {name}")
            for weapon in loadout['pylons'].values():
                station = getattr(aircraft, f"Pylon{weapon['num']}", None)
                choices = [v for v in vars(station).values() if isinstance(v, tuple)] if station else []
                match = next((v for v in choices if v[1]['clsid'] == weapon['CLSID']), None)
                if match is None:
                    raise ValueError(f"Incompatible pylon: {name} {weapon}")
                group.units[0].load_pylon(match)
            data = group.dict()
            data.pop('groupId', None)
            for unit in data['units'].values():
                unit.pop('unitId', None)
            for point in data['route']['points'].values():
                point['task'] = {'id': 'ComboTask', 'params': {'tasks': {}}}
            result[side][name] = {**preset, 'group': data}
            mission.remove_plane_group(group)
    return result


if __name__ == '__main__':
    config = json.loads(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text(json.dumps(build_templates(config), indent=2) + '\n')
