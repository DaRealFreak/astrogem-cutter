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


if __name__ == "__main__":
    unittest.main()
