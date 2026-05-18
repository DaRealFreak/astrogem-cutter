from __future__ import annotations

import unittest

from arkgrid import (
    DPS_COEFF,
    DPS_EFFECTS,
    DPS_PRIORITY,
    GEM_TYPES,
    SUPPORT_COEFF,
    SUPPORT_EFFECTS,
    SUPPORT_PRIORITY,
)
from arkgrid.constants import FUSION_E_POINTS, fusion_avg_coeff


class TestGemTypes(unittest.TestCase):
    def test_each_gem_type_has_2_dps_2_support(self) -> None:
        for name, effects in GEM_TYPES.items():
            dps = [e for e in effects if e in DPS_EFFECTS]
            sup = [e for e in effects if e in SUPPORT_EFFECTS]
            self.assertEqual(len(dps), 2, f"{name} should have 2 DPS effects")
            self.assertEqual(len(sup), 2, f"{name} should have 2 support effects")

    def test_all_effects_covered_by_priorities(self) -> None:
        all_effects = set()
        for effects in GEM_TYPES.values():
            all_effects.update(effects)
        for e in all_effects:
            self.assertTrue(
                e in DPS_PRIORITY or e in SUPPORT_PRIORITY,
                f"{e} missing from priority maps",
            )

    def test_priority_matches_coefficients(self) -> None:
        # Priority ordering must match coefficient ordering
        dps_sorted = sorted(DPS_COEFF, key=lambda e: DPS_COEFF[e])
        prio_sorted = sorted(DPS_PRIORITY, key=lambda e: DPS_PRIORITY[e])
        self.assertEqual(dps_sorted, prio_sorted)

        sup_sorted = sorted(SUPPORT_COEFF, key=lambda e: SUPPORT_COEFF[e])
        sprio_sorted = sorted(SUPPORT_PRIORITY, key=lambda e: SUPPORT_PRIORITY[e])
        self.assertEqual(sup_sorted, sprio_sorted)

    def test_order_chaos_pairs_share_effects(self) -> None:
        self.assertEqual(
            set(GEM_TYPES["order_stability"]),
            set(GEM_TYPES["chaos_erosion"]),
        )
        self.assertEqual(
            set(GEM_TYPES["order_fortitude"]),
            set(GEM_TYPES["chaos_distortion"]),
        )
        self.assertEqual(
            set(GEM_TYPES["order_immutability"]),
            set(GEM_TYPES["chaos_collapse"]),
        )


class TestFusionAvgCoeff(unittest.TestCase):
    """fusion_avg_coeff = pool_coeff_sum * E[points|grade] / 8."""

    def test_dps_immutability(self) -> None:
        # order_immutability DPS pool = additional_damage 700 + boss_damage 1000
        # relic:  1700 * 16.25 / 8 = 3453.125 -> 3453
        # ancient: 1700 * 19.05 / 8 = 4048.125 -> 4048
        self.assertEqual(fusion_avg_coeff("order_immutability", "dps", "relic"), 3453)
        self.assertEqual(fusion_avg_coeff("order_immutability", "dps", "ancient"), 4048)

    def test_dps_fortitude(self) -> None:
        # order_fortitude DPS pool = attack_power 400 + boss_damage 1000 = 1400
        self.assertEqual(fusion_avg_coeff("order_fortitude", "dps", "relic"), 2844)
        self.assertEqual(fusion_avg_coeff("order_fortitude", "dps", "ancient"), 3334)

    def test_support_fortitude(self) -> None:
        # order_fortitude SUPPORT pool = ally_damage 600 + ally_attack 1500 = 2100
        self.assertEqual(fusion_avg_coeff("order_fortitude", "support", "relic"), 4266)
        self.assertEqual(fusion_avg_coeff("order_fortitude", "support", "ancient"), 5001)

    def test_order_chaos_pairs_share_pool(self) -> None:
        # order/chaos pairs share an effect pool -> identical averages
        self.assertEqual(
            fusion_avg_coeff("order_stability", "dps", "relic"),
            fusion_avg_coeff("chaos_erosion", "dps", "relic"),
        )

    def test_unknown_gem_type_returns_zero(self) -> None:
        self.assertEqual(fusion_avg_coeff("", "dps", "relic"), 0)

    def test_e_points_keys(self) -> None:
        self.assertEqual(set(FUSION_E_POINTS), {"legendary", "relic", "ancient"})

    def test_legendary_grade(self) -> None:
        # order_immutability dps pool 1700: round(1700 * 9.62 / 8)
        #   = round(2044.25) = 2044
        self.assertEqual(
            fusion_avg_coeff("order_immutability", "dps", "legendary"), 2044)


if __name__ == "__main__":
    unittest.main()
