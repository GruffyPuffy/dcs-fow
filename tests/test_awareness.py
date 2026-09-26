"""Awareness layer: attrition, presence, and objective capture."""

import unittest

from fow.campaign import CampaignEngine, Side, load_scenario
from fow.dcs.awareness import Awareness
from pathlib import Path


SCENARIO = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"


def group(name, coalition, lat, lon, units=4, category=2):
    return {
        "name": name, "coalition": coalition, "category": category,
        "units": [{"lat": lat, "lon": lon, "speed_mps": 0, "type": "infantry"}] * units,
    }


class AwarenessTest(unittest.TestCase):
    def setUp(self):
        self.engine = CampaignEngine(load_scenario(SCENARIO))
        self.state = self.engine.new_game()
        self.awareness = Awareness()

    def test_tracks_follow_live_groups_and_drop_dead_ones(self):
        snapshot = {"mission_time": 10, "groups": [group("G1", 1, 45.0, 38.0)]}
        self.awareness.update_tracks(snapshot)
        self.assertIn("G1", self.awareness.state_dict()["tracks"])
        snapshot = {"mission_time": 15, "groups": []}
        self.awareness.update_tracks(snapshot)
        self.assertNotIn("G1", self.awareness.state_dict()["tracks"])

    def test_new_kill_reports_are_consumed_once(self):
        snapshot = {"kill_reports": [{"id": 3}, {"id": 5}]}
        first = self.awareness.new_kill_reports(snapshot)
        self.assertEqual([r["id"] for r in first], [3, 5])
        self.assertEqual(self.awareness.new_kill_reports(snapshot), [])
        snapshot = {"kill_reports": [{"id": 3}, {"id": 5}, {"id": 7}]}
        self.assertEqual([r["id"] for r in self.awareness.new_kill_reports(snapshot)], [7])

    def test_presence_counts_ground_units_near_objectives(self):
        scenario = self.engine.scenario
        krymsk = scenario.objectives["krymsk"]
        snapshot = {"groups": [
            group("Red G", 1, krymsk.lat, krymsk.lon, units=4),
            group("Blue G", 2, krymsk.lat + 0.001, krymsk.lon, units=2),
            group("Air G", 1, krymsk.lat, krymsk.lon, units=2, category=0),
        ]}
        presence = self.awareness.objective_presence(scenario, snapshot)
        self.assertEqual(presence["krymsk"], {1: 4, 2: 2})

    def test_capture_flips_when_attacker_present_and_defenders_gone(self):
        scenario = self.engine.scenario
        krymsk = scenario.objectives["krymsk"]
        # Blue assault force arrives, Red defenders dead.
        snapshot = {"groups": [group("Blue Assault", 2, krymsk.lat, krymsk.lon, units=4)]}
        presence = self.awareness.objective_presence(scenario, snapshot)
        flips = self.engine.evaluate_capture(self.state, presence)
        self.assertEqual(flips, [{"objective": "krymsk", "from": "red", "to": "blue"}])
        self.assertEqual(self.state.objectives["krymsk"].owner, Side.BLUE)
        self.assertEqual(self.state.events[-1].kind, "objective_captured")

    def test_no_flip_while_defenders_hold(self):
        scenario = self.engine.scenario
        krymsk = scenario.objectives["krymsk"]
        snapshot = {"groups": [
            group("Blue Assault", 2, krymsk.lat, krymsk.lon, units=4),
            group("Red Defense", 1, krymsk.lat + 0.001, krymsk.lon, units=2),
        ]}
        presence = self.awareness.objective_presence(scenario, snapshot)
        self.assertEqual(self.engine.evaluate_capture(self.state, presence), [])
        self.assertEqual(self.state.objectives["krymsk"].owner, Side.RED)

    def test_neutral_objective_captured_by_present_side(self):
        scenario = self.engine.scenario
        alpha = scenario.objectives["alpha"]
        snapshot = {"groups": [group("Red Force", 1, alpha.lat, alpha.lon, units=4)]}
        presence = self.awareness.objective_presence(scenario, snapshot)
        flips = self.engine.evaluate_capture(self.state, presence)
        self.assertEqual(flips, [{"objective": "alpha", "from": None, "to": "red"}])


if __name__ == "__main__":
    unittest.main()
