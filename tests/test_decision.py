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
from arkgrid.decision import TurnMetrics, _ev_cell, _relic_chase_active
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
    confirm_risk: Optional[float] = None,
    confirm_min_coeff: Optional[int] = None,
    endgame_risk: bool = False,
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
    confirm_active = (confirm_risk is not None
                      or confirm_min_coeff is not None)
    risk_table = (
        GoalProbabilityTable(g, turns_total, _POOL,
                             max_rerolls=base_rerolls, early_finish=False)
        if confirm_active else None
    )
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
        confirm_active=confirm_active,
        confirm_risk=confirm_risk if confirm_risk is not None else 0.0,
        confirm_min_coeff=(confirm_min_coeff
                           if confirm_min_coeff is not None else 0),
        risk_prob_table=risk_table,
        endgame_risk=endgame_risk,
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

    def test_change_first_effect_counts_as_progress_when_side_coeff_first_is_zero(self):
        """change_first_effect is progress when the current first effect contributes
        nothing to the side-coeff goal (side_coeff_first == 0).

        Scenario: --min-side-coeff run optimising DPS; first_effect is ally_attack
        (a support effect, coeff 0 for DPS), so it contributes nothing.
        The only non-negative offer is change_first_effect, which is the rescue
        move — without it the heuristic would force-reroll the offer away.
        """
        # first_effect="ally_attack" is not in DPS_EFFECTS -> side_coeff_first = 0
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="ally_attack",
                         second_effect="boss_damage")
        # Only useful offer is change_first_effect; the rest are negative deltas.
        offers = make_offers("change_first_effect", "will-1", "chaos-1", "second-1")
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        # min_side_coeff > 0, side_coeff_first = 0 (ally_attack has no DPS coeff),
        # side_coeff_second = 1000 (boss_damage).
        self.assertTrue(
            has_progress_offer(offers, state, goal,
                               min_side_coeff=2000,
                               side_coeff_first=0,
                               side_coeff_second=1000),
            "change_first_effect should be progress when first effect is not in "
            "the target set (side_coeff_first == 0) and min_side_coeff > 0",
        )

    def test_change_second_effect_counts_as_progress_when_side_coeff_second_is_zero(self):
        """Symmetric test for the second slot."""
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="boss_damage",
                         second_effect="ally_attack")
        offers = make_offers("change_second_effect", "will-1", "chaos-1", "first-1")
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertTrue(
            has_progress_offer(offers, state, goal,
                               min_side_coeff=2000,
                               side_coeff_first=1000,
                               side_coeff_second=0),
            "change_second_effect should be progress when second effect is not in "
            "the target set (side_coeff_second == 0) and min_side_coeff > 0",
        )

    def test_change_first_effect_not_progress_when_side_coeff_first_already_positive(self):
        """change_first_effect is NOT progress when first already contributes to the goal
        (side_coeff_first > 0) — changing it might downgrade the effect."""
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="boss_damage",
                         second_effect="attack_power")
        # Only offer is change_first_effect; side_coeff_first=1000 (boss_damage already contributing).
        offers = make_offers("change_first_effect", "will-1", "chaos-1", "second-1")
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertFalse(
            has_progress_offer(offers, state, goal,
                               min_side_coeff=2000,
                               side_coeff_first=1000,
                               side_coeff_second=400),
            "change_first_effect should NOT be progress when first effect already "
            "contributes to the goal (side_coeff_first > 0)",
        )

    def test_change_effect_not_progress_when_min_side_coeff_is_zero(self):
        """change_effect is not considered progress when --min-side-coeff is not set."""
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="ally_attack",
                         second_effect="boss_damage")
        offers = make_offers("change_first_effect", "will-1", "chaos-1", "second-1")
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        # min_side_coeff=0 -> change_effect should not count as progress
        self.assertFalse(
            has_progress_offer(offers, state, goal,
                               min_side_coeff=0,
                               side_coeff_first=0,
                               side_coeff_second=1000),
            "change_first_effect should NOT be progress when min_side_coeff == 0 "
            "(--min-side-coeff not set)",
        )

    def test_change_second_effect_not_progress_when_min_side_coeff_is_zero(self):
        """change_second_effect is not considered progress when --min-side-coeff is not set."""
        state = GemState(will=2, chaos=3, first=3, second=3,
                         first_effect="boss_damage",
                         second_effect="ally_attack")
        offers = make_offers("change_second_effect", "will-1", "chaos-1", "first-1")
        goal = LastTurnGoal(min_will=4, min_chaos=3)
        # min_side_coeff=0 -> change_second_effect should not count as progress
        self.assertFalse(
            has_progress_offer(offers, state, goal,
                               min_side_coeff=0,
                               side_coeff_first=1000,
                               side_coeff_second=0),
            "change_second_effect should NOT be progress when min_side_coeff == 0 "
            "(--min-side-coeff not set)",
        )


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


class TestGate1ConfirmFinish(unittest.TestCase):
    """Gate #1 — finish-vs-continue under --confirm-risk."""

    def _met_state(self):
        # Goal min_will=4/min_chaos=3 fully met, side nodes mid-level.
        return GemState(will=4, chaos=3, first=3, second=3,
                        first_effect="boss_damage",
                        second_effect="attack_power")

    def test_no_upside_finishes_silently(self):
        ctx = build_ctx(confirm_risk=0.1, optimize="dps")
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st, offers=make_offers("will+1", "chaos+1",
                                                   "first+1", "second+1"),
                      turn=8, turns_left=2)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_risky_valuable_needs_confirmation(self):
        # State: goal met exactly (will=4, chaos=3), few turns left and no
        # rerolls — every cut from this threshold state risks a -1 dropping
        # the gem below goal.  Measured DP risk at turns_left=1, rerolls=0:
        # ~7.5%, which comfortably clears a confirm_risk=0.05 threshold.
        # Side coefficient: boss_damage(1000)*3 + attack_power(400)*3 = 4200
        # which is above the 1000 floor, so confirmation must be required.
        ctx = build_ctx(confirm_risk=0.05, confirm_min_coeff=1000,
                        optimize="dps", relic_no_early_finish=0.0)
        st = self._met_state()
        ti = build_ti(state=st, offers=make_offers("will-1", "chaos-1",
                                                   "first+1", "second+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertTrue(d.needs_confirmation)
        self.assertIn(ActionKind.PROCESS, d.confirm_choices)

    def test_risky_cheap_finishes_silently(self):
        # Same risky state (turns_left=1, rerolls=0, risk ~7.5%) but
        # confirm_min_coeff is enormous so the gem's side_coeff (4200)
        # falls below the floor — no confirmation dialog, finish silently.
        ctx = build_ctx(confirm_risk=0.05, confirm_min_coeff=999999,
                        optimize="dps", relic_no_early_finish=0.0)
        st = self._met_state()
        ti = build_ti(state=st, offers=make_offers("will-1", "chaos-1",
                                                   "first+1", "second+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_feature_off_uses_legacy_path(self):
        # No confirm flags -> legacy --early-finish-coeff behavior.
        # Uses risky offers (will-1/chaos-1) so the legacy path fires.
        # With rerolls=0, the legacy path returns FINISH (not REROLL).
        ctx = build_ctx(early_finish_coeff=0)
        st = self._met_state()
        ti = build_ti(state=st, offers=make_offers("will-1", "chaos-1",
                                                   "first+1", "second+1"),
                      turn=8, turns_left=2, rerolls=0)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_continue_silently_when_risk_acceptable(self):
        # risk < confirm_risk -> None (continue silently).
        # Same risky met-goal state as test_risky_valuable_needs_confirmation
        # (turns_left=1, rerolls=0, measured risk ~7.5%), but with
        # confirm_risk=0.99 so 7.5% < 99% -> continue silently.
        ctx = build_ctx(confirm_risk=0.99, confirm_min_coeff=1000,
                        optimize="dps", relic_no_early_finish=0.0)
        st = self._met_state()
        ti = build_ti(state=st, offers=make_offers("will-1", "chaos-1",
                                                   "first+1", "second+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        d = early_finish_decision(ctx, ti, m)
        # risk ~7.5% < confirm_risk 99% -> continue silently (None)
        self.assertIsNone(d, f"should continue silently but got {d}")

    def test_relic_override_suppresses_confirm_finish(self):
        # The relic+ override inside _confirm_finish_decision keeps cutting
        # while relic+ (>=16) is still being chased. State total = 15 < 16
        # so _relic_chase_active applies; offers push toward 16 so
        # p_keep_relic clears the 0.25 threshold -> override returns None.
        ctx = build_ctx(confirm_risk=0.05, relic_no_early_finish=0.25,
                        optimize="dps")
        st = GemState(will=4, chaos=4, first=4, second=3,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st, offers=make_offers("first+1", "chaos+1",
                                                   "will+1", "second+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        m = compute_post_roll_metrics(ctx, ti)
        self.assertGreater(m.p_keep_relic, 0.25,
                           f"p_keep_relic={m.p_keep_relic} should exceed 0.25")
        d = early_finish_decision(ctx, ti, m)
        self.assertIsNone(d, f"relic+ override should suppress finish but got {d}")

    def test_change_effect_offer_does_not_force_finish(self):
        """Regression lock: a change_effect card in the offer set must NOT
        cause an instant finish via the confirmation gate.

        The OLD legacy --early-finish-coeff path had a bug where a
        change_effect offer drove avg_coeff_change negative and triggered
        a finish even when the goal was met and the player should continue.
        The new --confirm-risk path computes risk from the DP risk_prob_table
        and does not inspect the offer set's coefficient deltas at all, so it
        is immune by construction.  This test locks that in: with
        confirm_risk=0.99 (almost any risk is acceptable), the gate should
        return None (continue silently) even when a change_effect card appears
        in the offer set.
        """
        # confirm_risk=0.99 means the gate only fires when P(miss) >= 99%,
        # which cannot happen from a normal mid-run state -> gate returns None.
        ctx = build_ctx(confirm_risk=0.99, confirm_min_coeff=1000,
                        optimize="dps", relic_no_early_finish=0.0)
        # Goal min_will=4/min_chaos=3 fully met, side nodes mid-level.
        # boss_damage(1000)*3 + attack_power(400)*3 = 4200 >= 1000 floor.
        st = GemState(will=4, chaos=3, first=3, second=3,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        # Offer set deliberately includes a change_first_effect card alongside
        # normal progress offers — this is the shape that triggered the old bug.
        offers = make_offers("change_first_effect", "will+1", "chaos+1",
                             "second+1")
        ti = build_ti(state=st, offers=offers, turn=5, turns_left=5,
                      rerolls=2, reset_available=True)
        m = compute_post_roll_metrics(ctx, ti)
        # With confirm_risk=0.99 the DP risk (well below 99%) must not
        # trigger a finish — gate must return None (continue silently).
        d = early_finish_decision(ctx, ti, m)
        self.assertIsNone(
            d,
            f"change_effect offer must not force an instant finish "
            f"when risk < confirm_risk=0.99, got: {d}",
        )


class TestGate2And3Confirm(unittest.TestCase):
    """Gate #2 (infeasibility) and #3 (reset) stamp needs_confirmation."""

    def test_infeasible_valuable_needs_confirmation(self):
        ctx = build_ctx(goal=LastTurnGoal(min_will=5, min_chaos=5),
                        confirm_min_coeff=1000, optimize="dps")
        st = GemState(will=1, chaos=1, first=4, second=4,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st, offers=make_offers("will+1", "chaos+1",
                                                   "first+1", "second+1"),
                      turn=9, turns_left=1, reset_available=False)
        d = infeasibility_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertTrue(d.needs_confirmation)
        self.assertIn(ActionKind.FINISH, d.confirm_choices)

    def test_infeasible_cheap_unchanged(self):
        ctx = build_ctx(goal=LastTurnGoal(min_will=5, min_chaos=5),
                        confirm_min_coeff=999999, optimize="dps")
        st = GemState(will=1, chaos=1, first=1, second=1,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st, offers=make_offers("will+1", "chaos+1",
                                                   "first+1", "second+1"),
                      turn=9, turns_left=1, reset_available=False)
        d = infeasibility_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertFalse(d.needs_confirmation)

    def test_prob_reset_valuable_needs_confirmation(self):
        ctx = build_ctx(prob_reset_threshold=0.99, confirm_min_coeff=1000,
                        optimize="dps")
        st = GemState(will=1, chaos=1, first=4, second=4,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st, offers=make_offers("will+1", "chaos+1",
                                                   "first+1", "second+1"),
                      turn=2, turns_left=8, reset_available=True)
        d = prob_reset_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.RESET)
        self.assertTrue(d.needs_confirmation)

    def test_no_feasible_offer_valuable_needs_confirmation(self):
        # Gate #4: no_feasible_offer_decision must stamp needs_confirmation
        # when confirm is active and the gem's side coefficient clears the floor.
        #
        # State: will=1 (far from goal min_will=5), first=4, second=4 with
        # boss_damage+attack_power => side_coeff = 1000*4 + 400*4 = 5600 >= 1000.
        # turns_left=1 (last turn), so no offer can bridge will 1→5 in one step.
        # Offers will+1/will+2/will+3/chaos+1 all leave will < 5, so every
        # post-click state has P(goal)=0 => feasible_count == 0.
        # infeasibility_decision fires only on the loose feasible() upper-bound
        # check — with goal=min_will=5 and will=1, turns_left=1, feasible()
        # returns False, so infeasibility_decision WOULD fire here; we verify
        # the no_feasible_offer path independently with reset_available=True.
        ctx = build_ctx(goal=LastTurnGoal(min_will=5),
                        confirm_min_coeff=1000, optimize="dps")
        st = GemState(will=1, chaos=5, first=4, second=4,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will+1", "will+2", "will+3",
                                         "chaos+1"),
                      turn=9, turns_left=1, reset_available=True)
        m = compute_post_roll_metrics(ctx, ti)
        self.assertEqual(m.feasible_count, 0)  # branch precondition
        d = no_feasible_offer_decision(ctx, ti, m)
        self.assertIsNotNone(d)
        self.assertTrue(d.needs_confirmation)


class TestEarlyFinishZeroRiskNoStop(unittest.TestCase):
    """F10: when miss_count == 0 (zero goal risk), _legacy_early_finish_decision
    must never stop cutting — even if avg_coeff_change < 0 due to a
    change_effect offer.

    Scenario: early_finish_coeff=750, goal min_will=4 min_chaos=4 met exactly.
    Offers: change_first_effect (drives avg_coeff_change deeply negative),
    first+1, second+2, will+1 — none of these drops will/chaos below 4 so
    miss_count == 0.  The old elif branch (`avg_coeff_change < 0`) fired and
    returned FINISH, abandoning free points on a zero-risk gem.
    """

    def test_zero_risk_goal_met_does_not_finish_when_change_effect_skews_avg_coeff(self):
        # GemState: goal min_will=4/min_chaos=4 fully met.
        # first_effect=boss_damage (DPS, coeff=1000), second_effect=brand_power
        # (support, coeff=0 for DPS optimize) — brand_power not in DPS_EFFECTS
        # so second slot contributes nothing to DPS side-coeff.
        # order_immutability has (additional_damage, boss_damage, brand_power,
        # ally_attack) so both boss_damage and brand_power are valid effects.
        state = GemState(
            will=4, chaos=4, first=4, second=2,
            first_effect="boss_damage", second_effect="brand_power",
        )
        # goal: min_will=4, min_chaos=4 — met by the state above
        goal = LastTurnGoal(min_will=4, min_chaos=4)
        ctx = build_ctx(
            goal=goal,
            early_finish_coeff=750,
            optimize="dps",
            gem_type="order_immutability",
            turns_total=9,
            base_rerolls=2,
            relic_no_early_finish=0.0,   # disable relic override so only
                                          # the early-finish path is tested
        )
        # Offers: change_first_effect makes avg_coeff_change < 0
        # (loses boss_damage level-4 contribution = -4000), but no offer
        # drops will or chaos below 4, so miss_count == 0.
        offers = make_offers("change_first_effect", "first+1", "second+2", "will+1")
        ti = build_ti(
            state=state, offers=offers,
            turn=5, turns_left=5, rerolls=0, reset_available=False,
        )
        m = compute_post_roll_metrics(ctx, ti)
        # Sanity: change_first_effect loses boss_damage*4 = 4000 pts,
        # remaining 3 offers have non-negative deltas, so avg_coeff_change < 0.
        self.assertLess(m.avg_coeff_change, 0,
                        "avg_coeff_change should be negative (change_effect skew)")
        # Sanity: no offer drops will or chaos below 4, so miss_count == 0.
        self.assertEqual(m.miss_count, 0,
                         "no offer should break the goal (miss_count must be 0)")
        # The key assertion: zero goal-risk means we must NOT finish early.
        # F10 fix: the elif branch on avg_coeff_change is removed so this
        # returns None (keep cutting for free points).
        d = early_finish_decision(ctx, ti, m)
        self.assertIsNone(
            d,
            f"zero-risk met goal must not trigger early finish but got: {d}",
        )

    def test_zero_risk_early_finish_coeff_zero_does_not_finish(self):
        """With early_finish_coeff=0 (safe default) and miss_count==0, the
        function must return None — zero risk means no danger, so
        early-finish must not trigger regardless of the coeff threshold.
        """
        state = GemState(
            will=4, chaos=4, first=3, second=3,
            first_effect="boss_damage", second_effect="brand_power",
        )
        goal = LastTurnGoal(min_will=4, min_chaos=4)
        ctx = build_ctx(
            goal=goal,
            early_finish_coeff=0,   # safe default: stop whenever p_miss > 0
            optimize="dps",
            gem_type="order_immutability",
            turns_total=9,
            base_rerolls=2,
            relic_no_early_finish=0.0,  # disable relic override
        )
        # All four offers improve stats and none drops will/chaos below 4,
        # so miss_count == 0.
        offers = make_offers("will+1", "chaos+1", "first+1", "second+1")
        ti = build_ti(
            state=state, offers=offers,
            turn=5, turns_left=5, rerolls=0, reset_available=False,
        )
        m = compute_post_roll_metrics(ctx, ti)
        # Sanity: all offers are goal-safe.
        self.assertEqual(m.miss_count, 0,
                         "no offer should break the goal (miss_count must be 0)")
        # With p_miss == 0 the `should_stop` block is never entered,
        # so early_finish_decision returns None even when coeff threshold is 0.
        d = early_finish_decision(ctx, ti, m)
        self.assertIsNone(
            d,
            f"zero-risk with coeff=0 must not trigger early finish but got: {d}",
        )


class TestEvMetrics(unittest.TestCase):
    """Task 1: compute_post_roll_metrics produces accurate two-axis EV
    and improving/degrading offer counts."""

    def test_turn9_offer_set(self):
        # order_fortitude, boss_damage(first)/attack_power(second).
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        min_side_coeff=2000,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        state = GemState(will=5, chaos=5, first=5, second=4,
                         first_effect="boss_damage",
                         second_effect="attack_power")
        offers = make_offers("second+1", "chaos-1", "second-1",
                             "change_second_effect")
        m = compute_post_roll_metrics(ctx, build_ti(
            state=state, offers=offers, turn=9, turns_left=1,
            rerolls=0, reset_available=False))
        # second+1: +400, chaos-1: 0, second-1: -400,
        # change_second_effect: 4*(0-400) = -1600  ->  -1600/4
        self.assertAlmostEqual(m.avg_coeff_change, -400.0, places=3)
        # points: +1, -1, -1, 0  ->  -1/4
        self.assertAlmostEqual(m.ev_points, -0.25, places=3)
        # improving: second+1 only. degrading: chaos-1, second-1, EC.
        self.assertEqual(m.improving_count, 1)
        self.assertEqual(m.degrading_count, 3)

    def test_f10_offer_set(self):
        # change_first dest pool {additional_damage(700), ally_attack(0)}
        # -> mean 350; boss_damage current 1000; level 4 -> 4*(350-1000).
        ctx = build_ctx(gem_type="order_immutability", optimize="dps",
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        state = GemState(will=4, chaos=4, first=4, second=2,
                         first_effect="boss_damage",
                         second_effect="brand_power")
        offers = make_offers("change_first_effect", "first+1",
                             "second+2", "will+1")
        m = compute_post_roll_metrics(ctx, build_ti(
            state=state, offers=offers, turn=5, turns_left=5,
            rerolls=0, reset_available=False))
        self.assertAlmostEqual(m.avg_coeff_change, -400.0, places=3)
        self.assertAlmostEqual(m.ev_points, 1.0, places=3)
        # improving: first+1, second+2, will+1. degrading: change_first.
        self.assertEqual(m.improving_count, 3)
        self.assertEqual(m.degrading_count, 1)

    def test_capped_level_offer_is_neutral(self):
        # first/second already at 5: first+1 / second+1 are no-ops.
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps")
        state = GemState(will=5, chaos=5, first=5, second=5,
                         first_effect="boss_damage",
                         second_effect="attack_power")
        offers = make_offers("first+1", "second+1", "will-1", "chaos-1")
        m = compute_post_roll_metrics(ctx, build_ti(
            state=state, offers=offers, turn=9, turns_left=1,
            rerolls=0, reset_available=False))
        self.assertAlmostEqual(m.avg_coeff_change, 0.0, places=3)
        self.assertAlmostEqual(m.ev_points, -0.5, places=3)
        # first+1 / second+1 clamped -> neutral; will-1 / chaos-1 degrade.
        self.assertEqual(m.improving_count, 0)
        self.assertEqual(m.degrading_count, 2)


def _m(coeff, pts, improving, degrading):
    """Synthetic TurnMetrics carrying just the fields _ev_cell reads."""
    return TurnMetrics(0.0, 0.0, 0.0, 0.0, 0, 0,
                       coeff, pts, improving, degrading)


class TestEvCell(unittest.TestCase):
    """Task 2: the 3x3 (odds x EV) classifier."""

    def test_full_grid(self):
        # (improving, degrading): good>bad=(3,1), even=(2,2), good<bad=(1,3)
        cases = [
            # EV improves an axis -> always continue
            (_m(400.0, 1.0, 3, 1), "continue"),
            (_m(400.0, 0.0, 2, 2), "continue"),
            (_m(400.0, 0.0, 1, 3), "continue"),
            # EV ~= 0
            (_m(0.0, 0.0, 3, 1), "continue"),
            (_m(0.0, 0.0, 2, 2), "optin"),
            (_m(0.0, 0.0, 1, 3), "finish"),
            # EV net loss
            (_m(-400.0, -0.25, 3, 1), "optin"),
            (_m(-400.0, -0.25, 2, 2), "finish"),
            (_m(-400.0, -0.25, 1, 3), "finish"),
        ]
        for m, expected in cases:
            with self.subTest(coeff=m.avg_coeff_change, pts=m.ev_points,
                              imp=m.improving_count, deg=m.degrading_count):
                self.assertEqual(_ev_cell(m), expected)


class TestRelicChaseActive(unittest.TestCase):
    """Task 2: relic suppressor only fires below 16 points."""

    def _ti(self, total_state):
        return build_ti(state=total_state,
                        offers=make_offers("first+1", "chaos+1", "will+1",
                                           "second+1"),
                        turn=8, turns_left=2, rerolls=0,
                        reset_available=False)

    def test_inactive_when_relic_already_locked(self):
        ctx = build_ctx(relic_no_early_finish=0.25, gem_type="order_fortitude")
        ti = self._ti(GemState(will=5, chaos=5, first=5, second=4,
                               first_effect="boss_damage",
                               second_effect="attack_power"))
        self.assertFalse(_relic_chase_active(ctx, ti,
                                             compute_post_roll_metrics(ctx, ti)))

    def test_active_when_relic_still_chaseable(self):
        ctx = build_ctx(relic_no_early_finish=0.25, gem_type="order_fortitude")
        ti = self._ti(GemState(will=4, chaos=4, first=4, second=3,
                               first_effect="boss_damage",
                               second_effect="attack_power"))
        self.assertTrue(_relic_chase_active(ctx, ti,
                                            compute_post_roll_metrics(ctx, ti)))

    def test_inactive_when_feature_disabled(self):
        ctx = build_ctx(relic_no_early_finish=0.0, gem_type="order_fortitude")
        ti = self._ti(GemState(will=4, chaos=4, first=4, second=3,
                               first_effect="boss_damage",
                               second_effect="attack_power"))
        self.assertFalse(_relic_chase_active(ctx, ti,
                                             compute_post_roll_metrics(ctx, ti)))


class TestEvMetrics(unittest.TestCase):
    """Task 1: compute_post_roll_metrics produces accurate two-axis EV
    and improving/degrading offer counts."""

    def test_turn9_offer_set(self):
        # order_fortitude, boss_damage(first)/attack_power(second).
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        min_side_coeff=2000,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        state = GemState(will=5, chaos=5, first=5, second=4,
                         first_effect="boss_damage",
                         second_effect="attack_power")
        offers = make_offers("second+1", "chaos-1", "second-1",
                             "change_second_effect")
        m = compute_post_roll_metrics(ctx, build_ti(
            state=state, offers=offers, turn=9, turns_left=1,
            rerolls=0, reset_available=False))
        # second+1: +400, chaos-1: 0, second-1: -400,
        # change_second_effect: 4*(0-400) = -1600  ->  -1600/4
        self.assertAlmostEqual(m.avg_coeff_change, -400.0, places=3)
        # points: +1, -1, -1, 0  ->  -1/4
        self.assertAlmostEqual(m.ev_points, -0.25, places=3)
        # improving: second+1 only. degrading: chaos-1, second-1, EC.
        self.assertEqual(m.improving_count, 1)
        self.assertEqual(m.degrading_count, 3)

    def test_f10_offer_set(self):
        # change_first dest pool {additional_damage(700), ally_attack(0)}
        # -> mean 350; boss_damage current 1000; level 4 -> 4*(350-1000).
        ctx = build_ctx(gem_type="order_immutability", optimize="dps",
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        state = GemState(will=4, chaos=4, first=4, second=2,
                         first_effect="boss_damage",
                         second_effect="brand_power")
        offers = make_offers("change_first_effect", "first+1",
                             "second+2", "will+1")
        m = compute_post_roll_metrics(ctx, build_ti(
            state=state, offers=offers, turn=5, turns_left=5,
            rerolls=0, reset_available=False))
        self.assertAlmostEqual(m.avg_coeff_change, -400.0, places=3)
        self.assertAlmostEqual(m.ev_points, 1.0, places=3)
        # improving: first+1, second+2, will+1. degrading: change_first.
        self.assertEqual(m.improving_count, 3)
        self.assertEqual(m.degrading_count, 1)

    def test_capped_level_offer_is_neutral(self):
        # first/second already at 5: first+1 / second+1 are no-ops.
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps")
        state = GemState(will=5, chaos=5, first=5, second=5,
                         first_effect="boss_damage",
                         second_effect="attack_power")
        offers = make_offers("first+1", "second+1", "will-1", "chaos-1")
        m = compute_post_roll_metrics(ctx, build_ti(
            state=state, offers=offers, turn=9, turns_left=1,
            rerolls=0, reset_available=False))
        self.assertAlmostEqual(m.avg_coeff_change, 0.0, places=3)
        self.assertAlmostEqual(m.ev_points, -0.5, places=3)
        # first+1 / second+1 clamped -> neutral; will-1 / chaos-1 degrade.
        self.assertEqual(m.improving_count, 0)
        self.assertEqual(m.degrading_count, 2)


def _m(coeff, pts, improving, degrading):
    """Synthetic TurnMetrics carrying just the fields _ev_cell reads."""
    return TurnMetrics(0.0, 0.0, 0.0, 0.0, 0, 0,
                       coeff, pts, improving, degrading)


class TestEvCell(unittest.TestCase):
    """Task 2: the 3x3 (odds x EV) classifier."""

    def test_full_grid(self):
        # (improving, degrading): good>bad=(3,1), even=(2,2), good<bad=(1,3)
        cases = [
            # EV improves an axis -> always continue
            (_m(400.0, 1.0, 3, 1), "continue"),
            (_m(400.0, 0.0, 2, 2), "continue"),
            (_m(400.0, 0.0, 1, 3), "continue"),
            # EV ~= 0
            (_m(0.0, 0.0, 3, 1), "continue"),
            (_m(0.0, 0.0, 2, 2), "optin"),
            (_m(0.0, 0.0, 1, 3), "finish"),
            # EV net loss
            (_m(-400.0, -0.25, 3, 1), "optin"),
            (_m(-400.0, -0.25, 2, 2), "finish"),
            (_m(-400.0, -0.25, 1, 3), "finish"),
        ]
        for m, expected in cases:
            with self.subTest(coeff=m.avg_coeff_change, pts=m.ev_points,
                              imp=m.improving_count, deg=m.degrading_count):
                self.assertEqual(_ev_cell(m), expected)


class TestRelicChaseActive(unittest.TestCase):
    """Task 2: relic suppressor only fires below 16 points."""

    def _ti(self, total_state):
        return build_ti(state=total_state,
                        offers=make_offers("first+1", "chaos+1", "will+1",
                                           "second+1"),
                        turn=8, turns_left=2, rerolls=0,
                        reset_available=False)

    def test_inactive_when_relic_already_locked(self):
        ctx = build_ctx(relic_no_early_finish=0.25, gem_type="order_fortitude")
        ti = self._ti(GemState(will=5, chaos=5, first=5, second=4,
                               first_effect="boss_damage",
                               second_effect="attack_power"))
        self.assertFalse(_relic_chase_active(ctx, ti,
                                             compute_post_roll_metrics(ctx, ti)))

    def test_active_when_relic_still_chaseable(self):
        ctx = build_ctx(relic_no_early_finish=0.25, gem_type="order_fortitude")
        ti = self._ti(GemState(will=4, chaos=4, first=4, second=3,
                               first_effect="boss_damage",
                               second_effect="attack_power"))
        self.assertTrue(_relic_chase_active(ctx, ti,
                                            compute_post_roll_metrics(ctx, ti)))

    def test_inactive_when_feature_disabled(self):
        ctx = build_ctx(relic_no_early_finish=0.0, gem_type="order_fortitude")
        ti = self._ti(GemState(will=4, chaos=4, first=4, second=3,
                               first_effect="boss_damage",
                               second_effect="attack_power"))
        self.assertFalse(_relic_chase_active(ctx, ti,
                                             compute_post_roll_metrics(ctx, ti)))


class TestLegacyEvCell(unittest.TestCase):
    """Task 3: gate-off wiring of _ev_cell in _legacy_early_finish_decision."""

    def _turn9(self, rerolls, turns_left=1, turn=9):
        # 1 good / 3 bad, net loss -> 'finish' cell.
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        min_side_coeff=2000, early_finish_coeff=0,
                        relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        state = GemState(will=5, chaos=5, first=5, second=4,
                         first_effect="boss_damage",
                         second_effect="attack_power")
        ti = build_ti(state=state,
                      offers=make_offers("second+1", "chaos-1", "second-1",
                                         "change_second_effect"),
                      turn=turn, turns_left=turns_left, rerolls=rerolls,
                      reset_available=False)
        return ctx, ti

    def test_finish_cell_last_turn_finishes(self):
        ctx, ti = self._turn9(rerolls=0)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)

    def test_finish_cell_rerolls_when_rerolls_remain(self):
        ctx, ti = self._turn9(rerolls=2)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertEqual(d.action, ActionKind.REROLL)

    def test_finish_cell_mid_run_no_rerolls_defers(self):
        ctx, ti = self._turn9(rerolls=0, turns_left=4, turn=6)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_finish_cell_ignores_endgame_risk_flag(self):
        # A 'finish' cell finishes even with --endgame-risk set.
        ctx, ti = self._turn9(rerolls=0)
        ctx.endgame_risk = True
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertEqual(d.action, ActionKind.FINISH)

    def _coinflip(self, endgame_risk):
        # 2 good / 2 bad, EV 0 on both axes -> 'optin' cell.
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        early_finish_coeff=0, relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4),
                        endgame_risk=endgame_risk)
        state = GemState(will=5, chaos=5, first=3, second=3,
                         first_effect="boss_damage",
                         second_effect="boss_damage")
        ti = build_ti(state=state,
                      offers=make_offers("first+1", "second+1", "first-1",
                                         "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        return ctx, ti

    def test_optin_cell_finishes_without_flag(self):
        ctx, ti = self._coinflip(endgame_risk=False)
        m = compute_post_roll_metrics(ctx, ti)
        self.assertAlmostEqual(m.avg_coeff_change, 0.0, places=3)
        self.assertAlmostEqual(m.ev_points, 0.0, places=3)
        d = early_finish_decision(ctx, ti, m)
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)

    def test_optin_cell_continues_with_flag(self):
        ctx, ti = self._coinflip(endgame_risk=True)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)


class TestConfirmEvCell(unittest.TestCase):
    """Task 4: gate-on wiring of _ev_cell in _confirm_finish_decision."""

    def test_finish_cell_finishes_silently(self):
        # turn 9 'finish' cell, gate on -> silent finish (no prompt).
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        min_side_coeff=2000, confirm_risk=0.05,
                        confirm_min_coeff=1000, relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        st = GemState(will=5, chaos=5, first=5, second=4,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("second+1", "chaos-1", "second-1",
                                         "change_second_effect"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_optin_cell_prompts(self):
        # coinflip 'optin' cell, gate on, last turn -> F1-F4 prompt.
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        confirm_risk=0.05, confirm_min_coeff=1000,
                        relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        st = GemState(will=5, chaos=5, first=3, second=3,
                      first_effect="boss_damage",
                      second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("first+1", "second+1", "first-1",
                                         "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertTrue(d.needs_confirmation)
        self.assertIn(ActionKind.PROCESS, d.confirm_choices)

    def test_optin_cell_below_coeff_floor_finishes_silently(self):
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        confirm_risk=0.05, confirm_min_coeff=999999,
                        relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        st = GemState(will=5, chaos=5, first=3, second=3,
                      first_effect="boss_damage",
                      second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("first+1", "second+1", "first-1",
                                         "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_stop_cell_rerolls_when_rerolls_remain(self):
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        min_side_coeff=2000, confirm_risk=0.05,
                        confirm_min_coeff=1000, relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        st = GemState(will=5, chaos=5, first=5, second=4,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("second+1", "chaos-1", "second-1",
                                         "change_second_effect"),
                      turn=9, turns_left=1, rerolls=2, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertEqual(d.action, ActionKind.REROLL)
        self.assertFalse(d.needs_confirmation)

    def test_stop_cell_mid_run_no_rerolls_defers(self):
        ctx = build_ctx(gem_type="order_fortitude", optimize="dps",
                        min_side_coeff=2000, confirm_risk=0.05,
                        confirm_min_coeff=1000, relic_no_early_finish=0.0,
                        goal=LastTurnGoal(min_will=4, min_chaos=4))
        st = GemState(will=5, chaos=5, first=5, second=4,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("second+1", "chaos-1", "second-1",
                                         "change_second_effect"),
                      turn=6, turns_left=4, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)


if __name__ == "__main__":
    unittest.main()
