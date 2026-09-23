import copy
from pathlib import Path
import tempfile
import unittest
from test_fow_contacts import ContactPicture, report, server
from fow_store import Store


def kill(**changes):
    event = dict(id=1, time=20, side=2, target_side=1, target_id=99,
                 target_type='MiG-29S', attacker='Hornet', attacker_group='CAP', weapon='AIM-120C')
    return dict(event, **changes)


class KillReportTest(unittest.TestCase):
    def test_confirmed_contact_not_just_lost(self):
        picture = ContactPicture()
        contact = picture.update(dict(time=10, awacs_reports=[report()]))[0]
        snapshot = dict(time=20, kill_reports=[kill()])
        result = picture.update(snapshot)[0]
        self.assertTrue(result['destroyed'])
        self.assertFalse(result['current'])
        self.assertEqual(result['lat'], contact['lat'])
        self.assertEqual(snapshot['kill_reports'][0]['contact_id'], contact['id'])
        self.assertEqual(picture.update(dict(time=81, kill_reports=[kill()])), [])

    def test_other_side_kill_does_not_confirm_observers_contact(self):
        picture = ContactPicture()
        picture.update(dict(time=10, awacs_reports=[report()]))
        result = picture.update(dict(time=20, kill_reports=[kill(side=0)]))[0]
        self.assertFalse(result.get('destroyed', False))

    def test_persist_deduplicate_filter_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'store.sqlite'
            store = Store(path)
            events = [kill(), kill(id=2, side=1, target_side=2), kill(id=3, side=0),
                      kill(id=4, target_side=2)]
            snapshot = dict(time=20, mission_id='a', groups=[], kill_reports=events)
            store.record_snapshot(snapshot)
            store.record_snapshot(snapshot)
            store = Store(path)
            self.assertEqual(len(store.dashboard()['kills']), 4)
            payload = dict(store.dashboard(), snapshot=copy.deepcopy(snapshot), range_rings={})
            blue = server.side_view(payload, 'blue')
            self.assertEqual([e['id'] for e in blue['kills']], [1])
            self.assertNotIn('kill_reports', blue['snapshot'])
            self.assertNotIn('target_id', blue['kills'][0])
            store.record_snapshot(dict(time=1, mission_id='b', groups=[]))
            self.assertEqual(store.dashboard()['kills'], [])
