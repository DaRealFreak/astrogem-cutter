"""Scenario-based tests for tracing simulator/policy decisions.

Define a specific game state, offers, and parameters, then check
what the reroll policy, early-finish logic, and DP probability say.

Usage:
    python -m unittest tests.test_scenarios -v
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from arkgrid import (
    AstroGem,
    GemSimulator,
    GemState,
    LastTurnGoal,
    Option,
    OptionPool,
    RerollPolicy,
)
from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, SUPPORT_COEFF, SUPPORT_EFFECTS


@dataclass
class ScenarioResult:
    """Collected decision outputs for a scenario."""
    # Reroll
    should_reroll: bool
    reroll_reasons: List[str]
    # Early finish
    should_early_finish: bool
    # Goal checks
    goal_satisfied: bool          # LastTurnGoal only (will/chaos/first/second)
    goal_fully_satisfied: bool    # Including side coeff + BIS
    # DP probabilities
    dp_current: float             # P(success) from current state
    dp_after_click: float         # Expected P(success) after random pick
    dp_baseline: float            # DP lookup at current state (for reroll comparison)
    # Feasibility
    feasible_frac: float          # Fraction of offers keeping goal feasible
    # Per-offer analysis
    per_offer: List[dict]         # [{key, state_after, dp_after, goal_still_met, coeff_after}]


class ScenarioHelper:
    """Build a simulator from scenario parameters and evaluate decisions."""

    POOL = OptionPool()
    OFFER_LOOKUP = {o.key: o for o in POOL.pool}

    @classmethod
    def make_offers(cls, *keys: str) -> List[Option]:
        return [cls.OFFER_LOOKUP[k] for k in keys]

    @classmethod
    def evaluate(
        cls,
        *,
        # Gem identity
        gem_type: str,
        first_effect: str,
        second_effect: str,
        optimize: str = "dps",
        # Current state
        will: int,
        chaos: int,
        first: int,
        second: int,
        rerolls: int = 0,
        cost_ratio: int = 0,
        # Turn info
        rarity: str = "epic",
        turn: int,
        # Offers (pool keys)
        offer_keys: Tuple[str, ...],
        # Goal
        goal: LastTurnGoal,
        # Policy / simulator params
        min_side_coeff: int = 0,
        early_finish_coeff: int = -1,
        use_extra_ticket: bool = False,
        use_reset_ticket: bool = False,
        side_node_threshold: float = 0.5,
        bis_only: bool = False,
        exact_draw: bool = False,
    ) -> ScenarioResult:
        astro_gem = AstroGem(gem_type, first_effect, second_effect, optimize)
        sim = GemSimulator(
            rarity=rarity,
            use_extra_ticket=use_extra_ticket,
            use_reset_ticket=use_reset_ticket,
            goal=goal,
            side_node_threshold=side_node_threshold,
            astro_gem=astro_gem,
            optimize=optimize,
            bis_only=bis_only,
            pool=cls.POOL,
            min_side_coeff=min_side_coeff,
            exact_draw=exact_draw,
            early_finish_coeff=early_finish_coeff,
        )

        turns_total = GemSimulator.RARITY_TURNS[rarity]
        turns_left = turns_total - turn + 1

        state = GemState(
            will=will, chaos=chaos, first=first, second=second,
            cost_ratio=cost_ratio, rerolls=rerolls,
            first_effect=first_effect, second_effect=second_effect,
        )
        offers = cls.make_offers(*offer_keys)

        # --- Reroll decision ---
        feasible_frac = sim.prob_goal_feasible_after_click(
            state, offers, turns_left - 1)
        goal_success_prob = sim.prob_table.expected_prob_after_click(
            state, offers, turns_left - 1)
        dp_baseline = sim.prob_table.lookup(state, turns_left)

        should_reroll, reroll_reasons = sim.reroll_policy.should_reroll(
            offers, state, turns_left, feasible_frac,
            goal_success_prob=goal_success_prob,
            dp_baseline=dp_baseline,
            rerolls_remaining=rerolls,
        )

        # --- Early finish / coefficient-aware reroll ---
        early = sim.should_early_finish(state, offers, turns_left)
        if early and rerolls > 0:
            # Reroll instead of finishing when rerolls remain
            should_reroll = True
            if "coeff_early_finish" not in reroll_reasons:
                reroll_reasons.append("coeff_early_finish")
            early = False

        # --- Goal checks ---
        goal_sat = goal.satisfied(state.will, state.chaos,
                                  state.first, state.second)
        goal_full = sim._goal_fully_satisfied(state)

        # --- Per-offer analysis ---
        coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        t_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        per_offer = []
        for o in offers:
            s = state.clone()
            sim.apply_option(o, s)
            dp_after = sim.prob_table.lookup(s, turns_left - 1)
            still_met = goal.satisfied(s.will, s.chaos, s.first, s.second)
            full_met = sim._goal_fully_satisfied(s)
            coeff_total = 0
            if s.first_effect in t_set:
                coeff_total += s.first * coeff_map[s.first_effect]
            if s.second_effect in t_set:
                coeff_total += s.second * coeff_map[s.second_effect]
            per_offer.append({
                "key": o.key,
                "state_after": f"w={s.will} c={s.chaos} f={s.first} s={s.second}",
                "dp_after": dp_after,
                "goal_still_met": still_met,
                "goal_fully_met": full_met,
                "side_coeff": coeff_total,
            })

        return ScenarioResult(
            should_reroll=should_reroll,
            reroll_reasons=reroll_reasons,
            should_early_finish=early,
            goal_satisfied=goal_sat,
            goal_fully_satisfied=goal_full,
            dp_current=dp_baseline,
            dp_after_click=goal_success_prob,
            dp_baseline=dp_baseline,
            feasible_frac=feasible_frac,
            per_offer=per_offer,
        )

    @classmethod
    def print_result(cls, result: ScenarioResult) -> None:
        """Pretty-print scenario results (useful when running interactively)."""
        print(f"\n{'='*60}")
        print(f"Goal satisfied (will/chaos):  {result.goal_satisfied}")
        print(f"Goal FULLY satisfied (+ coeff): {result.goal_fully_satisfied}")
        print(f"DP current P(success):  {result.dp_current:.4f}")
        print(f"DP after click (avg):   {result.dp_after_click:.4f}")
        print(f"Feasible fraction:      {result.feasible_frac:.2f}")
        print(f"Should reroll:          {result.should_reroll}  {result.reroll_reasons}")
        print(f"Should early finish:    {result.should_early_finish}")
        print(f"\nPer-offer breakdown:")
        for o in result.per_offer:
            print(f"  {o['key']:>12s} -> {o['state_after']}  "
                  f"DP={o['dp_after']:.4f}  "
                  f"goal={o['goal_still_met']}  "
                  f"full={o['goal_fully_met']}  "
                  f"coeff={o['side_coeff']}")
        print(f"{'='*60}\n")


# ======================================================================
# Scenario tests
# ======================================================================

class TestScenarioEpicTurn7SideCoeff(unittest.TestCase):
    """Turn 7/9, will=4 chaos=5, boss_dmg=1 brand_power=1.
    Offers: will-1, chaos-1, first+3, cost-100.
    --min-side-coeff 3000 --early-finish-coeff 700
    """

    def setUp(self) -> None:
        self.result = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=4, chaos=5, first=1, second=1,
            rerolls=0,
            rarity="epic",
            turn=7,
            offer_keys=("will-1", "chaos-1", "first+3", "cost-100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            min_side_coeff=3000,
            early_finish_coeff=700,
        )

    def test_goal_satisfied_but_not_fully(self) -> None:
        """Will/chaos goal is met, but side coeff (1000) < 3000."""
        self.assertTrue(self.result.goal_satisfied)
        self.assertFalse(self.result.goal_fully_satisfied)

    def test_no_early_finish(self) -> None:
        """Can't early finish — side coeff goal not met yet."""
        self.assertFalse(self.result.should_early_finish)

    def test_no_reroll(self) -> None:
        """Heuristic: goal met + first+3 is a big side upgrade → don't reroll."""
        self.assertFalse(self.result.should_reroll)

    def test_first_plus3_achieves_full_goal(self) -> None:
        """Picking first+3 gives boss_damage=4 → coeff 4000 >= 3000."""
        offer = next(o for o in self.result.per_offer if o["key"] == "first+3")
        self.assertTrue(offer["goal_fully_met"])
        self.assertGreaterEqual(offer["side_coeff"], 3000)

    def test_will_minus1_breaks_goal(self) -> None:
        """Picking will-1 drops will to 3, breaking min_will=4."""
        offer = next(o for o in self.result.per_offer if o["key"] == "will-1")
        self.assertFalse(offer["goal_still_met"])

    def test_chaos_minus1_breaks_goal(self) -> None:
        """Picking chaos-1 drops chaos to 4, breaking min_chaos=5."""
        offer = next(o for o in self.result.per_offer if o["key"] == "chaos-1")
        self.assertFalse(offer["goal_still_met"])

    def test_print_details(self) -> None:
        """Print full scenario breakdown (visible with -v)."""
        ScenarioHelper.print_result(self.result)


class TestScenarioEpicTurn7SideCoeffWithRerolls(unittest.TestCase):
    """Same scenario but with 2 rerolls available."""

    def setUp(self) -> None:
        self.result = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=4, chaos=5, first=1, second=1,
            rerolls=2,
            rarity="epic",
            turn=7,
            offer_keys=("will-1", "chaos-1", "first+3", "cost-100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            min_side_coeff=3000,
            early_finish_coeff=700,
        )

    def test_still_no_reroll(self) -> None:
        """Even with rerolls, first+3 is too good to reroll away."""
        self.assertFalse(self.result.should_reroll)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)


class TestScenarioEarlyFinishWhenFullGoalMet(unittest.TestCase):
    """Same gem but boss_damage already at 3 (coeff=3000 met).
    Should early finish kick in with --early-finish-coeff 700?
    """

    def setUp(self) -> None:
        self.result = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=4, chaos=5, first=3, second=1,
            rerolls=0,
            rarity="epic",
            turn=9,
            offer_keys=("will-1", "chaos-1", "first+3", "cost-100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            min_side_coeff=3000,
            early_finish_coeff=800,
        )

    def test_goal_fully_satisfied(self) -> None:
        """boss_damage=3 * 1000 = 3000 >= 3000."""
        self.assertTrue(self.result.goal_fully_satisfied)

    def test_early_finish_triggers(self) -> None:
        """P(miss)=0.5 (will-1, chaos-1 break goal). Last turn (turns_left=1).
        avg_coeff = (0 + 0 + 3000 + 0) / 4 = 750.
        expected = 750 * 1 = 750 <= 800 → early finish.
        """
        self.assertTrue(self.result.should_early_finish)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)


class TestScenarioEarlyFinishSafeOffers(unittest.TestCase):
    """Full goal met with safe offers (no downgrades) → don't early finish."""

    def setUp(self) -> None:
        self.result = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=4, chaos=5, first=3, second=1,
            rerolls=0,
            rarity="epic",
            turn=7,
            offer_keys=("first+1", "second+1", "maintain", "cost-100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            min_side_coeff=3000,
            early_finish_coeff=700,
        )

    def test_no_early_finish(self) -> None:
        """No offer breaks the goal → P(miss)=0 → continue for free upgrades."""
        self.assertFalse(self.result.should_early_finish)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)


class TestScenarioDesperateMode(unittest.TestCase):
    """Will=1 chaos=1, need min_will=4 min_chaos=5 on epic turn 5.
    Low feasibility → desperate mode, only goal upgrades matter.
    """

    def setUp(self) -> None:
        self.result = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=1, chaos=1, first=1, second=1,
            rerolls=1,
            rarity="epic",
            turn=5,
            offer_keys=("first+3", "second+2", "cost-100", "maintain"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            min_side_coeff=3000,
            early_finish_coeff=700,
        )

    def test_rerolls_due_to_no_goal_upgrade(self) -> None:
        """No will/chaos upgrade in offers → desperate mode → reroll."""
        self.assertTrue(self.result.should_reroll)
        self.assertIn("no_goal_upgrade", self.result.reroll_reasons)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)


if __name__ == "__main__":
    unittest.main()
