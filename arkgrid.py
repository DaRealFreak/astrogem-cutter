from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

# -----------------------------
# Gem effect definitions
# -----------------------------

DPS_EFFECTS = frozenset({"attack_power", "additional_damage", "boss_damage"})
SUPPORT_EFFECTS = frozenset({"ally_damage", "brand_power", "ally_attack"})

# Higher number = higher priority (user-specified ordering)
DPS_PRIORITY: Dict[str, int] = {"boss_damage": 3, "additional_damage": 2, "attack_power": 1}
SUPPORT_PRIORITY: Dict[str, int] = {"ally_attack": 3, "brand_power": 2, "ally_damage": 1}

# Each gem type's 4 available effects (2 DPS + 2 support per type)
GEM_TYPES: Dict[str, Tuple[str, ...]] = {
    "order_stability": ("attack_power", "additional_damage", "ally_damage", "brand_power"),
    "order_fortitude": ("attack_power", "boss_damage", "ally_damage", "ally_attack"),
    "order_immutability": ("additional_damage", "boss_damage", "brand_power", "ally_attack"),
    "chaos_erosion": ("attack_power", "additional_damage", "ally_damage", "brand_power"),
    "chaos_distortion": ("attack_power", "boss_damage", "ally_damage", "ally_attack"),
    "chaos_collapse": ("additional_damage", "boss_damage", "brand_power", "ally_attack"),
}


# -----------------------------
# Core data types
# -----------------------------

@dataclass(frozen=True)
class Option:
    key: str
    weight: float
    kind: str  # will/chaos/first/second/view/cost/other
    delta: int = 0


@dataclass(frozen=True)
class LastTurnGoal:
    # Any field left as None is ignored.
    min_will: Optional[int] = None
    min_chaos: Optional[int] = None
    exact_will: Optional[int] = None
    exact_chaos: Optional[int] = None
    min_total_will_chaos: Optional[int] = None
    exact_total_will_chaos: Optional[int] = None

    def satisfied(self, will: int, chaos: int) -> bool:
        if self.exact_will is not None and will != self.exact_will:
            return False
        if self.exact_chaos is not None and chaos != self.exact_chaos:
            return False
        if self.min_will is not None and will < self.min_will:
            return False
        if self.min_chaos is not None and chaos < self.min_chaos:
            return False

        total = will + chaos
        if self.exact_total_will_chaos is not None and total != self.exact_total_will_chaos:
            return False
        if self.min_total_will_chaos is not None and total < self.min_total_will_chaos:
            return False
        return True

    def feasible(self, will: int, chaos: int, turns_left: int) -> bool:
        """
        Necessary feasibility check for min_will/min_chaos goals:
          - will/chaos capped at 5
          - one click can raise at most ONE of (will, chaos) by up to +4
          - for exact targets below current we return False (not handled here)
        """
        target_w = self.exact_will if self.exact_will is not None else self.min_will
        target_c = self.exact_chaos if self.exact_chaos is not None else self.min_chaos

        if target_w is not None and target_w > 5:
            return False
        if target_c is not None and target_c > 5:
            return False

        if self.exact_will is not None and will > self.exact_will:
            return False
        if self.exact_chaos is not None and chaos > self.exact_chaos:
            return False

        req_w = max(0, (target_w - will)) if target_w is not None else 0
        req_c = max(0, (target_c - chaos)) if target_c is not None else 0

        if will + req_w > 5:
            return False
        if chaos + req_c > 5:
            return False

        turns_needed_w = math.ceil(req_w / 4) if req_w > 0 else 0
        turns_needed_c = math.ceil(req_c / 4) if req_c > 0 else 0
        if turns_needed_w + turns_needed_c > turns_left:
            return False

        # Optional total constraints (loose safe bound)
        total = will + chaos
        if self.exact_total_will_chaos is not None:
            if total > self.exact_total_will_chaos:
                return False
            req_total = self.exact_total_will_chaos - total
            if math.ceil(max(0, req_total) / 4) > turns_left:
                return False

        if self.min_total_will_chaos is not None:
            req_total = self.min_total_will_chaos - total
            if math.ceil(max(0, req_total) / 4) > turns_left:
                return False

        return True


@dataclass(frozen=True)
class AstroGem:
    gem_type: str  # key into GEM_TYPES, e.g. "chaos_distortion"
    first_effect: str  # starting first effect, e.g. "attack_power"
    second_effect: str  # starting second effect, e.g. "ally_damage"
    optimize: str  # "dps" or "support"


@dataclass
class GemState:
    will: int = 1
    chaos: int = 1
    first: int = 1
    second: int = 1
    cost_ratio: int = 0
    rerolls: int = 0
    first_effect: str = ""
    second_effect: str = ""

    def clone(self) -> "GemState":
        return GemState(
            will=self.will,
            chaos=self.chaos,
            first=self.first,
            second=self.second,
            cost_ratio=self.cost_ratio,
            rerolls=self.rerolls,
            first_effect=self.first_effect,
            second_effect=self.second_effect,
        )

    def total_points(self) -> int:
        return self.will + self.chaos + self.first + self.second


@dataclass
class RunResult:
    success: bool
    reason: str
    reset_used: bool
    state: GemState
    total_points: int
    rerolls_left: int
    turn_log: Optional[List[Dict[str, Any]]] = None


# -----------------------------
# Pool + offer generation
# -----------------------------

class OptionPool:
    def __init__(self) -> None:
        self.pool: List[Option] = self._build_pool()

    @staticmethod
    def _build_pool() -> List[Option]:
        pool: List[Option] = []

        def add(key: str, weight: float, kind: str, delta: int = 0) -> None:
            pool.append(Option(key, weight, kind, delta))

        # Willpower
        add("will+1", 11.6500, "will", 1)
        add("will+2", 4.4000, "will", 2)
        add("will+3", 1.7500, "will", 3)
        add("will+4", 0.4500, "will", 4)
        add("will-1", 3.0000, "will", -1)

        # Chaos
        add("chaos+1", 11.6500, "chaos", 1)
        add("chaos+2", 4.4000, "chaos", 2)
        add("chaos+3", 1.7500, "chaos", 3)
        add("chaos+4", 0.4500, "chaos", 4)
        add("chaos-1", 3.0000, "chaos", -1)

        # First
        add("first+1", 11.6500, "first", 1)
        add("first+2", 4.4000, "first", 2)
        add("first+3", 1.7500, "first", 3)
        add("first+4", 0.4500, "first", 4)
        add("first-1", 3.0000, "first", -1)

        # Second
        add("second+1", 11.6500, "second", 1)
        add("second+2", 4.4000, "second", 2)
        add("second+3", 1.7500, "second", 3)
        add("second+4", 0.4500, "second", 4)
        add("second-1", 3.0000, "second", -1)

        # Other
        add("change_first_effect", 3.2500, "other", 0)
        add("change_second_effect", 3.2500, "other", 0)
        add("maintain", 1.7500, "other", 0)

        # Cost modifiers
        add("cost+100", 1.7500, "cost", 0)
        add("cost-100", 1.7500, "cost", 0)

        # View => modeled as gaining rerolls
        add("view+1", 2.5000, "view", 1)
        add("view+2", 0.7500, "view", 2)

        return pool

    @staticmethod
    def _can_increase(cur: int, k: int) -> bool:
        return cur <= 5 - k

    @staticmethod
    def _can_decrease(cur: int) -> bool:
        return cur >= 2

    def eligible(self, opt: Option, state: GemState, turn: int, turns_left: int) -> bool:
        if opt.kind == "will":
            return self._can_increase(state.will, opt.delta) if opt.delta > 0 else self._can_decrease(state.will)
        if opt.kind == "chaos":
            return self._can_increase(state.chaos, opt.delta) if opt.delta > 0 else self._can_decrease(state.chaos)
        if opt.kind == "first":
            return self._can_increase(state.first, opt.delta) if opt.delta > 0 else self._can_decrease(state.first)
        if opt.kind == "second":
            return self._can_increase(state.second, opt.delta) if opt.delta > 0 else self._can_decrease(state.second)

        # cost options excluded on last turn
        if opt.kind == "cost":
            if turns_left == 1:
                return False
            if opt.key == "cost+100":
                return state.cost_ratio < 100
            if opt.key == "cost-100":
                return state.cost_ratio > -100
            return True

        # view options excluded on turn 1 and last turn
        if opt.kind == "view":
            if turn == 1:
                return False
            if turns_left == 1:
                return False
            return True

        return True

    @staticmethod
    def _weighted_choice(options: List[Option], rng: random.Random) -> Option:
        total = sum(o.weight for o in options)
        r = rng.random() * total
        acc = 0.0
        for o in options:
            acc += o.weight
            if r <= acc:
                return o
        return options[-1]

    def _weighted_sample_without_replacement(self, options: List[Option], k: int, rng: random.Random) -> List[Option]:
        chosen: List[Option] = []
        remaining = options[:]
        for _ in range(k):
            pick = self._weighted_choice(remaining, rng)
            chosen.append(pick)
            remaining.remove(pick)
        return chosen

    def generate_offers(self, state: GemState, turn: int, turns_left: int, rng: random.Random) -> List[Option]:
        elig = [o for o in self.pool if self.eligible(o, state, turn, turns_left)]
        if len(elig) <= 4:
            return elig
        return self._weighted_sample_without_replacement(elig, 4, rng)


# -----------------------------
# Reroll policy (your original rules)
# -----------------------------

class RerollPolicy:
    GOAL_UPGRADES = {"will+1", "will+2", "will+3", "will+4",
                     "chaos+1", "chaos+2", "chaos+3", "chaos+4"}
    GOAL_BIG_UPGRADES = {"will+2", "will+3", "will+4",
                         "chaos+2", "chaos+3", "chaos+4"}
    GOAL_DOWNGRADES = {"will-1", "chaos-1"}
    SIDE_UPGRADES = {"first+1", "first+2", "first+3", "first+4",
                     "second+1", "second+2", "second+3", "second+4"}
    SIDE_BIG_UPGRADES = {"first+2", "first+3", "first+4",
                         "second+2", "second+3", "second+4"}
    ALL_DOWNGRADES = {"will-1", "chaos-1", "first-1", "second-1"}

    def __init__(self, goal: LastTurnGoal, side_node_threshold: float = 0.5,
                 astro_gem: Optional[AstroGem] = None) -> None:
        self.goal = goal
        # When this fraction (or more) of offers keep the goal feasible,
        # also consider side-node upgrades as valuable instead of focusing
        # solely on will/chaos.  0.0 = always value side nodes,
        # 1.0+ = never value side nodes until goal is fully met.
        self.side_node_threshold = side_node_threshold
        self.astro_gem = astro_gem

    # ------------------------------------------------------------------
    # Target-aware helpers
    # ------------------------------------------------------------------

    def _target_side_sets(self, state: GemState) -> Tuple[set, set]:
        """Return (upgrades, big_upgrades) filtered to optimisation-target slots."""
        if self.astro_gem is None:
            return self.SIDE_UPGRADES, self.SIDE_BIG_UPGRADES

        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        slots: List[str] = []
        if state.first_effect in target:
            slots.append("first")
        if state.second_effect in target:
            slots.append("second")

        ups: set = set()
        big: set = set()
        for slot in slots:
            for n in range(1, 5):
                ups.add(f"{slot}+{n}")
                if n >= 2:
                    big.add(f"{slot}+{n}")
        return ups, big

    def _has_good_effect_change(self, keys: set, state: GemState) -> bool:
        """True if any change_effect option would improve the target priority."""
        if self.astro_gem is None:
            return False

        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        prio = DPS_PRIORITY if self.astro_gem.optimize == "dps" else SUPPORT_PRIORITY
        pool = GEM_TYPES[self.astro_gem.gem_type]

        for key, cur_eff in [("change_first_effect", state.first_effect),
                             ("change_second_effect", state.second_effect)]:
            if key not in keys:
                continue
            available = [e for e in pool
                         if e != state.first_effect and e != state.second_effect]
            if not available:
                continue
            best = max(available, key=lambda e: (e in target, prio.get(e, 0)))
            cur_score = (cur_eff in target, prio.get(cur_eff, 0))
            best_score = (best in target, prio.get(best, 0))
            if best_score > cur_score:
                return True
        return False

    # ------------------------------------------------------------------

    def should_reroll(
            self,
            offers: List[Option],
            state: GemState,
            turns_left: int,
            goal_feasible_frac: float,
    ) -> Tuple[bool, List[str]]:
        keys = {o.key for o in offers}
        reasons: List[str] = []
        goal_met = self.goal.satisfied(state.will, state.chaos)

        # Target-aware side-node key sets
        side_ups, side_big_ups = self._target_side_sets(state)
        good_change = self._has_good_effect_change(keys, state)

        # Always reroll on last turn if goal not met
        if turns_left == 1 and not goal_met:
            reasons.append("last_turn_goal_not_met")
            return True, reasons

        # Always reroll if every offer would make goal infeasible
        if not goal_met and goal_feasible_frac == 0.0:
            reasons.append("no_offer_keeps_goal_feasible")
            return True, reasons

        if goal_met:
            # Goal achieved — optimise side nodes, avoid any downgrades
            has_positive = (
                    any(o.delta > 0 and o.kind in ("will", "chaos", "first", "second")
                        for o in offers)
                    or good_change
            )
            has_downgrade = bool(keys & self.ALL_DOWNGRADES)
            has_big = bool(keys & (side_big_ups | self.GOAL_BIG_UPGRADES))

            if has_downgrade and not has_big:
                reasons.append("goal_met_downgrade_without_big_upgrade")
            if not has_positive:
                reasons.append("goal_met_no_positive_upgrade")

        elif goal_feasible_frac >= self.side_node_threshold:
            # Comfortable — any positive upgrade (goal or side) is acceptable
            has_any_upgrade = bool(keys & (self.GOAL_UPGRADES | side_ups)) or good_change
            has_any_downgrade = bool(keys & self.ALL_DOWNGRADES)
            has_any_big = bool(keys & (self.GOAL_BIG_UPGRADES | side_big_ups))

            if has_any_downgrade and not has_any_big:
                reasons.append("downgrade_without_any_big_upgrade")
            if not has_any_upgrade:
                reasons.append("no_useful_upgrade")

        else:
            # Desperate — focus purely on will/chaos
            has_goal_upgrade = any(
                o.kind in ("will", "chaos") and o.delta > 0 for o in offers
            )
            has_goal_downgrade = bool(keys & self.GOAL_DOWNGRADES)
            has_goal_big = bool(keys & self.GOAL_BIG_UPGRADES)

            if has_goal_downgrade and not has_goal_big:
                reasons.append("goal_downgrade_without_big_upgrade")
            if not has_goal_upgrade:
                reasons.append("no_goal_upgrade")

        return len(reasons) > 0, reasons


# -----------------------------
# Simulator
# -----------------------------

class GemSimulator:
    RARITY_REROLLS = {"common": 0, "rare": 1, "epic": 2}
    RARITY_TURNS = {"common": 5, "rare": 7, "epic": 9}

    def __init__(
            self,
            rarity: str,
            use_extra_ticket: bool,
            use_reset_ticket: bool,
            goal: LastTurnGoal,
            side_node_threshold: float = 0.5,
            astro_gem: Optional[AstroGem] = None,
            optimize: str = "dps",
            pool: Optional[OptionPool] = None,
    ) -> None:
        self.rarity = rarity
        self.goal = goal
        self._configured_gem = astro_gem
        self.optimize = optimize
        # Active gem/policy are set per-run in simulate_one;
        # initialize with the configured gem (or None) for direct method calls.
        self.astro_gem = astro_gem
        self.side_node_threshold = side_node_threshold
        self.reroll_policy = RerollPolicy(goal, side_node_threshold, astro_gem)

        self.use_extra_ticket = use_extra_ticket
        self.use_reset_ticket = use_reset_ticket

        self.base_rerolls = self.RARITY_REROLLS[rarity] + (1 if use_extra_ticket else 0)
        self.turns_total = self.RARITY_TURNS[rarity]
        self.pool = pool or OptionPool()

    @staticmethod
    def _random_astro_gem(rng: random.Random, optimize: str) -> AstroGem:
        """Generate a random AstroGem: random type, random 2-of-4 effects."""
        gem_type = rng.choice(list(GEM_TYPES.keys()))
        effects = list(GEM_TYPES[gem_type])
        rng.shuffle(effects)
        return AstroGem(gem_type, effects[0], effects[1], optimize)

    def _best_effect_change(self, state: GemState, slot: str) -> str:
        """Resolve an effect change: pick the best effect for the optimisation target.

        On equal probability, always selects the higher-priority effect
        (boss_damage > additional_damage > attack_power for DPS;
         ally_attack > brand_power > ally_damage for support).
        """
        if self.astro_gem is None:
            return getattr(state, f"{slot}_effect")

        pool = GEM_TYPES[self.astro_gem.gem_type]
        available = [e for e in pool
                     if e != state.first_effect and e != state.second_effect]
        if not available:
            return getattr(state, f"{slot}_effect")

        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        prio = DPS_PRIORITY if self.astro_gem.optimize == "dps" else SUPPORT_PRIORITY
        # Target-type effects first, then highest priority within group
        available.sort(key=lambda e: (0 if e in target else 1, -prio.get(e, 0)))
        return available[0]

    def apply_option(self, opt: Option, state: GemState) -> None:
        if opt.kind == "will":
            state.will = min(5, max(1, state.will + opt.delta))
        elif opt.kind == "chaos":
            state.chaos = min(5, max(1, state.chaos + opt.delta))
        elif opt.kind == "first":
            state.first = min(5, max(1, state.first + opt.delta))
        elif opt.kind == "second":
            state.second = min(5, max(1, state.second + opt.delta))
        elif opt.kind == "cost":
            if opt.key == "cost+100":
                state.cost_ratio = min(100, state.cost_ratio + 100)
            elif opt.key == "cost-100":
                state.cost_ratio = max(-100, state.cost_ratio - 100)
        elif opt.kind == "view":
            state.rerolls += opt.delta
        elif opt.key == "change_first_effect":
            state.first_effect = self._best_effect_change(state, "first")
        elif opt.key == "change_second_effect":
            state.second_effect = self._best_effect_change(state, "second")

    def prob_goal_feasible_after_click(self, state: GemState, offers: List[Option], turns_left_after: int) -> float:
        if not offers:
            return 0.0
        ok = 0
        for o in offers:
            s = state.clone()
            self.apply_option(o, s)
            if self.goal.feasible(s.will, s.chaos, turns_left_after):
                ok += 1
        return ok / len(offers)

    def roll_offers_with_rerolls(
            self,
            state: GemState,
            turn: int,
            rng: random.Random,
            log_obj: Optional[Dict[str, Any]] = None,
    ) -> List[Option]:
        turns_left = self.turns_total - turn + 1
        turns_left_after = turns_left - 1

        offers = self.pool.generate_offers(state, turn, turns_left, rng)

        if log_obj is not None:
            log_obj["offers_history"] = [sorted(o.key for o in offers)]
            log_obj["reroll_reasons_history"] = []

        while turn != 1 and state.rerolls > 0:
            goal_feasible_frac = self.prob_goal_feasible_after_click(state, offers, turns_left_after)
            should, reasons = self.reroll_policy.should_reroll(offers, state, turns_left, goal_feasible_frac)

            if not should:
                break

            state.rerolls -= 1
            if log_obj is not None:
                log_obj["reroll_reasons_history"].append(reasons)

            offers = self.pool.generate_offers(state, turn, turns_left, rng)
            if log_obj is not None:
                log_obj["offers_history"].append(sorted(o.key for o in offers))

        return offers

    def simulate_one(self, seed: Optional[int] = None, log: bool = False) -> RunResult:
        rng = random.Random(seed)

        # Resolve gem for this run (configured or random)
        run_gem = (self._configured_gem
                   if self._configured_gem is not None
                   else self._random_astro_gem(rng, self.optimize))
        self.astro_gem = run_gem
        self.reroll_policy.astro_gem = run_gem

        reset_available = bool(self.use_reset_ticket)
        reset_used = False

        for attempt in range(1, 3):
            state = GemState(
                will=1, chaos=1, first=1, second=1,
                cost_ratio=0, rerolls=self.base_rerolls,
                first_effect=run_gem.first_effect,
                second_effect=run_gem.second_effect,
            )
            turn_log: List[Dict[str, Any]] = []

            for turn in range(1, self.turns_total + 1):
                turns_left = self.turns_total - turn + 1

                # goal-based feasibility check
                if not self.goal.feasible(state.will, state.chaos, turns_left):
                    if reset_available and not reset_used:
                        reset_used = True
                        if log:
                            turn_log.append({
                                "turn": turn,
                                "turns_left": turns_left,
                                "action": "RESET (goal infeasible before rolling)",
                                "state_before_reset": {
                                    "will": state.will,
                                    "chaos": state.chaos,
                                    "first": state.first,
                                    "second": state.second,
                                    "total_points": state.total_points(),
                                    "rerolls": state.rerolls,
                                    "first_effect": state.first_effect,
                                    "second_effect": state.second_effect,
                                },
                            })
                        break
                    return RunResult(
                        success=False,
                        reason="impossible_no_reset_available",
                        reset_used=reset_used,
                        state=state,
                        total_points=state.total_points(),
                        rerolls_left=state.rerolls,
                        turn_log=turn_log if log else None,
                    )

                entry: Optional[Dict[str, Any]] = {"turn": turn, "turns_left": turns_left} if log else None
                offers = self.roll_offers_with_rerolls(state, turn, rng, entry if log else None)

                # after rerolls: if still no feasible path, reset/fail
                p_feasible_after = self.prob_goal_feasible_after_click(state, offers, turns_left - 1)
                if p_feasible_after == 0.0:
                    if reset_available and not reset_used:
                        reset_used = True
                        if log:
                            entry["action"] = "RESET (no feasible path after click)"
                            entry["state_before_reset"] = {
                                "will": state.will,
                                "chaos": state.chaos,
                                "first": state.first,
                                "second": state.second,
                                "total_points": state.total_points(),
                                "rerolls": state.rerolls,
                                "first_effect": state.first_effect,
                                "second_effect": state.second_effect,
                            }
                            turn_log.append(entry)
                        break

                    if log:
                        entry["action"] = "FAIL (no feasible path after click)"
                        entry["state_after"] = {
                            "will": state.will,
                            "chaos": state.chaos,
                            "first": state.first,
                            "second": state.second,
                            "total_points": state.total_points(),
                            "rerolls": state.rerolls,
                            "first_effect": state.first_effect,
                            "second_effect": state.second_effect,
                        }
                        turn_log.append(entry)

                    return RunResult(
                        success=False,
                        reason="forced_fail_no_feasible_path_after_click",
                        reset_used=reset_used,
                        state=state,
                        total_points=state.total_points(),
                        rerolls_left=state.rerolls,
                        turn_log=turn_log if log else None,
                    )

                picked = rng.choice(offers)
                self.apply_option(picked, state)

                if log:
                    entry["action"] = "click"
                    entry["picked"] = picked.key
                    entry["state_after"] = {
                        "will": state.will,
                        "chaos": state.chaos,
                        "first": state.first,
                        "second": state.second,
                        "total_points": state.total_points(),
                        "rerolls": state.rerolls,
                        "first_effect": state.first_effect,
                        "second_effect": state.second_effect,
                    }
                    turn_log.append(entry)

            else:
                success = self.goal.satisfied(state.will, state.chaos)
                return RunResult(
                    success=success,
                    reason="goal_met" if success else "goal_not_met",
                    reset_used=reset_used,
                    state=state,
                    total_points=state.total_points(),
                    rerolls_left=state.rerolls,
                    turn_log=turn_log if log else None,
                )

            # reset used on attempt 1 -> retry
            if reset_used and attempt == 1:
                continue

            return RunResult(
                success=False,
                reason="ended_unexpectedly",
                reset_used=reset_used,
                state=state,
                total_points=state.total_points(),
                rerolls_left=state.rerolls,
                turn_log=turn_log if log else None,
            )

        raise RuntimeError("Simulation exceeded expected attempts")


# -----------------------------
# Analyzer (probability estimates)
# -----------------------------

class GemAnalyzer:
    @staticmethod
    def wilson_ci(p_hat: float, n: int, z: float = 1.96) -> Tuple[float, float]:
        if n == 0:
            return (0.0, 1.0)
        denom = 1 + z ** 2 / n
        center = (p_hat + z ** 2 / (2 * n)) / denom
        half = (z * math.sqrt((p_hat * (1 - p_hat) / n) + (z ** 2 / (4 * n ** 2)))) / denom
        return (max(0.0, center - half), min(1.0, center + half))

    @staticmethod
    def estimate_summary(
            trials: int,
            simulator: GemSimulator,
            relic_threshold: int = 16,
            ancient_threshold: int = 19,
            seed: int = 12345,
    ) -> Dict[str, float]:
        rng = random.Random(seed)

        wins = 0
        resets = 0
        sum_points = 0
        relic_plus = 0
        ancient = 0

        for _ in range(trials):
            s = rng.randrange(1, 2 ** 31 - 1)
            r = simulator.simulate_one(seed=s, log=False)

            wins += 1 if r.success else 0
            resets += 1 if r.reset_used else 0

            sum_points += r.total_points
            relic_plus += 1 if r.total_points >= relic_threshold else 0
            ancient += 1 if r.total_points >= ancient_threshold else 0

        p_success = wins / trials
        lo, hi = GemAnalyzer.wilson_ci(p_success, trials)

        return {
            "p_success": p_success,
            "p_success_ci_lo": lo,
            "p_success_ci_hi": hi,
            "avg_total_points": sum_points / trials,
            "p_relic_plus": relic_plus / trials,
            "p_ancient": ancient / trials,
            "reset_rate": resets / trials,
        }


def pprint_result(title: str, result: Dict[str, float]) -> None:
    print(title)
    print(
        f"  Success rate: {result['p_success'] * 100:.2f}% (CI: {result['p_success_ci_lo'] * 100:.2f}% - {result['p_success_ci_hi'] * 100:.2f}%)")
    print(f"  Average total points: {result['avg_total_points']:.3f}")
    print(f"  Relic+ rate (>=16): {result['p_relic_plus'] * 100:.2f}%")
    print(f"  Ancient rate (>=19): {result['p_ancient'] * 100:.2f}%")
    print(f"  Reset usage rate: {result['reset_rate'] * 100:.2f}%")
    print("")


# -----------------------------
# CLI
# -----------------------------

ALL_EFFECTS = sorted(DPS_EFFECTS | SUPPORT_EFFECTS)


def _build_parser() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        description="Lost Ark Astrogem cutting simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # ---- shared arguments ----
    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--rarity", choices=["common", "rare", "epic"], default=None,
                        help="Gem rarity (default: run all three)")
        p.add_argument("--optimize", choices=["dps", "support"], default="dps",
                        help="Side-node optimisation target (default: dps)")
        p.add_argument("--min-will", type=int, default=None, metavar="N",
                        help="Minimum willpower goal")
        p.add_argument("--min-chaos", type=int, default=None, metavar="N",
                        help="Minimum chaos goal")
        p.add_argument("--exact-will", type=int, default=None, metavar="N")
        p.add_argument("--exact-chaos", type=int, default=None, metavar="N")
        p.add_argument("--extra-ticket", action="store_true", default=True,
                        help="Use extra reroll ticket (default: yes)")
        p.add_argument("--no-extra-ticket", action="store_false", dest="extra_ticket")
        p.add_argument("--reset-ticket", action="store_true", default=None,
                        help="Use reset ticket (default: run both with/without)")
        p.add_argument("--no-reset-ticket", action="store_false", dest="reset_ticket")
        p.add_argument("--side-threshold", type=float, default=0.5, metavar="F",
                        help="Goal-feasibility fraction above which side nodes are valued (default: 0.5)")
        grp = p.add_argument_group("gem configuration (omit for random gem each run)")
        grp.add_argument("--gem-type", choices=list(GEM_TYPES.keys()), default=None,
                         help="Gem type")
        grp.add_argument("--first-effect", choices=ALL_EFFECTS, default=None,
                         help="First effect on the gem")
        grp.add_argument("--second-effect", choices=ALL_EFFECTS, default=None,
                         help="Second effect on the gem")

    # ---- stats ----
    p_stats = sub.add_parser("stats", help="Run Monte Carlo probability estimation")
    add_common(p_stats)
    p_stats.add_argument("--trials", type=int, default=200_000,
                         help="Number of simulation trials (default: 200000)")
    p_stats.add_argument("--seed", type=int, default=12345,
                         help="RNG seed for reproducibility (default: 12345)")

    # ---- sim ----
    p_sim = sub.add_parser("sim", help="Run a single simulation with turn-by-turn log")
    add_common(p_sim)
    p_sim.add_argument("--seed", type=int, default=42,
                       help="RNG seed (default: 42)")

    return parser


def _resolve_args(args: "argparse.Namespace") -> Tuple[
    LastTurnGoal, Optional[AstroGem], List[str], List[Optional[bool]]
]:
    goal = LastTurnGoal(
        min_will=args.min_will,
        min_chaos=args.min_chaos,
        exact_will=args.exact_will,
        exact_chaos=args.exact_chaos,
    )

    astro_gem: Optional[AstroGem] = None
    if args.gem_type:
        pool = set(GEM_TYPES[args.gem_type])
        first = args.first_effect
        second = args.second_effect
        if not first or first not in pool:
            raise SystemExit(
                f"--first-effect must be one of {sorted(pool)} for {args.gem_type}"
            )
        if not second or second not in pool:
            raise SystemExit(
                f"--second-effect must be one of {sorted(pool)} for {args.gem_type}"
            )
        if first == second:
            raise SystemExit("--first-effect and --second-effect must differ")
        astro_gem = AstroGem(args.gem_type, first, second, args.optimize)

    rarities = [args.rarity] if args.rarity else ["common", "rare", "epic"]

    if args.reset_ticket is None:
        reset_variants: List[Optional[bool]] = [False, True]
    else:
        reset_variants = [args.reset_ticket]

    return goal, astro_gem, rarities, reset_variants


def _print_config(args: "argparse.Namespace", goal: LastTurnGoal,
                  astro_gem: Optional[AstroGem]) -> None:
    parts: List[str] = []
    if goal.min_will is not None:
        parts.append(f"min_will={goal.min_will}")
    if goal.min_chaos is not None:
        parts.append(f"min_chaos={goal.min_chaos}")
    if goal.exact_will is not None:
        parts.append(f"exact_will={goal.exact_will}")
    if goal.exact_chaos is not None:
        parts.append(f"exact_chaos={goal.exact_chaos}")
    goal_str = ", ".join(parts) if parts else "(no goal constraints)"

    if astro_gem:
        gem_str = f"{astro_gem.gem_type} [{astro_gem.first_effect} + {astro_gem.second_effect}]"
    else:
        gem_str = "random"

    print(f"Goal:     {goal_str}")
    print(f"Gem:      {gem_str}")
    print(f"Optimize: {args.optimize}")
    print(f"Extra ticket: {'yes' if args.extra_ticket else 'no'}")
    print(f"Side threshold: {args.side_threshold}")
    print()


def cmd_stats(args: "argparse.Namespace") -> None:
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    _print_config(args, goal, astro_gem)

    for use_reset in reset_variants:
        label = "With reset ticket" if use_reset else "Without reset ticket"
        print(f"--- {label} ---")
        for rarity in rarities:
            sim = GemSimulator(
                rarity=rarity,
                use_extra_ticket=args.extra_ticket,
                use_reset_ticket=use_reset,
                goal=goal,
                side_node_threshold=args.side_threshold,
                astro_gem=astro_gem,
                optimize=args.optimize,
            )
            summary = GemAnalyzer.estimate_summary(
                trials=args.trials, simulator=sim, seed=args.seed,
            )
            pprint_result(f"  {rarity.capitalize()}", summary)


def cmd_sim(args: "argparse.Namespace") -> None:
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    rarity = rarities[0]
    use_reset = reset_variants[-1]
    _print_config(args, goal, astro_gem)

    sim = GemSimulator(
        rarity=rarity,
        use_extra_ticket=args.extra_ticket,
        use_reset_ticket=use_reset,
        goal=goal,
        side_node_threshold=args.side_threshold,
        astro_gem=astro_gem,
        optimize=args.optimize,
    )
    r = sim.simulate_one(seed=args.seed, log=True)

    print(f"Rarity: {rarity}  |  Seed: {args.seed}")
    print(f"Result: {'SUCCESS' if r.success else 'FAIL'} ({r.reason})")
    print(f"Reset used: {r.reset_used}")
    print(f"Final state: will={r.state.will} chaos={r.state.chaos} "
          f"first={r.state.first} second={r.state.second}  "
          f"(total={r.total_points})")
    print(f"Effects: {r.state.first_effect} / {r.state.second_effect}")
    print(f"Rerolls left: {r.rerolls_left}")
    print()

    for t in (r.turn_log or []):
        hdr = f"Turn {t['turn']} (left={t['turns_left']})"
        print(hdr)
        if "offers_history" in t:
            for i, offers in enumerate(t["offers_history"]):
                if i == 0:
                    print(f"  offers:  {offers}")
                else:
                    print(f"  reroll:  {offers}  reasons={t['reroll_reasons_history'][i - 1]}")
        print(f"  action:  {t['action']}")
        if "picked" in t:
            print(f"  picked:  {t['picked']}")
        sa = t.get("state_after") or t.get("state_before_reset")
        if sa:
            print(f"  state:   w={sa['will']} c={sa['chaos']} "
                  f"1st={sa['first']} 2nd={sa['second']}  "
                  f"(total={sa['total_points']})  "
                  f"effects={sa['first_effect']}/{sa['second_effect']}")
        print()


if __name__ == "__main__":
    import argparse

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "sim":
        cmd_sim(args)
    else:
        parser.print_help()
