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
