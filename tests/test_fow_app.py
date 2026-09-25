from pathlib import Path
import tempfile
import unittest

from fow.app import FoWService


SCENARIO = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"


class StubGateway:
    def public_status(self):
        return {"connected": False, "error": "offline", "snapshot": None}

    def public_snapshot(self):
        return None


class RecordingGateway:
    def __init__(self):
        self.mission_id = "mission-1"
        self.groups = []
        self.spawn_calls = 0

    def public_status(self):
        return {"connected": True, "error": None, "snapshot": {"groups": len(self.groups)}}

    def public_snapshot(self):
        return {
            "mission_id": self.mission_id,
            "mission_time": 1,
            "groups": list(self.groups),
            "statics": [],
            "airbases": [],
        }

    def spawn_group(self, spawn_data):
        self.spawn_calls += 1
        self.groups.append({
            "name": spawn_data["group_data"]["name"],
            "coalition": 2 if spawn_data["country_id"] == 2 else 1,
            "category": spawn_data["category"],
            "units": spawn_data["group_data"]["units"],
        })
        return {"ok": True, "result": "SPAWN_ACCEPTED"}


class FoWServiceTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.service = FoWService(SCENARIO, StubGateway(), clock=lambda: self.now)

    def test_new_game_populates_overview_without_dcs(self):
        self.assertIsNone(self.service.overview()["campaign"])
        campaign = self.service.new_game()
        overview = self.service.overview()
        self.assertEqual(campaign["phase"], "active")
        self.assertEqual(overview["campaign"]["resources"], {"red": 680, "blue": 680})
        self.assertEqual(len(overview["deployments"]), 8)
        self.assertTrue(all(item["status"] == "waiting" for item in overview["deployments"]))
        self.assertTrue(all(
            item["waypoints"] for item in overview["deployments"]
            if item["action"] != "reinforce"))
        blue_awacs = next(item for item in overview["deployments"]
                          if item["side"] == "blue" and item["action"] == "awacs")
        red_awacs = next(item for item in overview["deployments"]
                         if item["side"] == "red" and item["action"] == "awacs")
        self.assertEqual(len(blue_awacs["waypoints"]), 3)
        self.assertEqual(len(red_awacs["waypoints"]), 3)
        self.assertEqual(blue_awacs["waypoints"][0]["lon"], 42.65)
        self.assertEqual(red_awacs["waypoints"][0]["lon"], 40.65)
        self.assertTrue(blue_awacs["waypoints"][-1]["label"].startswith("RTB"))
        self.assertEqual(overview["generals"]["next_income_seconds"], 300)
        self.assertTrue(overview["legal_actions"]["blue"])
        self.assertFalse(overview["persistence"]["enabled"])

    def test_income_turn_pays_both_sides_and_preserves_reserve(self):
        self.service.new_game()
        self.now += 300
        self.service.tick()
        overview = self.service.overview()
        resources = overview["campaign"]["resources"]
        self.assertGreaterEqual(resources["blue"], 500)
        self.assertGreaterEqual(resources["red"], 500)
        self.assertIn("income_collected", [
            event["kind"] for event in overview["campaign"]["events"]])

    def test_restart_adopts_opening_deployments_without_spawning_again(self):
        gateway = RecordingGateway()
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "runtime.json"
            first = FoWService(
                SCENARIO, gateway, clock=lambda: self.now,
                wall_clock=lambda: 10_000, checkpoint_path=state_file)
            first.new_game()
            self.assertEqual(gateway.spawn_calls, 14)
            resources = first.overview()["campaign"]["resources"]

            restarted = FoWService(
                SCENARIO, gateway, clock=lambda: self.now,
                wall_clock=lambda: 10_010, checkpoint_path=state_file)
            restarted.tick()

        self.assertEqual(gateway.spawn_calls, 14)
        self.assertEqual(restarted.overview()["campaign"]["resources"], resources)
        self.assertTrue(all(
            deployment["status"] == "active"
            for deployment in restarted.overview()["deployments"]))

    def test_dcs_mission_restart_rehydrates_each_deployment_once(self):
        gateway = RecordingGateway()
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "runtime.json"
            service = FoWService(
                SCENARIO, gateway, clock=lambda: self.now,
                wall_clock=lambda: 10_000, checkpoint_path=state_file)
            service.new_game()
            gateway.mission_id = "mission-2"
            retained_group = gateway.groups[0]
            gateway.groups = [retained_group]
            service.tick()
            service.tick()

        self.assertEqual(gateway.spawn_calls, 27)
        self.assertEqual(
            sum(group["name"] == retained_group["name"] for group in gateway.groups), 1)


if __name__ == "__main__":
    unittest.main()