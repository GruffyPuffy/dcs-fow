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
        })
        self.assertEqual(snapshot.summary(), {
            "mission_id": "mission-1",
            "mission_time": 12.5,
            "groups": 1,
            "units": 2,
            "airbases": 1,
        })

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


if __name__ == "__main__":
    unittest.main()