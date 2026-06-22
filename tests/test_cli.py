"""Regression tests for CLI argument resolution logic (arkgrid.cli)."""
from __future__ import annotations

import unittest

from arkgrid.cli import _build_parser, _resolve_args


class TestResetTicketVariants(unittest.TestCase):
    """_resolve_args must return reset_variants[0] == False when --reset-ticket
    is omitted, and reset_variants[0] == <value> when it is explicitly passed.

    cmd_sim and cmd_auto both use reset_variants[0] — so these tests pin the
    contract that index 0 is always the correct selection for those commands.
    """

    def _parse_sim(self, extra_args=None):
        parser = _build_parser()
        argv = ["sim", "--min-will", "4", "--min-chaos", "3",
                "--rarity", "epic"]
        if extra_args:
            argv.extend(extra_args)
        args = parser.parse_args(argv)
        _, _, _, reset_variants = _resolve_args(args)
        return reset_variants

    def test_sim_no_flag_gives_false_at_index_0(self):
        """Without --reset-ticket, reset_variants[0] is False (disabled)."""
        rv = self._parse_sim()
        self.assertIs(rv[0], False,
                      "sim without --reset-ticket must default to False at index 0")

    def test_sim_no_flag_yields_both_variants(self):
        """Without --reset-ticket, both variants [False, True] are present for stats."""
        rv = self._parse_sim()
        self.assertEqual(rv, [False, True])

    def test_sim_explicit_flag_gives_true_at_index_0(self):
        """--reset-ticket (bare flag) sets reset_variants to [True]."""
        rv = self._parse_sim(["--reset-ticket"])
        self.assertEqual(rv, [True])
        self.assertIs(rv[0], True)

    def test_sim_no_reset_ticket_flag_gives_false_at_index_0(self):
        """--no-reset-ticket sets reset_variants to [False]."""
        rv = self._parse_sim(["--no-reset-ticket"])
        self.assertEqual(rv, [False])
        self.assertIs(rv[0], False)

    def test_sim_rarity_threshold_at_index_0(self):
        """--reset-ticket epic sets reset_variants to ['epic'] at index 0."""
        rv = self._parse_sim(["--reset-ticket", "epic"])
        self.assertEqual(rv, ["epic"])
        self.assertEqual(rv[0], "epic")

    def _parse_auto(self, extra_args=None):
        parser = _build_parser()
        argv = ["auto", "--min-will", "4", "--min-chaos", "3",
                "--rarity", "epic"]
        if extra_args:
            argv.extend(extra_args)
        args = parser.parse_args(argv)
        _, _, _, reset_variants = _resolve_args(args)
        return reset_variants

    def test_auto_no_flag_gives_false_at_index_0(self):
        """Without --reset-ticket, auto's reset_variants[0] is False (disabled)."""
        rv = self._parse_auto()
        self.assertIs(rv[0], False,
                      "auto without --reset-ticket must default to False at index 0")

    def test_auto_explicit_flag_gives_true_at_index_0(self):
        """--reset-ticket (bare flag) on auto yields [True]."""
        rv = self._parse_auto(["--reset-ticket"])
        self.assertIs(rv[0], True)

    def _parse_stats(self, extra_args=None):
        parser = _build_parser()
        argv = ["stats", "--min-will", "4", "--min-chaos", "3",
                "--rarity", "epic"]
        if extra_args:
            argv.extend(extra_args)
        args = parser.parse_args(argv)
        _, _, _, reset_variants = _resolve_args(args)
        return reset_variants

    def test_stats_no_flag_yields_both_variants(self):
        """Without --reset-ticket, stats receives [False, True] so it iterates both."""
        rv = self._parse_stats()
        self.assertEqual(rv, [False, True],
                         "stats without --reset-ticket must yield [False, True] "
                         "so cmd_stats iterates both variants")


class TestTierFlags(unittest.TestCase):
    """--relic-coeff / --ancient-coeff / --endgame-risk default to None; retired flags gone."""

    def test_relic_ancient_coeff_default_none(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertIsNone(args.relic_coeff)
        self.assertIsNone(args.ancient_coeff)

    def test_relic_ancient_coeff_parse(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(
            ["sim", "--min-will", "4", "--relic-coeff", "3000",
             "--ancient-coeff", "8000"])
        self.assertEqual(args.relic_coeff, 3000)
        self.assertEqual(args.ancient_coeff, 8000)

    def test_endgame_risk_is_float(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(
            ["sim", "--min-will", "4", "--endgame-risk", "2000"])
        self.assertEqual(args.endgame_risk, 2000.0)
        args0 = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertIsNone(args0.endgame_risk)

    def test_retired_flags_rejected(self):
        from arkgrid.cli import _build_parser
        for flag in ("--early-finish-coeff", "--relic-no-early-finish",
                     "--confirm-risk"):
            with self.assertRaises(SystemExit):
                _build_parser().parse_args(
                    ["sim", "--min-will", "4", flag, "1"])


class TestFusionAutoDefaults(unittest.TestCase):
    """The three fusion/endgame knobs default to None (auto)."""

    def _parse_sim(self, extra=None):
        from arkgrid.cli import _build_parser
        parser = _build_parser()
        argv = ["sim", "--min-will", "4", "--min-chaos", "3", "--rarity", "epic"]
        if extra:
            argv.extend(extra)
        return parser.parse_args(argv)

    def test_defaults_are_none(self):
        args = self._parse_sim()
        self.assertIsNone(args.endgame_risk)
        self.assertIsNone(args.relic_coeff)
        self.assertIsNone(args.ancient_coeff)

    def test_explicit_values_parse(self):
        args = self._parse_sim(["--endgame-risk", "500",
                                "--relic-coeff", "3000",
                                "--ancient-coeff", "8000"])
        self.assertEqual(args.endgame_risk, 500.0)
        self.assertEqual(args.relic_coeff, 3000)
        self.assertEqual(args.ancient_coeff, 8000)


class TestWillChaosTotalGoal(unittest.TestCase):
    def test_min_total_will_chaos_parses_and_resolves(self):
        parser = _build_parser()
        args = parser.parse_args(["sim", "--min-total-will-chaos", "8"])
        goal, _, _, _ = _resolve_args(args)
        self.assertEqual(goal.min_total_will_chaos, 8)
        self.assertTrue(goal.satisfied(4, 4))
        self.assertTrue(goal.satisfied(3, 5))
        self.assertFalse(goal.satisfied(3, 4))

    def test_min_total_will_chaos_default_none(self):
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertIsNone(args.min_total_will_chaos)
        goal, _, _, _ = _resolve_args(args)
        self.assertIsNone(goal.min_total_will_chaos)

    def test_ignore_side_node_values_parses(self):
        args = _build_parser().parse_args(
            ["sim", "--min-total-will-chaos", "8", "--ignore-side-node-values"])
        self.assertTrue(args.ignore_side_node_values)

    def test_ignore_side_node_values_default_false(self):
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertFalse(args.ignore_side_node_values)

    def test_reroll_goal_flags_parse(self):
        args = _build_parser().parse_args(
            ["sim", "--min-total-will-chaos", "7", "--reroll-goal", "9",
             "--reroll-goal-threshold", "0.15"])
        self.assertEqual(args.reroll_goal, 9)
        self.assertAlmostEqual(args.reroll_goal_threshold, 0.15)

    def test_reroll_goal_defaults(self):
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertIsNone(args.reroll_goal)
        self.assertEqual(args.reroll_goal_threshold, 0.0)


if __name__ == "__main__":
    unittest.main()
