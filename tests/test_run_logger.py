from __future__ import annotations

import json
import tempfile
import unittest

from arkgrid.models import GemState
from arkgrid.run_logger import (
    GemOutcome, RunLogger, format_gem_result, format_run_overview,
    format_tally,
)


def _outcome(idx, success, *, stats=(5, 5, 3, 3), rarity="epic",
             reason="early_finish", shortfalls=()):
    w, c, f, s = stats
    state = GemState(will=w, chaos=c, first=f, second=s,
                     first_effect="boss_damage",
                     second_effect="attack_power")
    return GemOutcome(gem_index=idx, success=success, final_state=state,
                      reason=reason, rarity=rarity, side_coeff=4200,
                      shortfalls=tuple(shortfalls))


def _records(emit):
    """Run `emit(logger)` against a fresh RunLogger; return its JSONL records."""
    with tempfile.TemporaryDirectory() as d:
        logger = RunLogger(log_dir=d)
        jsonl = logger.jsonl_path
        emit(logger)
        logger.close()
        with open(jsonl, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]


class TestRunTally(unittest.TestCase):
    """Per-gem result line, running all-mode tally, and end-of-run overview."""

    def test_tally_counts_successes(self):
        outcomes = [_outcome(i, i in (4, 9, 17)) for i in range(1, 26)]
        self.assertEqual(format_tally(outcomes), "3/25 successes (12.0%)")

    def test_tally_empty_run(self):
        self.assertEqual(format_tally([]), "0/0 successes (0.0%)")

    def test_gem_result_success(self):
        self.assertEqual(
            format_gem_result(_outcome(3, True, reason="ran_to_end")),
            "Result: SUCCESS  [gem #3, epic, ran_to_end]")

    def test_gem_result_fail_names_missed_conditions(self):
        outcome = _outcome(1, False, rarity="rare",
                           shortfalls=("will 1<4", "chaos 1<5"))
        self.assertEqual(
            format_gem_result(outcome),
            "Result: FAIL (missed: will 1<4, chaos 1<5)  "
            "[gem #1, rare, early_finish]")

    def test_gem_result_without_rarity(self):
        self.assertEqual(format_gem_result(_outcome(2, True, rarity=None)),
                         "Result: SUCCESS  [gem #2, early_finish]")

    def test_overview_lists_only_successful_gems(self):
        outcomes = [
            _outcome(1, False, stats=(1, 1, 1, 3), rarity="rare"),
            _outcome(2, True, stats=(5, 5, 4, 3), rarity="epic"),   # 17 relic
            _outcome(3, False, stats=(5, 5, 5, 4), rarity="epic"),  # 19 ancient
        ]
        lines = format_run_overview(outcomes)
        self.assertEqual(lines[0],
                         "=== All mode summary: 1/3 successes (33.3%) ===")
        text = "\n".join(lines)
        self.assertIn("Relic+ (>=16): 2/3   Ancient (>=19): 1/3", text)
        self.assertIn("By rarity: rare 0/1, epic 1/2", text)
        gem_lines = [ln.strip() for ln in lines if ln.strip().startswith("#")]
        self.assertEqual(len(gem_lines), 1)
        self.assertTrue(gem_lines[0].startswith(
            "#2  epic  w=5 c=5 1st=4 2nd=3  (total=17)  "
            "effects=boss_damage/attack_power  side_coeff=4200"),
            gem_lines[0])

    def test_overview_without_successes(self):
        lines = format_run_overview([_outcome(1, False)])
        self.assertIn("  No successful gems.", lines)
        self.assertFalse(any(ln.strip().startswith("#") for ln in lines))


class TestRunSummaryJsonl(unittest.TestCase):
    """gem_end carries the gem index + missed conditions; run_end carries the
    success tally so a JSONL can be filtered without replaying the log.
    """

    def test_gem_end_carries_index_and_missed(self):
        state = GemState(will=1, chaos=1, first=1, second=3)
        records = _records(lambda lg: lg.log_gem_end(
            success=False, total_points=6, side_coeff=0, reset_used=False,
            extra_ticket_used=False, final_state=state,
            reason="early_finish", gem_index=7,
            missed=["will 1<4", "chaos 1<5"]))
        gem_end = [r for r in records if r["event"] == "gem_end"]
        self.assertEqual(len(gem_end), 1)
        self.assertEqual(gem_end[0]["gem_index"], 7)
        self.assertEqual(gem_end[0]["missed"], ["will 1<4", "chaos 1<5"])

    def test_run_end_summary(self):
        outcomes = [_outcome(1, False), _outcome(2, True), _outcome(3, True)]
        records = _records(lambda lg: lg.log_run_end(outcomes))
        run_end = [r for r in records if r["event"] == "run_end"]
        self.assertEqual(len(run_end), 1)
        self.assertEqual(run_end[0]["gems"], 3)
        self.assertEqual(run_end[0]["successes"], 2)
        self.assertAlmostEqual(run_end[0]["success_rate"], 2 / 3)
        self.assertEqual(run_end[0]["successful_gems"], [2, 3])

    def test_run_end_without_outcomes_stays_bare(self):
        records = _records(lambda lg: lg.log_run_end())
        run_end = [r for r in records if r["event"] == "run_end"]
        self.assertEqual(len(run_end), 1)
        self.assertNotIn("gems", run_end[0])


class TestLogConfirm(unittest.TestCase):
    """RunLogger.log_confirm writes a `confirm` JSONL record."""

    def test_confirm_event_written(self):
        with tempfile.TemporaryDirectory() as d:
            logger = RunLogger(log_dir=d)
            jsonl = logger.jsonl_path
            logger.log_confirm(turn=4, branch="confirm_finish",
                               auto_action="finish", user_choice="process",
                               metrics={"risk": 0.3, "side_coeff": 3000})
            logger.close()
            with open(jsonl, encoding="utf-8") as fh:
                records = [json.loads(ln) for ln in fh if ln.strip()]
        confirm = [r for r in records if r.get("event") == "confirm"]
        self.assertEqual(len(confirm), 1)
        self.assertEqual(confirm[0]["branch"], "confirm_finish")
        self.assertEqual(confirm[0]["auto_action"], "finish")
        self.assertEqual(confirm[0]["user_choice"], "process")

    def test_confirm_default_user_choice_is_none(self):
        """log_confirm without user_choice writes JSON null for user_choice."""
        with tempfile.TemporaryDirectory() as d:
            logger = RunLogger(log_dir=d)
            jsonl = logger.jsonl_path
            logger.log_confirm(turn=2, branch="confirm_finish",
                               auto_action="finish")
            logger.close()
            with open(jsonl, encoding="utf-8") as fh:
                records = [json.loads(ln) for ln in fh if ln.strip()]
        confirm = [r for r in records if r.get("event") == "confirm"]
        self.assertEqual(len(confirm), 1)
        self.assertIsNone(confirm[0]["user_choice"])


if __name__ == "__main__":
    unittest.main()
