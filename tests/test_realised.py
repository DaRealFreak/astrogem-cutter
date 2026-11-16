"""`RealisedSuccessTable`: the success rate the bot's OWN policy delivers.

`P(goal)` from the goal table assumes play stops the moment the goal is met.
The bot keeps cutting for side value (risking the goal) and can spend a reset
ticket, so what it really delivers differs — a little lower without a reset,
far higher with one. The realised table must match Monte Carlo of the
simulator, which plays that policy.
"""
from __future__ import annotations

import random
import unittest

from arkgrid.constants import GEM_TYPES
from arkgrid.models import AstroGem, GemState, LastTurnGoal
from arkgrid.pool import OptionPool
from arkgrid.probability import (
    RealisedSuccessTable, SideValueTable, _hand_moments, hand_atoms,
    hand_context, hand_e_max,
)
from arkgrid.simulator import GemSimulator

GOAL = LastTurnGoal(min_will=4, min_chaos=5)
GEM = AstroGem("order_immutability", "boss_damage", "additional_damage", "dps")


class TestHandAtoms(unittest.TestCase):
    """The explicit hand distribution must be the one `hand_e_max` prices."""

    def _cases(self):
        pool = OptionPool()
        rng = random.Random(3)
        for trial in range(60):
            state = GemState(will=rng.randint(1, 5), chaos=rng.randint(1, 5),
                             first=rng.randint(1, 5), second=rng.randint(1, 5))
            elig = [o for o in pool.pool
                    if pool.eligible(o, state, 3, rng.choice((1, 4)))]
            ctx = hand_context([o.weight for o in elig])
            if trial % 3 == 0:      # hit-or-miss
                posts = [float(rng.random() < 0.2) for _ in elig]
            elif trial % 3 == 1:    # rare big values
                posts = [rng.random() ** 6 for _ in elig]
            else:
                posts = [rng.random() for _ in elig]
            yield ctx, posts, rng

    def test_atoms_reproduce_hand_e_max(self) -> None:
        for ctx, posts, rng in self._cases():
            mu, m2, m3, m4, m5, rho = _hand_moments(ctx, posts)
            if m2 <= 0.0:
                continue
            atoms = hand_atoms(mu, m2, m3, m4, m5, rho)
            self.assertAlmostEqual(sum(p for _h, p in atoms), 1.0, places=10)
            self.assertAlmostEqual(sum(h * p for h, p in atoms), mu, places=10)
            for t in (mu * rng.uniform(0.6, 1.4), 0.0):
                self.assertAlmostEqual(
                    sum(p * max(h, t) for h, p in atoms),
                    hand_e_max(mu, m2, m3, m4, m5, rho, t), places=10)


class TestRealisedSuccessTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.svt = SideValueTable(
            GOAL, 9, OptionPool(), gem_type=GEM.gem_type, optimize="dps",
            min_side_coeff=2000, max_rerolls=3)
        cls.plain = RealisedSuccessTable(cls.svt)
        cls.fresh = cls.plain.lookup(cls._start(), 9, rerolls=2)
        cls.with_reset = RealisedSuccessTable(cls.svt, fresh=cls.fresh)

    @staticmethod
    def _start(**kw) -> GemState:
        return GemState(first_effect=GEM.first_effect,
                        second_effect=GEM.second_effect, **kw)

    def test_finished_gem_is_its_goal_status(self) -> None:
        met = self._start(will=4, chaos=5, first=2, second=2)       # coeff 3400
        low_coeff = self._start(will=4, chaos=5, first=1, second=1)  # 1700 < 2000
        missed = self._start(will=3, chaos=5, first=5, second=5)
        self.assertEqual(self.plain.lookup(met, 0), 1.0)
        self.assertEqual(self.plain.lookup(low_coeff, 0), 0.0)
        self.assertEqual(self.plain.lookup(missed, 0), 0.0)

    def test_maxed_gem_is_certain(self) -> None:
        # Nothing can improve it, so the policy finishes: success is certain.
        maxed = self._start(will=5, chaos=5, first=5, second=5)
        self.assertEqual(self.plain.lookup(maxed, 4, rerolls=0), 1.0)

    def test_value_chasing_costs_some_success(self) -> None:
        # Stop-when-met is the most success any policy can have, so the
        # bot's realised success sits a little below the goal table.
        from arkgrid.probability import GoalProbabilityTable
        goal_table = GoalProbabilityTable(
            GOAL, 9, OptionPool(), min_side_coeff=2000, early_finish=True,
            max_rerolls=3, effect_aware=True, gem_type=GEM.gem_type,
            optimize="dps")
        p_goal = goal_table.lookup(self._start(), 9, rerolls=2)
        self.assertLess(self.fresh, p_goal)
        self.assertGreater(self.fresh, p_goal - 0.03)

    def test_reset_ticket_raises_it(self) -> None:
        with_reset = self.with_reset.lookup(self._start(), 9, rerolls=2)
        self.assertGreater(with_reset, self.fresh + 0.05)
        # A dead gem is worth exactly a fresh start while the reset remains.
        dead = self._start(will=1, chaos=1, first=1, second=1)
        self.assertEqual(self.plain.lookup(dead, 1, rerolls=0), 0.0)
        self.assertAlmostEqual(self.with_reset.lookup(dead, 1, rerolls=0),
                               self.fresh, places=12)

    def test_more_rerolls_never_hurt(self) -> None:
        mid = self._start(will=2, chaos=3, first=2, second=2)
        vals = [self.plain.lookup(mid, 5, rerolls=r) for r in range(4)]
        self.assertEqual(vals, sorted(vals))

    def test_expected_after_click_averages_the_offers_in_hand(self) -> None:
        # The value of processing THIS hand: one of the 4 offers is applied
        # uniformly. A change-effect card hides its destination (average of
        # the two non-equipped effects); a view card adds rerolls.
        pool = OptionPool()
        by_key = {o.key: o for o in pool.pool}
        offers = [by_key["will+1"], by_key["first+1"], by_key["view+1"],
                  by_key["change_first_effect"]]
        mid = self._start(will=3, chaos=4, first=2, second=2)
        others = [e for e in GEM_TYPES[GEM.gem_type]
                  if e not in (GEM.first_effect, GEM.second_effect)]
        self.assertEqual(len(others), 2)
        for table in (self.plain, self.with_reset):
            want = (
                table.lookup(self._start(will=4, chaos=4, first=2, second=2),
                             4, rerolls=1)
                + table.lookup(self._start(will=3, chaos=4, first=3, second=2),
                               4, rerolls=1)
                + table.lookup(mid, 4, rerolls=2)
                + 0.5 * sum(
                    table.lookup(GemState(
                        will=3, chaos=4, first=2, second=2, first_effect=e,
                        second_effect=GEM.second_effect), 4, rerolls=1)
                    for e in others)) / 4.0
            self.assertAlmostEqual(
                table.expected_after_click(mid, offers, 4, rerolls=1), want,
                places=12)
        self.assertEqual(self.plain.expected_after_click(mid, [], 4), 0.0)

    def test_unknown_gem_type_is_disabled(self) -> None:
        svt = SideValueTable(GOAL, 9, OptionPool(), gem_type="", optimize="dps")
        table = RealisedSuccessTable(svt)
        self.assertFalse(table.enabled)
        self.assertEqual(table.lookup(GemState(), 9, rerolls=2), 0.0)


class TestRealisedMatchesTheSimulator(unittest.TestCase):
    """End to end: the table's number vs Monte Carlo of the real policy."""

    TRIALS = 20000

    def _check(self, *, reset: bool) -> None:
        sim = GemSimulator(
            "epic", use_extra_ticket=True, use_reset_ticket=reset,
            goal=GOAL, astro_gem=GEM, optimize="dps", min_side_coeff=2000)
        wins = sum(sim.simulate_one(seed=s).success
                   for s in range(self.TRIALS))
        mc = wins / self.TRIALS
        start = GemState(first_effect=GEM.first_effect,
                         second_effect=GEM.second_effect)
        realised = sim.realised_success(start, 9, rerolls=3,
                                        reset_available=reset)
        # ~0.6pp of MC noise (2 sigma); the stop-when-met P(goal) is ~1pp
        # high without a reset and ~11pp LOW with one.
        self.assertAlmostEqual(realised, mc, delta=0.012)
        p_goal = sim.prob_table.lookup(start, 9, rerolls=3)
        if reset:
            self.assertGreater(realised, p_goal + 0.08)

    def test_without_reset(self) -> None:
        self._check(reset=False)

    def test_with_reset(self) -> None:
        self._check(reset=True)


class TestSimulatorHelpers(unittest.TestCase):
    def test_reset_allowed_follows_the_coefficient_bar(self) -> None:
        sim = GemSimulator("epic", use_extra_ticket=None, use_reset_ticket=True,
                           goal=GOAL, astro_gem=GEM, reset_min_coeff=1700)
        self.assertTrue(sim.reset_allowed(GEM))                 # 1000 + 700
        self.assertFalse(sim.reset_allowed(AstroGem(
            "order_fortitude", "attack_power", "boss_damage", "dps")))  # 1400
        no_reset = GemSimulator("epic", use_extra_ticket=None,
                                use_reset_ticket=False, goal=GOAL,
                                astro_gem=GEM)
        self.assertFalse(no_reset.reset_allowed(GEM))

    def test_turn_log_carries_the_bot_column(self) -> None:
        sim = GemSimulator("epic", use_extra_ticket=None, use_reset_ticket=True,
                           goal=GOAL, astro_gem=GEM, min_side_coeff=2000,
                           log_policy_success=True)
        first = sim.simulate_one(seed=3, log=True).turn_log[0]
        # Turn 1 with the reset in hand: far above the stop-when-met number.
        self.assertGreater(first["bot_prob"], first["goal_prob"] + 0.05)
        self.assertLessEqual(first["bot_prob"], 1.0)

    def test_auto_header_helper_matches_the_simulator(self) -> None:
        # `auto` builds its tables itself; its P(bot) must be the number the
        # simulator reports for the same gem, state and budgets.
        try:
            from arkgrid.automation import _bot_success
        except RuntimeError:
            self.skipTest("arkgrid.automation requires Windows")
        sim = GemSimulator("epic", use_extra_ticket=True, use_reset_ticket=True,
                           goal=GOAL, astro_gem=GEM, min_side_coeff=2000)
        sim.simulate_one(seed=1)                     # swap in per-gem tables
        ctx = sim._decision_context()
        state = GemState(will=2, chaos=3, first=2, second=2,
                         first_effect=GEM.first_effect,
                         second_effect=GEM.second_effect)
        for reset_live in (False, True):
            got = _bot_success(
                {}, ctx.side_value_table, ctx,
                (GEM.first_effect, GEM.second_effect), 9, 2, True,
                None, False, reset_live, state, 5, 2)
            want = sim.realised_success(state, 5, 2,
                                        reset_available=reset_live)
            self.assertAlmostEqual(got, want, places=12)


if __name__ == "__main__":
    unittest.main()
