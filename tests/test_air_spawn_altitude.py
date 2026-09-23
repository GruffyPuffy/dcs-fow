import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dcs_structures import build_air_spawn_data


class SpawnAltitudeTest(unittest.TestCase):
    def test_altitude_replaces_template_start_and_mission_route(self):
        catalog = json.loads((ROOT / 'missions/air_trial.json').read_text())
        templates = json.loads((ROOT / 'missions/air_templates.json').read_text())
        for side, presets in catalog['presets'].items():
            for name, preset in presets.items():
                template = templates[side][name]['group']
                original = copy.deepcopy(template)
                result = build_air_spawn_data(side, dict(preset, altitude_m=6096), template,
                                              42, 41, 42.1, 41.1, 'Altitude test')
                group = result['group_data']
                self.assertEqual(group['units'][0]['alt'], 6096)
                self.assertEqual(group['units'][0]['alt_type'], 'BARO')
                for point in group['route']['points'][:2]:
                    self.assertEqual(point['alt'], 6096)
                    self.assertEqual(point['alt_type'], 'BARO')
                self.assertEqual(template, original)
