"""Regression tests for the 2026-11 probability-model fixes.

* exact applied probabilities (4 offers drawn without replacement, one applied)
  instead of the single-draw `weight / total` approximation;
* hand-level reroll model (keep-vs-reroll is decided on the 4-offer hand, not
  per option) in the reroll-aware goal DP;
* reroll-aware fresh-start value and reset-threshold posterior;
* the same hand model in the reroll-aware side-value table;
* relic/ancient tables count a gem that already holds the grade as secured.
"""
from __future__ import annotations

import itertools
import random
import unittest

from arkgrid.constants import DPS_COEFF, GEM_TYPES, change_dest_coeffs
from arkgrid.decision import ActionKind, TurnInput, decide_post_roll
from arkgrid.models import AstroGem, GemState, LastTurnGoal
from arkgrid.pool import OptionPool
from arkgrid.probability import (
    GoalProbabilityTable, SideValueTable, _hand_moments, _hand_turn_value,
    applied_probs, hand_context,
)
from arkgrid.simulator import GemSimulator


def _brute_force_applied(weights):
    """P(option i is the applied one): enumerate every ordered 4-draw."""
    n = len(weights)
    total = sum(weights)
    incl = [0.0] * n
    for order in itertools.permutations(range(n), 4):
        p = 1.0
        rem = total
        for i in order:
            p *= weights[i] / rem
            rem -= weights[i]
        for i in order:
            incl[i] += p
    return [x / 4 for x in incl]


class TestAppliedProbs(unittest.TestCase):
    WEIGHTS = [11.65, 11.65, 4.4, 3.0, 1.75, 0.45, 3.25, 2.5]

    def test_matches_brute_force_enumeration(self) -> None:
        got = applied_probs(self.WEIGHTS)
        want = _brute_force_applied(self.WEIGHTS)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=12)

    def test_sums_to_one(self) -> None:
        pool = OptionPool()
        state = GemState(will=3, chaos=2, first=5, second=1)
        weights = [o.weight for o in pool.pool
                   if pool.eligible(o, state, 3, 5)]
        self.assertAlmostEqual(sum(applied_probs(weights)), 1.0, places=12)

    def test_heavy_options_are_applied_less_often_than_their_weight_share(self) -> None:
        # A heavy option can only occupy one of the four slots, so its
        # applied probability is below weight/total; a light one is above.
        probs = applied_probs(self.WEIGHTS)
        total = sum(self.WEIGHTS)
        self.assertLess(probs[0], self.WEIGHTS[0] / total)
        self.assertGreater(probs[5], self.WEIGHTS[5] / total)

    def test_four_or_fewer_options_are_all_offered(self) -> None:
        # With <= 4 eligible options every one is in the hand: uniform pick.
        self.assertEqual(applied_probs([5.0, 1.0, 1.0]), [1 / 3] * 3)


_PERM_SUM = {}


def _hand_probability(ws, total):
    """P(these 4 options form the hand), summed over the 24 draw orders."""
    key = (tuple(sorted(ws)), total)
    h = _PERM_SUM.get(key)
    if h is None:
        h = sum(1.0 / (total * (total - a) * (total - a - b)
                       * (total - a - b - c))
                for a, b, c, _d in itertools.permutations(ws))
        _PERM_SUM[key] = h
    return ws[0] * ws[1] * ws[2] * ws[3] * h


def _exact_hand(weights, values, alt):
    """(E[max(hand mean, alt)], Var(hand mean)) by enumerating every hand."""
    total = sum(weights)
    e_max = mean = second = 0.0
    for idx in itertools.combinations(range(len(weights)), 4):
        p = _hand_probability([weights[i] for i in idx], total)
        h = sum(values[i] for i in idx) / 4
        e_max += p * max(h, alt)
        mean += p * h
        second += p * h * h
    return e_max, second - mean * mean


def _turn_inputs(table, state, turn, turns_left, rerolls):
    """(weights, post-click values, reroll value) of one real table state."""
    pool = table.pool
    elig = [o for o in pool.pool
            if pool.eligible(o, state, turn, turns_left)]
    posts = [table.prob_after_option(state, o, turns_left - 1,
                                     rerolls=rerolls) for o in elig]
    alt = table.lookup(state, turns_left, rerolls=rerolls - 1)
    return [o.weight for o in elig], posts, alt


class TestHandContext(unittest.TestCase):
    WEIGHTS = [11.65, 11.65, 4.4, 3.0, 1.75, 0.45, 3.25, 2.5, 4.4]
    VALUES = [0.31, 0.02, 0.77, 0.05, 0.4, 0.93, 0.11, 0.6, 0.25]

    def test_hand_variance_is_exact(self) -> None:
        # The 4 offers are DISTINCT options: the variance of their mean is
        # not var/4 (independent draws), it follows from the pairwise
        # inclusion probabilities.
        ctx = hand_context(self.WEIGHTS)
        _mu, m2, _m3, _m4, _m5, rho = _hand_moments(ctx, self.VALUES)
        _e, exact_var = _exact_hand(self.WEIGHTS, self.VALUES, 0.0)
        self.assertAlmostEqual(m2 * rho / 4, exact_var, places=12)
        self.assertLess(rho, 1.0)

    def test_uniform_weights_give_the_finite_population_correction(self) -> None:
        n = 11
        ctx = hand_context([1.0] * n)
        *_rest, rho = _hand_moments(ctx, [i * i % 7 for i in range(n)])
        self.assertAlmostEqual(rho, (n - 4) / (n - 1), places=12)

    def test_constant_values_are_a_plain_max(self) -> None:
        ctx = hand_context(self.WEIGHTS)
        self.assertAlmostEqual(_hand_turn_value(ctx, [0.3] * 9, 0.5), 0.5, places=12)
        self.assertAlmostEqual(_hand_turn_value(ctx, [0.7] * 9, 0.5), 0.7, places=12)

    def test_four_or_fewer_options_make_a_certain_hand(self) -> None:
        # Every eligible option is in the hand, so its mean is known.
        ctx = hand_context([5.0, 1.0, 1.0, 2.0])
        self.assertEqual(_hand_turn_value(ctx, [0.0, 1.0, 1.0, 0.0], 0.2), 0.5)
        self.assertEqual(_hand_turn_value(ctx, [0.0, 1.0, 1.0, 0.0], 0.8), 0.8)

    def test_never_below_mean_or_alternative(self) -> None:
        ctx = hand_context(self.WEIGHTS)
        mu = _hand_moments(ctx, self.VALUES)[0]
        for alt in (0.0, mu * 0.8, mu, mu * 1.3, 2.0):
            v = _hand_turn_value(ctx, self.VALUES, alt)
            self.assertGreaterEqual(v, mu - 1e-12)
            self.assertGreaterEqual(v, alt - 1e-12)


class TestHandModelMatchesExactEnumeration(unittest.TestCase):
    """`_hand_turn_value` against the exact E[max(hand mean, reroll value)]
    over all C(n, 4) hands, at real table states.

    The "option value" is what the model adds over deciding blind,
    `E[max(H, t)] - max(E[H], t)`. Two effects must both be right: the hand
    holds 4 DISTINCT offers (less spread than 4 independent draws — this is
    what made easy goals read high), and the value distribution is lumpy
    (a bulk of similar offers plus rare big ones — this is what a two-point
    fit loses on hard goals).
    """

    # (will, chaos, first, second, turn, rerolls) for an epic gem
    STATES = [
        (1, 1, 1, 1, 2, 2), (2, 2, 1, 2, 4, 2), (3, 3, 2, 2, 6, 1),
        (2, 4, 3, 1, 7, 2), (3, 2, 1, 1, 5, 1), (3, 4, 2, 3, 8, 1),
        (4, 4, 2, 2, 9, 1), (3, 5, 1, 1, 9, 2), (2, 3, 4, 2, 6, 2),
        (1, 3, 2, 2, 3, 2), (4, 3, 3, 3, 7, 1), (2, 2, 3, 3, 5, 2),
    ]

    def _option_value_error(self, table):
        model_gain = exact_gain = 0.0
        for w, c, f, s, turn, r in self.STATES:
            state = GemState(will=w, chaos=c, first=f, second=s)
            weights, posts, alt = _turn_inputs(table, state, turn,
                                               10 - turn, r)
            ctx = hand_context(weights)
            model = _hand_turn_value(ctx, posts, alt)
            exact, _var = _exact_hand(weights, posts, alt)
            blind = max(_hand_moments(ctx, posts)[0], alt)
            if exact > 0:
                self.assertAlmostEqual(model, exact, delta=0.02 * exact,
                                       msg=f"state {(w, c, f, s, turn, r)}")
            model_gain += model - blind
            exact_gain += exact - blind
        return model_gain / exact_gain - 1.0

    def test_hard_goal(self) -> None:
        table = GoalProbabilityTable(
            LastTurnGoal(min_will=4, min_chaos=5), 9, OptionPool(),
            early_finish=True, max_rerolls=2)
        self.assertAlmostEqual(self._option_value_error(table), 0.0, delta=0.06)

    def test_easy_many_valued_goal(self) -> None:
        # Total-points goal: every +1 moves the value, so the spread comes
        # from the common offers. Independent draws read ~15% high here.
        table = GoalProbabilityTable(
            LastTurnGoal(min_total=16), 9, OptionPool(),
            early_finish=True, max_rerolls=2)
        self.assertAlmostEqual(self._option_value_error(table), 0.0, delta=0.06)


class TestRerollValueIsHandLevel(unittest.TestCase):
    """A reroll rejects the whole 4-offer hand, never a single offer."""

    def test_last_turn_single_out_matches_exact_value(self) -> None:
        # Goal will>=5 from will=4 on the last turn: `will+1` is the only
        # out. With inclusion probability pi = 4a the hand succeeds with
        # 1/4 if the out was drawn, so with one reroll the exact value is
        #   pi * 1/4 + (1 - pi) * a = a * (2 - 4a).
        pool = OptionPool()
        goal = LastTurnGoal(min_will=5)
        table = GoalProbabilityTable(goal, 7, pool, early_finish=True,
                                     max_rerolls=1)
        state = GemState(will=4, chaos=1, first=1, second=1)
        elig = [o for o in pool.pool if pool.eligible(o, state, 7, 1)]
        a = applied_probs([o.weight for o in elig])[
            [o.key for o in elig].index("will+1")]
        exact = a * (2 - 4 * a)
        self.assertAlmostEqual(table.lookup(state, 1, rerolls=0), a, places=12)
        # (The per-option model priced this state at a * (2 - a): ~28% high;
        # four independent draws at a * (1 + (1 - a)**4): ~7% high.)
        self.assertAlmostEqual(table.lookup(state, 1, rerolls=1), exact,
                               places=9)


class TestRerollAwareTableIsCalibrated(unittest.TestCase):
    """The reroll-aware DP must predict what its own policy achieves."""

    TRIALS = 12000

    @classmethod
    def setUpClass(cls) -> None:
        cls.gem = AstroGem("order_immutability", "boss_damage",
                           "additional_damage", "dps")
        cls.sim = GemSimulator(
            "epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=5),
            astro_gem=cls.gem, optimize="dps")
        wins = sum(cls.sim.simulate_one(seed=i).success
                   for i in range(cls.TRIALS))
        cls.mc = wins / cls.TRIALS

    def test_start_probability_matches_monte_carlo(self) -> None:
        start = GemState(first_effect=self.gem.first_effect,
                         second_effect=self.gem.second_effect)
        dp = self.sim.prob_table.lookup(start, 9, rerolls=2)
        self.assertAlmostEqual(dp, self.mc, delta=0.02)

    def test_fresh_start_prob_matches_monte_carlo(self) -> None:
        # The reset comparison must weigh a hand against what a fresh
        # cutting process really achieves (it gets its rerolls back).
        self.assertAlmostEqual(self.sim.fresh_start_prob(self.gem), self.mc,
                               delta=0.02)


def _play_value_policy(svt, gem_type, first_effect, second_effect,
                       rerolls, trials, seed):
    """Mean final gem value when the table's OWN policy (finish / reroll /
    process, whichever it values highest) is played under the real 4-offer
    mechanics. A calibrated table predicts this number."""
    pool = OptionPool()
    rng = random.Random(seed)
    turns = svt.max_turns
    total = 0.0
    for _ in range(trials):
        st = GemState(first_effect=first_effect, second_effect=second_effect)
        r = rerolls
        value = None
        for turn in range(1, turns + 1):
            tl = turns - turn + 1
            while True:
                offers = pool.generate_offers(st, turn, tl, rng)
                fin = svt.gem_value(st)
                keep = svt.expected_value_after_click(
                    st, offers, tl - 1, rerolls=r)
                if turn != 1 and r > 0:
                    redraw = svt.lookup(st, tl, rerolls=r - 1)
                    if redraw > keep and redraw > fin + 1e-9:
                        r -= 1
                        continue
                break
            if fin >= keep:
                value = fin
                break
            o = rng.choice(offers)
            if o.kind in ("will", "chaos", "first", "second"):
                setattr(st, o.kind,
                        min(5, max(1, getattr(st, o.kind) + o.delta)))
            elif o.kind == "view":
                r += o.delta
            elif o.kind == "cost":
                st.cost_ratio = (min(100, st.cost_ratio + 100)
                                 if o.key == "cost+100"
                                 else max(-100, st.cost_ratio - 100))
            elif o.key in ("change_first_effect", "change_second_effect"):
                dest = rng.choice([
                    e for e in GEM_TYPES[gem_type]
                    if e != st.first_effect and e != st.second_effect])
                if o.key == "change_first_effect":
                    st.first_effect = dest
                else:
                    st.second_effect = dest
        total += svt.gem_value(st) if value is None else value
    return total / trials


class TestSideValueTableIsCalibrated(unittest.TestCase):
    """The reroll-aware side-value table must predict what its own policy
    achieves. On a hard goal the gem's value hinges on a few rare offers —
    the skewed regime a normal approximation of the hand over-prices."""

    def test_hard_goal_value_matches_monte_carlo(self) -> None:
        gem_type, fe, se = "order_immutability", "boss_damage", "additional_damage"
        svt = SideValueTable(
            LastTurnGoal(min_will=4, min_chaos=5), 9, OptionPool(),
            gem_type=gem_type, optimize="dps", max_rerolls=4)
        start = GemState(first_effect=fe, second_effect=se)
        predicted = svt.lookup(start, 9, rerolls=2)
        achieved = _play_value_policy(svt, gem_type, fe, se, rerolls=2,
                                      trials=20000, seed=4242)
        # 20k trials put ~2% of noise (1 sigma) on `achieved`; the Gaussian
        # hand model sat 13% high here.
        self.assertAlmostEqual(predicted, achieved, delta=0.07 * achieved)

    def test_easy_goal_value_matches_monte_carlo(self) -> None:
        # Easy goal + side-coefficient floor with 3 rerolls: the value is
        # spread over many common offers. Treating the hand as 4 independent
        # draws read 6.7% high here.
        gem_type, fe, se = "order_stability", "additional_damage", "attack_power"
        svt = SideValueTable(
            LastTurnGoal(min_total_will_chaos=8), 9, OptionPool(),
            gem_type=gem_type, optimize="dps", min_side_coeff=2000,
            max_rerolls=4)
        start = GemState(first_effect=fe, second_effect=se)
        predicted = svt.lookup(start, 9, rerolls=3)
        achieved = _play_value_policy(svt, gem_type, fe, se, rerolls=3,
                                      trials=30000, seed=4243)
        # ~1% of noise (1 sigma) on `achieved`.
        self.assertAlmostEqual(predicted, achieved, delta=0.035 * achieved)


class TestLastTurnResetUsesRerollAwareFreshStart(unittest.TestCase):
    def test_one_in_four_hand_is_reset_when_fresh_start_is_better(self) -> None:
        # epic, will>=4 chaos>=4: a fresh attempt (2 rerolls) succeeds ~30%
        # of the time, so a last-turn hand with a single out (25%) should be
        # reset. The no-reroll fresh value (~21%) wrongly kept it.
        sim = GemSimulator(
            "epic", use_extra_ticket=False, use_reset_ticket=True,
            goal=LastTurnGoal(min_will=4, min_chaos=4), astro_gem=None)
        ctx = sim._decision_context(p_fresh=sim.fresh_start_prob(None))
        self.assertGreater(ctx.p_fresh, 0.25)
        by_key = {o.key: o for o in sim.pool.pool}
        state = GemState(will=3, chaos=4, first=2, second=2, rerolls=0)
        ti = TurnInput(
            state=state,
            offers=[by_key[k] for k in
                    ("will+1", "first+1", "second+1", "maintain")],
            turn=9, turns_left=1, rerolls=0, reset_available=True)
        decision = decide_post_roll(ctx, ti)
        self.assertEqual(decision.action, ActionKind.RESET)
        self.assertEqual(decision.branch, "last_turn_fresh")


class TestProbResetThresholdIsRerollAware(unittest.TestCase):
    def test_rerolls_in_hand_keep_a_gem_above_the_threshold(self) -> None:
        # epic, will>=4 chaos>=5, turn 1 with the 2 free rerolls still in
        # hand and a neutral hand. Ignoring the rerolls the gem reads ~8%
        # and a 10% threshold would reset it on the spot; counting them it
        # is worth ~13%, so the threshold must not fire.
        goal = LastTurnGoal(min_will=4, min_chaos=5)
        threshold = 0.10
        sim = GemSimulator(
            "epic", use_extra_ticket=False, use_reset_ticket=True,
            goal=goal, astro_gem=None, prob_reset_threshold=threshold)
        ctx = sim._decision_context(p_fresh=sim.fresh_start_prob(None))
        by_key = {o.key: o for o in sim.pool.pool}
        offers = [by_key[k] for k in
                  ("first+1", "second+1", "maintain", "cost+100")]
        state = GemState(rerolls=2)

        no_reroll = GoalProbabilityTable(goal, 9, sim.pool, early_finish=True)
        self.assertLess(
            no_reroll.expected_prob_after_click(state, offers, 8), threshold)
        self.assertGreater(
            sim.prob_table.expected_prob_after_click(
                state, offers, 8, rerolls=2), threshold)

        ti = TurnInput(state=state, offers=offers, turn=1, turns_left=9,
                       rerolls=2, reset_available=True)
        decision = decide_post_roll(ctx, ti)
        self.assertNotEqual(decision.action, ActionKind.RESET)

    def test_threshold_still_resets_a_gem_below_it(self) -> None:
        goal = LastTurnGoal(min_will=4, min_chaos=5)
        sim = GemSimulator(
            "epic", use_extra_ticket=False, use_reset_ticket=True,
            goal=goal, astro_gem=None, prob_reset_threshold=0.30)
        ctx = sim._decision_context(p_fresh=sim.fresh_start_prob(None))
        by_key = {o.key: o for o in sim.pool.pool}
        offers = [by_key[k] for k in
                  ("first+1", "second+1", "maintain", "cost+100")]
        ti = TurnInput(state=GemState(rerolls=2), offers=offers, turn=1,
                       turns_left=9, rerolls=2, reset_available=True)
        decision = decide_post_roll(ctx, ti)
        self.assertEqual(decision.action, ActionKind.RESET)
        self.assertEqual(decision.branch, "prob_reset")


class TestGradeTablesLockInAHeldGrade(unittest.TestCase):
    def test_relic_table_counts_a_relic_gem_as_secured(self) -> None:
        sim = GemSimulator(
            "epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=5), astro_gem=None)
        relic = GemState(will=4, chaos=4, first=4, second=4)
        self.assertEqual(sim._relic_prob_table.lookup(relic, 3, rerolls=0), 1.0)


class TestFeasibilityNeverContradictsTheDp(unittest.TestCase):
    """`feasible()` is a necessary check: it may never say "infeasible" for
    a state the effect-aware DP can still win from."""

    def test_side_coeff_goal_over_every_effect_pair(self) -> None:
        gem_type, floor = "order_immutability", 6000
        goal = LastTurnGoal(min_will=1)
        table = GoalProbabilityTable(
            goal, 9, OptionPool(), min_side_coeff=floor, early_finish=True,
            effect_aware=True, gem_type=gem_type, optimize="dps")
        effects = GEM_TYPES[gem_type]
        for fe, se in itertools.permutations(effects, 2):
            dests = change_dest_coeffs(gem_type, fe, se, "dps")
            for f, s, tl in itertools.product(range(1, 6), range(1, 6),
                                              range(0, 10)):
                state = GemState(first=f, second=s,
                                 first_effect=fe, second_effect=se)
                if table.lookup(state, tl) <= 0:
                    continue
                self.assertTrue(
                    goal.feasible(
                        1, 1, tl, first=f, second=s, min_side_coeff=floor,
                        side_coeff_first=DPS_COEFF.get(fe, 0),
                        side_coeff_second=DPS_COEFF.get(se, 0),
                        change_dest_coeffs=dests),
                    f"{fe}/{se} f={f} s={s} tl={tl}")


if __name__ == "__main__":
    unittest.main()
