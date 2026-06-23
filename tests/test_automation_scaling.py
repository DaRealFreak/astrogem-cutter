"""Tests for the pure coordinate-scaling helper in arkgrid.automation.

The helper ``scale_to_screen(ref_x, ref_y, width, height)`` converts
1920x1080 reference button coordinates to physical screen coordinates
using *uniform* scale + centering offsets (letterbox / pillar-box model).

Formula:
    s        = min(width / 1920, height / 1080)
    offset_x = (width  - 1920 * s) / 2
    offset_y = (height - 1080 * s) / 2
    screen_x = int(round(ref_x * s + offset_x))
    screen_y = int(round(ref_y * s + offset_y))

Rounding: ``int(round(...))`` so results are deterministic for the
expected values below.
"""

from __future__ import annotations

import unittest


# automation.py raises ``RuntimeError`` unconditionally at import time on
# non-Windows platforms (the very first ``if sys.platform != "win32": raise``
# guard fires before any ctypes call).  We catch it here so the test file
# can be collected on Linux/macOS CI runners without failing the import,
# and skip the whole class on those platforms via ``_IMPORT_OK``.
try:
    from arkgrid.automation import scale_to_screen, _build_reset_table
    _IMPORT_OK = True
except RuntimeError:
    # Raised on non-Windows: "The 'auto' command requires Windows."
    _IMPORT_OK = False

from arkgrid.models import GemState, LastTurnGoal
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable


@unittest.skipUnless(_IMPORT_OK, "arkgrid.automation requires Windows")
class TestScaleToScreen(unittest.TestCase):
    """Unit tests for scale_to_screen()."""

    # ------------------------------------------------------------------
    # 1920x1080 — identity mapping
    # ------------------------------------------------------------------

    def test_identity_center(self) -> None:
        """Center of 1920x1080 reference maps to center of 1920x1080 screen."""
        self.assertEqual(scale_to_screen(960, 540, 1920, 1080), (960, 540))

    def test_identity_top_left(self) -> None:
        """Top-left corner stays at origin on a 1920x1080 screen."""
        self.assertEqual(scale_to_screen(0, 0, 1920, 1080), (0, 0))

    def test_identity_bottom_right(self) -> None:
        """Bottom-right corner maps to (1919, 1079) on 1920x1080."""
        self.assertEqual(scale_to_screen(1919, 1079, 1920, 1080), (1919, 1079))

    # ------------------------------------------------------------------
    # 2560x1080 — ultrawide, pillar-boxed (black bars left and right)
    # ------------------------------------------------------------------
    # s = min(2560/1920, 1080/1080) = min(1.333…, 1.0) = 1.0
    # offset_x = (2560 - 1920*1.0) / 2 = 320
    # offset_y = (1080 - 1080*1.0) / 2 = 0

    def test_ultrawide_center(self) -> None:
        """Center of reference maps to display center on 2560x1080."""
        # ref (960, 540) → (960*1 + 320, 540*1 + 0) = (1280, 540)
        self.assertEqual(scale_to_screen(960, 540, 2560, 1080), (1280, 540))

    def test_ultrawide_top_left_ref(self) -> None:
        """Top-left of reference (0,0) maps to the left pillar edge on 2560x1080."""
        # (0*1 + 320, 0*1 + 0) = (320, 0)
        self.assertEqual(scale_to_screen(0, 0, 2560, 1080), (320, 0))

    def test_ultrawide_bottom_right_ref(self) -> None:
        """Bottom-right reference corner maps correctly on 2560x1080."""
        # (1919*1 + 320, 1079*1 + 0) = (2239, 1079)
        self.assertEqual(scale_to_screen(1919, 1079, 2560, 1080), (2239, 1079))

    # ------------------------------------------------------------------
    # 1920x1200 — 16:10, letter-boxed (black bars top and bottom)
    # ------------------------------------------------------------------
    # s = min(1920/1920, 1200/1080) = min(1.0, 1.111…) = 1.0
    # offset_x = (1920 - 1920*1.0) / 2 = 0
    # offset_y = (1200 - 1080*1.0) / 2 = 60

    def test_16x10_center(self) -> None:
        """Center of reference shifts down by the letterbox offset on 1920x1200."""
        # (960*1 + 0, 540*1 + 60) = (960, 600)
        self.assertEqual(scale_to_screen(960, 540, 1920, 1200), (960, 600))

    def test_16x10_top_left_ref(self) -> None:
        """Top-left reference maps to the top letterbox edge on 1920x1200."""
        # (0 + 0, 0 + 60) = (0, 60)
        self.assertEqual(scale_to_screen(0, 0, 1920, 1200), (0, 60))

    def test_16x10_bottom_right_ref(self) -> None:
        """Bottom-right reference maps correctly on 1920x1200."""
        # (1919 + 0, 1079 + 60) = (1919, 1139)
        self.assertEqual(scale_to_screen(1919, 1079, 1920, 1200), (1919, 1139))

    # ------------------------------------------------------------------
    # 1280x720 — downscale, uniform (no bars either axis)
    # ------------------------------------------------------------------
    # s = min(1280/1920, 720/1080) = min(0.6667, 0.6667) = 0.6667
    # offset_x = (1280 - 1920 * 2/3) / 2 = (1280 - 1280) / 2 = 0
    # offset_y = (720  - 1080 * 2/3) / 2 = (720  - 720)  / 2 = 0
    # s is exactly 2/3

    def test_downscale_center(self) -> None:
        """Center of reference maps exactly to center of 1280x720 (no bars)."""
        # s = 2/3 exactly; (960 * 2/3, 540 * 2/3) = (640, 360)
        self.assertEqual(scale_to_screen(960, 540, 1280, 720), (640, 360))

    def test_downscale_top_left(self) -> None:
        """Top-left of reference maps to origin on 1280x720."""
        self.assertEqual(scale_to_screen(0, 0, 1280, 720), (0, 0))

    def test_downscale_bottom_right(self) -> None:
        """Bottom-right reference maps correctly on 1280x720."""
        # int(round(1919 * 2/3)) = int(round(1279.333…)) = 1279
        # int(round(1079 * 2/3)) = int(round(719.333…))  = 719
        self.assertEqual(scale_to_screen(1919, 1079, 1280, 720), (1279, 719))

    # ------------------------------------------------------------------
    # 3840x2160 — 4K upscale, uniform (no bars either axis)
    # ------------------------------------------------------------------
    # s = min(3840/1920, 2160/1080) = min(2.0, 2.0) = 2.0
    # offset_x = (3840 - 1920 * 2.0) / 2 = 0
    # offset_y = (2160 - 1080 * 2.0) / 2 = 0

    def test_4k_center(self) -> None:
        """Center of reference doubles to 4K center with no letterbox offset."""
        # (960 * 2.0 + 0, 540 * 2.0 + 0) = (1920, 1080)
        self.assertEqual(scale_to_screen(960, 540, 3840, 2160), (1920, 1080))

    def test_4k_top_left(self) -> None:
        """Top-left of reference maps to origin on 3840x2160."""
        # (0 * 2.0 + 0, 0 * 2.0 + 0) = (0, 0)
        self.assertEqual(scale_to_screen(0, 0, 3840, 2160), (0, 0))

    def test_4k_corner_btn_process(self) -> None:
        """BTN_PROCESS (1068, 765) doubles cleanly on 3840x2160."""
        # (1068 * 2.0 + 0, 765 * 2.0 + 0) = (2136, 1530)
        self.assertEqual(scale_to_screen(1068, 765, 3840, 2160), (2136, 1530))

    # ------------------------------------------------------------------
    # Specific button coordinates used by the automation
    # ------------------------------------------------------------------

    def test_btn_process_identity(self) -> None:
        """BTN_PROCESS (1068, 765) is unchanged on native 1920x1080."""
        self.assertEqual(scale_to_screen(1068, 765, 1920, 1080), (1068, 765))

    def test_btn_reset_ultrawide(self) -> None:
        """BTN_RESET (962, 255) on 2560x1080 shifts right by the pillar offset."""
        # (962*1 + 320, 255*1 + 0) = (1282, 255)
        self.assertEqual(scale_to_screen(962, 255, 2560, 1080), (1282, 255))

    def test_btn_reroll_16x10(self) -> None:
        """BTN_REROLL (1254, 595) on 1920x1200 shifts down by the letter offset."""
        # (1254*1 + 0, 595*1 + 60) = (1254, 655)
        self.assertEqual(scale_to_screen(1254, 595, 1920, 1200), (1254, 655))


@unittest.skipUnless(_IMPORT_OK, "arkgrid.automation requires Windows")
class TestBuildResetTable(unittest.TestCase):
    """Regression: run_auto's reset/p_fresh DP table must be effect-aware with
    the side-coeff floor for --min-side-coeff goals, matching the simulator.

    The old code built a plain (non-effect-aware) table that dropped the
    side-coeff requirement entirely, so p_fresh was over-optimistic and auto's
    reset decisions diverged from the simulator's.
    """

    _GEM = "chaos_distortion"  # pool contains attack_power + boss_damage
    _GOAL = LastTurnGoal(min_total_will_chaos=6)
    _MIN_SIDE_COEFF = 4000
    _TURNS = 7
    _START = dict(will=1, chaos=1, first=1, second=1,
                  first_effect="attack_power", second_effect="boss_damage")

    def test_reset_table_matches_simulator_for_min_side_coeff_goal(self):
        pool = OptionPool()
        start = GemState(**self._START)

        auto_tbl = _build_reset_table(
            self._GOAL, self._TURNS, pool,
            gem_type_domain=self._GEM, optimize="dps",
            min_side_coeff=self._MIN_SIDE_COEFF, effect_aware=True)
        # What GemSimulator._get_ea_tables builds for resets.
        sim_tbl = GoalProbabilityTable(
            self._GOAL, self._TURNS, pool,
            min_side_coeff=self._MIN_SIDE_COEFF, early_finish=True,
            effect_aware=True, gem_type=self._GEM, optimize="dps")
        # The old, buggy automation table (plain, side-coeff ignored).
        plain_tbl = GoalProbabilityTable(
            self._GOAL, self._TURNS, pool, early_finish=True)

        p_auto = auto_tbl.lookup(start, self._TURNS)
        p_sim = sim_tbl.lookup(start, self._TURNS)
        p_plain = plain_tbl.lookup(start, self._TURNS)

        self.assertAlmostEqual(
            p_auto, p_sim, places=9,
            msg="auto reset table must match the simulator's effect-aware "
                "reset table for a --min-side-coeff goal")
        self.assertGreater(
            p_plain, p_auto + 1e-6,
            "the plain (non-EA) table over-estimates p_fresh because it "
            "ignores the side-coeff floor — that was the bug")

    def test_unknown_gem_type_falls_back_to_plain_table(self):
        pool = OptionPool()
        tbl = _build_reset_table(
            self._GOAL, self._TURNS, pool,
            gem_type_domain="not_a_real_gem", optimize="dps",
            min_side_coeff=self._MIN_SIDE_COEFF, effect_aware=True)
        self.assertFalse(tbl.effect_aware)


if __name__ == "__main__":
    unittest.main()
