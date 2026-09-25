"""Deterministic, DCS-independent campaign rule engine."""

from dataclasses import replace

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
        state.events.append(CampaignEvent(1, "campaign_started", None, {}))
        return state

    def legal_actions(self, state: CampaignState, side: Side) -> list[ActionPlan]:
        if state.phase != CampaignPhase.ACTIVE:
            return []
        plans = []
        for action in self.scenario.actions.values():
            if state.resources[side] < action.cost:
                continue
            for target_id in self.scenario.objectives:
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
            state.objectives[target_id] = replace(
                current, defense_level=current.defense_level + 1)
        state.events.append(CampaignEvent(
            sequence=len(state.events) + 1,
            kind="action_accepted",
            side=side,
            detail={"action": action.id, "target": target_id, "cost": action.cost},
        ))
        return plan

    def _target_is_legal(self, state: CampaignState, side: Side, target_id: str,
                         action: ActionRule) -> bool:
        owner = state.objectives[target_id].owner
        if action.target_ownership == "friendly" and owner != side:
            return False
        if action.target_ownership == "not_friendly" and owner == side:
            return False
        if action.requires_connection:
            target = self.scenario.objectives[target_id]
            return any(state.objectives[neighbor].owner == side for neighbor in target.connections)
        return True