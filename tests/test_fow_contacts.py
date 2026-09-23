import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fow_contacts import ContactPicture

spec = importlib.util.spec_from_file_location('fow_server', ROOT / 'scripts/fow-server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def report(side=2, **changes):
    return dict(side=side, target_id=99, source='AWACS', lat=42, lon=41,
                altitude_m=6000, **changes)


class ContactTests(unittest.TestCase):
    def test_memory_expires_without_following_truth(self):
        picture = ContactPicture()
        contact = picture.update(dict(time=10, awacs_reports=[report()]))[0]
        self.assertIsNone(contact['type'])
        lost = picture.update(dict(time=30, groups=[{'units': [{'id':99, 'lat':0}]}]))[0]
        self.assertEqual(lost['lat'], 42)
        self.assertFalse(lost['current'])
        self.assertEqual(lost['age_seconds'], 20)
        self.assertEqual(contact['id'], lost['id'])
        self.assertEqual(picture.update(dict(time=311)), [])

    def test_merge_reacquire_and_reset(self):
        picture = ContactPicture()
        first = report(type='MiG-29S')
        second = dict(first, source='Other AWACS')
        result = picture.update(dict(time=10, mission_id='a', awacs_reports=[first, second]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['sources'], ['AWACS', 'Other AWACS'])
        picture.update(dict(time=20, mission_id='a'))
        result = picture.update(dict(time=30, mission_id='a', awacs_reports=[report()]))
        self.assertEqual(result[0]['type'], 'MiG-29S')
        self.assertEqual(result[0]['sources'], ['AWACS'])
        self.assertTrue(result[0]['current'])
        self.assertEqual(picture.update(dict(time=40, mission_id='b')), [])
        picture.update(dict(time=50, mission_id='b', awacs_reports=[report()]))
        self.assertEqual(picture.update(dict(time=1, mission_id='b')), [])

    def test_side_filter_does_not_leak_raw_reports_or_enemy_truth(self):
        picture = ContactPicture()
        contacts = picture.update(dict(time=10, awacs_reports=[report(), report(side=1)]))
        payload = dict(snapshot=dict(groups=[dict(name='enemy', coalition=1, units=[])],
                       statics=[], awacs_reports=[report(), report(side=1)], contacts=contacts),
                       orders=[], tracks={}, range_rings={}, aliases={}, roe={},
                       roster={'by_coalition':{}})
        view = server.side_view(copy.deepcopy(payload), 'blue')['snapshot']
        self.assertEqual(view['groups'], [])
        self.assertNotIn('awacs_reports', view)
        self.assertEqual(len(view['contacts']), 1)
        self.assertEqual(view['contacts'][0]['side'], 2)
        self.assertNotIn('target_id', view['contacts'][0])
        self.assertNotEqual(contacts[0]['id'], contacts[1]['id'])


if __name__ == '__main__':
    unittest.main()
