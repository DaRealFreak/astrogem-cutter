from __future__ import annotations

import unittest

from arkgrid import (
    AstroGem,
    GemState,
    LastTurnGoal,
    Option,
    OptionPool,
    RerollPolicy,
)


class TestRerollPolicy(unittest.TestCase):
    def _make_offers(self, *keys: str) -> list[Option]:
        pool = OptionPool()
        lookup = {o.key: o for o in pool.pool}
        return [lookup[k] for k in keys]

    def test_last_turn_goal_not_met_triggers_reroll(self) -> None:
        policy = RerollPolicy(LastTurnGoal(min_will=5))
        state = GemState(will=3)
        offers = self._make_offers("will+1", "first+1", "second+1", "maintain")
        should, reasons = policy.should_reroll(offers, state, turns_left=1, goal_feasible_frac=1.0)
        self.assertTrue(should)
        self.assertIn("last_turn_goal_not_met", reasons)

    def test_goal_met_no_positive_triggers_reroll(self) -> None:
        policy = RerollPolicy(LastTurnGoal(min_will=1))
        state = GemState(will=1)
        offers = self._make_offers("maintain", "change_first_effect",
                                   "change_second_effect", "cost+100")
        should, reasons = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=1.0)
        self.assertTrue(should)
        self.assertIn("goal_met_no_positive_upgrade", reasons)

    def test_goal_met_accepts_upgrade(self) -> None:
        policy = RerollPolicy(LastTurnGoal(min_will=1))
        state = GemState(will=1)
        offers = self._make_offers("first+1", "second+1", "maintain", "cost-100")
        should, _ = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=1.0)
        self.assertFalse(should)

    def test_desperate_no_goal_upgrade_triggers_reroll(self) -> None:
        policy = RerollPolicy(LastTurnGoal(min_will=5))
        state = GemState(will=1)
        offers = self._make_offers("first+1", "second+1", "maintain", "cost-100")
        should, reasons = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.25)
        self.assertTrue(should)
        self.assertIn("no_goal_upgrade", reasons)

    def test_comfortable_accepts_side_upgrade(self) -> None:
        policy = RerollPolicy(LastTurnGoal(min_will=5), side_node_threshold=0.5)
        state = GemState(will=1)
        offers = self._make_offers("first+3", "second+1", "maintain", "cost-100")
        should, _ = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.75)
        self.assertFalse(should)

    def test_infeasible_triggers_reroll(self) -> None:
        policy = RerollPolicy(LastTurnGoal(min_will=5))
        state = GemState(will=1)
        offers = self._make_offers("first+1", "second+1", "maintain", "cost-100")
        should, reasons = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.0)
        self.assertTrue(should)
        self.assertIn("no_offer_keeps_goal_feasible", reasons)

    # --- target-aware side sets ---

    def test_target_side_sets_no_astro(self) -> None:
        policy = RerollPolicy(LastTurnGoal())
        ups, big = policy._target_side_sets(GemState())
        self.assertEqual(ups, RerollPolicy.SIDE_UPGRADES)
        self.assertEqual(big, RerollPolicy.SIDE_BIG_UPGRADES)

    def test_target_side_sets_dps_first_slot(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        ups, big = policy._target_side_sets(state)
        # only first slot is DPS
        self.assertIn("first+1", ups)
        self.assertIn("first+3", big)
        self.assertNotIn("second+1", ups)

    def test_target_side_sets_support_second_slot(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "support")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        ups, _ = policy._target_side_sets(state)
        self.assertNotIn("first+1", ups)
        self.assertIn("second+1", ups)

    # --- good effect change detection ---

    def test_good_effect_change_resolved_to_target(self) -> None:
        gem = AstroGem("order_stability", "ally_damage", "brand_power", "dps")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="ally_damage", second_effect="brand_power")
        # resolved to attack_power (DPS target) → good
        offers = [Option("change_first_effect", 1, "other", resolved_effect="attack_power")]
        self.assertTrue(policy._has_good_effect_change(offers, state))

    def test_bad_effect_change_resolved_to_nontarget(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        # resolved to ally_attack (support) → bad for DPS
        offers = [Option("change_first_effect", 1, "other", resolved_effect="ally_attack")]
        self.assertFalse(policy._has_good_effect_change(offers, state))

    def test_no_good_effect_change_without_resolved(self) -> None:
        gem = AstroGem("chaos_distortion", "boss_damage", "ally_attack", "dps")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="boss_damage", second_effect="ally_attack")
        # no resolved_effect → not good
        offers = [Option("change_first_effect", 1, "other")]
        self.assertFalse(policy._has_good_effect_change(offers, state))


class TestDPOverride(unittest.TestCase):
    """Tests for the DP-based reroll override logic."""

    def _make_offers(self, *keys: str) -> list[Option]:
        pool = OptionPool()
        lookup = {o.key: o for o in pool.pool}
        return [lookup[k] for k in keys]

    def test_dp_override_rerolls_below_baseline(self) -> None:
        """Heuristic accepts (will+1 present) but offers are below baseline → reroll."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        state = GemState(will=1)
        offers = self._make_offers("will+1", "maintain", "cost+100", "view+1")
        should, reasons = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.75,
            goal_success_prob=0.10, dp_baseline=0.25, rerolls_remaining=2)
        self.assertTrue(should)
        self.assertIn("dp_override_below_baseline", reasons)

    def test_dp_override_keeps_above_baseline(self) -> None:
        """Heuristic rerolls (no goal upgrade) but offers are above baseline → don't reroll."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        state = GemState(will=1)
        offers = self._make_offers("first+1", "second+1", "maintain", "cost-100")
        # Heuristic says reroll (no goal upgrade in desperate mode)
        # But DP says these offers are above baseline
        should, reasons = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.25,
            goal_success_prob=0.30, dp_baseline=0.25, rerolls_remaining=1)
        self.assertFalse(should)
        self.assertIn("dp_override_above_baseline", reasons)

    def test_dp_override_respects_hard_constraint_last_turn(self) -> None:
        """Never override last_turn_goal_not_met."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        state = GemState(will=3)
        offers = self._make_offers("will+1", "first+1", "second+1", "maintain")
        should, reasons = policy.should_reroll(
            offers, state, turns_left=1, goal_feasible_frac=1.0,
            goal_success_prob=0.90, dp_baseline=0.10, rerolls_remaining=1)
        self.assertTrue(should)
        self.assertIn("last_turn_goal_not_met", reasons)

    def test_dp_override_respects_hard_constraint_infeasible(self) -> None:
        """Never override no_offer_keeps_goal_feasible."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        state = GemState(will=1)
        offers = self._make_offers("first+1", "second+1", "maintain", "cost-100")
        should, reasons = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.0,
            goal_success_prob=0.50, dp_baseline=0.20, rerolls_remaining=1)
        self.assertTrue(should)
        self.assertIn("no_offer_keeps_goal_feasible", reasons)

    def test_dp_override_margin_scales_with_surplus_rerolls(self) -> None:
        """Surplus rerolls reduce effective margin, making reroll easier."""
        # Use turns_left=2 to avoid last_turn_goal_not_met hard constraint
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.10)
        state = GemState(will=1)
        offers = self._make_offers("will+1", "maintain", "cost+100", "view+1")

        # Borderline case: p_current=0.23, dp_baseline=0.25
        # With 2 turns left and 6 rerolls: effective_margin = 0.10 * (2/6) ≈ 0.033
        # threshold = 0.25 * (1 - 0.033) = 0.242 → 0.23 < 0.242 → reroll
        should_surplus, reasons_s = policy.should_reroll(
            offers, state, turns_left=2, goal_feasible_frac=0.75,
            goal_success_prob=0.23, dp_baseline=0.25, rerolls_remaining=6)
        self.assertTrue(should_surplus)
        self.assertIn("dp_override_below_baseline", reasons_s)

        # With 2 turns left and 2 rerolls: effective_margin = 0.10 * (2/2) = 0.10
        # threshold = 0.25 * (1 - 0.10) = 0.225 → 0.23 > 0.225 → don't reroll
        should_scarce, reasons_sc = policy.should_reroll(
            offers, state, turns_left=2, goal_feasible_frac=0.75,
            goal_success_prob=0.23, dp_baseline=0.25, rerolls_remaining=2)
        self.assertFalse(should_scarce)

    def test_dp_override_none_values_passthrough(self) -> None:
        """When dp_baseline or goal_success_prob is None, heuristic passes through."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        state = GemState(will=1)
        offers = self._make_offers("will+1", "maintain", "cost+100", "view+1")
        should, _ = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.25,
            goal_success_prob=0.05, dp_baseline=None, rerolls_remaining=2)
        # Heuristic accepts (will+1 is goal upgrade), no override without dp_baseline
        self.assertFalse(should)

    def test_side_quality_keeps_high_value_upgrade(self) -> None:
        """A +4 boss_damage suppresses reroll even when goal prob is below baseline."""
        gem = AstroGem("chaos_distortion", "boss_damage", "ally_attack", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03,
                              astro_gem=gem, side_quality_weight=2.0)
        state = GemState(will=1, first_effect="boss_damage", second_effect="ally_attack")
        # Heuristic says reroll (no goal upgrade in desperate mode).
        # p_current=0.23 < p_baseline=0.25, but +4 boss_damage quality=1.0
        # side_adjustment = 1.0 * 0.03 * 2 = 0.06
        # Case 2 threshold: 0.25 * (1 - 0.06) = 0.235 → 0.23 < 0.235 → still rerolls
        # But at p_current=0.24: 0.24 >= 0.235 → suppresses reroll
        offers = self._make_offers("first+4", "will-1", "maintain", "cost+100")
        should, reasons = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.25,
            goal_success_prob=0.24, dp_baseline=0.25, rerolls_remaining=1)
        self.assertFalse(should)
        self.assertIn("dp_override_above_baseline", reasons)

    def test_side_quality_low_coeff_less_impact(self) -> None:
        """A +2 attack_power has much less impact than a +4 boss_damage."""
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03,
                              astro_gem=gem, side_quality_weight=2.0)
        state = GemState(will=1, first_effect="attack_power", second_effect="ally_damage")
        # +2 attack_power: quality = (2/4) * (400/1000) = 0.2
        # side_adjustment = 0.2 * 0.03 * 2 = 0.012
        # Case 2 threshold: 0.25 * (1 - 0.012) = 0.247
        # p_current=0.24 < 0.247 → does NOT suppress reroll
        offers = self._make_offers("first+2", "will-1", "maintain", "cost+100")
        should, _ = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.25,
            goal_success_prob=0.24, dp_baseline=0.25, rerolls_remaining=1)
        self.assertTrue(should)

    def test_side_quality_no_astro_gem(self) -> None:
        """Without astro_gem, side quality is 0 and doesn't affect the margin."""
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        state = GemState(will=1)
        offers = self._make_offers("first+4", "will-1", "maintain", "cost+100")
        # No astro_gem → side_quality=0, no adjustment
        # Heuristic: desperate, has will-1 downgrade, no big goal upgrade → reroll
        # DP: p_current=0.24 < p_baseline=0.25 → doesn't suppress
        should, _ = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.25,
            goal_success_prob=0.24, dp_baseline=0.25, rerolls_remaining=1)
        self.assertTrue(should)

    def test_side_quality_prevents_reroll_override(self) -> None:
        """Side quality prevents DP from overriding heuristic to reroll when good sides present."""
        gem = AstroGem("order_immutability", "boss_damage", "ally_attack", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03,
                              astro_gem=gem, side_quality_weight=2.0)
        state = GemState(will=3, first_effect="boss_damage", second_effect="ally_attack")
        offers = self._make_offers("will+1", "first+3", "maintain", "cost+100")
        # Heuristic: don't reroll (will+1 is goal upgrade).
        # +3 boss_damage: quality = (3/4)*1.0 = 0.75
        # side_adjustment = 0.75 * 0.03 * 2 = 0.045
        # effective_margin = 0.03 + 0.045 = 0.075
        # threshold = 0.25 * (1 - 0.075) = 0.25 * 0.925 = 0.23125
        # p_current=0.235 > 0.23125 → does NOT override to reroll
        should, _ = policy.should_reroll(
            offers, state, turns_left=5, goal_feasible_frac=0.75,
            goal_success_prob=0.235, dp_baseline=0.25, rerolls_remaining=1)
        self.assertFalse(should)

        # Without side bonus (no astro_gem): margin=0.03
        # threshold = 0.25 * 0.97 = 0.2425 → 0.235 < 0.2425 → WOULD reroll
        policy_no_gem = RerollPolicy(LastTurnGoal(min_will=5), dp_reroll_margin=0.03)
        should2, reasons2 = policy_no_gem.should_reroll(
            offers, GemState(will=3), turns_left=5, goal_feasible_frac=0.75,
            goal_success_prob=0.235, dp_baseline=0.25, rerolls_remaining=1)
        self.assertTrue(should2)
        self.assertIn("dp_override_below_baseline", reasons2)


class TestRerollPolicyAstroGem(unittest.TestCase):
    """Verify the reroll policy correctly filters side-node upgrades by target."""

    def _make_offers(self, *keys: str) -> list[Option]:
        pool = OptionPool()
        lookup = {o.key: o for o in pool.pool}
        return [lookup[k] for k in keys]

    def test_comfortable_accepts_target_side_upgrade(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=5), astro_gem=gem)
        state = GemState(will=1, first_effect="attack_power", second_effect="ally_damage")
        # first+3 is a DPS-slot upgrade -> target side upgrade
        # attack_power has coeff 400 -> effective threshold = 0.8, so frac must exceed that
        offers = self._make_offers("first+3", "maintain", "cost-100", "cost+100")
        should, _ = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.9)
        self.assertFalse(should)

    def test_comfortable_rejects_nontarget_only(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=5), astro_gem=gem)
        state = GemState(will=1, first_effect="attack_power", second_effect="ally_damage")
        # second+3 is support-slot -> NOT a target upgrade for DPS
        offers = self._make_offers("second+3", "maintain", "cost-100", "cost+100")
        should, reasons = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.9)
        self.assertTrue(should)
        self.assertIn("no_useful_upgrade", reasons)

    def test_good_effect_change_counts_as_upgrade(self) -> None:
        gem = AstroGem("order_stability", "ally_damage", "brand_power", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=1), astro_gem=gem)
        state = GemState(will=1, first_effect="ally_damage", second_effect="brand_power")
        # goal met, change_first resolved to attack_power (DPS) → counts as positive
        pool = OptionPool()
        lookup = {o.key: o for o in pool.pool}
        offers = [
            Option("change_first_effect", lookup["change_first_effect"].weight,
                   "other", resolved_effect="attack_power"),
            lookup["maintain"], lookup["cost-100"], lookup["cost+100"],
        ]
        should, _ = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=1.0)
        self.assertFalse(should)


if __name__ == "__main__":
    unittest.main()
