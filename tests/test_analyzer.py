from __future__ import annotations

import contextlib
import io
import unittest

from arkgrid import GemAnalyzer, GemSimulator, LastTurnGoal
from arkgrid.analyzer import pprint_result


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
                     "avg_total_points", "avg_side_coeff", "p_relic_plus", "p_ancient",
                     "reset_rate", "extra_ticket_available_rate"):
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

    def test_estimate_summary_trials_zero_no_crash(self) -> None:
        """trials=0 must return a zeroed summary dict without raising ZeroDivisionError."""
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=3),
        )
        # Must not raise ZeroDivisionError
        result = GemAnalyzer.estimate_summary(trials=0, simulator=sim, seed=1)
        # Keys must match the normal (trials > 0) summary keys
        expected_keys = (
            "p_success", "p_success_ci_lo", "p_success_ci_hi",
            "avg_total_points", "avg_side_coeff",
            "p_relic_plus", "p_ancient",
            "reset_rate", "extra_ticket_available_rate",
        )
        for key in expected_keys:
            self.assertIn(key, result)
        # All numeric values must be zero (or within the CI defaults)
        self.assertEqual(result["p_success"], 0.0)
        self.assertEqual(result["p_success_ci_lo"], 0.0)
        self.assertEqual(result["p_success_ci_hi"], 1.0)
        self.assertEqual(result["avg_total_points"], 0.0)
        self.assertEqual(result["avg_side_coeff"], 0.0)
        self.assertEqual(result["p_relic_plus"], 0.0)
        self.assertEqual(result["p_ancient"], 0.0)
        self.assertEqual(result["reset_rate"], 0.0)
        self.assertEqual(result["extra_ticket_available_rate"], 0.0)


class TestPprintResult(unittest.TestCase):
    def test_both_dp_bounds_displayed(self) -> None:
        """pprint_result must display both the reroll-aware (optimistic) and the
        no-reroll (conservative) DP lines when dp_prob_no_reroll is present in the summary."""
        summary = {
            "dp_prob": 0.45,
            "dp_prob_no_reroll": 0.30,
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pprint_result("  Epic", summary)
        output = buf.getvalue()

        # Reroll-aware optimistic label and value must appear
        self.assertIn("optimistic", output)
        self.assertIn("45.00%", output)

        # No-reroll conservative label and value must appear
        self.assertIn("conservative", output)
        self.assertIn("30.00%", output)

    def test_dp_prob_only_no_crash(self) -> None:
        """pprint_result must not crash or print a conservative line when
        dp_prob_no_reroll is absent from the summary."""
        summary = {"dp_prob": 0.60}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pprint_result("  Common", summary)
        output = buf.getvalue()

        self.assertIn("optimistic", output)
        self.assertIn("60.00%", output)
        self.assertNotIn("conservative", output)


if __name__ == "__main__":
    unittest.main()
