"""General standing rules: support replacement and AWACS escort."""

import unittest

from fow.campaign import AlgorithmicGeneral, CampaignEngine, Side, load_scenario
from pathlib import Path


SCENARIO = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"


class StandingRulesTest(unittest.TestCase):
    def setUp(self):
        self.engine = CampaignEngine(load_scenario(SCENARIO))
        self.state = self.engine.new_game()
        self.general = AlgorithmicGeneral(
            Side.RED, self.engine, 149, 500,
            opening_endowment=self.engine.scenario.economy.red_opening_endowment)

    def _spend_opening(self):
        for plan in self.general.opening_actions(self.state):
            self.engine.apply_action(self.state, plan.side, plan.action, plan.target)
        self.engine.settle_opening_endowment(self.state)

    def test_replaces_shot_down_awacs_before_anything_else(self):
        self._spend_opening()
        self.general.live_support = {"tanker", "cap"}  # AWACS was shot down
        choice = self.general.choose_action(self.state)
        self.assertIsNotNone(choice)
        self.assertEqual(choice.action, "awacs")

    def test_replaces_shot_down_tanker(self):
        self._spend_opening()
        self.general.live_support = {"awacs", "cap"}  # tanker was shot down
        choice = self.general.choose_action(self.state)
        self.assertEqual(choice.action, "tanker")

    def test_escorts_airborne_awacs_with_cap(self):
        self._spend_opening()
        self.general.live_support = {"awacs", "tanker"}  # no CAP up
        choice = self.general.choose_action(self.state)
        self.assertEqual(choice.action, "cap")

    def test_attacks_when_support_complete(self):
        self._spend_opening()
        self.general.live_support = {"awacs", "tanker", "cap"}
        choice = self.general.choose_action(self.state)
        self.assertIsNotNone(choice)
        self.assertIn(choice.action, ("assault", "reinforce"))

    def test_defense_levels_are_capped_by_difficulty(self):
        # Bravo is easy: cap 2. Krymsk is hard: cap 6.
        for _ in range(2):
            self.engine.apply_action(self.state, Side.RED, "reinforce", "bravo")
        with self.assertRaisesRegex(Exception, "maximum"):
            self.engine.apply_action(self.state, Side.RED, "reinforce", "bravo")
        legal = {plan.target for plan in
                 self.engine.legal_actions(self.state, Side.RED)
                 if plan.action == "reinforce"}
        self.assertNotIn("bravo", legal)
        self.assertIn("krymsk", legal)


if __name__ == "__main__":
    unittest.main()
