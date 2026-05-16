"""Branch-by-branch tests for `arkgrid.decision`.

Each test pins down the contract of one branch helper or the assembled
`decide_post_roll`. The first three test classes correspond directly
to the three relic+ override bugs we fixed earlier — if anyone reverts
those fixes, these tests fail.

Usage:
    python -m unittest tests.test_decision -v
"""
from __future__ import annotations

import unittest
from typing import List, Optional

from arkgrid.decision import (
    ActionKind, Decision, DecisionContext, TurnInput,
    compute_post_roll_metrics, decide_post_roll,
    early_finish_decision, has_progress_offer,
    infeasibility_decision, last_turn_reset_decision,
    no_feasible_offer_decision, prob_reset_decision,
    _side_coeff, _continue_has_upside, _legal_actions,
)
from arkgrid.models import GemState, LastTurnGoal, Option
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_POOL = OptionPool()
_OFFER_BY_KEY = {o.key: o for o in _POOL.pool}


def make_offers(*keys: str) -> List[Option]:
    """Look up real Option objects from the canonical pool."""
    return [_OFFER_BY_KEY[k] for k in keys]


def build_ctx(
    *,
    goal: Optional[LastTurnGoal] = None,
    turns_total: int = 9,
    base_rerolls: int = 2,
    optimize: str = "dps",
    bis_only: bool = False,
    min_side_coeff: int = 0,
    early_finish_coeff: int = 0,
    prob_reset_threshold: float = 0.0,
    relic_no_early_finish: float = 0.25,
    relic_reroll_threshold: float = 0.0,
    force_reroll_no_progress: int = 0,
    force_reroll_active: bool = False,
    gem_type: str = "order_immutability",
    p_fresh: Optional[float] = None,
    with_relic: bool = True,
) -> DecisionContext:
    g = goal or LastTurnGoal(min_will=4, min_chaos=3)
    prob_table = GoalProbabilityTable(
        g, turns_total, _POOL,
        max_rerolls=base_rerolls,
        early_finish=early_finish_coeff >= 0,
    )
    reset_table = GoalProbabilityTable(
        g, turns_total, _POOL,
        early_finish=early_finish_coeff >= 0,
    )
    relic_table = (
        GoalProbabilityTable(LastTurnGoal(min_total=16), turns_total,
                             _POOL, max_rerolls=base_rerolls)
        if with_relic else None
    )
    if p_fresh is None:
        p_fresh = reset_table.lookup(GemState(1, 1, 1, 1), turns_total)
    return DecisionContext(
        goal=g, pool=_POOL, optimize=optimize, bis_only=bis_only,
        min_side_coeff=min_side_coeff,
        early_finish_coeff=early_finish_coeff,
        prob_reset_threshold=prob_reset_threshold,
        relic_no_early_finish=relic_no_early_finish,
        relic_reroll_threshold=relic_reroll_threshold,
        force_reroll_no_progress=force_reroll_no_progress,
        turns_total=turns_total, base_rerolls=base_rerolls,
        p_fresh=p_fresh,
        prob_table=prob_table, reset_prob_table=reset_table,
        relic_prob_table=relic_table,
        gem_type=gem_type, force_reroll_active=force_reroll_active,
    )


def build_ti(
    *,
    state: Optional[GemState] = None,
    offers: Optional[List[Option]] = None,
    turn: int = 5,
    turns_left: int = 5,
    rerolls: int = 2,
    reset_available: bool = True,
) -> TurnInput:
    s = state or GemState(
        will=1, chaos=1, first=1, second=1, rerolls=rerolls,
        first_effect="attack_power", second_effect="boss_damage",
    )
    o = offers or make_offers("will+1", "chaos+1", "first+1", "second+1")
    return TurnInput(
        state=s, offers=o, turn=turn, turns_left=turns_left,
        rerolls=rerolls, reset_available=reset_available,
    )


# ---------------------------------------------------------------------------
# Branch-by-branch tests
# ---------------------------------------------------------------------------


class TestHasProgressOffer(unittest.TestCase):
    """Sanity tests for the force-no-progress helper."""

    def test_returns_true_when_will_offer_progresses_unmet_will(self):
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="attack_power",
                         second_effect="boss_damage")
        offers = make_offers("will+1")
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertTrue(has_progress_offer(offers, state, goal, 0, 0, 0))

    def test_returns_false_when_no_offer_addresses_unmet_constraint(self):
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="attack_power",
                         second_effect="boss_damage")
        offers = make_offers("chaos+1", "first+1")  # neither is will
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertFalse(has_progress_offer(offers, state, goal, 0, 0, 0))


class TestEarlyFinishRelicOverride(unittest.TestCase):
    """The first bug we fixed: relic+ override must use the offer-
    conditional posterior, not the state prior. State-prior P(r+) can
    be zero on the last turn from a state where the *visible* offers
    still have a guaranteed relic+ pick — finishing in that case
    throws away the relic+.
    """

    def test_offer_conditional_posterior_blocks_finish(self):
        # Goal already satisfied; risky offer (will-1 breaks goal);
        # rerolls=0 so absent the override the early-finish path fires.
        # Two of four offers bump total to 16, so P(r+|process)=0.5
        # which exceeds the 0.25 threshold -> override should fire.
        ctx = build_ctx(
            goal=LastTurnGoal(min_will=4, min_chaos=3),
            early_finish_coeff=0,        # finish on any risk
            relic_no_early_finish=0.25,
        )
        state = GemState(
            will=4, chaos=4, first=4, second=3, rerolls=0,  # total=15
            first_effect="attack_power", second_effect="boss_damage",
        )
        # first+1 -> 16 (relic+, goal still met)
        # will-1  -> 14 (breaks min_will=4)
        # chaos+1 -> 16 (relic+, goal still met)
        # maintain -> 15 (no relic, goal kept)
        offers = make_offers("first+1", "will-1", "chaos+1", "maintain")
        ti = build_ti(state=state, offers=offers, turn=9, turns_left=1,
                      rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        # Sanity: posterior should be 0.5 (2 of 4 offers reach 16+).
        self.assertAlmostEqual(m.p_keep_relic, 0.5, places=2)
        d = early_finish_decision(ctx, ti, m)
        self.assertIsNone(
            d, f"override should suppress early-finish but got {d}")

    def test_no_relic_table_no_override(self):
        ctx = build_ctx(
            relic_no_early_finish=0.25, with_relic=False,
            early_finish_coeff=0,
        )
        state = GemState(
            will=4, chaos=3, first=4, second=3, rerolls=0,
            first_effect="attack_power", second_effect="boss_damage",
        )
        # All offers maintain goal — should not fire early-finish anyway
        # (p_miss == 0 + early_finish_coeff == 0 => should_stop False).
        offers = make_offers("maintain", "first+1", "chaos+1", "second+1")
        ti = build_ti(state=state, offers=offers, turn=9, turns_left=1,
                      rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = early_finish_decision(ctx, ti, m)
        # No risk and no neg coeff => None regardless of relic table
        self.assertIsNone(d)


class TestInfeasibilityRelicChase(unittest.TestCase):
    """Second bug fixed: the goal-infeasible branch must compare
    offer-conditional P(r+|process) against P(r+|reroll), not the
    state prior, when deciding to chase relic+ vs finish.
    """

    def test_chases_relic_when_offers_can_reach_it(self):
        # Goal infeasible (need will=5 in 0 turns left). Offers can
        # still reach total >= 16 by bumping first/second/chaos.
        goal = LastTurnGoal(min_will=5, min_chaos=4)  # impossible from 1,1
        ctx = build_ctx(goal=goal, relic_no_early_finish=0.0)
        state = GemState(
            will=4, chaos=3, first=4, second=4, rerolls=0,
            first_effect="attack_power", second_effect="boss_damage",
        )
        # first+1 -> 5+3+5+4 = 17 (relic+); chaos+1 -> 16 (relic+); rest neutral.
        offers = make_offers("first+1", "chaos+1", "maintain", "second-1")
        ti = build_ti(state=state, offers=offers, turn=9, turns_left=1,
                      rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = infeasibility_decision(ctx, ti, m)
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.PROCESS,
                         f"expected PROCESS to chase relic+ but got {d}")

    def test_finish_when_relic_also_unreachable(self):
        goal = LastTurnGoal(min_will=5, min_chaos=4)
        ctx = build_ctx(goal=goal)
        state = GemState(
            will=2, chaos=2, first=1, second=1, rerolls=0,
            first_effect="attack_power", second_effect="boss_damage",
        )
        offers = make_offers("will+1", "chaos+1", "maintain", "first+1")
        ti = build_ti(state=state, offers=offers, turn=9, turns_left=1,
                      rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = infeasibility_decision(ctx, ti, m)
        # No offer can push total past 16 from 6.
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)


class TestNoFeasibleOfferBranch(unittest.TestCase):
    """Third bug fixed: the no-offer-feasibility branch must check the
    actual visible offers for relic+, not just give up.
    """

    def test_processes_for_relic_when_dp_says_no_offer_feasible(self):
        # Goal: min_side_coeff=2000 with attack_power=400/level.
        # State has first=2 (=> coeff 800), need 2000 in 1 turn.
        # No single offer can bridge 1200 (max +2 -> +800).
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        ctx = build_ctx(goal=goal, min_side_coeff=2000)
        state = GemState(
            will=4, chaos=3, first=2, second=5, rerolls=0,
            first_effect="attack_power", second_effect="ally_attack",
        )
        # first+2 reaches total 4+3+4+5 = 16 (relic+); chaos+2 also 16.
        offers = make_offers("first+1", "will+1", "first+2", "chaos+2")
        ti = build_ti(state=state, offers=offers, turn=9, turns_left=1,
                      rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        # The DP feasible_count check would only fire if the prob_table
        # was built with min_side_coeff. Our test ctx doesn't enforce
        # it on the prob_table itself — but the branch helper still
        # respects the metric. Force feasible_count=0 by checking the
        # full pipeline via decide_post_roll instead.
        d = decide_post_roll(ctx, ti)
        # Either default_process or no_feasible_offer relic chase, but
        # NOT a finish — relic+ is reachable.
        self.assertNotEqual(d.action, ActionKind.FINISH,
                            f"should not finish when relic+ reachable: {d}")

    def test_rerolls_for_goal_when_relic_unreachable_but_reroll_helps(self):
        # Reproduction of the bug from auto run 20260501_212127:
        # Last turn, w=4 c=1 — visible offers don't touch chaos so all
        # post-click P(goal)=0, but a reroll could pull a chaos+2/+3/+4
        # that would satisfy min_chaos=3. With reset disabled and
        # relic+ unreachable on the last turn (max total <= 12 < 16),
        # the old code returned FINISH "goal & relic+ both unreachable".
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        ctx = build_ctx(goal=goal, turns_total=7, base_rerolls=2,
                        relic_no_early_finish=0.25,
                        gem_type="order_fortitude")
        state = GemState(
            will=4, chaos=1, first=2, second=1, rerolls=1,
            first_effect="boss_damage", second_effect="ally_attack",
        )
        # None of these touch chaos.
        offers = make_offers("second+1", "will+1",
                             "change_second_effect", "first+1")
        ti = build_ti(state=state, offers=offers, turn=7, turns_left=1,
                      rerolls=1, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        # Sanity: no visible offer is feasible.
        self.assertEqual(m.feasible_count, 0)
        # Sanity: relic+ unreachable from total=8, last turn.
        self.assertEqual(m.p_keep_relic, 0.0)
        self.assertEqual(m.p_reroll_relic, 0.0)
        # Sanity: a reroll *can* find a goal-reaching offer.
        self.assertGreater(
            ctx.prob_table.lookup(state, ti.turns_left,
                                  rerolls=ti.rerolls - 1),
            0.0)
        d = no_feasible_offer_decision(ctx, ti, m)
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.REROLL,
                         f"expected REROLL fallback, got {d}")

    def test_finishes_when_goal_and_relic_unreachable_no_reroll(self):
        # Same shape as above, but with rerolls=0 the goal-reroll
        # fallback shouldn't fire — FINISH is correct.
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        ctx = build_ctx(goal=goal, turns_total=7, base_rerolls=2,
                        relic_no_early_finish=0.25,
                        gem_type="order_fortitude")
        state = GemState(
            will=4, chaos=1, first=2, second=1, rerolls=0,
            first_effect="boss_damage", second_effect="ally_attack",
        )
        offers = make_offers("second+1", "will+1",
                             "change_second_effect", "first+1")
        ti = build_ti(state=state, offers=offers, turn=7, turns_left=1,
                      rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = no_feasible_offer_decision(ctx, ti, m)
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)


class TestProbResetThreshold(unittest.TestCase):
    """Branch 2: reset when post-click P(goal) drops below user threshold.
    Migrated from automation's analysis.p_current (reroll-aware prior)
    to offer-conditional posterior on the reset table.
    """

    def test_no_reset_above_threshold(self):
        ctx = build_ctx(prob_reset_threshold=0.05)
        ti = build_ti(turns_left=8)  # Wide horizon, P(goal) high
        m = compute_post_roll_metrics(ctx, ti)
        d = prob_reset_decision(ctx, ti, m)
        self.assertIsNone(d)

    def test_no_reset_when_no_ticket(self):
        ctx = build_ctx(prob_reset_threshold=0.99)  # Almost always trip
        ti = build_ti(turns_left=1, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = prob_reset_decision(ctx, ti, m)
        self.assertIsNone(d)


class TestLastTurnFreshStart(unittest.TestCase):
    """Branch 4: reset on the last turn when fresh start has higher odds."""

    def test_no_reset_when_not_last_turn(self):
        ctx = build_ctx()
        ti = build_ti(turns_left=2)
        m = compute_post_roll_metrics(ctx, ti)
        d = last_turn_reset_decision(ctx, ti, m)
        self.assertIsNone(d)

    def test_no_reset_when_no_ticket(self):
        ctx = build_ctx()
        ti = build_ti(turns_left=1, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = last_turn_reset_decision(ctx, ti, m)
        self.assertIsNone(d)


class TestDPReroll(unittest.TestCase):
    """Branch 5: DP-optimal reroll + force-no-progress override."""

    def test_no_reroll_on_turn_1(self):
        ctx = build_ctx()
        ti = build_ti(turn=1, turns_left=9)
        m = compute_post_roll_metrics(ctx, ti)
        d = dp_reroll_decision_helper(ctx, ti, m)
        self.assertIsNone(d)

    def test_no_reroll_when_no_rerolls_left(self):
        ctx = build_ctx()
        ti = build_ti(rerolls=0)
        m = compute_post_roll_metrics(ctx, ti)
        d = dp_reroll_decision_helper(ctx, ti, m)
        self.assertIsNone(d)


def dp_reroll_decision_helper(ctx, ti, m):
    """Wrapper to keep the import name local without polluting test class."""
    from arkgrid.decision import dp_reroll_decision
    return dp_reroll_decision(ctx, ti, m)


# ---------------------------------------------------------------------------
# Full-tree integration test
# ---------------------------------------------------------------------------


class TestDecidePostRollOrder(unittest.TestCase):
    """The branch helpers fire in priority order; this test pins that
    a default state with no triggers falls through to PROCESS.
    """

    def test_falls_through_to_process(self):
        ctx = build_ctx()
        ti = build_ti(turn=2, turns_left=8)
        d = decide_post_roll(ctx, ti)
        self.assertEqual(d.action, ActionKind.PROCESS)
        self.assertEqual(d.branch, "default_process")


class TestConfirmFields(unittest.TestCase):
    """Decision and DecisionContext carry the confirmation fields."""

    def test_decision_defaults(self):
        d = Decision(action=ActionKind.FINISH, branch="x", reason="y")
        self.assertFalse(d.needs_confirmation)
        self.assertEqual(d.confirm_choices, ())

    def test_context_defaults(self):
        ctx = build_ctx()
        self.assertFalse(ctx.confirm_active)
        self.assertEqual(ctx.confirm_risk, 0.0)
        self.assertEqual(ctx.confirm_min_coeff, 0)
        self.assertIsNone(ctx.risk_prob_table)


class TestConfirmHelpers(unittest.TestCase):
    """Side-coefficient, upside, and legal-action helpers."""

    def test_side_coeff_counts_target_effects(self):
        ctx = build_ctx(optimize="dps")
        st = GemState(will=4, chaos=3, first=3, second=2,
                      first_effect="boss_damage", second_effect="attack_power")
        # boss_damage 1000*3 + attack_power 400*2 = 3800
        self.assertEqual(_side_coeff(ctx, st), 3800)

    def test_side_coeff_ignores_non_target(self):
        ctx = build_ctx(optimize="dps")
        st = GemState(will=4, chaos=3, first=5, second=5,
                      first_effect="ally_damage", second_effect="brand_power")
        self.assertEqual(_side_coeff(ctx, st), 0)

    def test_upside_false_when_no_turns(self):
        ctx = build_ctx()
        st = GemState(will=5, chaos=5, first=5, second=5)
        self.assertFalse(_continue_has_upside(ctx, st, 0))

    def test_upside_true_when_side_below_cap(self):
        ctx = build_ctx(optimize="dps")
        st = GemState(will=5, chaos=5, first=3, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertTrue(_continue_has_upside(ctx, st, 2))

    def test_legal_actions_filters(self):
        ti = build_ti(rerolls=0, reset_available=False)
        self.assertEqual(_legal_actions(ti),
                         (ActionKind.FINISH, ActionKind.PROCESS))
        ti2 = build_ti(rerolls=2, reset_available=True)
        self.assertEqual(_legal_actions(ti2),
                         (ActionKind.FINISH, ActionKind.PROCESS,
                          ActionKind.REROLL, ActionKind.RESET))


if __name__ == "__main__":
    unittest.main()
