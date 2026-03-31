from __future__ import annotations

import random
import unittest

from arkgrid import GemState, Option, OptionPool


class TestOptionPool(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = OptionPool()

    def test_pool_weights_sum_to_100(self) -> None:
        total = sum(o.weight for o in self.pool.pool)
        self.assertAlmostEqual(total, 100.0, places=4)

    def test_pool_has_27_options(self) -> None:
        # 5 per stat (4 stats) + 3 other + 2 cost + 2 view = 27
        self.assertEqual(len(self.pool.pool), 27)

    def test_plus1_weights_match_official(self) -> None:
        for kind in ("will", "chaos", "first", "second"):
            opt = next(o for o in self.pool.pool if o.key == f"{kind}+1")
            self.assertAlmostEqual(opt.weight, 11.6500)

    def test_no_duplicate_keys(self) -> None:
        keys = [o.key for o in self.pool.pool]
        self.assertEqual(len(keys), len(set(keys)))


class TestEligibility(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = OptionPool()
        self.state = GemState()

    def _opt(self, key: str) -> Option:
        return next(o for o in self.pool.pool if o.key == key)

    # --- stat increase caps ---

    def test_plus1_eligible_at_4(self) -> None:
        self.state.will = 4
        self.assertTrue(self.pool.eligible(self._opt("will+1"), self.state, 2, 5))

    def test_plus1_excluded_at_5(self) -> None:
        self.state.will = 5
        self.assertFalse(self.pool.eligible(self._opt("will+1"), self.state, 2, 5))

    def test_plus4_eligible_at_1(self) -> None:
        self.state.chaos = 1
        self.assertTrue(self.pool.eligible(self._opt("chaos+4"), self.state, 2, 5))

    def test_plus4_excluded_at_2(self) -> None:
        self.state.chaos = 2
        self.assertFalse(self.pool.eligible(self._opt("chaos+4"), self.state, 2, 5))

    def test_plus3_excluded_at_3(self) -> None:
        self.state.first = 3
        self.assertFalse(self.pool.eligible(self._opt("first+3"), self.state, 2, 5))

    def test_plus2_excluded_at_4(self) -> None:
        self.state.second = 4
        self.assertFalse(self.pool.eligible(self._opt("second+2"), self.state, 2, 5))

    # --- stat decrease ---

    def test_minus1_eligible_at_2(self) -> None:
        self.state.will = 2
        self.assertTrue(self.pool.eligible(self._opt("will-1"), self.state, 2, 5))

    def test_minus1_excluded_at_1(self) -> None:
        self.state.will = 1
        self.assertFalse(self.pool.eligible(self._opt("will-1"), self.state, 2, 5))

    # --- cost modifiers ---

    def test_cost_plus_excluded_at_100(self) -> None:
        self.state.cost_ratio = 100
        self.assertFalse(self.pool.eligible(self._opt("cost+100"), self.state, 2, 5))

    def test_cost_minus_excluded_at_neg100(self) -> None:
        self.state.cost_ratio = -100
        self.assertFalse(self.pool.eligible(self._opt("cost-100"), self.state, 2, 5))

    def test_cost_excluded_on_last_turn(self) -> None:
        self.assertFalse(self.pool.eligible(self._opt("cost+100"), self.state, 5, 1))
        self.assertFalse(self.pool.eligible(self._opt("cost-100"), self.state, 5, 1))

    def test_cost_eligible_mid_game(self) -> None:
        self.assertTrue(self.pool.eligible(self._opt("cost+100"), self.state, 2, 5))

    # --- view modifiers ---

    def test_view_excluded_on_turn_1(self) -> None:
        self.assertFalse(self.pool.eligible(self._opt("view+1"), self.state, 1, 9))

    def test_view_excluded_on_last_turn(self) -> None:
        self.assertFalse(self.pool.eligible(self._opt("view+1"), self.state, 9, 1))

    def test_view_eligible_mid_game(self) -> None:
        self.assertTrue(self.pool.eligible(self._opt("view+1"), self.state, 2, 5))

    # --- generate offers ---

    def test_generate_offers_returns_4(self) -> None:
        rng = random.Random(42)
        offers = self.pool.generate_offers(self.state, 2, 5, rng)
        self.assertEqual(len(offers), 4)

    def test_generate_offers_no_duplicates(self) -> None:
        rng = random.Random(42)
        offers = self.pool.generate_offers(self.state, 2, 5, rng)
        keys = [o.key for o in offers]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
