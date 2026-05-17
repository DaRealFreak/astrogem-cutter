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
    _side_coeff, _legal_actions,
)
from arkgrid.decision import TurnMetrics, _side_value_finish_decision
from arkgrid.models import GemState, LastTurnGoal, Option
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable, SideValueTable


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
    endgame_risk: float = 0.0,
    relic_coeff: int = 0,
    ancient_coeff: int = 0,
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
    side_value_table = SideValueTable(
        g, turns_total, _POOL, gem_type=gem_type, optimize=optimize,
        min_side_coeff=min_side_coeff,
        relic_coeff=relic_coeff, ancient_coeff=ancient_coeff,
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
        side_value_table=side_value_table,
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

    def test_legal_actions_filters(self):
        ti = build_ti(rerolls=0, reset_available=False)
        self.assertEqual(_legal_actions(ti),
                         (ActionKind.FINISH, ActionKind.PROCESS))
        ti2 = build_ti(rerolls=2, reset_available=True)
        self.assertEqual(_legal_actions(ti2),
                         (ActionKind.FINISH, ActionKind.PROCESS,
                          ActionKind.REROLL, ActionKind.RESET))


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


class TestSideValueFinish(unittest.TestCase):
    """Task 4: _side_value_finish_decision — the turns-aware finish."""

    def _ctx(self, **kw):
        kw.setdefault("gem_type", "order_fortitude")
        kw.setdefault("optimize", "dps")
        kw.setdefault("goal", LastTurnGoal(min_will=4, min_chaos=4))
        kw.setdefault("relic_no_early_finish", 0.0)
        return build_ctx(**kw)

    def test_played_out_gem_last_turn_finishes(self):
        # Goal met, sides capped, last turn, no offer can help -> FINISH.
        ctx = self._ctx()
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_improvable_gem_continues(self):
        # Goal met early, side nodes low, turns left -> continuing wins,
        # decision defers (None -> PROCESS via the tree).
        ctx = self._ctx()
        st = GemState(will=4, chaos=4, first=2, second=2,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("first+1", "second+1",
                                         "will+1", "chaos+1"),
                      turn=3, turns_left=7, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_no_side_value_table_never_finishes(self):
        # Gem type unknown -> table disabled -> no early finish.
        ctx = self._ctx(gem_type="")
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_goal_not_met_returns_none(self):
        ctx = self._ctx()
        st = GemState(will=2, chaos=2, first=3, second=3,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st, turn=9, turns_left=1, rerolls=0,
                      reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_free_reroll_preferred_over_finish(self):
        # Played-out last turn but a reroll is free -> REROLL, not FINISH.
        ctx = self._ctx()
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=8, turns_left=2, rerolls=2, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.REROLL)

    def test_gate_on_above_floor_prompts_on_finish(self):
        # Confirm gate active, valuable gem, finish call -> F1-F4 prompt.
        ctx = self._ctx(confirm_min_coeff=1000)
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertTrue(d.needs_confirmation)
        self.assertIn(ActionKind.PROCESS, d.confirm_choices)

    def test_gate_on_below_floor_finishes_silently(self):
        ctx = self._ctx(confirm_min_coeff=999999)
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)


if __name__ == "__main__":
    unittest.main()
