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

    def test_good_effect_change_dps(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        # change_first can get boss_damage (better DPS) or ally_attack
        self.assertTrue(policy._has_good_effect_change({"change_first_effect"}, state))

    def test_no_good_effect_change_already_best(self) -> None:
        gem = AstroGem("chaos_distortion", "boss_damage", "ally_attack", "dps")
        policy = RerollPolicy(LastTurnGoal(), astro_gem=gem)
        state = GemState(first_effect="boss_damage", second_effect="ally_attack")
        # change_first can get attack_power (worse DPS) or ally_damage (support)
        self.assertFalse(policy._has_good_effect_change({"change_first_effect"}, state))


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
        offers = self._make_offers("first+3", "maintain", "cost-100", "cost+100")
        should, _ = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.75)
        self.assertFalse(should)

    def test_comfortable_rejects_nontarget_only(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=5), astro_gem=gem)
        state = GemState(will=1, first_effect="attack_power", second_effect="ally_damage")
        # second+3 is support-slot -> NOT a target upgrade for DPS
        offers = self._make_offers("second+3", "maintain", "cost-100", "cost+100")
        should, reasons = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=0.75)
        self.assertTrue(should)
        self.assertIn("no_useful_upgrade", reasons)

    def test_good_effect_change_counts_as_upgrade(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        policy = RerollPolicy(LastTurnGoal(min_will=1), astro_gem=gem)
        state = GemState(will=1, first_effect="attack_power", second_effect="ally_damage")
        # goal met, change_first_effect would improve DPS (attack_power -> boss_damage)
        offers = self._make_offers("change_first_effect", "maintain", "cost-100", "cost+100")
        should, _ = policy.should_reroll(offers, state, turns_left=5, goal_feasible_frac=1.0)
        self.assertFalse(should)


if __name__ == "__main__":
    unittest.main()
