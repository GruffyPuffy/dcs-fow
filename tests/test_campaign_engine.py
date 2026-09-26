from pathlib import Path
import unittest

from fow.campaign import AlgorithmicGeneral, CampaignEngine, RuleViolation, Side, load_scenario


SCENARIO = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"


class CampaignEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = CampaignEngine(load_scenario(SCENARIO))
        self.state = self.engine.new_game()

    def test_sides_start_with_symmetric_rules_and_resources(self):
        red_endowment = self.engine.scenario.economy.red_opening_endowment
        blue_endowment = self.engine.scenario.economy.blue_opening_endowment
        self.assertEqual(self.state.resources[Side.BLUE],
                         self.state.resources[Side.RED] - red_endowment + blue_endowment)
        blue = {(plan.action, plan.cost) for plan in self.engine.legal_actions(self.state, Side.BLUE)}
        red = {(plan.action, plan.cost) for plan in self.engine.legal_actions(self.state, Side.RED)}
        self.assertEqual(blue, red)

    def test_assault_requires_an_adjacent_non_friendly_objective(self):
        blue_targets = {
            plan.target for plan in self.engine.legal_actions(self.state, Side.BLUE)
            if plan.action == "assault"
        }
        self.assertEqual(blue_targets, {"alpha", "charlie"})
        red_targets = {
            plan.target for plan in self.engine.legal_actions(self.state, Side.RED)
            if plan.action == "assault"
        }
        self.assertNotIn("carrier", red_targets)
        with self.assertRaisesRegex(RuleViolation, "Target is not legal"):
            self.engine.apply_action(self.state, Side.BLUE, "assault", "krymsk")

    def test_accepted_action_spends_resources_and_records_event(self):
        plan = self.engine.apply_action(self.state, Side.BLUE, "reinforce", "anapa")
        self.assertEqual(plan.package, "garrison")
        self.assertEqual(self.state.resources[Side.BLUE],
                         2000 + self.engine.scenario.economy.blue_opening_endowment - 180)
        self.assertEqual(self.state.resources[Side.RED],
                         2000 + self.engine.scenario.economy.red_opening_endowment)
        self.assertEqual(self.state.objectives["anapa"].defense_level, 1)
        self.assertEqual(self.state.events[-1].detail["action"], "reinforce")

    def test_opening_endowment_settles_back_to_starting_resources(self):
        engine = self.engine
        state = self.state
        general = AlgorithmicGeneral(
            Side.RED, engine, engine.scenario.economy.general_seed,
            engine.scenario.economy.general_reserve)
        for plan in general.opening_actions(state):
            engine.apply_action(state, plan.side, plan.action, plan.target)
        engine.settle_opening_endowment(state)
        self.assertGreaterEqual(
            state.resources[Side.RED], engine.scenario.economy.general_reserve)
        self.assertLessEqual(
            state.resources[Side.RED], engine.scenario.starting_resources)

    def test_general_opens_with_garrison_and_preserves_reserve(self):
        general = AlgorithmicGeneral(
            Side.BLUE, self.engine, self.engine.scenario.economy.general_seed,
            self.engine.scenario.economy.general_reserve)
        plans = general.opening_actions(self.state)
        actions = [(plan.action, plan.target) for plan in plans]
        self.assertIn(("awacs", "anapa"), actions)
        self.assertIn(("tanker", "anapa"), actions)
        self.assertIn(("cap", "anapa"), actions)
        self.assertTrue(all(target == "anapa" for action, target in actions
                            if action == "reinforce"))
        for plan in plans:
            self.engine.apply_action(self.state, plan.side, plan.action, plan.target)
        # Blue intentionally keeps only half the scenario reserve so it can
        # stay offensive against Red's larger economy.
        self.assertGreaterEqual(
            self.state.resources[Side.BLUE],
            self.engine.scenario.economy.general_reserve // 2)

    def test_red_opening_garrisons_every_owned_objective(self):
        general = AlgorithmicGeneral(
            Side.RED, self.engine, self.engine.scenario.economy.general_seed,
            self.engine.scenario.economy.general_reserve,
            opening_endowment=self.engine.scenario.economy.red_opening_endowment)
        plans = general.opening_actions(self.state)
        garrisoned = {plan.target for plan in plans if plan.action == "reinforce"}
        owned = {objective_id for objective_id, objective in self.state.objectives.items()
                 if objective.owner == Side.RED}
        self.assertEqual(garrisoned, owned)
        # No scripted opening assaults: the endowment only funds the budget;
        # assaults emerge from the doctrine's normal rolls in decision rounds.

    def test_carrier_objective_is_blue_only_and_skipped_by_ground_policies(self):
        carrier = self.engine.scenario.objectives["carrier"]
        self.assertEqual(carrier.kind, "carrier")
        self.assertEqual(carrier.initial_owner, Side.BLUE)
        red_plans = self.engine.legal_actions(self.state, Side.RED)
        self.assertFalse(any(plan.target == "carrier" for plan in red_plans))
        general = AlgorithmicGeneral(
            Side.RED, self.engine, self.engine.scenario.economy.general_seed,
            self.engine.scenario.economy.general_reserve)
        self.assertFalse(any(
            plan.target == "carrier"
            for plan in general.opening_actions(self.state) + [general.choose_action(self.state)]
            if plan))

    def test_owned_objectives_pay_symmetric_income(self):
        income = self.engine.collect_income(self.state)
        endowment = self.engine.scenario.economy.red_opening_endowment
        # Base stipend (40) plus objective income. Red's factor (0.9):
        # (85 + 40) * 0.9 = 112. Blue's 1.5 factor: (20 + 40) * 1.5 = 90.
        # The stipend keeps an attacker spending while it holds little.
        self.assertEqual(income, {Side.RED: 112, Side.BLUE: 90})
        blue_endowment = self.engine.scenario.economy.blue_opening_endowment
        self.assertEqual(self.state.resources,
                         {Side.RED: 2000 + endowment + 112,
                          Side.BLUE: 2000 + blue_endowment + 90})
        self.assertEqual(self.state.events[-1].kind, "income_collected")


if __name__ == "__main__":
    unittest.main()