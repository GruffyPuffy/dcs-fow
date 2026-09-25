from pathlib import Path
import unittest

from fow.campaign import CampaignEngine, RuleViolation, Side, load_scenario


SCENARIO = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"


class CampaignEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = CampaignEngine(load_scenario(SCENARIO))
        self.state = self.engine.new_game()

    def test_sides_start_with_symmetric_rules_and_resources(self):
        self.assertEqual(self.state.resources[Side.BLUE], self.state.resources[Side.RED])
        blue = {(plan.action, plan.cost) for plan in self.engine.legal_actions(self.state, Side.BLUE)}
        red = {(plan.action, plan.cost) for plan in self.engine.legal_actions(self.state, Side.RED)}
        self.assertEqual(blue, red)

    def test_assault_requires_an_adjacent_non_friendly_objective(self):
        blue_targets = {
            plan.target for plan in self.engine.legal_actions(self.state, Side.BLUE)
            if plan.action == "assault"
        }
        self.assertEqual(blue_targets, {"kobuleti"})
        with self.assertRaisesRegex(RuleViolation, "Target is not legal"):
            self.engine.apply_action(self.state, Side.BLUE, "assault", "gudauta")

    def test_accepted_action_spends_resources_and_records_event(self):
        plan = self.engine.apply_action(self.state, Side.BLUE, "reinforce", "batumi")
        self.assertEqual(plan.package, "garrison")
        self.assertEqual(self.state.resources[Side.BLUE], 880)
        self.assertEqual(self.state.resources[Side.RED], 1000)
        self.assertEqual(self.state.objectives["batumi"].defense_level, 1)
        self.assertEqual(self.state.events[-1].detail["action"], "reinforce")


if __name__ == "__main__":
    unittest.main()