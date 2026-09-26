"""Seeded algorithmic commander policy using the public campaign rules."""

import random

from .engine import CampaignEngine
from .models import ActionPlan, CampaignState, Side


class AlgorithmicGeneral:
    # Decision cadence and spending rate limit. The general decides every
    # decision_interval_seconds but may only spend spend_rate credits per
    # second on average (bucket capacity = one big purchase), so it can buy
    # immediately after saving up but must pace itself afterwards.
    decision_interval_seconds = 60
    spend_rate_per_second = 1.5
    bucket_capacity = 300
    # Max live ground groups per side. Protects the DCS server from runaway
    # spawning; the general stops buying ground forces at the cap.
    max_ground_groups = 40
    # Max concurrent assault packages on a single objective. Stacking three
    # assaults on one zone is a steamroll, not an operation - and it hammers
    # the DCS server with simultaneous large ground groups.
    max_assaults_per_objective = 1
    # Max live air deployments per side, and per mission type. CAP used to
    # respawn endlessly because the escort rule only checked "is any CAP up";
    # now the general stops buying at the caps and diversifies instead.
    max_air_deployments = 8
    max_per_air_type = 2

    def __init__(self, side: Side, engine: CampaignEngine, seed: int, reserve: int,
                 opening_endowment: int = 0):
        self.side = side
        self.engine = engine
        # Blue is the underdog that must push to have a chance without players;
        # it keeps a smaller reserve than the scenario default so it can afford
        # assaults while Red hoards its bigger starting economy.
        self.reserve = reserve // 2 if side == Side.BLUE else reserve
        # Pre-existing fortification budget: spent during the setup phase on top
        # of starting resources, mirroring an enemy that has held the area for
        # a long time. It does not carry over to the running campaign.
        self.opening_endowment = opening_endowment
        # Live support flights, reported by the service each tick. A general
        # always re-buys a shot-down AWACS or tanker before anything else.
        self.live_support: set[str] = set()
        # Reactive triggers fed by the service: objectives under enemy attack
        # (our garrison dying) and objectives we just lost. These get priority
        # over the routine assault/reinforce roll.
        self.threatened: set[str] = set()
        self.lost: set[str] = set()
        # Enemy assaults in progress (objective ids), fed by the service from
        # active enemy assault deployments. Drives counter-doctrine: strike
        # the staging force, CAP over the fight, counter-assault the source.
        self.enemy_assaults: set[str] = set()
        # Objectives with CONFIRMED enemy ground troops (weighted presence
        # > 0), fed by the service from awareness. CAS strikes these - troops
        # in the open, not empty zones.
        self.confirmed_enemy_troops: set[str] = set()
        # Player requests awaiting approval (e.g. JTAC support). The general
        # approves them on the normal cadence if the budget allows.
        self.pending_requests: list[dict] = []
        # Live ground group count, fed by the service from the DCS snapshot.
        self.live_ground_groups = 0
        # Objectives already under one of our live assaults, fed by the
        # service. Limits stacking multiple assault packages on one target.
        self.live_assault_targets: set[str] = set()
        # Live air deployment counts, fed by the service: total and per
        # action type (cap/cas/sead/strike/awacs/tanker). Enforce the air
        # caps so the general diversifies instead of stacking CAPs.
        self.live_air_total = 0
        self.live_air_by_type: dict[str, int] = {}
        # Set when the next CAP purchase is a free AWACS escort (doctrine).
        self.free_escort = False
        # Human-readable decision log for tuning: one entry per choose_action.
        self.decision_log: list[dict] = []
        self._bucket = self.bucket_capacity
        self._random = random.Random(seed + (1 if side == Side.BLUE else 2))

    def state_dict(self) -> dict:
        return {"random_state": self._random.getstate(),
                "decision_log": self.decision_log[-50:],
                "bucket": self._bucket}

    def restore(self, data: dict) -> None:
        def tuples(value):
            return tuple(tuples(item) for item in value) if isinstance(value, list) else value

        self._random.setstate(tuples(data["random_state"]))
        self.decision_log = list(data.get("decision_log", []))
        self._bucket = float(data.get("bucket", self.bucket_capacity))

    def accrue(self, seconds: float) -> None:
        """Refill the spending bucket up to one big purchase."""
        self._bucket = min(self.bucket_capacity,
                           self._bucket + self.spend_rate_per_second * seconds)

    def _affordable(self, state: CampaignState, plans: list[ActionPlan],
                    urgent: bool) -> list[ActionPlan]:
        """Filter plans by resources and the spending bucket. Urgent reactions
        (counter-attacks, support replacement) may overdraw the bucket.
        Assaults are the point of the game: they only need a small token
        balance (100), otherwise the reserve locks both sides into passivity.
        Offensive air (strike/SEAD/CAS) is the same kind of push, so it gets
        the same token floor instead of the full reserve.
        Reinforcing what we own is maintenance (50 floor). Other expensive
        actions keep the reserve as a soft floor."""
        result = []
        for plan in plans:
            if plan.action == "reinforce":
                floor = 50
            elif plan.action in ("assault", "strike", "sead", "cas"):
                floor = 100
            else:
                floor = self.reserve if plan.cost > 150 else self.reserve // 2
            if state.resources[self.side] - plan.cost < floor:
                continue
            if urgent or self._bucket >= plan.cost:
                result.append(plan)
        return result

    def opening_actions(self, state: CampaignState) -> list[ActionPlan]:
        """Setup phase: garrison owned objectives with seeded-random intensity
        and placement, then buy support flights while preserving the reserve.
        No scripted opening moves: the opening endowment simply gives the
        side the budget to assault right away if its doctrine rolls that way."""
        plans = [plan for plan in self.engine.legal_actions(state, self.side)
                 if plan.action in ("reinforce", "cap", "awacs", "tanker",
                                    "assault")
                 and self.scenario_objective_kind(plan.target) != "carrier"]
        owned = [plan for plan in plans if plan.action == "reinforce"]
        support = [plan for plan in plans if plan.action != "reinforce"]

        selected = []
        # new_game() already credits the endowment into the state balance, so
        # it must not be added again here (it is only a budgeting hint).
        available = state.resources[self.side]
        # Reserve budget for AWACS and tanker before garrisoning; CAP is optional.
        support_cost = 0
        for action in ("awacs", "tanker"):
            candidates = [plan for plan in support if plan.action == action]
            if candidates:
                support_cost += candidates[0].cost
        # Garrison budget: everything except the support flights. The doctrine
        # "every owned objective gets a garrison" outranks the reserve floor -
        # an unguarded objective is a gift to the enemy. The reserve only
        # limits EXTRA packages beyond the first per objective.
        garrison_budget = available - support_cost
        owned_plans = sorted(
            owned,
            key=lambda item: (-self.engine.scenario.objectives[item.target].income,
                              item.target))
        # Opening blitz: the attacker spends the war chest on assaults on
        # adjacent neutral objectives BEFORE buying CAP - the war starts with
        # ground pushing, not an air umbrella. Emergent: this is just budget
        # priority, the assault roll stays the same in decision rounds.
        opening_assaults = [plan for plan in plans if plan.action == "assault"]
        self._random.shuffle(opening_assaults)
        for plan in opening_assaults[:2]:
            if available - plan.cost < 0:
                break
            selected.append(plan)
            available -= plan.cost
        # Every owned objective gets at least one garrison; extra packages are
        # seeded-random, weighted by difficulty.
        for plan in owned_plans:
            if garrison_budget < plan.cost:
                break
            selected.append(plan)
            available -= plan.cost
            garrison_budget -= plan.cost
        for plan in owned_plans:
            objective = self.engine.scenario.objectives[plan.target]
            for _ in range(self._random.randint(1, self.garrison_weight(objective)) - 1):
                if (available - plan.cost < self.reserve
                        or garrison_budget < plan.cost):
                    break
                selected.append(plan)
                available -= plan.cost
                garrison_budget -= plan.cost
        # Support flights: AWACS and tanker first (standing doctrine - blind
        # and unfuelled is worse than a low balance), then CAP. The attacker
        # opens with the war chest, not the air umbrella: assaults come first.
        for action in ("awacs", "tanker", "cap"):
            candidates = [plan for plan in support if plan.action == action]
            self._random.shuffle(candidates)
            floor = 0 if action in ("awacs", "tanker") else self.reserve
            if candidates and available - candidates[0].cost >= floor:
                selected.append(candidates[0])
                available -= candidates[0].cost
        return selected

    def scenario_objective_kind(self, target_id: str) -> str:
        return self.engine.scenario.objectives[target_id].kind

    def garrison_weight(self, objective) -> int:
        """Random upper bound for garrison packages at an objective.

        Difficulty tiers make some objectives cheap to take (easy) and others
        a real fight (hard), so players of different skill levels find targets.
        """
        return {"easy": 1, "normal": 2, "hard": 3}[objective.difficulty]

    def choose_action(self, state: CampaignState) -> ActionPlan | None:
        all_plans = [plan for plan in self.engine.legal_actions(state, self.side)
                     if plan.action in ("assault", "reinforce", "awacs", "tanker", "cap", "strike", "sead", "cas")
                     and self.scenario_objective_kind(plan.target) != "carrier"]
        # Force cap: at the limit, only air/support actions remain.
        if self.live_ground_groups >= self.max_ground_groups:
            all_plans = [plan for plan in all_plans
                         if plan.action not in ("assault", "reinforce")]
        # Assault stacking cap: one assault package per objective at a time,
        # EXCEPT when the objective is contested (a fight is in progress).
        # Fresh waves may join a winning fight - that is how you penetrate a
        # defense - but a quiet objective never stacks multiple assaults.
        contested = {objective_id for objective_id, state
                     in state.objectives.items()
                     if state.contested_since is not None}
        all_plans = [plan for plan in all_plans
                     if plan.action != "assault"
                     or plan.target not in self.live_assault_targets
                     or plan.target in contested]
        # CAS needs troops, not empty ground: only target objectives where
        # enemy presence is confirmed (weighted presence > 0 from awareness).
        all_plans = [plan for plan in all_plans
                     if plan.action != "cas"
                     or plan.target in self.confirmed_enemy_troops]
        # Air caps: stop buying aircraft at the total cap, and stop buying a
        # type at its per-type cap. This forces diversity - a side at its CAP
        # limit buys strike/CAS/SEAD or nothing, never more CAP.
        if self.live_air_total >= self.max_air_deployments:
            all_plans = [plan for plan in all_plans
                         if plan.action not in ("cap", "cas", "sead", "strike",
                                                "awacs", "tanker")]
        else:
            all_plans = [
                plan for plan in all_plans
                if plan.action not in ("cap", "cas", "sead", "strike",
                                       "awacs", "tanker")
                or self.live_air_by_type.get(plan.action, 0)
                < self.max_per_air_type]
        # Reactive triggers first: counter-attack a lost objective, reinforce
        # a threatened one, or recapture a cut-off objective (its income is
        # not flowing - the supply line must be restored). May overdraw bucket.
        cut_off = {objective_id for objective_id, objective_state
                   in state.objectives.items()
                   if objective_state.owner == self.side
                   and not self.engine.connected_to_home(
                       state, self.side, objective_id)}
        urgent = [plan for plan in all_plans
                  if (plan.action == "assault"
                      and (plan.target in self.lost or plan.target in cut_off))
                  or (plan.action == "reinforce" and plan.target in self.threatened)]
        # Counter-doctrine: an enemy assault in progress gets an armed response
        # - strike the attacking force, CAP over the fight, or counter-assault
        # the same objective. These may overdraw the bucket like other urgent
        # reactions; war does not wait for payday.
        if self.enemy_assaults:
            urgent += [plan for plan in all_plans
                       if plan.action in ("strike", "cas", "cap", "assault")
                       and plan.target in self.enemy_assaults]
        urgent = self._affordable(state, urgent, urgent=True)
        # Support replacement is also urgent (standing rule): always airborne.
        # It ignores the reserve floor entirely - a side without AWACS/tanker
        # is blind and unfuelled, which is worse than a low balance.
        if "awacs" not in self.live_support or "tanker" not in self.live_support:
            urgent += [plan for plan in all_plans
                       if plan.action in ("awacs", "tanker")
                       and plan.action not in self.live_support
                       and state.resources[self.side] - plan.cost >= 50]
        routine = self._affordable(state, all_plans, urgent=False)
        choice = self._choose(state, urgent, routine)
        if choice:
            self._bucket = max(0.0, self._bucket - choice.cost)
        self.decision_log.append({
            "resources": state.resources[self.side],
            "bucket": round(self._bucket, 1),
            "live_support": sorted(self.live_support),
            "threatened": sorted(self.threatened),
            "lost": sorted(self.lost),
            "options": sorted({plan.action for plan in routine}),
            "choice": {"action": choice.action, "target": choice.target} if choice else None,
        })
        return choice

    def _choose(self, state: CampaignState, urgent: list[ActionPlan],
                routine: list[ActionPlan]) -> ActionPlan | None:
        if urgent:
            return self._random.choice(urgent)
        if not routine:
            return None
        plans = routine
        # Standing rules, in priority order. Support replacement is urgent and
        # may overdraw the bucket: an AWACS or tanker must always be airborne.
        for action in ("awacs", "tanker"):
            if action in self.live_support:
                continue
            replacements = [plan for plan in plans if plan.action == action]
            if replacements:
                return self._random.choice(replacements)
        # Player requests (JTAC etc.) are approved when affordable: they are
        # cheap support that helps the coalition, so no random roll.
        while self.pending_requests:
            request = self.pending_requests[0]
            affordable = [plan for plan in plans
                          if plan.action == request.get("action")
                          and plan.target == request.get("target")]
            if affordable:
                self.pending_requests.pop(0)
                return affordable[0]
            # Cannot afford it right now: keep it queued and stop this round.
            break
        if "awacs" in self.live_support and "cap" not in self.live_support:
            escorts = [plan for plan in plans if plan.action == "cap"]
            if escorts:
                return self._random.choice(escorts)
        # Free escort: one CAP per airborne AWACS or tanker is doctrine, not
        # an expense. High-value support assets (a MiG just hunted the tanker)
        # get a fighter escort bought for them; the service refunds the cost
        # via the free_escort flag.
        if ("awacs" in self.live_support or "tanker" in self.live_support) \
                and "cap" not in self.live_support:
            escorts = [plan for plan in plans if plan.action == "cap"]
            if escorts:
                self.free_escort = True
                return escorts[0]
        # Air-power doctrine: 40% of rounds launch an air mission instead of
        # a ground move. Deep missions (strike/SEAD) are preferred over CAS
        # so players actually see them; SEAD targets objectives with known
        # SAMs (hard ones), strike/CAS hit enemy-held objectives - softening
        # before an assault.
        if self._random.random() < 0.4:
            air_missions = [plan for plan in plans
                            if plan.action in ("sead", "strike", "cas")]
            if air_missions:
                # Strike attraction: objectives that would cut enemy income
                # (hubs like Krymsk) draw the deep missions. Weighted, not
                # deterministic - 70% pick the highest-value target.
                if self._random.random() < 0.7:
                    air_missions.sort(
                        key=lambda plan: -self.engine.income_value(
                            state, self.side, plan.target))
                    return air_missions[0]
                # Prefer SEAD against hard (SAM-heavy) objectives.
                sead = [plan for plan in air_missions
                        if plan.action == "sead"
                        and self.engine.scenario.objectives[plan.target].difficulty == "hard"]
                if sead and self._random.random() < 0.5:
                    return self._random.choice(sead)
                deep = [plan for plan in air_missions
                        if plan.action in ("sead", "strike")]
                if deep and self._random.random() < 0.7:
                    return self._random.choice(deep)
                return self._random.choice(air_missions)
        assaults = [plan for plan in plans if plan.action == "assault"]
        # Reinforce is the safe bet; cap how often it eats a round so the
        # battlefield stays offensive. At most every other routine round.
        reinforces = [plan for plan in plans if plan.action == "reinforce"]
        if reinforces and self._random.random() < 0.5:
            plans = [plan for plan in plans if plan.action != "reinforce"] or reinforces
        candidates = assaults if assaults and self._random.random() < 0.7 else plans
        return self._random.choice(candidates)