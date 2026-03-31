from __future__ import annotations

import unittest

from arkgrid import GemAnalyzer, GemSimulator, LastTurnGoal


class TestGemAnalyzer(unittest.TestCase):
    def test_wilson_ci_bounds(self) -> None:
        lo, hi = GemAnalyzer.wilson_ci(0.5, 100)
        self.assertGreater(lo, 0.0)
        self.assertLess(hi, 1.0)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_wilson_ci_zero_trials(self) -> None:
        lo, hi = GemAnalyzer.wilson_ci(0.0, 0)
        self.assertEqual(lo, 0.0)
        self.assertEqual(hi, 1.0)

    def test_estimate_summary_keys(self) -> None:
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=3),
        )
        result = GemAnalyzer.estimate_summary(trials=100, simulator=sim, seed=1)
        for key in ("p_success", "p_success_ci_lo", "p_success_ci_hi",
                     "avg_total_points", "p_relic_plus", "p_ancient", "reset_rate"):
            self.assertIn(key, result)

    def test_success_rate_in_range(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=LastTurnGoal(min_will=3, min_chaos=3),
        )
        result = GemAnalyzer.estimate_summary(trials=500, simulator=sim, seed=42)
        self.assertGreaterEqual(result["p_success"], 0.0)
        self.assertLessEqual(result["p_success"], 1.0)
        self.assertLessEqual(result["p_success_ci_lo"], result["p_success"])
        self.assertGreaterEqual(result["p_success_ci_hi"], result["p_success"])


if __name__ == "__main__":
    unittest.main()
