from __future__ import annotations

import unittest

from arkgrid import GemState, LastTurnGoal


class TestLastTurnGoal(unittest.TestCase):
    def test_satisfied_min(self) -> None:
        g = LastTurnGoal(min_will=4, min_chaos=5)
        self.assertTrue(g.satisfied(4, 5))
        self.assertTrue(g.satisfied(5, 5))
        self.assertFalse(g.satisfied(3, 5))
        self.assertFalse(g.satisfied(4, 4))

    def test_satisfied_exact(self) -> None:
        g = LastTurnGoal(exact_will=3, exact_chaos=3)
        self.assertTrue(g.satisfied(3, 3))
        self.assertFalse(g.satisfied(4, 3))
        self.assertFalse(g.satisfied(3, 2))

    def test_satisfied_total(self) -> None:
        g = LastTurnGoal(min_total_will_chaos=8)
        self.assertTrue(g.satisfied(4, 4))
        self.assertTrue(g.satisfied(3, 5))
        self.assertFalse(g.satisfied(3, 4))

    def test_feasible_basic(self) -> None:
        g = LastTurnGoal(min_will=4, min_chaos=5)
        # need will+3 and chaos+4 => 2 turns minimum
        self.assertTrue(g.feasible(1, 1, 2))
        self.assertFalse(g.feasible(1, 1, 1))

    def test_feasible_already_met(self) -> None:
        g = LastTurnGoal(min_will=3, min_chaos=3)
        self.assertTrue(g.feasible(3, 3, 0))

    def test_feasible_exact_overshoot(self) -> None:
        g = LastTurnGoal(exact_will=3)
        self.assertFalse(g.feasible(4, 1, 5))

    def test_feasible_target_above_cap(self) -> None:
        g = LastTurnGoal(min_will=6)
        self.assertFalse(g.feasible(1, 1, 9))

    def test_satisfied_min_total(self) -> None:
        g = LastTurnGoal(min_total=16)
        self.assertTrue(g.satisfied(4, 4, 4, 4))   # total=16
        self.assertTrue(g.satisfied(5, 5, 3, 3))   # total=16
        self.assertTrue(g.satisfied(5, 5, 5, 5))   # total=20
        self.assertFalse(g.satisfied(4, 4, 4, 3))  # total=15
        self.assertFalse(g.satisfied(3, 3, 3, 3))  # total=12

    def test_satisfied_min_total_combined(self) -> None:
        g = LastTurnGoal(min_will=4, min_chaos=5, min_total=16)
        self.assertTrue(g.satisfied(4, 5, 4, 3))   # will/chaos ok, total=16
        self.assertFalse(g.satisfied(3, 5, 4, 4))  # will too low
        self.assertFalse(g.satisfied(4, 5, 3, 3))  # total=15

    def test_feasible_min_total(self) -> None:
        g = LastTurnGoal(min_total=16)
        # starts at 4, need +12, max +4/turn => 3 turns
        self.assertTrue(g.feasible(1, 1, 3, first=1, second=1))
        # starts at 4, need +12, but only 2 turns => max +8 => 12 < 16
        self.assertFalse(g.feasible(1, 1, 2, first=1, second=1))
        # already at 16
        self.assertTrue(g.feasible(4, 4, 0, first=4, second=4))
        # cap at 20: starts at 8, +4*3=12 => 20 >= 16
        self.assertTrue(g.feasible(2, 2, 3, first=2, second=2))

    def test_feasible_side_coeff_default_disabled(self) -> None:
        # min_side_coeff=0 must preserve old behavior (passes when other
        # constraints are met, regardless of effect coefficients).
        g = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertTrue(g.feasible(3, 5, 1, first=1, second=4))

    def test_feasible_side_coeff_unreachable(self) -> None:
        # Case 2 from the bug report: turn 9, w=3 c=5 1st=1 2nd=4,
        # both equipped effects are support (coeff=0 in DPS), turns_left=1.
        # Need will+1 (1 turn) -> 0 turns left for any side_coeff action.
        g = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertFalse(g.feasible(
            3, 5, 1, first=1, second=4,
            min_side_coeff=2000,
            side_coeff_first=0, side_coeff_second=0,
            change_dest_max_coeff=1000,  # boss_damage available via change
        ))

    def test_feasible_side_coeff_via_change(self) -> None:
        # Case 2 turn 8: turns_left=2.  Need will+1 (1 turn) leaves 1 turn,
        # which can change_second_effect -> boss_damage at level 4 (=4000).
        g = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertTrue(g.feasible(
            3, 5, 2, first=1, second=4,
            min_side_coeff=2000,
            side_coeff_first=0, side_coeff_second=0,
            change_dest_max_coeff=1000,
        ))

    def test_feasible_side_coeff_no_change_destination(self) -> None:
        # If both equipped slots and both change destinations are
        # zero-coeff (e.g. support gem cut for DPS), no path exists.
        g = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertFalse(g.feasible(
            3, 5, 5, first=1, second=4,
            min_side_coeff=1000,
            side_coeff_first=0, side_coeff_second=0,
            change_dest_max_coeff=0,
        ))

    def test_feasible_side_coeff_already_met(self) -> None:
        # Equipped second has coeff 1500 at level 4 = 6000 > 2000 already.
        g = LastTurnGoal(min_will=4, min_chaos=3)
        self.assertTrue(g.feasible(
            3, 5, 1, first=1, second=4,
            min_side_coeff=2000,
            side_coeff_first=0, side_coeff_second=1500,
            change_dest_max_coeff=0,
        ))


class TestGemState(unittest.TestCase):
    def test_clone_independence(self) -> None:
        s = GemState(will=3, chaos=2, first=4, second=1, rerolls=2,
                     first_effect="attack_power", second_effect="ally_damage")
        c = s.clone()
        c.will = 5
        c.first_effect = "boss_damage"
        self.assertEqual(s.will, 3)
        self.assertEqual(s.first_effect, "attack_power")

    def test_total_points(self) -> None:
        s = GemState(will=3, chaos=5, first=2, second=4)
        self.assertEqual(s.total_points(), 14)


if __name__ == "__main__":
    unittest.main()
