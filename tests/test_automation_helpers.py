"""Unit tests for pure helpers extracted from arkgrid.automation.

The run_auto loop itself is interactive/Windows-bound and has no test
harness; these helpers carry the logic that used to be inline.

Usage:
    python -m unittest tests.test_automation_helpers -v
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from arkgrid.automation import _offer_signature, _run_success, _still_waiting
from arkgrid.models import GemState, LastTurnGoal


def _det(cards):
    return SimpleNamespace(options=[
        SimpleNamespace(name_key=n, delta_key=d) for n, d in cards
    ])


_HAND_A = (("will", "+1"), ("chaos", "+2"), ("first", "-1"), ("maintain", ""))
_HAND_B = (("will", "+3"), ("cost", "+100"), ("second", "+1"), ("view", "+1"))


class TestOfferSignature(unittest.TestCase):
    def test_full_hand_yields_signature(self):
        self.assertEqual(_offer_signature(_det(_HAND_A)), _HAND_A)

    def test_incomplete_hand_yields_none(self):
        # Mid-animation frames: fewer than 4 cards or unmatched names.
        self.assertIsNone(_offer_signature(_det(_HAND_A[:3])))
        self.assertIsNone(_offer_signature(
            _det(((None, "+1"),) + _HAND_A[1:])))


class TestStillWaiting(unittest.TestCase):
    """Post-action settle gate. Regression: after a Charge (ticket) reroll
    neither the turn nor the free-reroll counter changes, so a gate keyed on
    (turn, rerolls) alone waited forever — the offer-card signature is the
    release signal there.
    """

    def test_charge_reroll_releases_on_new_offers(self):
        waiting = (3, "0", None, _HAND_A)
        self.assertFalse(_still_waiting(3, "0", _HAND_B, waiting))

    def test_same_offers_keep_waiting(self):
        waiting = (3, "0", None, _HAND_A)
        self.assertTrue(_still_waiting(3, "0", _HAND_A, waiting))

    def test_incomplete_detection_keeps_waiting(self):
        waiting = (3, "0", None, _HAND_A)
        self.assertTrue(_still_waiting(3, "0", None, waiting))

    def test_free_reroll_releases_on_counter_change(self):
        waiting = (3, "2", None, _HAND_A)
        self.assertFalse(_still_waiting(3, "1", _HAND_A, waiting))

    def test_process_releases_on_turn_change(self):
        waiting = (3, "1", None, None)
        self.assertFalse(_still_waiting(4, "1", _HAND_A, waiting))

    def test_reset_waits_for_target_turn(self):
        waiting = (5, "1", 1, None)
        self.assertTrue(_still_waiting(5, "1", _HAND_B, waiting))
        self.assertFalse(_still_waiting(1, "1", _HAND_B, waiting))


class TestRunSuccess(unittest.TestCase):
    """End-of-gem success must mirror the simulator's check — including the
    bis_only target-effect requirement the auto JSONL used to omit.
    """

    def _state(self, first_effect="boss_damage", second_effect="attack_power"):
        return GemState(will=5, chaos=5, first=3, second=3,
                        first_effect=first_effect,
                        second_effect=second_effect)

    def test_goal_met_on_target_effects(self):
        goal = LastTurnGoal(min_will=5, min_chaos=5)
        self.assertTrue(_run_success(goal, self._state(), "dps",
                                     bis_only=False, min_side_coeff=0))

    def test_bis_only_rejects_off_target_effect(self):
        goal = LastTurnGoal(min_will=5, min_chaos=5)
        state = self._state(second_effect="ally_damage")
        self.assertTrue(_run_success(goal, state, "dps",
                                     bis_only=False, min_side_coeff=0))
        self.assertFalse(_run_success(goal, state, "dps",
                                      bis_only=True, min_side_coeff=0))

    def test_min_side_coeff_floor(self):
        goal = LastTurnGoal(min_will=5, min_chaos=5)
        # 3*1000 + 3*400 = 4200
        self.assertTrue(_run_success(goal, self._state(), "dps",
                                     bis_only=False, min_side_coeff=4200))
        self.assertFalse(_run_success(goal, self._state(), "dps",
                                      bis_only=False, min_side_coeff=4201))


if __name__ == "__main__":
    unittest.main()
