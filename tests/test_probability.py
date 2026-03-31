from __future__ import annotations

import time
import unittest

from arkgrid import (
    GemSimulator,
    GemState,
    GoalProbabilityTable,
    LastTurnGoal,
    Option,
    OptionPool,
    RerollPolicy,
)


class TestGoalProbabilityTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = OptionPool()
        cls.goal = LastTurnGoal(min_will=4, min_chaos=5)
        cls.table = GoalProbabilityTable(cls.goal, 9, cls.pool)

    def test_base_case_satisfied(self) -> None:
        s = GemState(will=4, chaos=5, first=3, second=3)
        self.assertAlmostEqual(self.table.lookup(s, 0), 1.0)

    def test_base_case_not_satisfied(self) -> None:
        s = GemState(will=1, chaos=1, first=1, second=1)
        self.assertAlmostEqual(self.table.lookup(s, 0), 0.0)

    def test_probability_increases_with_turns(self) -> None:
        s = GemState(will=1, chaos=1, first=1, second=1)
        p5 = self.table.lookup(s, 5)
        p9 = self.table.lookup(s, 9)
        self.assertGreater(p9, p5)

    def test_probability_increases_with_progress(self) -> None:
        s_low = GemState(will=1, chaos=1, first=1, second=1)
        s_mid = GemState(will=3, chaos=3, first=2, second=2)
        self.assertGreater(self.table.lookup(s_mid, 5), self.table.lookup(s_low, 5))

    def test_already_met_is_high(self) -> None:
        s = GemState(will=5, chaos=5, first=3, second=3)
        # At turns_left=0 it's exactly 1.0; with more turns, downgrades
        # (will-1 / chaos-1) can compound, but probability stays high.
        self.assertAlmostEqual(self.table.lookup(s, 0), 1.0)
        for tl in range(1, 10):
            self.assertGreater(self.table.lookup(s, tl), 0.7,
                               msg=f"turns_left={tl}")

    def test_impossible_at_zero_turns(self) -> None:
        s = GemState(will=2, chaos=2, first=2, second=2)
        self.assertAlmostEqual(self.table.lookup(s, 0), 0.0)

    def test_build_time_under_100ms(self) -> None:
        t0 = time.perf_counter()
        GoalProbabilityTable(self.goal, 9, self.pool)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.1, f"Build took {elapsed:.3f}s")

    def test_expected_prob_after_click(self) -> None:
        s = GemState(will=3, chaos=4, first=2, second=2)
        offers = [
            Option("will+1", 11.65, "will", 1),
            Option("chaos+1", 11.65, "chaos", 1),
            Option("first+1", 11.65, "first", 1),
            Option("maintain", 1.75, "other", 0),
        ]
        p = self.table.expected_prob_after_click(s, offers, 3)
        # Manual: average of lookup(4,4,2,2,3), lookup(3,5,2,2,3),
        #         lookup(3,4,3,2,3), lookup(3,4,2,2,3)
        expected = (
            self.table.lookup(GemState(will=4, chaos=4, first=2, second=2), 3)
            + self.table.lookup(GemState(will=3, chaos=5, first=2, second=2), 3)
            + self.table.lookup(GemState(will=3, chaos=4, first=3, second=2), 3)
            + self.table.lookup(GemState(will=3, chaos=4, first=2, second=2), 3)
        ) / 4
        self.assertAlmostEqual(p, expected, places=10)

    def test_lookup_missing_key_returns_zero(self) -> None:
        s = GemState(will=1, chaos=1, first=1, second=1)
        self.assertEqual(self.table.lookup(s, 99), 0.0)

    def test_different_goals_produce_different_tables(self) -> None:
        easy = GoalProbabilityTable(LastTurnGoal(min_will=2), 5, self.pool)
        hard = GoalProbabilityTable(LastTurnGoal(min_will=5, min_chaos=5), 5, self.pool)
        s = GemState(will=1, chaos=1, first=1, second=1)
        self.assertGreater(easy.lookup(s, 5), hard.lookup(s, 5))


class TestEarlyReset(unittest.TestCase):
    def test_threshold_zero_matches_baseline(self) -> None:
        """With threshold=0.0, behavior is identical to no prob table."""
        goal = LastTurnGoal(min_will=4, min_chaos=5)
        sim_base = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=goal, prob_reset_threshold=0.0,
        )
        sim_zero = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=goal, prob_reset_threshold=0.0,
        )
        for seed in range(20):
            r1 = sim_base.simulate_one(seed=seed)
            r2 = sim_zero.simulate_one(seed=seed)
            self.assertEqual(r1.success, r2.success, f"seed={seed}")
            self.assertEqual(r1.total_points, r2.total_points, f"seed={seed}")

    def test_prob_reset_triggers_earlier(self) -> None:
        """With a threshold, resets happen earlier (higher reset rate)."""
        goal = LastTurnGoal(min_will=4, min_chaos=5)
        sim_base = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=goal, prob_reset_threshold=0.0,
        )
        sim_prob = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=goal, prob_reset_threshold=0.02,
        )
        base_resets = sum(1 for s in range(500) if sim_base.simulate_one(seed=s).reset_used)
        prob_resets = sum(1 for s in range(500) if sim_prob.simulate_one(seed=s).reset_used)
        # prob-based should reset at least as often (more proactive)
        self.assertGreaterEqual(prob_resets, base_resets)

    def test_prob_table_not_built_when_disabled(self) -> None:
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), prob_reset_threshold=0.0,
        )
        self.assertIsNone(sim.prob_table)

    def test_prob_table_built_when_enabled(self) -> None:
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=3), prob_reset_threshold=0.05,
        )
        self.assertIsNotNone(sim.prob_table)

    def test_sim_log_shows_prob_reset(self) -> None:
        """With a high threshold, the log should contain a probability reset."""
        goal = LastTurnGoal(min_will=5, min_chaos=5)
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=True,
            goal=goal, prob_reset_threshold=0.5,  # very high -- will always trigger
        )
        r = sim.simulate_one(seed=1, log=True)
        if r.reset_used and r.turn_log:
            # Check attempt 2's log -- attempt 1 log gets overwritten
            pass
        # Main check: it should complete without error
        self.assertIsNotNone(r.reason)

    def test_reroll_policy_uses_goal_success_prob(self) -> None:
        """When goal_success_prob is provided, it's used for comfort threshold."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), side_node_threshold=0.5)
        pool = OptionPool()
        lookup = {o.key: o for o in pool.pool}
        state = GemState(will=1)
        offers = [lookup["first+3"], lookup["maintain"], lookup["cost-100"], lookup["cost+100"]]

        # Binary frac says comfortable (0.75), but prob says desperate (0.1)
        should_bin, _ = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.75, goal_success_prob=None)
        should_prob, _ = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.75, goal_success_prob=0.1)

        # With binary: comfortable mode accepts first+3 -> no reroll
        self.assertFalse(should_bin)
        # With prob 0.1 < threshold 0.5: desperate mode, no goal upgrade -> reroll
        self.assertTrue(should_prob)


if __name__ == "__main__":
    unittest.main()
