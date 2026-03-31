from __future__ import annotations

import math
import random
import unittest

from arkgrid import (
    AstroGem,
    DPS_EFFECTS,
    DPS_PRIORITY,
    GEM_TYPES,
    GemAnalyzer,
    GemSimulator,
    GemState,
    LastTurnGoal,
    Option,
    OptionPool,
    RerollPolicy,
    SUPPORT_EFFECTS,
    SUPPORT_PRIORITY,
)


# ------------------------------------------------------------------ #
#  Pool weights & structure
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
#  Eligibility rules
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
#  apply_option
# ------------------------------------------------------------------ #

class TestApplyOption(unittest.TestCase):
    def _sim(self, astro_gem: AstroGem | None = None) -> GemSimulator:
        return GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), astro_gem=astro_gem,
        )

    def test_will_increase_clamped(self) -> None:
        sim = self._sim()
        s = GemState(will=4)
        sim.apply_option(Option("will+3", 1, "will", 3), s)
        self.assertEqual(s.will, 5)

    def test_will_decrease_clamped(self) -> None:
        sim = self._sim()
        s = GemState(will=1)
        sim.apply_option(Option("will-1", 1, "will", -1), s)
        self.assertEqual(s.will, 1)

    def test_cost_additive_positive(self) -> None:
        sim = self._sim()
        s = GemState(cost_ratio=0)
        sim.apply_option(Option("cost+100", 1, "cost"), s)
        self.assertEqual(s.cost_ratio, 100)

    def test_cost_additive_cancels(self) -> None:
        sim = self._sim()
        s = GemState(cost_ratio=100)
        sim.apply_option(Option("cost-100", 1, "cost"), s)
        self.assertEqual(s.cost_ratio, 0)

    def test_cost_additive_double_negative(self) -> None:
        sim = self._sim()
        s = GemState(cost_ratio=-100)
        sim.apply_option(Option("cost-100", 1, "cost"), s)
        self.assertEqual(s.cost_ratio, -100)  # clamped

    def test_view_adds_rerolls(self) -> None:
        sim = self._sim()
        s = GemState(rerolls=1)
        sim.apply_option(Option("view+2", 1, "view", 2), s)
        self.assertEqual(s.rerolls, 3)

    def test_change_first_effect_no_astro(self) -> None:
        sim = self._sim(astro_gem=None)
        s = GemState(first_effect="attack_power", second_effect="ally_damage")
        sim.apply_option(Option("change_first_effect", 1, "other"), s)
        self.assertEqual(s.first_effect, "attack_power")  # unchanged

    def test_change_first_effect_with_astro(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        sim = self._sim(astro_gem=gem)
        s = GemState(first_effect="attack_power", second_effect="ally_damage")
        sim.apply_option(Option("change_first_effect", 1, "other"), s)
        # chaos_distortion effects: attack_power, boss_damage, ally_damage, ally_attack
        # available: boss_damage, ally_attack (excl attack_power + ally_damage)
        # DPS optimise -> boss_damage preferred
        self.assertEqual(s.first_effect, "boss_damage")

    def test_change_second_effect_support_optimise(self) -> None:
        gem = AstroGem("order_fortitude", "attack_power", "ally_damage", "support")
        sim = self._sim(astro_gem=gem)
        s = GemState(first_effect="attack_power", second_effect="ally_damage")
        sim.apply_option(Option("change_second_effect", 1, "other"), s)
        # order_fortitude effects: attack_power, boss_damage, ally_damage, ally_attack
        # available: boss_damage, ally_attack (excl attack_power + ally_damage)
        # support optimise -> ally_attack preferred
        self.assertEqual(s.second_effect, "ally_attack")


# ------------------------------------------------------------------ #
#  LastTurnGoal
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
#  GemState
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
#  RerollPolicy
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
#  AstroGem effect definitions
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
#  Best effect change resolution
# ------------------------------------------------------------------ #

class TestBestEffectChange(unittest.TestCase):
    def _sim(self, gem: AstroGem) -> GemSimulator:
        return GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), astro_gem=gem,
        )

    def test_picks_boss_damage_for_dps(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        sim = self._sim(gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        # available: boss_damage, ally_attack -> DPS pref -> boss_damage
        self.assertEqual(sim._best_effect_change(state, "first"), "boss_damage")

    def test_picks_ally_attack_for_support(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "support")
        sim = self._sim(gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        # available: boss_damage, ally_attack -> support pref -> ally_attack
        self.assertEqual(sim._best_effect_change(state, "second"), "ally_attack")

    def test_picks_target_over_nontarget(self) -> None:
        # order_stability: attack_power, additional_damage, ally_damage, brand_power
        gem = AstroGem("order_stability", "attack_power", "ally_damage", "dps")
        sim = self._sim(gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        # available: additional_damage (DPS), brand_power (support)
        # DPS optimise -> additional_damage
        self.assertEqual(sim._best_effect_change(state, "first"), "additional_damage")

    def test_no_change_when_astro_gem_attr_none(self) -> None:
        """Before simulate_one sets a run gem, _best_effect_change is a no-op."""
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), astro_gem=None,
        )
        # Before any simulate_one call, astro_gem is still None
        state = GemState(first_effect="attack_power")
        self.assertEqual(sim._best_effect_change(state, "first"), "attack_power")


# ------------------------------------------------------------------ #
#  Simulator integration
# ------------------------------------------------------------------ #

class TestSimulator(unittest.TestCase):
    def test_simulate_one_deterministic(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=5),
        )
        r1 = sim.simulate_one(seed=123)
        r2 = sim.simulate_one(seed=123)
        self.assertEqual(r1.success, r2.success)
        self.assertEqual(r1.total_points, r2.total_points)
        self.assertEqual(r1.state.will, r2.state.will)

    def test_reset_ticket_used_for_hard_goal(self) -> None:
        # Very hard goal on common (5 turns) should frequently trigger reset
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=True,
            goal=LastTurnGoal(min_will=5, min_chaos=5),
        )
        reset_count = sum(
            1 for seed in range(100)
            if sim.simulate_one(seed=seed).reset_used
        )
        self.assertGreater(reset_count, 0, "Reset should be used at least once in 100 trials")

    def test_common_has_5_turns(self) -> None:
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(),
        )
        r = sim.simulate_one(seed=1, log=True)
        click_turns = [t for t in (r.turn_log or []) if t["action"] == "click"]
        self.assertEqual(len(click_turns), 5)

    def test_epic_has_9_turns(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(),
        )
        r = sim.simulate_one(seed=1, log=True)
        click_turns = [t for t in (r.turn_log or []) if t["action"] == "click"]
        self.assertEqual(len(click_turns), 9)

    def test_rerolls_not_used_on_turn_1(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=5, min_chaos=5),
        )
        r = sim.simulate_one(seed=42, log=True)
        turn_1 = next(t for t in (r.turn_log or []) if t["turn"] == 1)
        # turn 1 should have exactly 1 offer set (no rerolls)
        if "offers_history" in turn_1:
            self.assertEqual(len(turn_1["offers_history"]), 1)

    def test_no_astro_gem_generates_random(self) -> None:
        sim = GemSimulator(
            rarity="rare", use_extra_ticket=True, use_reset_ticket=True,
            goal=LastTurnGoal(min_will=3, min_chaos=3),
        )
        r = sim.simulate_one(seed=77)
        # Should complete and have valid effects from some gem type
        self.assertIn(r.reason, ("goal_met", "goal_not_met",
                                 "impossible_no_reset_available",
                                 "forced_fail_no_feasible_path_after_click",
                                 "ended_unexpectedly"))
        self.assertNotEqual(r.state.first_effect, "")
        self.assertNotEqual(r.state.second_effect, "")
        self.assertNotEqual(r.state.first_effect, r.state.second_effect)

    def test_random_gem_deterministic_with_seed(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=3),
        )
        r1 = sim.simulate_one(seed=42)
        r2 = sim.simulate_one(seed=42)
        self.assertEqual(r1.state.first_effect, r2.state.first_effect)
        self.assertEqual(r1.state.second_effect, r2.state.second_effect)
        self.assertEqual(r1.total_points, r2.total_points)

    def test_random_gem_varies_across_seeds(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(),
        )
        effects = set()
        for seed in range(50):
            r = sim.simulate_one(seed=seed)
            effects.add((r.state.first_effect, r.state.second_effect))
        # 50 seeds should produce more than 1 unique effect pair
        self.assertGreater(len(effects), 1)

    def test_optimize_param_used_for_random_gem(self) -> None:
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), optimize="support",
        )
        sim.simulate_one(seed=1)
        self.assertEqual(sim.astro_gem.optimize, "support")

    def test_configured_gem_overrides_optimize(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "support")
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), astro_gem=gem, optimize="dps",
        )
        sim.simulate_one(seed=1)
        # astro_gem.optimize wins over the optimize param
        self.assertEqual(sim.astro_gem.optimize, "support")

    def test_astro_gem_effects_initialised(self) -> None:
        gem = AstroGem("chaos_distortion", "boss_damage", "ally_attack", "dps")
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), astro_gem=gem,
        )
        r = sim.simulate_one(seed=1, log=True)
        turn_1 = (r.turn_log or [])[0]
        self.assertIn(turn_1["state_after"]["first_effect"],
                      set(GEM_TYPES["chaos_distortion"]))

    def test_stats_clamped_1_to_5(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=LastTurnGoal(),
        )
        for seed in range(50):
            r = sim.simulate_one(seed=seed)
            for attr in ("will", "chaos", "first", "second"):
                val = getattr(r.state, attr)
                self.assertGreaterEqual(val, 1, f"seed={seed} {attr}={val}")
                self.assertLessEqual(val, 5, f"seed={seed} {attr}={val}")


# ------------------------------------------------------------------ #
#  Random AstroGem generation
# ------------------------------------------------------------------ #

class TestRandomAstroGem(unittest.TestCase):
    def test_produces_valid_gem(self) -> None:
        rng = random.Random(99)
        gem = GemSimulator._random_astro_gem(rng, "dps")
        self.assertIn(gem.gem_type, GEM_TYPES)
        pool = set(GEM_TYPES[gem.gem_type])
        self.assertIn(gem.first_effect, pool)
        self.assertIn(gem.second_effect, pool)
        self.assertNotEqual(gem.first_effect, gem.second_effect)
        self.assertEqual(gem.optimize, "dps")

    def test_respects_optimize_param(self) -> None:
        rng = random.Random(1)
        gem = GemSimulator._random_astro_gem(rng, "support")
        self.assertEqual(gem.optimize, "support")

    def test_variety_across_seeds(self) -> None:
        types_seen: set = set()
        for seed in range(100):
            gem = GemSimulator._random_astro_gem(random.Random(seed), "dps")
            types_seen.add(gem.gem_type)
        # Should hit multiple gem types across 100 seeds
        self.assertGreater(len(types_seen), 1)


# ------------------------------------------------------------------ #
#  Analyzer
# ------------------------------------------------------------------ #

class TestGemAnalyzer(unittest.TestCase):
    def test_wilson_ci_bounds(self) -> None:
        lo, hi = GemAnalyzer.wilson_ci(0.5, 100)
        self.assertGreater(lo, 0.0)
        self.assertLess(hi, 1.0)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_wilson_ci_zero_trials(self) -> None:
        lo, hi = GemAnalyzer.wilson_ci(0.0, 0)
        self.assertEqual(lo, 0.0)
        self.assertEqual(hi, 1.0)

    def test_estimate_summary_keys(self) -> None:
        sim = GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=3),
        )
        result = GemAnalyzer.estimate_summary(trials=100, simulator=sim, seed=1)
        for key in ("p_success", "p_success_ci_lo", "p_success_ci_hi",
                     "avg_total_points", "p_relic_plus", "p_ancient", "reset_rate"):
            self.assertIn(key, result)

    def test_success_rate_in_range(self) -> None:
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=True,
            goal=LastTurnGoal(min_will=3, min_chaos=3),
        )
        result = GemAnalyzer.estimate_summary(trials=500, simulator=sim, seed=42)
        self.assertGreaterEqual(result["p_success"], 0.0)
        self.assertLessEqual(result["p_success"], 1.0)
        self.assertLessEqual(result["p_success_ci_lo"], result["p_success"])
        self.assertGreaterEqual(result["p_success_ci_hi"], result["p_success"])


# ------------------------------------------------------------------ #
#  Reroll policy with AstroGem + comfortable mode interaction
# ------------------------------------------------------------------ #

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
