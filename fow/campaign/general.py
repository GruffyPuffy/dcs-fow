"""Seeded algorithmic commander policy using the public campaign rules."""

import random

from .engine import CampaignEngine
from .models import ActionPlan, CampaignState, Side


class AlgorithmicGeneral:
    def __init__(self, side: Side, engine: CampaignEngine, seed: int, reserve: int):
        self.side = side
        self.engine = engine
        self.reserve = reserve
        self._random = random.Random(seed + (1 if side == Side.BLUE else 2))

    def state_dict(self) -> dict:
        return {"random_state": self._random.getstate()}

    def restore(self, data: dict) -> None:
        def tuples(value):
            return tuple(tuples(item) for item in value) if isinstance(value, list) else value

        self._random.setstate(tuples(data["random_state"]))

    def opening_actions(self, state: CampaignState) -> list[ActionPlan]:
        plans = [plan for plan in self.engine.legal_actions(state, self.side)
                 if plan.action in ("reinforce", "cap", "awacs", "tanker")]
        selected_by_action = []
        for action in ("reinforce", "cap", "awacs", "tanker"):
            candidates = [plan for plan in plans if plan.action == action]
            self._random.shuffle(candidates)
            if candidates:
                selected_by_action.append(candidates[0])
        selected = []
        available = state.resources[self.side]
        for plan in selected_by_action:
            if available - plan.cost < self.reserve:
                continue
            selected.append(plan)
            available -= plan.cost
        return selected

    def choose_action(self, state: CampaignState) -> ActionPlan | None:
        plans = [plan for plan in self.engine.legal_actions(state, self.side)
                 if plan.action in ("assault", "reinforce")
                 and state.resources[self.side] - plan.cost >= self.reserve]
        if not plans:
            return None
        assaults = [plan for plan in plans if plan.action == "assault"]
        candidates = assaults if assaults and self._random.random() < 0.7 else plans
        return self._random.choice(candidates)