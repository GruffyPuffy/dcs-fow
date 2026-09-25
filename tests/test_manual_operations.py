from pathlib import Path
import math
import unittest

from fow.app import FoWService
from fow.campaign import ActionPlan, Side


class RecordingGateway:
    def __init__(self):
        self.spawn = None
        self.spawns = []

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
        self.spawns.append(spawn_data)
        return {"ok": True, "result": "SPAWN_ACCEPTED"}

    def ground_position(self, lat, lon, offsets, search_radius=2000,
                        airbase_clearance=1200):
        self.position_request = (lat, lon, offsets, search_radius, airbase_clearance)
        return lat, lon

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

    def test_generals_spawn_symmetric_opening_garrisons(self):
        campaign = self.service.new_game()
        names = [spawn["group_data"]["name"] for spawn in self.gateway.spawns]
        self.assertEqual(campaign["resources"], {"red": 680, "blue": 680})
        self.assertEqual(len(names), 14)
        self.assertTrue(any("Blue Reinforce Batumi" in name for name in names))
        self.assertTrue(any("Red Reinforce Gudauta" in name for name in names))
        self.assertTrue(any("Blue Cap Batumi" in name for name in names))
        self.assertTrue(any("Red Awacs Gudauta" in name for name in names))
        self.assertTrue(any("Blue Tanker Batumi" in name for name in names))
        self.assertTrue(any("Red Tanker Gudauta" in name for name in names))
        ground = [spawn for spawn in self.gateway.spawns if spawn["category"] == 2]
        air = [spawn for spawn in self.gateway.spawns if spawn["category"] == 0]
        self.assertEqual(len(ground), 8)
        self.assertEqual(len(air), 6)
        expected_stations = {
            "Blue Tanker": ((41.4500, 42.2500), (41.5500, 43.4000), 10800),
            "Blue Awacs": ((41.2500, 42.6500), (41.3500, 43.8000), 14400),
            "Red Tanker": ((43.6500, 40.4500), (43.6500, 41.6500), 10800),
            "Red Awacs": ((43.9500, 40.6500), (43.9500, 41.8500), 14400),
        }
        for name_part, (expected_start, expected_end, duration) in expected_stations.items():
            spawn = next(item for item in air if name_part in item["group_data"]["name"])
            route = spawn["group_data"]["route"]["points"]
            self.assertEqual(
                (route[1]["__geo"]["lat"], route[1]["__geo"]["lon"]), expected_start)
            self.assertEqual(
                (route[2]["__geo"]["lat"], route[2]["__geo"]["lon"]), expected_end)
            tasks = route[1]["task"]["params"]["tasks"]
            orbit = next(task for task in tasks if task["id"] == "Orbit")
            self.assertEqual(orbit["params"]["pattern"], "Race-Track")
            self.assertEqual(orbit["stopCondition"]["duration"], duration)
            self.assertEqual(route[3]["type"], "Land")
            if "Tanker" in name_part:
                latitude = math.radians((expected_start[0] + expected_end[0]) / 2)
                leg_km = math.hypot(
                    (expected_end[0] - expected_start[0]) * 111,
                    (expected_end[1] - expected_start[1]) * 111 * math.cos(latitude))
                self.assertGreater(leg_km, 90)
        awacs = [item for item in air if " Awacs " in item["group_data"]["name"]]
        tankers = [item for item in air if " Tanker " in item["group_data"]["name"]]
        self.assertTrue(all(item["group_data"]["units"][0]["alt"] == 9000 for item in awacs))
        self.assertTrue(all(item["group_data"]["units"][0]["alt"] == 8000 for item in tankers))
        self.assertTrue(all(len(spawn["group_data"]["units"]) == 4 for spawn in ground))
        centers = {"Blue": (41.6103, 41.5997), "Red": (43.1050, 40.6019)}
        for spawn in ground:
            side = "Blue" if " Blue " in f" {spawn['group_data']['name']} " else "Red"
            geo = spawn["group_data"]["__geo"]
            lat_scale = 111_000
            lon_scale = 111_000 * math.cos(math.radians(centers[side][0]))
            distance = math.hypot(
                (geo["lat"] - centers[side][0]) * lat_scale,
                (geo["lon"] - centers[side][1]) * lon_scale)
            self.assertGreater(distance, 1500)

    def test_builds_and_sends_ground_spawn(self):
        result = self.service.debug_spawn("ground", {
            "side": "blue", "template": "platoon", "name": "Debug Platoon",
            "lat": 41.61, "lon": 41.60,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.gateway.spawn["category"], 2)
        self.assertEqual(self.gateway.spawn["group_data"]["name"], "Debug Platoon")

    def test_assault_stages_at_friendly_base_and_routes_to_target(self):
        state = self.service.engine.new_game()
        plan = ActionPlan("assault", Side.BLUE, "kobuleti", 250, "assault_force")

        result = self.service.executor.execute(plan, 5, state)

        self.assertEqual(result["status"], "accepted")
        group = self.gateway.spawn["group_data"]
        spawn = group["__geo"]
        destination = group["route"]["points"][-1]["__geo"]
        self.assertLess(abs(spawn["lat"] - 41.6103), 0.01)
        self.assertLess(abs(spawn["lon"] - 41.5997), 0.01)
        self.assertEqual(destination, {"lat": 41.9294, "lon": 41.8639})

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