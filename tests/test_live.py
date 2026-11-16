"""`live`: the screenshot analysis shows what the bot's own policy delivers.

`P(goal)~` is the success rate if play stops the moment the goal is met;
`P(bot)~` is the rate of the policy the bot actually plays (it keeps cutting
for side value, and uses the reset ticket when one is allowed and the button
is still lit).
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import unittest

import tests  # noqa: F401  (test-run defaults: larger table cache)

try:
    import cv2  # noqa: F401
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Rare gem (order_stability, attack_power + brand_power), turn 5 of 7, one
# reroll, will 2 / chaos 4, Reset button lit.
_SHOT = os.path.join(PROJECT_ROOT, "examples", "20260716033035_1.jpg")


def _percent(label: str, out: str) -> float:
    m = re.search(re.escape(label) + r"\s+([\d.]+)%", out)
    if m is None:
        raise AssertionError(f"no {label!r} line in:\n{out}")
    return float(m.group(1))


@unittest.skipUnless(_HAVE_CV2, "opencv-python not installed")
class TestLivePolicySuccess(unittest.TestCase):
    def _run(self, *extra: str) -> str:
        from arkgrid.cli import _build_parser, cmd_live
        args = _build_parser().parse_args(
            ["live", "--screenshot", _SHOT, "--min-will", "4",
             "--min-chaos", "4", "--optimize", "dps", *extra])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_live(args)
        return buf.getvalue()

    def test_prints_the_policy_success_under_p_goal(self) -> None:
        out = self._run()
        p_goal = _percent("P(goal)~:", out)
        p_bot = _percent("P(bot)~:", out)
        # No reset ticket: stopping the moment the goal is met is the most
        # any policy can reach, so the policy's own rate cannot exceed it
        # (one-decimal print rounding aside), and it stays close.
        self.assertLessEqual(p_bot, p_goal + 0.1)
        self.assertGreater(p_bot, p_goal - 5.0)
        self.assertLess(out.index("P(goal)~:"), out.index("P(bot)~:"))

    def test_an_allowed_reset_ticket_raises_it(self) -> None:
        plain = _percent("P(bot)~:", self._run())
        with_reset = self._run("--reset-ticket", "rare")
        self.assertGreater(_percent("P(bot)~:", with_reset), plain + 1.0)
        self.assertIn("reset ticket included", with_reset)

    def test_a_reset_the_policy_does_not_allow_is_not_counted(self) -> None:
        # --reset-ticket epic does not cover this rare gem.
        plain = self._run()
        epic_only = self._run("--reset-ticket", "epic")
        self.assertEqual(_percent("P(bot)~:", epic_only),
                         _percent("P(bot)~:", plain))
        self.assertNotIn("reset ticket included", epic_only)


if __name__ == "__main__":
    unittest.main()
