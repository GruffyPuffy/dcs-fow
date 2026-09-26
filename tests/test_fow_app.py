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

    def set_slot_access(self, slots, enabled):
        return {"ok": True}

    def add_radio_command(self, coalition_id, name, path, command_id):
        return {"ok": True}

    def smoke(self, lat, lon, color, duration=300):
        return {"ok": True}

    def mark(self, lat, lon, text, coalition_id=-1):
        return {"ok": True}

    def message(self, text, coalition_id=-1, seconds=20):
        return {"ok": True}


class RecordingGateway:
    def __init__(self):
        self.mission_id = "mission-1"
        self.groups = []
        self.spawn_calls = 0
        self.slot_access_calls = []

    def public_status(self):
        return {"connected": True, "error": None, "snapshot": {"groups": len(self.groups)}}

    def set_slot_access(self, slots, enabled):
        self.slot_access_calls.append((list(slots), enabled))
        return {"ok": True}

    def add_radio_command(self, coalition_id, name, path, command_id):
        return {"ok": True}

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

    def ground_position(self, lat, lon, offsets, search_radius=2000,
                        airbase_clearance=1200):
        return lat, lon

    def set_task(self, group_name, task_data):
        return {"ok": True}

    def smoke(self, lat, lon, color, duration=300):
        return {"ok": True}

    def mark(self, lat, lon, text, coalition_id=-1):
        return {"ok": True}


class FoWServiceTest(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.service = FoWService(SCENARIO, StubGateway(), clock=lambda: self.now)

    def test_new_game_populates_overview_without_dcs(self):
        self.assertIsNone(self.service.overview()["campaign"])
        campaign = self.service.new_game()
        overview = self.service.overview()
        reserve = self.service.scenario.economy.general_reserve
        self.assertEqual(campaign["phase"], "active")
        # Invariants: reserve preserved on both sides, deployments exist, and
        # support flights have racetrack waypoints.
        self.assertGreaterEqual(overview["campaign"]["resources"]["blue"], reserve)
        self.assertGreaterEqual(overview["campaign"]["resources"]["red"], reserve)
        self.assertGreater(len(overview["deployments"]), 0)
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
        # Blue keeps a half reserve (underdog pushing), Red the full one.
        # The tick catches up several decision rounds, so Blue may spend down
        # to its 250 floor minus one cheap action.
        self.assertGreaterEqual(resources["blue"], 200)
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
            spawn_calls_after_opening = gateway.spawn_calls
            self.assertGreater(spawn_calls_after_opening, 0)
            resources = first.overview()["campaign"]["resources"]

            restarted = FoWService(
                SCENARIO, gateway, clock=lambda: self.now,
                wall_clock=lambda: 10_010, checkpoint_path=state_file)
            restarted.tick()

        self.assertEqual(gateway.spawn_calls, spawn_calls_after_opening)
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
            spawn_calls_after_opening = gateway.spawn_calls
            gateway.mission_id = "mission-2"
            retained_group = gateway.groups[0]
            gateway.groups = [retained_group]
            service.tick()
            service.tick()

        # Each deployment rehydrates exactly once; the retained group itself is
        # not spawned again (one spawn fewer than a full rehydration).
        expected_rehydrations = sum(
            4 if deployment["action"] == "reinforce" else 1
            for deployment in service.overview()["deployments"]) - 1
        self.assertEqual(gateway.spawn_calls,
                         spawn_calls_after_opening + expected_rehydrations)
        self.assertEqual(
            sum(group["name"] == retained_group["name"] for group in gateway.groups), 1)


if __name__ == "__main__":
    unittest.main()