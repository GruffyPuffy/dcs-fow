from pathlib import Path
import unittest

from fow.campaign import AlgorithmicGeneral, CampaignEngine, RuleViolation, Side, load_scenario


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
        self.assertEqual(self.state.resources[Side.BLUE], 1380)
        self.assertEqual(self.state.resources[Side.RED], 1500)
        self.assertEqual(self.state.objectives["batumi"].defense_level, 1)
        self.assertEqual(self.state.events[-1].detail["action"], "reinforce")

    def test_general_opens_with_garrison_and_preserves_reserve(self):
        general = AlgorithmicGeneral(
            Side.BLUE, self.engine, self.engine.scenario.economy.general_seed,
            self.engine.scenario.economy.general_reserve)
        plans = general.opening_actions(self.state)
        self.assertEqual([(plan.action, plan.target) for plan in plans], [
            ("reinforce", "batumi"), ("cap", "batumi"), ("awacs", "batumi"),
            ("tanker", "batumi")])
        for plan in plans:
            self.engine.apply_action(self.state, plan.side, plan.action, plan.target)
        self.assertGreaterEqual(
            self.state.resources[Side.BLUE], self.engine.scenario.economy.general_reserve)

    def test_owned_objectives_pay_symmetric_income(self):
        income = self.engine.collect_income(self.state)
        self.assertEqual(income, {Side.RED: 20, Side.BLUE: 20})
        self.assertEqual(self.state.resources, {Side.RED: 1520, Side.BLUE: 1520})
        self.assertEqual(self.state.events[-1].kind, "income_collected")


if __name__ == "__main__":
    unittest.main()