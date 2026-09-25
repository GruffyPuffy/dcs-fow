import unittest

from fow.dcs import DcsGateway, DcsSnapshot


class RecordingClient:
    def __init__(self):
        self.call = None

    def request(self, operation, **fields):
        self.call = (operation, fields)
        return {"ok": True}


class DcsSnapshotTest(unittest.TestCase):
    def test_parses_and_summarizes_bridge_status(self):
        snapshot = DcsSnapshot.from_reply({
            "ok": True,
            "mission_id": "mission-1",
            "time": 12.5,
            "groups": [{"units": [{"id": 1}, {"id": 2}]}],
            "statics": [],
            "airbases": [{"name": "Batumi"}],
            "kill_reports": [{"id": 4, "target_type": "M-1 Abrams"}],
            "awacs_reports": [{"target_id": 9, "lat": 42, "lon": 41}],
            "awacs_sensor_errors": 1,
        })
        self.assertEqual(snapshot.summary(), {
            "mission_id": "mission-1",
            "mission_time": 12.5,
            "groups": 1,
            "units": 2,
            "airbases": 1,
        })
        self.assertEqual(snapshot.as_dict()["kill_reports"][0]["id"], 4)
        self.assertEqual(snapshot.as_dict()["awacs_reports"][0]["target_id"], 9)
        self.assertEqual(snapshot.as_dict()["awacs_sensor_errors"], 1)

    def test_rejects_failed_status(self):
        with self.assertRaisesRegex(ValueError, "not successful"):
            DcsSnapshot.from_reply({"ok": False})

    def test_gateway_sends_explicit_slot_access(self):
        client = RecordingClient()
        gateway = DcsGateway(client)
        self.assertEqual(gateway.set_slot_access(["Kobuleti Hornet 1"], True), {"ok": True})
        self.assertEqual(client.call, (
            "set_slot_access",
            {"slots": ["Kobuleti Hornet 1"], "enabled": True},
        ))
        with self.assertRaisesRegex(ValueError, "at least one"):
            gateway.set_slot_access([], False)

    def test_gateway_sends_generic_bridge_commands(self):
        client = RecordingClient()
        gateway = DcsGateway(client)
        spawn = {"country_id": 2, "category": 2, "group_data": {"name": "Test"}}
        gateway.spawn_group(spawn)
        self.assertEqual(client.call, ("spawn_group", spawn))
        gateway.set_route("Test", {"points": []})
        self.assertEqual(client.call, (
            "set_route", {"group_name": "Test", "route_data": {"points": []}},
        ))
        gateway.set_task("Test", {"id": "Hold", "params": {}})
        self.assertEqual(client.call[0], "set_task")
        gateway.set_command("Test", {"id": "Start", "params": {}})
        self.assertEqual(client.call[0], "set_command")
        gateway.set_option("Test", 0, 4)
        self.assertEqual(client.call, (
            "set_option", {"group_name": "Test", "option_id": 0, "value": 4},
        ))


if __name__ == "__main__":
    unittest.main()