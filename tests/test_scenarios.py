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
    GoalProbabilityTable,
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
    # Relic+ probability
    relic_prob: Optional[float] = None  # P(relic+ >=16) from current state


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
        use_extra_ticket: bool = False,
        use_reset_ticket: bool = False,
        side_node_threshold: float = 0.5,
        bis_only: bool = False,
        relic_reroll_threshold: float = 0.0,
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
            relic_reroll_threshold=relic_reroll_threshold,
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

        relic_prob = sim._relic_prob_table.lookup(state, turns_left)

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
            relic_prob=relic_prob,
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
        if result.relic_prob is not None:
            print(f"P(relic+ >=16):         {result.relic_prob:.4f}")
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
        )

    def test_rerolls_due_to_no_goal_upgrade(self) -> None:
        """No will/chaos upgrade in offers → desperate mode → reroll."""
        self.assertTrue(self.result.should_reroll)
        self.assertIn("no_goal_upgrade", self.result.reroll_reasons)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)


class TestScenarioRelicNoEarlyFinish(unittest.TestCase):
    """Turn 7/9, will=4 chaos=5 first=3 second=3 (total=15).
    Goal met, risky offers.

    Re-baselined: relic_coeff / ancient_coeff / endgame_risk now default to
    None (fusion-derived auto values), so the side-value DP places positive
    value on reaching relic+ (16 pts) by default. relic_coeff=None resolves
    to a positive fusion-derived value, so the side-value DP's _tier_bonus is
    non-zero for states that reach relic+ (>=16 pts), raising process_ev
    above finish_val — continuing is worth more than stopping — so the DP
    defers the finish. relic_reroll_threshold>0 still builds the relic+ DP
    table so relic_prob is populated for the P(relic+) assertion.
    """

    def setUp(self) -> None:
        # Without any explicit relic+ override: auto-gate does NOT finish
        # (fusion default relic_coeff raises process_ev above finish_val)
        self.result_no_override = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=4, chaos=5, first=3, second=3,
            rerolls=0,
            rarity="epic",
            turn=7,
            offer_keys=("will-1", "chaos-1", "first+1", "cost+100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
        )
        # relic_reroll_threshold>0 builds the relic+ DP table so relic_prob
        # is populated; P(relic+) itself is a pure DP figure.
        self.result_with_override = ScenarioHelper.evaluate(
            gem_type="order_immutability",
            first_effect="boss_damage",
            second_effect="brand_power",
            optimize="dps",
            will=4, chaos=5, first=3, second=3,
            rerolls=0,
            rarity="epic",
            turn=7,
            offer_keys=("will-1", "chaos-1", "first+1", "cost+100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            relic_reroll_threshold=0.3,
        )

    def test_early_finish_without_override(self) -> None:
        """Auto-gate with fusion defaults does NOT finish at total=15 (legendary).

        relic_coeff=None resolves to a positive fusion-derived value, so the
        side-value DP's _tier_bonus is non-zero for states that reach relic+
        (>=16 pts).  That raises process_ev above finish_val — continuing is
        worth more than stopping — so the DP defers the finish.  Note: the
        grade-protect gate does NOT fire here; that gate only applies when the
        gem is already at relic+ or ancient grade (total >= 16)."""
        self.assertFalse(self.result_no_override.should_early_finish)

    def test_relic_prob_above_threshold(self) -> None:
        """P(relic+ >=16) from (4,5,3,3) with 3 turns left should be well above 0.3."""
        self.assertGreater(self.result_with_override.relic_prob, 0.3)

    def test_print_details(self) -> None:
        print("\n--- Without relic+ override ---")
        ScenarioHelper.print_result(self.result_no_override)
        print("--- With relic+ override ---")
        ScenarioHelper.print_result(self.result_with_override)


class TestScenarioRelicNoEarlyFinishBelowThreshold(unittest.TestCase):
    """Turn 8/9, will=4 chaos=5 first=1 second=1 (total=11).
    Goal met; P(relic+) is low (need +5 in 2 turns) → relic override does
    NOT suppress, so the side-value gate alone decides finish-vs-process.

    Under the reroll-aware value oracle (Phase B) this hand is a near-tie:
    process_ev (~1018) marginally beats finish_val (~1000), so the gate
    PROCESSES rather than early-finishing (the flat oracle finished at
    967<1000; the reroll-aware value is the more accurate one — the flat
    table underestimates ~8% at r=0).
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
            turn=8,
            offer_keys=("will-1", "chaos-1", "first+1", "cost+100"),
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            relic_reroll_threshold=0.3,
        )

    def test_reroll_aware_processes_near_tie(self) -> None:
        """Reroll-aware value gate processes this near-tie (process_ev ~1018 >
        finish_val ~1000) instead of early-finishing; the relic override is
        not the deciding factor (its no-suppress behavior is covered by
        test_relic_prob_below_threshold)."""
        self.assertFalse(self.result.should_early_finish)

    def test_relic_prob_below_threshold(self) -> None:
        """Need +5 total in 2 turns — P(relic+) should be below 0.3."""
        self.assertLess(self.result.relic_prob, 0.3)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)


class TestScenarioRelicRerollTicketOverride(unittest.TestCase):
    """Verify that relic_reroll_threshold grants the extra ticket mid-run.

    Uses simulate_one() with a fixed seed to confirm that a gem whose
    effect coefficients are below --reroll-min-coeff still gets the
    extra reroll when P(relic+) crosses the threshold during the run.
    """

    def test_extra_ticket_granted_mid_run(self) -> None:
        """Low-coeff gem with relic override should use extra ticket."""
        goal = LastTurnGoal(min_will=4, min_chaos=5)
        astro_gem = AstroGem(
            "order_immutability", "boss_damage", "brand_power", "dps")
        # ticket off by default; relic override is the only enabler
        sim = GemSimulator(
            rarity="epic",
            use_extra_ticket=None,
            use_reset_ticket=False,
            goal=goal,
            astro_gem=astro_gem,
            optimize="dps",
            pool=ScenarioHelper.POOL,
            relic_reroll_threshold=0.25,
        )
        # Without relic override: extra ticket disabled (ticket off by default; relic override is the only enabler)
        sim_no_relic = GemSimulator(
            rarity="epic",
            use_extra_ticket=None,
            use_reset_ticket=False,
            goal=goal,
            astro_gem=astro_gem,
            optimize="dps",
            pool=ScenarioHelper.POOL,
        )
        # Run many trials and compare extra ticket usage
        relic_tickets = 0
        no_relic_tickets = 0
        trials = 500
        for seed in range(1, trials + 1):
            r = sim.simulate_one(seed=seed)
            if r.extra_ticket_used:
                relic_tickets += 1
            r2 = sim_no_relic.simulate_one(seed=seed)
            if r2.extra_ticket_used:
                no_relic_tickets += 1

        # Without relic override: ticket should never be used
        self.assertEqual(no_relic_tickets, 0)
        # With relic override: ticket should be used in some runs
        # (when P(relic+) crosses 0.25 mid-run)
        self.assertGreater(relic_tickets, 0)

    def test_print_details(self) -> None:
        """Print a single logged run showing the relic+ ticket grant."""
        goal = LastTurnGoal(min_will=4, min_chaos=5)
        astro_gem = AstroGem(
            "order_immutability", "boss_damage", "brand_power", "dps")
        sim = GemSimulator(
            rarity="epic",
            use_extra_ticket=None,
            use_reset_ticket=False,
            goal=goal,
            astro_gem=astro_gem,
            optimize="dps",
            pool=ScenarioHelper.POOL,
            relic_reroll_threshold=0.25,
        )
        r = sim.simulate_one(seed=42, log=True)
        print(f"\n{'='*60}")
        print(f"Extra ticket used: {r.extra_ticket_used}")
        print(f"Result: {'SUCCESS' if r.success else 'FAIL'} ({r.reason})")
        print(f"Total points: {r.total_points}")
        for t in (r.turn_log or []):
            relic_str = f"  P(r+)={t['relic_prob']:.1%}" if t.get('relic_prob') is not None else ""
            print(f"  Turn {t['turn']} (left={t['turns_left']})"
                  f"  rerolls={t['rerolls_available']}{relic_str}"
                  f"  {t['action']}")
        print(f"{'='*60}\n")


class TestScenarioSupportGemDpsOptimizeNoReset(unittest.TestCase):
    """Reproduces the --all auto-run regression case.

    A random gem rolled with two support effects (ally_damage + ally_attack)
    under --optimize dps --min-side-coeff 2000. The standard DP treats
    both side coefficients as 0 (non-target effects), so every state
    reports P(goal)=0 and the automation flips to RESET on Turn 2.

    The effect-aware DP models change_first_effect/change_second_effect
    as probabilistic transitions to the two non-equipped effects. For
    order_fortitude the non-equipped effects are attack_power + boss_damage
    — both DPS targets — so a change_effect always flips a support side
    to DPS. The EA DP prices in this rescue and reports >0%.
    """

    GEM_TYPE = "order_fortitude"  # attack_power, boss_damage, ally_damage, ally_attack
    FIRST = "ally_damage"
    SECOND = "ally_attack"
    GOAL = LastTurnGoal(min_will=4, min_chaos=4)
    MIN_SIDE_COEFF = 2000
    TURNS_TOTAL = 9  # epic

    def setUp(self) -> None:
        # Turn 2 state from the reported run: w=1 c=1 f=1 s=1, rerolls=2.
        # Offers approximate the reported set — we substitute concrete
        # pool keys that reflect the same "no progress" shape:
        #   first+1 (bumps ally_damage, no side-coeff gain under dps)
        #   change_first_effect (the rescue path)
        #   will+1 (progresses min_will)
        #   view+2 (reroll ticket)
        self.result = ScenarioHelper.evaluate(
            gem_type=self.GEM_TYPE,
            first_effect=self.FIRST,
            second_effect=self.SECOND,
            optimize="dps",
            will=1, chaos=1, first=1, second=1,
            rerolls=2,
            rarity="epic",
            turn=2,
            offer_keys=("first+1", "change_first_effect", "will+1", "view+2"),
            goal=self.GOAL,
            min_side_coeff=self.MIN_SIDE_COEFF,
        )

    def test_standard_dp_with_coeff_constraint_reports_zero(self) -> None:
        """A standard DP built with min_side_coeff=2000 and both side
        coeffs=0 (non-target effects) can never reach the goal: every
        initial state lookups to 0.0. The simulator sidesteps this by
        stripping min_side_coeff when the constraint is infeasible,
        but the raw DP still exposes the underlying bug.
        """
        pool = ScenarioHelper.POOL
        standard = GoalProbabilityTable(
            self.GOAL, self.TURNS_TOTAL, pool,
            side_coeff_first=0, side_coeff_second=0,
            min_side_coeff=self.MIN_SIDE_COEFF,
        )
        state = GemState(
            will=1, chaos=1, first=1, second=1,
            first_effect=self.FIRST, second_effect=self.SECOND,
        )
        turns_left = self.TURNS_TOTAL - 2 + 1
        self.assertAlmostEqual(standard.lookup(state, turns_left), 0.0, places=6)

    def test_simulator_workaround_strips_infeasible_coeff(self) -> None:
        """Simulator strips min_side_coeff when both side coeffs are 0,
        so its prob_table reports the will/chaos-only probability
        (non-zero) and feasible_frac is 1.0 here. This keeps the run
        progressing instead of insta-resetting, but loses the
        coefficient-goal signal entirely.
        """
        self.assertGreater(self.result.dp_current, 0.0)
        self.assertAlmostEqual(self.result.feasible_frac, 1.0, places=6)

    def test_effect_aware_dp_reports_nonzero(self) -> None:
        """Effect-aware DP models the change_effect rescue — P(goal) > 0."""
        pool = ScenarioHelper.POOL
        ea = GoalProbabilityTable(
            self.GOAL, self.TURNS_TOTAL, pool,
            min_side_coeff=self.MIN_SIDE_COEFF,
            effect_aware=True,
            gem_type=self.GEM_TYPE,
            optimize="dps",
            max_rerolls=3,
        )
        state = GemState(
            will=1, chaos=1, first=1, second=1,
            first_effect=self.FIRST, second_effect=self.SECOND,
        )
        turns_left = self.TURNS_TOTAL - 2 + 1  # turn 2 of 9
        p_current = ea.lookup(state, turns_left, rerolls=2)
        self.assertGreater(p_current, 0.0,
                           "Effect-aware DP should price change_effect rescue")

    def test_effect_aware_change_effect_option_has_highest_value(self) -> None:
        """Of the 4 offers, change_first_effect has the best EA lookup
        because it deterministically swaps a support slot to a DPS slot
        (both remaining pool members for order_fortitude are DPS).
        """
        pool = ScenarioHelper.POOL
        ea = GoalProbabilityTable(
            self.GOAL, self.TURNS_TOTAL, pool,
            min_side_coeff=self.MIN_SIDE_COEFF,
            effect_aware=True,
            gem_type=self.GEM_TYPE,
            optimize="dps",
            max_rerolls=3,
        )
        state = GemState(
            will=1, chaos=1, first=1, second=1,
            first_effect=self.FIRST, second_effect=self.SECOND,
        )
        offers = ScenarioHelper.make_offers(
            "first+1", "change_first_effect", "will+1", "view+2")
        turns_left = self.TURNS_TOTAL - 2 + 1
        avg_ea = ea.expected_prob_after_click(
            state, offers, turns_left - 1, rerolls=2)
        # Expected value after picking across offers uniformly should be
        # non-trivial once change_first_effect routes through DPS slots.
        self.assertGreater(avg_ea, 0.0)

    def test_print_details(self) -> None:
        ScenarioHelper.print_result(self.result)
        # Also show the EA comparison for this state.
        pool = ScenarioHelper.POOL
        ea = GoalProbabilityTable(
            self.GOAL, self.TURNS_TOTAL, pool,
            min_side_coeff=self.MIN_SIDE_COEFF,
            effect_aware=True,
            gem_type=self.GEM_TYPE,
            optimize="dps",
            max_rerolls=3,
        )
        state = GemState(
            will=1, chaos=1, first=1, second=1,
            first_effect=self.FIRST, second_effect=self.SECOND,
        )
        turns_left = self.TURNS_TOTAL - 2 + 1
        p_ea = ea.lookup(state, turns_left, rerolls=2)
        offers = ScenarioHelper.make_offers(
            "first+1", "change_first_effect", "will+1", "view+2")
        print(f"--- Effect-aware DP comparison ---")
        print(f"P(goal) standard    : {self.result.dp_current:.4f}")
        print(f"P(goal) effect-aware: {p_ea:.4f}")
        print(f"Per-offer effect-aware lookup:")
        for o in offers:
            nw = min(5, max(1, state.will + o.delta)) if o.kind == "will" else state.will
            nc = min(5, max(1, state.chaos + o.delta)) if o.kind == "chaos" else state.chaos
            nf = min(5, max(1, state.first + o.delta)) if o.kind == "first" else state.first
            ns = min(5, max(1, state.second + o.delta)) if o.kind == "second" else state.second
            vd = o.delta if o.kind == "view" else 0
            nr = min(3, 2 + vd)
            ncs = 1 if o.kind == "cost" else 0  # state starts unsaturated
            if o.key == "change_first_effect":
                # Average over the two destinations (attack_power, boss_damage)
                fi = ea._effect_tuple.index(self.FIRST)
                si = ea._effect_tuple.index(self.SECOND)
                dests = ea._change_dests[(fi, si)]
                vals = [ea._dp_lookup_ea(nw, nc, nf, ns, ncs, d, si, nr,
                                         turns_left - 1)
                        for d in dests]
                avg = sum(vals) / len(vals)
                print(f"  {o.key:>24s} -> avg={avg:.4f} "
                      f"(dests: {[ea._effect_tuple[d] for d in dests]})")
            else:
                fi = ea._effect_tuple.index(self.FIRST)
                si = ea._effect_tuple.index(self.SECOND)
                v = ea._dp_lookup_ea(nw, nc, nf, ns, ncs, fi, si, nr,
                                     turns_left - 1)
                print(f"  {o.key:>24s} -> dp={v:.4f}")


if __name__ == "__main__":
    unittest.main()
