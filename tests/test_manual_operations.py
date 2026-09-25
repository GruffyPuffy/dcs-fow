from pathlib import Path
import unittest

from fow.app import FoWService


class RecordingGateway:
    def __init__(self):
        self.spawn = None

    def public_status(self):
        return {"connected": True, "error": None, "snapshot": {"groups": 0}}

    def public_snapshot(self):
        return {
            "mission_id": "test", "mission_time": 1,
            "groups": [
                {"name": "Blue Armor", "coalition": 2, "category": 2,
                 "units": [{"lat": 41.6, "lon": 41.7, "type": "M-1 Abrams", "y": 20}]},
                {"name": "Blue CAP", "coalition": 2, "category": 0,
                 "units": [{"lat": 41.7, "lon": 41.8, "type": "FA-18C_hornet", "y": 6000}]},
            ],
            "statics": [],
            "airbases": [{"name": "Batumi", "coalition": 2, "lat": 41.61, "lon": 41.60}],
        }

    def spawn_group(self, spawn_data):
        self.spawn = spawn_data
        return {"ok": True, "result": "SPAWN_ACCEPTED"}

    def set_route(self, group_name, route_data):
        self.order = ("set_route", group_name, route_data)
        return {"ok": True}

    def set_task(self, group_name, task_data):
        self.order = ("set_task", group_name, task_data)
        return {"ok": True}

    def set_command(self, group_name, command_data):
        self.order = ("set_command", group_name, command_data)
        return {"ok": True}

    def set_option(self, group_name, option_id, value):
        self.order = ("set_option", group_name, option_id, value)
        return {"ok": True}


class ManualOperationsTest(unittest.TestCase):
    def setUp(self):
        scenario = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"
        self.gateway = RecordingGateway()
        self.service = FoWService(scenario, self.gateway)

    def test_exposes_full_debug_status_and_catalogs(self):
        self.assertEqual(self.service.debug_status()["snapshot"]["mission_id"], "test")
        catalogs = self.service.debug_catalogs()
        self.assertIn("fighting_force", catalogs["ground"]["blue"])
        self.assertIn("hornet_cap", catalogs["air"]["presets"]["blue"])

    def test_builds_and_sends_ground_spawn(self):
        result = self.service.debug_spawn("ground", {
            "side": "blue", "template": "platoon", "name": "Debug Platoon",
            "lat": 41.61, "lon": 41.60,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.gateway.spawn["category"], 2)
        self.assertEqual(self.gateway.spawn["group_data"]["name"], "Debug Platoon")

    def test_builds_and_sends_air_spawn(self):
        result = self.service.debug_spawn("air", {
            "side": "red", "preset": "mig29_cap", "name": "Debug CAP",
            "lat": 43.1, "lon": 40.6, "altitude_m": 6500,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.gateway.spawn["category"], 0)
        self.assertEqual(self.gateway.spawn["group_data"]["units"][0]["alt"], 6500)

    def test_rejects_invalid_manual_spawn(self):
        with self.assertRaisesRegex(ValueError, "Unknown ground template"):
            self.service.debug_spawn("ground", {
                "side": "blue", "template": "missing", "lat": 41, "lon": 42,
            })

    def test_sends_ground_move_and_roe_orders(self):
        self.service.debug_order({
            "side": "blue", "group": "Blue Armor", "op": "move", "lat": 42, "lon": 42.1,
        })
        self.assertEqual(self.gateway.order[0:2], ("set_route", "Blue Armor"))
        self.service.debug_order({
            "side": "blue", "group": "Blue Armor", "op": "set_roe", "mode": "weapon_hold",
        })
        self.assertEqual(self.gateway.order, ("set_option", "Blue Armor", 0, 4))

    def test_sends_air_mission_and_rtb_orders(self):
        self.service.debug_order({
            "side": "blue", "group": "Blue CAP", "op": "set_mission",
            "mission_type": "CAP", "lat": 42, "lon": 42.1, "altitude_m": 7000,
        })
        self.assertEqual(self.gateway.order[0:2], ("set_route", "Blue CAP"))
        self.service.debug_order({
            "side": "blue", "group": "Blue CAP", "op": "rtb", "airbase": "Batumi",
        })
        self.assertEqual(self.gateway.order[0:2], ("set_task", "Blue CAP"))


if __name__ == "__main__":
    unittest.main()