"""Deterministic, DCS-independent campaign rule engine."""

from dataclasses import replace
from typing import Any

from .models import ActionPlan, CampaignEvent, CampaignPhase, CampaignState, ObjectiveState, Side
from .scenario import ActionRule, Scenario


class RuleViolation(ValueError):
    """A requested campaign action is not currently legal."""


class CampaignEngine:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def new_game(self) -> CampaignState:
        state = CampaignState(
            scenario_id=self.scenario.id,
            phase=CampaignPhase.ACTIVE,
            resources={side: self.scenario.starting_resources for side in Side},
            objectives={
                objective.id: ObjectiveState(owner=objective.initial_owner)
                for objective in self.scenario.objectives.values()
            },
        )
        # Pre-existing fortification credit: Red's opening garrisons are paid
        # from this endowment, not from the running campaign balance.
        endowment = self.scenario.economy.red_opening_endowment
        if endowment:
            state.resources[Side.RED] += endowment
        state.events.append(CampaignEvent(1, "campaign_started", None, {}))
        return state

    def settle_opening_endowment(self, state: CampaignState) -> None:
        """Remove the unspent part of Red's opening endowment after setup."""
        endowment = self.scenario.economy.red_opening_endowment
        if endowment:
            state.resources[Side.RED] = max(
                self.scenario.starting_resources, state.resources[Side.RED] - endowment)

    def legal_actions(self, state: CampaignState, side: Side) -> list[ActionPlan]:
        if state.phase != CampaignPhase.ACTIVE:
            return []
        plans = []
        for action in self.scenario.actions.values():
            if state.resources[side] < action.cost:
                continue
            for target_id in self.scenario.objectives:
                if (action.id == "reinforce"
                        and state.objectives[target_id].defense_level
                        >= self.max_defense_level(target_id)):
                    continue
                if self._target_is_legal(state, side, target_id, action):
                    plans.append(ActionPlan(
                        action=action.id,
                        side=side,
                        target=target_id,
                        cost=action.cost,
                        package=action.package,
                    ))
        return plans

    def apply_action(self, state: CampaignState, side: Side, action_id: str,
                     target_id: str) -> ActionPlan:
        if state.phase != CampaignPhase.ACTIVE:
            raise RuleViolation("Campaign is not active")
        action = self.scenario.actions.get(action_id)
        if not action:
            raise RuleViolation("Unknown campaign action")
        if target_id not in self.scenario.objectives:
            raise RuleViolation("Unknown objective")
        if state.resources[side] < action.cost:
            raise RuleViolation("Insufficient resources")
        if not self._target_is_legal(state, side, target_id, action):
            raise RuleViolation("Target is not legal for this action")

        plan = ActionPlan(action.id, side, target_id, action.cost, action.package)
        state.resources[side] -= action.cost
        if action.id == "reinforce":
            current = state.objectives[target_id]
            if current.defense_level >= self.max_defense_level(target_id):
                raise RuleViolation("Objective defenses are already at maximum")
            state.objectives[target_id] = replace(
                current, defense_level=current.defense_level + 1)
        state.events.append(CampaignEvent(
            sequence=len(state.events) + 1,
            kind="action_accepted",
            side=side,
            detail={"action": action.id, "target": target_id, "cost": action.cost},
        ))
        return plan

    def max_defense_level(self, target_id: str) -> int:
        """Defense ceiling per objective; keeps Red beatable and creates
        easy/normal/hard targets for players."""
        return {"easy": 2, "normal": 4, "hard": 6}[
            self.scenario.objectives[target_id].difficulty]

    def evaluate_capture(self, state: CampaignState,
                         presence: dict[str, dict[int, int]]) -> list[dict[str, Any]]:
        """Flip objective ownership from observed ground presence.

        An objective changes hands when an assaulting coalition has ground
        units inside it and the owning coalition has none. Neutral objectives
        are captured by whichever side is present. Returns the flips made.
        """
        flips: list[dict[str, Any]] = []
        for objective_id, counts in presence.items():
            current = state.objectives[objective_id]
            owner = current.owner
            attacker = None
            if owner == Side.RED and counts[2] > 0 and counts[1] == 0:
                attacker = Side.BLUE
            elif owner == Side.BLUE and counts[1] > 0 and counts[2] == 0:
                attacker = Side.RED
            elif owner is None:
                if counts[1] > 0 and counts[2] == 0:
                    attacker = Side.RED
                elif counts[2] > 0 and counts[1] == 0:
                    attacker = Side.BLUE
            if attacker is None or attacker == owner:
                continue
            state.objectives[objective_id] = replace(
                current, owner=attacker, defense_level=0)
            flips.append({
                "objective": objective_id,
                "from": owner.value if owner else None,
                "to": attacker.value,
            })
            state.events.append(CampaignEvent(
                sequence=len(state.events) + 1,
                kind="objective_captured",
                side=attacker,
                detail={"objective": objective_id,
                        "from": owner.value if owner else None},
            ))
        return flips

    def collect_income(self, state: CampaignState) -> dict[Side, int]:
        income = {side: 0 for side in Side}
        for objective_id, objective_state in state.objectives.items():
            if objective_state.owner:
                income[objective_state.owner] += self.scenario.objectives[objective_id].income
        # Side multipliers create the campaign's tipping point: Red earns less
        # per objective, so Blue overtakes as it captures territory.
        factors = self.scenario.economy
        for side in Side:
            factor = (factors.red_income_factor if side == Side.RED
                      else factors.blue_income_factor)
            income[side] = int(income[side] * factor)
        for side, amount in income.items():
            state.resources[side] += amount
        state.events.append(CampaignEvent(
            sequence=len(state.events) + 1,
            kind="income_collected",
            side=None,
            detail={side.value: amount for side, amount in income.items()},
        ))
        return income

    def _target_is_legal(self, state: CampaignState, side: Side, target_id: str,
                         action: ActionRule) -> bool:
        target = self.scenario.objectives[target_id]
        if target.kind == "carrier" and side != Side.BLUE:
            return False
        owner = state.objectives[target_id].owner
        if action.target_ownership == "friendly" and owner != side:
            return False
        if action.target_ownership == "not_friendly" and owner == side:
            return False
        if action.requires_connection:
            target = self.scenario.objectives[target_id]
            return any(state.objectives[neighbor].owner == side for neighbor in target.connections)
        return True