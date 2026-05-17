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


class TestEndgameRiskFlag(unittest.TestCase):
    """Task 5: --endgame-risk parses and defaults to off."""

    def test_default_is_false(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertFalse(args.endgame_risk)

    def test_flag_sets_true(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(
            ["auto", "--min-will", "4", "--endgame-risk"])
        self.assertTrue(args.endgame_risk)


if __name__ == "__main__":
    unittest.main()
