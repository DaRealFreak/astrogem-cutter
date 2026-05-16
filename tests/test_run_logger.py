from __future__ import annotations

import json
import os
import tempfile
import unittest

from arkgrid.run_logger import RunLogger


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
