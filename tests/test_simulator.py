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

    def test_extra_ticket_renews_after_reset(self) -> None:
        # The extra reroll ticket is once per CUTTING PROCESS, and a reset starts
        # a NEW cutting process — so the ticket must be available again in the
        # post-reset attempt. Regression: `ticket_available` used to persist
        # across the reset (stuck False once consumed pre-reset), so a reset gem
        # could never use its extra ticket again.
        #
        # On common (0 free rerolls) with a force-on ticket, `ticket_lent` per
        # turn == "the ticket is currently available" (the force-on enabler is
        # always true), so the post-reset lend flags expose the bug directly.
        sim = GemSimulator(
            rarity="common", use_extra_ticket=True, use_reset_ticket=True,
            goal=LastTurnGoal(min_will=5, min_chaos=5),
        )
        r = sim.simulate_one(seed=0, log=True)
        self.assertTrue(r.reset_used, "seed 0 should trigger a reset")
        log = r.turn_log or []
        reset_i = next(
            (i for i, e in enumerate(log)
             if str(e.get("action", "")).startswith("RESET")),
            None,
        )
        self.assertIsNotNone(reset_i, "expected a RESET entry in the turn log")
        pre, post = log[:reset_i + 1], log[reset_i + 1:]
        # Sanity: the ticket was lent (and consumed) before the reset.
        self.assertTrue(any(e.get("ticket_lent") for e in pre),
                        "ticket should have been lent before the reset")
        self.assertTrue(post, "the post-reset cutting process should have turns")
        # The fix: the ticket renews for the new cutting process, so it is lent
        # again post-reset. Pre-fix every post entry was False (gone for good).
        self.assertTrue(any(e.get("ticket_lent") for e in post),
                        "extra ticket must be available again after a reset")

    def test_reroll_accounting_resets_between_attempts(self) -> None:
        # `rerolls_by_turn` must not leak attempt-1 counts into the post-reset
        # attempt. Regression: the dict was initialized once outside the
        # attempt loop and only overwritten when a turn spent >0 rerolls, so
        # the ticket reconciliation in attempt 2 could read a stale attempt-1
        # count — falsely marking the renewed reroll ticket consumed AND
        # skipping the "return the lent +1" branch (a phantom free reroll).
        #
        # Scripted scenario (epic: 2 free rerolls, owned ticket, reset ticket):
        #   attempt 1: T1 process, T2 process, T3 reroll x2 + process
        #              (rerolls_by_turn[3] = 2), T4 reset.
        #   attempt 2: T1 process, T2 reroll + process, T3 process with the
        #              ticket lent (free_before=1) and 0 rerolls used —
        #              pre-fix the stale [3]=2 > 1 marked the ticket spent and
        #              leaked the lent +1 — T4 finish.
        from unittest import mock
        from arkgrid.decision import ActionKind, Decision

        def d(action: ActionKind) -> Decision:
            return Decision(action=action, branch="scripted", reason="")

        script = iter([
            # attempt 1
            d(ActionKind.PROCESS), d(ActionKind.PROCESS),
            d(ActionKind.REROLL), d(ActionKind.REROLL), d(ActionKind.PROCESS),
            d(ActionKind.RESET),
            # attempt 2
            d(ActionKind.PROCESS),
            d(ActionKind.REROLL), d(ActionKind.PROCESS),
            d(ActionKind.PROCESS),
            d(ActionKind.FINISH),
        ])

        # Neutralize DP-driven rerolls inside the roll loop so the scripted
        # decision-loop rerolls are the only reroll spend.
        def roll_plain(self, state, turn, rng, log_obj=None):
            turns_left = self.turns_total - turn + 1
            offers = self.pool.generate_offers(state, turn, turns_left, rng)
            return self._resolve_effect_offers(offers, state, rng)

        sim = GemSimulator(
            rarity="epic", use_extra_ticket=None, use_reset_ticket=True,
            goal=LastTurnGoal(),
            astro_gem=AstroGem(
                gem_type="chaos_distortion", first_effect="attack_power",
                second_effect="ally_damage", optimize="dps"),
        )
        with mock.patch("arkgrid.simulator.decide_post_roll",
                        side_effect=lambda ctx, ti: next(script)), \
                mock.patch("arkgrid.simulator.ticket_enabled",
                           return_value=True), \
                mock.patch.object(GemSimulator, "roll_offers_with_rerolls",
                                  roll_plain):
            r = sim.simulate_one(seed=7)

        self.assertTrue(r.reset_used)
        # The ticket was never actually spent in either attempt (free rerolls
        # covered every reroll), so it must not be reported consumed.
        self.assertFalse(
            r.extra_ticket_used,
            "reroll ticket falsely marked consumed from stale attempt-1 counts")
        # attempt 2 spent 1 of 2 free rerolls; the lent-but-unused ticket must
        # be returned every turn — no phantom reroll may remain.
        self.assertEqual(r.rerolls_left, 1)
        # The reported per-turn counts describe the final cutting process only.
        self.assertEqual(r.rerolls_by_turn, {2: 1})

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
        # Verifies the epic 9-turn budget: the run reaches turn 9.  Under the
        # reroll-aware value oracle (Phase B, on by default) this seed's gem
        # clicks all 9 turns — the more-accurate reroll-aware value of
        # processing the final offer edges out finishing (the flat oracle
        # underestimates value, so it early-finished turn 9 here instead).
        turns_reached = max(t["turn"] for t in (r.turn_log or []))
        self.assertEqual(turns_reached, 9)
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

    def test_grade_value_table_uses_grade_only_mode_when_set(self):
        # Dead-goal fallback under --ignore-side-node-values must value grade
        # ONLY (relic/ancient tier), not side-node coefficients the player
        # opted out of — so it finishes when no higher grade is reachable.
        sim = self._sim(ignore_side_node_values=True)
        gvt = sim._get_grade_value_table("order_fortitude")
        self.assertEqual(gvt.value_mode, "grade_only")

    def test_grade_value_table_uses_grade_only_mode_by_default(self):
        # Dead-goal turns value GRADE ONLY even without
        # --ignore-side-node-values: a gem that missed its goal won't be
        # equipped, so its side-node coefficients are worthless and only its
        # fusion grade (relic/ancient) matters. The table therefore finishes
        # the instant no grade upgrade is reachable instead of clicking on to
        # chase a side coefficient the dead gem can't cash in.
        sim = self._sim()  # no ignore_side_node_values
        gvt = sim._get_grade_value_table("order_fortitude")
        self.assertEqual(gvt.value_mode, "grade_only")

    def test_default_side_value_table_is_side_mode(self):
        sim = self._sim()
        svt = sim._get_side_value_table("order_fortitude")
        self.assertEqual(svt.value_mode, "side")

    def test_maxed_value_table_is_side_mode_when_set(self):
        sim = self._sim(ignore_side_node_values=True)
        mvt = sim._get_maxed_value_table("order_fortitude")
        self.assertEqual(mvt.value_mode, "side")

    def test_maxed_value_table_in_context_under_flag(self):
        sim = self._sim(ignore_side_node_values=True)
        sim.astro_gem = AstroGem("order_fortitude", "boss_damage",
                                 "attack_power", "dps")
        ctx = sim._decision_context(p_fresh=0.5)
        self.assertIsNotNone(ctx.maxed_value_table)
        self.assertEqual(ctx.maxed_value_table.value_mode, "side")

    def test_maxed_value_table_absent_without_flag(self):
        sim = self._sim()  # no ignore_side_node_values
        sim.astro_gem = AstroGem("order_fortitude", "boss_damage",
                                 "attack_power", "dps")
        ctx = sim._decision_context(p_fresh=0.5)
        self.assertIsNone(ctx.maxed_value_table)
        # The raw per-run attribute must also stay unset without the flag.
        self.assertIsNone(sim._maxed_value_table)


class TestRerollGoalThreshold(unittest.TestCase):
    """--reroll-goal / --reroll-goal-threshold enables the off-by-default
    extra reroll ticket when P(will+chaos >= reroll_goal) crosses the
    threshold."""

    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_extra_ticket=None, use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=7),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            optimize="dps", effect_aware=True,
        )
        defaults.update(kw)
        return GemSimulator(**defaults)

    def test_grants_ticket_when_prob_crosses(self):
        # ticket off by default, but P(will+chaos>=8) easily
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

    def test_both_triggers_lend_one_ticket(self):
        # Both enablers armed and trivially crossable -> the ticket is lent
        # (logged separately from the free count). The ticket adds at most +1 a
        # turn; the free reroll count on turn 1 stays at the epic base of 2.
        sim = self._sim(relic_reroll_threshold=0.0001,
                        reroll_goal=8, reroll_goal_threshold=0.0001)
        r = sim.simulate_one(seed=1, log=True)
        self.assertTrue(r.extra_ticket_used)
        self.assertTrue(r.turn_log[0]["ticket_lent"])
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)


class TestExtraTicketOffByDefault(unittest.TestCase):
    """The extra reroll ticket is off by default (use_extra_ticket=None) and now
    re-evaluated PER TURN (never banked): each turn it is "lent" (logged as
    ticket_lent) only when an enabler clears its bar, and consumed
    (extra_ticket_used) only when actually spent. The FREE reroll count
    (rerolls_available in the log) is unaffected by the ticket — epic base = 2.
    --no-extra-ticket (False) is a hard off. The coeff enabler now compares the
    EXPECTED side coefficient (DP, goal-conditioned) against the bar, not the
    gem's static effect-coeff sum."""

    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=7),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            optimize="dps", effect_aware=True,
        )
        defaults.update(kw)
        return GemSimulator(**defaults)

    def test_default_none_no_enabler_never_lends(self):
        # No ticket flag, no enabler -> never lent, never consumed.
        sim = self._sim(use_extra_ticket=None)
        r = sim.simulate_one(seed=1, log=True)
        self.assertFalse(r.extra_ticket_used)
        self.assertFalse(any(e.get("ticket_lent") for e in r.turn_log))
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)  # free count

    def test_force_on_lends_every_turn_without_enabler(self):
        # Explicit --extra-ticket (True) = always lent, no enabler needed; the
        # free reroll count is unchanged (the ticket is separate).
        sim = self._sim(use_extra_ticket=True)
        r = sim.simulate_one(seed=1, log=True)
        self.assertTrue(r.turn_log[0]["ticket_lent"])
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)

    def test_force_on_ignores_low_coeff(self):
        # Force-on outranks --reroll-min-coeff: lent even below the coeff floor.
        sim = self._sim(use_extra_ticket=True, reroll_min_coeff=99999)
        r = sim.simulate_one(seed=1, log=True)
        self.assertTrue(r.turn_log[0]["ticket_lent"])

    def test_coeff_enabler_lends_when_expected_coeff_clears_bar(self):
        # Tiny bar -> the expected side coefficient clears it while the goal is
        # live, so the ticket is lent.
        sim = self._sim(use_extra_ticket=None, reroll_min_coeff=1)
        r = sim.simulate_one(seed=1, log=True)
        self.assertTrue(r.turn_log[0]["ticket_lent"])

    def test_coeff_enabler_below_threshold_stays_off(self):
        # Unreachable bar -> the expected side coefficient never clears it.
        sim = self._sim(use_extra_ticket=None, reroll_min_coeff=10**9)
        r = sim.simulate_one(seed=1, log=True)
        self.assertFalse(r.extra_ticket_used)
        self.assertFalse(any(e.get("ticket_lent") for e in r.turn_log))

    def test_hard_off_disarms_enablers(self):
        # --no-extra-ticket (False) overrides a trivially-crossable relic enabler.
        sim = self._sim(use_extra_ticket=False, relic_reroll_threshold=0.0001)
        r = sim.simulate_one(seed=1, log=True)
        self.assertFalse(r.extra_ticket_used)
        self.assertFalse(any(e.get("ticket_lent") for e in r.turn_log))
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)


class TestHasProgressOfferUsesLiveCoeffs(unittest.TestCase):
    """Regression: the simulator's reroll-loop progress check must use the
    LIVE side coefficients of the current state, matching the shared
    `decision.has_progress_offer` that automation uses.

    `GemSimulator._has_progress_offer` reads `self._side_coeff_first/second`,
    which are computed ONCE in `__init__` from the *configured* gem — they are
    (0, 0) for random-gem runs (no `astro_gem`) and go stale after a mid-run
    `change_effect`. The shared `decision.has_progress_offer` (used by
    automation and by the sim's own main-tree dp_reroll branch) computes the
    coefficients live from `state.first_effect/second_effect`. With
    `--force-reroll-no-progress` + `--min-side-coeff`, this makes the
    simulator's reroll loop and the live automation loop take OPPOSITE
    force-reroll decisions on the same hand.
    """

    def _live_coeffs(self, state):
        from arkgrid.constants import DPS_COEFF, DPS_EFFECTS
        first = (DPS_COEFF.get(state.first_effect, 0)
                 if state.first_effect in DPS_EFFECTS else 0)
        second = (DPS_COEFF.get(state.second_effect, 0)
                  if state.second_effect in DPS_EFFECTS else 0)
        return first, second

    def test_random_gem_run_matches_live_progress_check(self):
        from arkgrid.decision import has_progress_offer
        MIN_SIDE_COEFF = 4000
        # Built like `cmd_sim` for a random-gem MC run: astro_gem=None.
        sim = GemSimulator(
            rarity="rare", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=6), astro_gem=None,
            optimize="dps", min_side_coeff=MIN_SIDE_COEFF,
            force_reroll_no_progress=1000,
        )
        # Live state: first side is boss_damage (DPS coeff 1000, contributing).
        state = GemState(will=3, chaos=3, first=2, second=1,
                         first_effect="boss_damage",
                         second_effect="ally_damage")
        # Only goal-progress is first+1 (raises the contributing side toward
        # the min_side_coeff floor); the will/chaos goal (>=6) is already met.
        offers = [
            Option("first+1", 1.0, "first", 1),
            Option("cost+100", 1.0, "cost", 0),
            Option("maintain", 1.0, "other", 0),
            Option("chaos-1", 1.0, "chaos", -1),
        ]
        live_first, live_second = self._live_coeffs(state)
        expected = has_progress_offer(offers, state, sim.goal, MIN_SIDE_COEFF,
                                      live_first, live_second)
        actual = sim._has_progress_offer(offers, state)
        self.assertEqual(
            actual, expected,
            "sim reroll-loop _has_progress_offer must agree with the live "
            "decision.has_progress_offer (automation's path); it used stale "
            f"side coeffs ({sim._side_coeff_first}, {sim._side_coeff_second}) "
            f"vs live ({live_first}, {live_second})",
        )


if __name__ == "__main__":
    unittest.main()
