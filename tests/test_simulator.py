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
        # Re-baselined for the side-value finish: this seed's gem has two
        # support effects (ally_damage/ally_attack), so under the default
        # dps optimize its side value is always 0.  The side-value DP
        # finishes turn 9 (the last turn) instead of clicking a worthless
        # final offer — turns 1-8 click, turn 9 is EARLY_FINISH.  The epic
        # 9-turn budget is still verified: the run reaches turn 9.
        turns_reached = max(t["turn"] for t in (r.turn_log or []))
        self.assertEqual(turns_reached, 9)
        click_turns = [t for t in (r.turn_log or []) if t["action"] == "click"]
        self.assertEqual(len(click_turns), 8)

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
    def test_dp_reroll_logs_optimal_reason(self) -> None:
        """DP-optimal reroll reasons should appear in the turn log."""
        sim = GemSimulator(
            rarity="rare", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
        )
        # Run enough seeds to find at least one DP-optimal reroll
        found_reroll = False
        for seed in range(200):
            r = sim.simulate_one(seed=seed, log=True)
            for t in (r.turn_log or []):
                for reasons in t.get("reroll_reasons_history", []):
                    if "dp_reroll_optimal" in reasons:
                        found_reroll = True
                        break
                if found_reroll:
                    break
            if found_reroll:
                break
        self.assertTrue(found_reroll,
                        "Expected at least one DP-optimal reroll in 200 seeds")

    def test_rerolls_saved_for_late_turns(self) -> None:
        """DP-optimal rerolls should distribute more rerolls to late turns."""
        goal = LastTurnGoal(min_will=4, min_chaos=4)
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=goal,
        )
        early_rerolls = 0
        late_rerolls = 0
        for seed in range(500):
            r = sim.simulate_one(seed=seed)
            if r.rerolls_by_turn:
                for turn, count in r.rerolls_by_turn.items():
                    if turn <= 3:
                        early_rerolls += count
                    elif turn >= 7:
                        late_rerolls += count
        self.assertGreater(late_rerolls, early_rerolls,
                           "DP-optimal should use more rerolls late than early")


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


class TestSimulatorConfirmObservability(unittest.TestCase):
    """A gated turn leaves a `confirm` marker in the turn log; the
    simulator still executes the recommended action."""

    def test_confirm_marker_recorded(self):
        # confirm_min_coeff=1 -> gate active for any gem with side coeff;
        # run enough trials that at least one gem hits a gated turn.
        seen_confirm = False
        for seed in range(40):
            sim = GemSimulator(
                rarity="epic", use_extra_ticket=False,
                use_reset_ticket=False,
                goal=LastTurnGoal(min_will=4, min_chaos=3),
                astro_gem=AstroGem("chaos_distortion", "boss_damage",
                                   "attack_power", "dps"),
                confirm_min_coeff=1,
            )
            r = sim.simulate_one(seed=seed, log=True)
            if r.turn_log and any("confirm" in e for e in r.turn_log):
                seen_confirm = True
                break
        self.assertTrue(seen_confirm,
                        "expected at least one gated turn across 40 seeds")


class TestRelicRerollTableSizing(unittest.TestCase):
    """When relic_reroll_threshold > 0, the reroll-aware DP tables must be
    sized to base_rerolls + 1 so that the mid-run override (state.rerolls += 1)
    is never clamped by GoalProbabilityTable.lookup."""

    def test_relic_threshold_active_sizes_tables_to_base_plus_one(self):
        # epic: RARITY_REROLLS=2, use_extra_ticket=False -> base_rerolls=2
        # relic_reroll_threshold > 0 -> dp_max_rerolls should be 3
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=3),
            relic_reroll_threshold=0.2,
        )
        expected = sim.base_rerolls + 1
        self.assertEqual(sim.prob_table._max_rerolls, expected,
                         "prob_table must be sized for the post-override reroll count")

    def test_relic_threshold_inactive_keeps_base_rerolls(self):
        # relic_reroll_threshold=0.0 (default) -> dp_max_rerolls == base_rerolls
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=3),
            relic_reroll_threshold=0.0,
        )
        self.assertEqual(sim.prob_table._max_rerolls, sim.base_rerolls,
                         "prob_table must equal base_rerolls when override is disabled")

    def test_relic_table_also_sized_to_base_plus_one(self):
        # The relic+ DP table must also cover base_rerolls + 1
        sim = GemSimulator(
            rarity="rare", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=3, min_chaos=3),
            relic_reroll_threshold=0.15,
        )
        # sim.base_rerolls = RARITY_REROLLS["rare"](1) + extra_ticket(1) = 2
        # relic_reroll_threshold > 0 adds +1 -> expected = sim.base_rerolls + 1 = 3
        self.assertIsNotNone(sim._relic_prob_table)
        self.assertEqual(sim._relic_prob_table._max_rerolls, sim.base_rerolls + 1)

    def test_ea_tables_reroll_sized_to_base_plus_one(self):
        # Effect-aware tables built by _get_ea_tables must also respect the
        # dp_max_rerolls = base_rerolls + 1 sizing when relic_reroll_threshold > 0.
        # sim.base_rerolls = RARITY_REROLLS["epic"](2) + extra_ticket(0) = 2
        # relic_reroll_threshold > 0 adds +1 -> expected = sim.base_rerolls + 1 = 3
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=3),
            relic_reroll_threshold=0.2,
            effect_aware=True,
        )
        reroll_tbl, reset_tbl = sim._get_ea_tables("chaos_collapse")
        expected = sim.base_rerolls + 1
        # Reroll-aware EA table must be sized to base_rerolls + 1
        self.assertEqual(reroll_tbl._max_rerolls, expected,
                         "EA reroll table must be sized for the post-override reroll count")
        # Reset table is not reroll-aware: it should NOT be sized up
        self.assertNotEqual(reset_tbl._max_rerolls, expected,
                            "EA reset table should not be sized up (non-reroll-aware)")


class TestEndgameRiskPlumbing(unittest.TestCase):
    """Task 5: GemSimulator stores endgame_risk and forwards it onto
    the DecisionContext."""

    def test_decision_context_carries_flag(self):
        from arkgrid.models import LastTurnGoal
        from arkgrid.simulator import GemSimulator
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            endgame_risk=1500.0,
        )
        self.assertEqual(sim.endgame_risk, 1500.0)
        self.assertEqual(sim._decision_context().endgame_risk, 1500.0)

    def test_default_is_none(self):
        # endgame_risk=None means auto-gate (fusion default), not 0.0
        from arkgrid.models import LastTurnGoal
        from arkgrid.simulator import GemSimulator
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
        )
        self.assertIsNone(sim.endgame_risk)


class TestSideValueTableWiring(unittest.TestCase):
    """Task 2: GemSimulator builds a per-gem-type side-value table and
    threads it into the DecisionContext."""

    def test_side_value_table_built_for_configured_gem(self):
        from arkgrid.models import AstroGem
        from arkgrid.probability import SideValueTable
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            relic_coeff=3000, ancient_coeff=8000,
        )
        sim.simulate_one(seed=1)
        tbl = sim._get_side_value_table("order_fortitude")
        self.assertIsInstance(tbl, SideValueTable)
        self.assertTrue(tbl.enabled)
        # Cached: a second call returns the same object.
        self.assertIs(tbl, sim._get_side_value_table("order_fortitude"))

    def test_decision_context_carries_side_value_table(self):
        from arkgrid.models import AstroGem
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
        )
        sim.simulate_one(seed=1)
        ctx = sim._decision_context()
        self.assertIsNotNone(ctx.side_value_table)

    def test_relic_ancient_coeff_default_none(self):
        # relic_coeff / ancient_coeff = None means resolve fusion default
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
        )
        self.assertIsNone(sim.relic_coeff)
        self.assertIsNone(sim.ancient_coeff)


class TestIgnoreSideNodeValuesTables(unittest.TestCase):
    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=8), optimize="dps",
        )
        defaults.update(kw)
        return GemSimulator(**defaults)

    def test_side_value_table_uses_will_chaos_mode_when_set(self):
        sim = self._sim(ignore_side_node_values=True)
        svt = sim._get_side_value_table("order_fortitude")
        self.assertEqual(svt.value_mode, "will_chaos")

    def test_grade_value_table_stays_side_mode_when_set(self):
        sim = self._sim(ignore_side_node_values=True)
        gvt = sim._get_grade_value_table("order_fortitude")
        self.assertEqual(gvt.value_mode, "side")

    def test_default_side_value_table_is_side_mode(self):
        sim = self._sim()
        svt = sim._get_side_value_table("order_fortitude")
        self.assertEqual(svt.value_mode, "side")


class TestRerollGoalThreshold(unittest.TestCase):
    """--reroll-goal / --reroll-goal-threshold re-enables a coeff-gated extra
    reroll ticket when P(will+chaos >= reroll_goal) crosses the threshold."""

    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=7),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            optimize="dps", effect_aware=True,
            reroll_min_coeff=99999,  # gate the extra ticket OFF for any gem
        )
        defaults.update(kw)
        return GemSimulator(**defaults)

    def test_grants_ticket_when_prob_crosses(self):
        # ticket gated off by reroll_min_coeff, but P(will+chaos>=8) easily
        # exceeds 1% -> override re-enables the extra ticket.
        sim = self._sim(reroll_goal=8, reroll_goal_threshold=0.01)
        r = sim.simulate_one(seed=1)
        self.assertTrue(r.extra_ticket_used)

    def test_no_flag_keeps_ticket_gated(self):
        sim = self._sim()  # no reroll_goal
        r = sim.simulate_one(seed=1)
        self.assertFalse(r.extra_ticket_used)

    def test_unreachable_threshold_does_not_grant(self):
        # threshold above 1.0 can never be crossed.
        sim = self._sim(reroll_goal=8, reroll_goal_threshold=2.0)
        r = sim.simulate_one(seed=1)
        self.assertFalse(r.extra_ticket_used)

    def test_no_extra_ticket_overrides_everything(self):
        # --no-extra-ticket is absolute: override must not fire.
        sim = self._sim(use_extra_ticket=False,
                        reroll_goal=8, reroll_goal_threshold=0.01)
        r = sim.simulate_one(seed=1)
        self.assertFalse(r.extra_ticket_used)


if __name__ == "__main__":
    unittest.main()
