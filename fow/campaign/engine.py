"""Deterministic, DCS-independent campaign rule engine."""

from dataclasses import replace
from time import time as time_now
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
        # from this endowment, not from the running campaign balance. Blue's
        # endowment funds its opening assaults on the neutral front line.
        if self.scenario.economy.red_opening_endowment:
            state.resources[Side.RED] += self.scenario.economy.red_opening_endowment
        if self.scenario.economy.blue_opening_endowment:
            state.resources[Side.BLUE] += self.scenario.economy.blue_opening_endowment
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
        easy/normal/hard targets for players. Kept low so bases cannot be
        stacked into impenetrable fortresses - reinforce is a patch, not a
        strategy."""
        return {"easy": 1, "normal": 2, "hard": 3}[
            self.scenario.objectives[target_id].difficulty]

    # Seconds an attacker must hold exclusive presence before an objective
    # flips. A walk-in does not take a base: the defender gets this window
    # to reinforce and fight. Two ticks at ~60s awareness cadence ~ 2 min.
    capture_hold_seconds = 120.0

    def evaluate_capture(self, state: CampaignState,
                         presence: dict[str, dict[int, int]]) -> list[dict[str, Any]]:
        """Flip objective ownership from observed ground presence.

        An objective changes hands when an assaulting coalition has held
        exclusive ground presence (owner has none) for capture_hold_seconds.
        While contested the owner may still reinforce - the base is only
        "taken" after the fight. Neutral objectives are contested by whichever
        side is present. Returns the flips made.
        """
        flips: list[dict[str, Any]] = []
        now = time_now()
        for objective_id, counts in presence.items():
            current = state.objectives[objective_id]
            owner = current.owner
            attacker = None
            # Zone control is weighted power, not headcount: a tank platoon
            # at the center outweighs an infantry section at the edge, but
            # enough soldiers contest a tank. A side controls the zone when
            # its weight dominates by a clear margin (2x) - a knife-edge
            # balance keeps the fight contested.
            if counts[2] > counts[1] * 2:
                attacker = Side.BLUE
            elif counts[1] > counts[2] * 2:
                attacker = Side.RED
            if attacker is None or attacker == owner:
                # Fight is over or never started: clear any stale contest.
                if current.contested_since is not None:
                    state.objectives[objective_id] = replace(
                        current, contested_since=None)
                continue
            # Start or continue the contest clock.
            if current.contested_since is None:
                state.objectives[objective_id] = replace(
                    current, contested_since=now)
                state.events.append(CampaignEvent(
                    sequence=len(state.events) + 1,
                    kind="objective_contested",
                    side=attacker,
                    detail={"objective": objective_id},
                ))
                continue
            if now - current.contested_since < self.capture_hold_seconds:
                continue  # still fighting; defender may reinforce
            state.objectives[objective_id] = replace(
                current, owner=attacker, defense_level=0, contested_since=None)
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

    # Supply hubs: income only flows along an unbroken path of same-side
    # objectives back to the side's home base. Cut-off objectives stop
    # paying - taking Krymsk starves Red's western wing, so hubs attract
    # strikes and recapturing a cut link becomes urgent.
    home_objectives = {Side.BLUE: "anapa", Side.RED: "krasnodar"}

    def connected_to_home(self, state: CampaignState, side: Side,
                          objective_id: str) -> bool:
        """True if objective_id has an unbroken same-side path to home."""
        home = self.home_objectives[side]
        if objective_id == home:
            return True
        seen = {objective_id}
        frontier = [objective_id]
        while frontier:
            current = frontier.pop()
            for neighbor in self.scenario.objectives[current].connections:
                if neighbor == home:
                    return True
                if (neighbor in seen
                        or state.objectives[neighbor].owner != side):
                    continue
                seen.add(neighbor)
                frontier.append(neighbor)
        return False

    def income_value(self, state: CampaignState, side: Side,
                     objective_id: str) -> int:
        """Income Blue/Red would GAIN (or deny the enemy) by taking this
        objective: its own income plus every enemy objective that would be
        cut off from home. Hubs like Krymsk score high - they attract
        strikes and assaults without any scripting."""
        objective = self.scenario.objectives[objective_id]
        enemy = Side.RED if side == Side.BLUE else Side.BLUE
        value = objective.income
        for other_id, other in self.scenario.objectives.items():
            if other_id == objective_id:
                continue
            other_state = state.objectives[other_id]
            if other_state.owner != enemy:
                continue
            # Would taking objective_id cut 'other' from enemy home?
            # Simulate: temporarily flip ownership.
            saved = state.objectives[objective_id]
            state.objectives[objective_id] = replace(saved, owner=side)
            cut = not self.connected_to_home(state, enemy, other_id)
            state.objectives[objective_id] = saved
            if cut:
                value += self.scenario.objectives[other_id].income
        return value

    def collect_income(self, state: CampaignState) -> dict[Side, int]:
        income = {side: self.scenario.economy.base_income for side in Side}
        for objective_id, objective_state in state.objectives.items():
            if objective_state.owner and self.connected_to_home(
                    state, objective_state.owner, objective_id):
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
        # "enemy" is stricter: only objectives currently HELD by the other
        # side. Strikes/SEAD/CAS hit confirmed troops and bases, not empty
        # neutral ground nobody owns.
        if action.target_ownership == "enemy":
            enemy = Side.RED if side == Side.BLUE else Side.BLUE
            if owner != enemy:
                return False
        if action.requires_connection:
            target = self.scenario.objectives[target_id]
            # Air missions (strike/SEAD/CAS) have the range to reach one
            # step past the ground front line - that is how deep air power
            # works IRL. Ground actions (assault) still need a bordering
            # friendly objective.
            if action.id in ("strike", "sead", "cas"):
                return any(
                    state.objectives[neighbor].owner == side
                    or any(state.objectives[hop].owner == side
                           for hop in self.scenario.objectives[neighbor].connections)
                    for neighbor in target.connections)
            return any(state.objectives[neighbor].owner == side for neighbor in target.connections)
        return True