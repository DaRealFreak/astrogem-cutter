from __future__ import annotations

import random
import unittest

from arkgrid import (
    AstroGem,
    GEM_TYPES,
    GemSimulator,
    GemState,
    LastTurnGoal,
    Option,
)


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
        sim.apply_option(Option("change_first_effect", 1, "other"), s, rng=random.Random(0))
        self.assertEqual(s.first_effect, "attack_power")  # unchanged (no astro_gem)

    def test_change_first_effect_with_astro(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        sim = self._sim(astro_gem=gem)
        s = GemState(first_effect="attack_power", second_effect="ally_damage")
        sim.apply_option(Option("change_first_effect", 1, "other"), s, rng=random.Random(0))
        # chaos_distortion: attack_power, boss_damage, ally_damage, ally_attack
        # available: boss_damage, ally_attack (excl attack_power + ally_damage)
        self.assertIn(s.first_effect, {"boss_damage", "ally_attack"})

    def test_change_second_effect_support_optimise(self) -> None:
        gem = AstroGem("order_fortitude", "attack_power", "ally_damage", "support")
        sim = self._sim(astro_gem=gem)
        s = GemState(first_effect="attack_power", second_effect="ally_damage")
        sim.apply_option(Option("change_second_effect", 1, "other"), s, rng=random.Random(0))
        # order_fortitude: attack_power, boss_damage, ally_damage, ally_attack
        # available: boss_damage, ally_attack (excl attack_power + ally_damage)
        self.assertIn(s.second_effect, {"boss_damage", "ally_attack"})

    def test_change_effect_no_op_without_rng(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        sim = self._sim(astro_gem=gem)
        s = GemState(first_effect="attack_power", second_effect="ally_damage")
        sim.apply_option(Option("change_first_effect", 1, "other"), s)  # no rng
        self.assertEqual(s.first_effect, "attack_power")  # unchanged


class TestResolveEffectChange(unittest.TestCase):
    def _sim(self, gem=None) -> GemSimulator:
        return GemSimulator(
            rarity="common", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(), astro_gem=gem,
        )

    def test_random_from_available_pool(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        sim = self._sim(gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        # available: boss_damage, ally_attack — both should appear across seeds
        results = {sim._resolve_effect_change(state, "first", random.Random(s))
                   for s in range(20)}
        self.assertEqual(results, {"boss_damage", "ally_attack"})

    def test_no_change_without_rng(self) -> None:
        gem = AstroGem("chaos_distortion", "attack_power", "ally_damage", "dps")
        sim = self._sim(gem)
        state = GemState(first_effect="attack_power", second_effect="ally_damage")
        self.assertEqual(sim._resolve_effect_change(state, "first"), "attack_power")

    def test_no_change_without_astro_gem(self) -> None:
        """Without an astro_gem, effect changes are a no-op."""
        sim = self._sim(gem=None)
        state = GemState(first_effect="attack_power")
        self.assertEqual(
            sim._resolve_effect_change(state, "first", random.Random(0)),
            "attack_power")


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


class TestDPRerollIntegration(unittest.TestCase):
    def test_dp_reroll_logs_override_reason(self) -> None:
        """DP override reasons should appear in the turn log."""
        sim = GemSimulator(
            rarity="rare", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            dp_reroll_margin=0.03, use_dp_override=True,
        )
        # Run enough seeds to find at least one DP override
        found_override = False
        for seed in range(200):
            r = sim.simulate_one(seed=seed, log=True)
            for t in (r.turn_log or []):
                for reasons in t.get("reroll_reasons_history", []):
                    if any("dp_override" in r for r in reasons):
                        found_override = True
                        break
                if found_override:
                    break
            if found_override:
                break
        self.assertTrue(found_override,
                        "Expected at least one DP override in 200 seeds")

    def test_dp_reroll_disabled_matches_heuristic_only(self) -> None:
        """With use_dp_override=False, results should differ from enabled."""
        goal = LastTurnGoal(min_will=4, min_chaos=4)
        sim_dp = GemSimulator(
            rarity="rare", use_extra_ticket=True, use_reset_ticket=False,
            goal=goal, use_dp_override=True, dp_reroll_margin=0.03,
        )
        sim_no_dp = GemSimulator(
            rarity="rare", use_extra_ticket=True, use_reset_ticket=False,
            goal=goal, use_dp_override=False,
        )
        # At least one seed should produce different results
        diff_count = sum(
            1 for seed in range(100)
            if sim_dp.simulate_one(seed=seed).success != sim_no_dp.simulate_one(seed=seed).success
        )
        # We don't assert a direction, just that the override changes behavior
        self.assertGreater(diff_count, 0,
                           "DP override should change at least one outcome in 100 seeds")


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


if __name__ == "__main__":
    unittest.main()
