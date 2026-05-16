from __future__ import annotations

import random
from typing import List, Optional, Dict, Any

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS, change_dest_max_coeff,
)
from arkgrid.decision import (
    ActionKind, DecisionContext, TurnInput,
    compute_post_roll_metrics, decide_post_roll,
    early_finish_decision, has_progress_offer,
)
from arkgrid.models import Option, LastTurnGoal, AstroGem, GemState, RunResult
from arkgrid.pool import OptionPool
from arkgrid.policy import RerollPolicy
from arkgrid.probability import GoalProbabilityTable


class GemSimulator:
    RARITY_REROLLS = {"common": 0, "rare": 1, "epic": 2}
    RARITY_TURNS = {"common": 5, "rare": 7, "epic": 9}

    def __init__(
            self,
            rarity: str,
            use_extra_ticket: bool,
            use_reset_ticket: bool,
            goal: LastTurnGoal,
            side_node_threshold: float = 0.5,
            astro_gem: Optional[AstroGem] = None,
            optimize: str = "dps",
            prob_reset_threshold: float = 0.0,
            bis_only: bool = False,
            pool: Optional[OptionPool] = None,
            reset_min_coeff: int = 0,
            reroll_min_coeff: int = 0,
            min_side_coeff: int = 0,
            early_finish_coeff: int = 0,
            relic_no_early_finish: float = 0.0,
            relic_reroll_threshold: float = 0.0,
            force_reroll_no_progress: int = 0,
            effect_aware: bool = True,
            confirm_risk: Optional[float] = None,
            confirm_min_coeff: Optional[int] = None,
    ) -> None:
        self.rarity = rarity
        self.goal = goal
        self._configured_gem = astro_gem
        self.optimize = optimize
        self.bis_only = bis_only
        self.min_side_coeff = min_side_coeff
        self.effect_aware = effect_aware
        self.confirm_active = (confirm_risk is not None
                               or confirm_min_coeff is not None)
        self.confirm_risk = confirm_risk if confirm_risk is not None else 0.0
        self.confirm_min_coeff = (confirm_min_coeff
                                  if confirm_min_coeff is not None else 0)
        self._ea_table_cache: Dict[str, GoalProbabilityTable] = {}
        self._ea_reset_table_cache: Dict[str, GoalProbabilityTable] = {}
        self._ea_risk_table_cache: Dict[str, GoalProbabilityTable] = {}
        # Active gem/policy are set per-run in simulate_one;
        # initialize with the configured gem (or None) for direct method calls.
        self.astro_gem = astro_gem
        self.side_node_threshold = side_node_threshold
        self.reroll_policy = RerollPolicy(
            goal, side_node_threshold, astro_gem, bis_only,
        )

        self.use_extra_ticket = use_extra_ticket
        self.use_reset_ticket = use_reset_ticket

        self.base_rerolls = self.RARITY_REROLLS[rarity] + (1 if use_extra_ticket else 0)
        self.turns_total = self.RARITY_TURNS[rarity]
        self.pool = pool or OptionPool()

        # DP probability table (built once, reused across all trials)
        self.prob_reset_threshold = prob_reset_threshold
        self.reset_min_coeff = reset_min_coeff
        self.reroll_min_coeff = reroll_min_coeff

        # Compute side-node coefficients for DP from configured gem
        side_coeff_first, side_coeff_second = 0, 0
        if astro_gem is not None and min_side_coeff > 0:
            coeff = DPS_COEFF if astro_gem.optimize == "dps" else SUPPORT_COEFF
            target = DPS_EFFECTS if astro_gem.optimize == "dps" else SUPPORT_EFFECTS
            if astro_gem.first_effect in target:
                side_coeff_first = coeff[astro_gem.first_effect]
            if astro_gem.second_effect in target:
                side_coeff_second = coeff[astro_gem.second_effect]
        self._side_coeff_first = side_coeff_first
        self._side_coeff_second = side_coeff_second
        self.early_finish_coeff = early_finish_coeff

        # When no gem is configured, coefficients are (0, 0) — don't pass
        # min_side_coeff to the DP or it would think the goal is always
        # impossible (0 < threshold).  The MC success check still applies
        # min_side_coeff using the per-run random gem's actual coefficients.
        dp_min_side_coeff = (min_side_coeff
                             if side_coeff_first > 0 or side_coeff_second > 0
                             else 0)

        # Reroll-aware DP table: extends state with reroll count so the
        # DP itself decides optimal reroll timing via backward induction.
        self.prob_table = GoalProbabilityTable(
            goal, self.turns_total, self.pool,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=dp_min_side_coeff,
            early_finish=early_finish_coeff >= 0,
            max_rerolls=self.base_rerolls,
        )
        # Standard (non-reroll) DP for reset decisions — the reroll-aware
        # DP overestimates p_fresh because the per-option max model
        # overstates reroll value vs actual 4-draw-pick-1 mechanics.
        self._reset_prob_table = GoalProbabilityTable(
            goal, self.turns_total, self.pool,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=dp_min_side_coeff,
            early_finish=early_finish_coeff >= 0,
        )

        # Relic+ (>=16 total points) DP table for probability tracking
        # and decision overrides.
        self.relic_no_early_finish = relic_no_early_finish
        self.relic_reroll_threshold = relic_reroll_threshold
        self.force_reroll_no_progress = force_reroll_no_progress
        self._force_reroll_active = False  # set per-run in simulate_one
        self._relic_prob_table: Optional[GoalProbabilityTable] = None
        if relic_no_early_finish > 0.0 or relic_reroll_threshold > 0.0:
            # Reroll-aware so lookups account for the value of available
            # rerolls when chasing relic+.  Without max_rerolls the table
            # is the no-reroll DP and systematically underestimates P(r+),
            # making the override fire too rarely.
            self._relic_prob_table = GoalProbabilityTable(
                LastTurnGoal(min_total=16), self.turns_total, self.pool,
                early_finish=False,
                max_rerolls=self.base_rerolls,
            )

        # Risk table: goal DP with early_finish=False, so its value at a
        # goal-satisfied state is P(goal still met at run end) — 1 minus
        # that is the confirm-gate's goal-loss risk.
        self._risk_prob_table: Optional[GoalProbabilityTable] = None
        if self.confirm_active:
            self._risk_prob_table = GoalProbabilityTable(
                goal, self.turns_total, self.pool,
                side_coeff_first=side_coeff_first,
                side_coeff_second=side_coeff_second,
                min_side_coeff=dp_min_side_coeff,
                early_finish=False,
                max_rerolls=self.base_rerolls,
            )

    def _get_ea_tables(self, gem_type: str) -> tuple:
        """Build or fetch cached effect-aware (reroll, reset, risk) DP tables
        for the given gem type. Used only when effect_aware is True.
        """
        if gem_type in self._ea_table_cache:
            return (self._ea_table_cache[gem_type],
                    self._ea_reset_table_cache[gem_type],
                    self._ea_risk_table_cache.get(gem_type))
        reroll_tbl = GoalProbabilityTable(
            self.goal, self.turns_total, self.pool,
            min_side_coeff=self.min_side_coeff,
            early_finish=self.early_finish_coeff >= 0,
            max_rerolls=self.base_rerolls,
            effect_aware=True,
            gem_type=gem_type,
            optimize=self.optimize,
        )
        reset_tbl = GoalProbabilityTable(
            self.goal, self.turns_total, self.pool,
            min_side_coeff=self.min_side_coeff,
            early_finish=self.early_finish_coeff >= 0,
            effect_aware=True,
            gem_type=gem_type,
            optimize=self.optimize,
        )
        if not self.confirm_active:
            self._ea_table_cache[gem_type] = reroll_tbl
            self._ea_reset_table_cache[gem_type] = reset_tbl
            return reroll_tbl, reset_tbl, None
        risk_tbl = GoalProbabilityTable(
            self.goal, self.turns_total, self.pool,
            min_side_coeff=self.min_side_coeff,
            early_finish=False,
            max_rerolls=self.base_rerolls,
            effect_aware=True,
            gem_type=gem_type,
            optimize=self.optimize,
        )
        self._ea_table_cache[gem_type] = reroll_tbl
        self._ea_reset_table_cache[gem_type] = reset_tbl
        self._ea_risk_table_cache[gem_type] = risk_tbl
        return reroll_tbl, reset_tbl, risk_tbl

    @staticmethod
    def _random_astro_gem(rng: random.Random, optimize: str) -> AstroGem:
        """Generate a random AstroGem: random type, random 2-of-4 effects."""
        gem_type = rng.choice(list(GEM_TYPES.keys()))
        effects = list(GEM_TYPES[gem_type])
        rng.shuffle(effects)
        return AstroGem(gem_type, effects[0], effects[1], optimize)

    def _resolve_effect_change(self, state: GemState, slot: str,
                               rng: Optional[random.Random] = None) -> str:
        """Resolve an effect change by randomly picking from the available pool.

        Matches the official game mechanic: the new effect is drawn uniformly
        from the gem's effect pool, excluding the current first and second
        effects.  Without rng (e.g. feasibility checks), returns the current
        effect unchanged.
        """
        if self.astro_gem is None or rng is None:
            return getattr(state, f"{slot}_effect")

        pool = GEM_TYPES[self.astro_gem.gem_type]
        available = [e for e in pool
                     if e != state.first_effect and e != state.second_effect]
        if not available:
            return getattr(state, f"{slot}_effect")

        return rng.choice(available)

    @staticmethod
    def _offer_keys(offers: List[Option]) -> List[str]:
        """Format offer keys for logging, showing resolved effects."""
        return sorted(
            f"{o.key}->{o.resolved_effect}" if o.resolved_effect else o.key
            for o in offers
        )

    def _resolve_effect_offers(self, offers: List[Option],
                               state: GemState,
                               rng: random.Random) -> List[Option]:
        """Pre-resolve change_effect options so the outcome is known at offer time."""
        result = []
        for o in offers:
            if o.key in ("change_first_effect", "change_second_effect"):
                slot = "first" if o.key == "change_first_effect" else "second"
                eff = self._resolve_effect_change(state, slot, rng)
                result.append(Option(o.key, o.weight, o.kind, o.delta, eff))
            else:
                result.append(o)
        return result

    def apply_option(self, opt: Option, state: GemState,
                     rng: Optional[random.Random] = None) -> None:
        if opt.kind == "will":
            state.will = min(5, max(1, state.will + opt.delta))
        elif opt.kind == "chaos":
            state.chaos = min(5, max(1, state.chaos + opt.delta))
        elif opt.kind == "first":
            state.first = min(5, max(1, state.first + opt.delta))
        elif opt.kind == "second":
            state.second = min(5, max(1, state.second + opt.delta))
        elif opt.kind == "cost":
            if opt.key == "cost+100":
                state.cost_ratio = min(100, state.cost_ratio + 100)
            elif opt.key == "cost-100":
                state.cost_ratio = max(-100, state.cost_ratio - 100)
        elif opt.kind == "view":
            state.rerolls += opt.delta
        elif opt.key == "change_first_effect":
            state.first_effect = (opt.resolved_effect
                                  or self._resolve_effect_change(state, "first", rng))
        elif opt.key == "change_second_effect":
            state.second_effect = (opt.resolved_effect
                                   or self._resolve_effect_change(state, "second", rng))

    def _goal_fully_satisfied(self, state: GemState) -> bool:
        """Check if goal + BIS + coeff constraints are all met."""
        if not self.goal.satisfied(state.will, state.chaos,
                                   state.first, state.second):
            return False
        if self.bis_only and self.astro_gem:
            target = (DPS_EFFECTS if self.astro_gem.optimize == "dps"
                      else SUPPORT_EFFECTS)
            if (state.first_effect not in target
                    or state.second_effect not in target):
                return False
        if self.min_side_coeff > 0 and self.astro_gem:
            coeff = (DPS_COEFF if self.astro_gem.optimize == "dps"
                     else SUPPORT_COEFF)
            t_set = (DPS_EFFECTS if self.astro_gem.optimize == "dps"
                     else SUPPORT_EFFECTS)
            coeff_total = 0
            if state.first_effect in t_set:
                coeff_total += state.first * coeff[state.first_effect]
            if state.second_effect in t_set:
                coeff_total += state.second * coeff[state.second_effect]
            if coeff_total < self.min_side_coeff:
                return False
        return True

    def _decision_context(self, p_fresh: float = 0.0) -> DecisionContext:
        """Build a DecisionContext from current simulator state.

        Used as a backward-compat shim by `should_early_finish` (which
        `tests/test_scenarios.py` calls directly). `simulate_one` will
        wire this through more directly in a later refactor step.
        """
        optimize = self.astro_gem.optimize if self.astro_gem else self.optimize
        gem_type = self.astro_gem.gem_type if self.astro_gem else ""
        return DecisionContext(
            goal=self.goal,
            pool=self.pool,
            optimize=optimize,
            bis_only=self.bis_only,
            min_side_coeff=self.min_side_coeff,
            early_finish_coeff=self.early_finish_coeff,
            prob_reset_threshold=self.prob_reset_threshold,
            relic_no_early_finish=self.relic_no_early_finish,
            relic_reroll_threshold=self.relic_reroll_threshold,
            force_reroll_no_progress=self.force_reroll_no_progress,
            turns_total=self.turns_total,
            base_rerolls=self.base_rerolls,
            p_fresh=p_fresh,
            prob_table=self.prob_table,
            reset_prob_table=self._reset_prob_table,
            relic_prob_table=self._relic_prob_table,
            gem_type=gem_type,
            force_reroll_active=self._force_reroll_active,
            confirm_active=self.confirm_active,
            confirm_risk=self.confirm_risk,
            confirm_min_coeff=self.confirm_min_coeff,
            risk_prob_table=self._risk_prob_table,
        )

    def should_early_finish(self, state: GemState, offers: List[Option],
                           turns_left: int = 1) -> bool:
        """Decide whether to finish early when goal is already satisfied.

        Thin bool wrapper around `decision.early_finish_decision` for
        backward compatibility with tests that call this method
        directly. The wrapper returns True for both FINISH and REROLL
        actions — `simulate_one` historically treats either as
        "stop normal play".
        """
        ctx = self._decision_context()
        turn = self.turns_total - turns_left + 1
        ti = TurnInput(
            state=state, offers=offers, turn=max(1, turn),
            turns_left=turns_left, rerolls=state.rerolls,
            reset_available=False,
        )
        m = compute_post_roll_metrics(ctx, ti)
        d = early_finish_decision(ctx, ti, m)
        return d is not None

    def _feasibility_args(self, state: GemState) -> dict:
        """Build keyword args for `LastTurnGoal.feasible()` reflecting the
        side-coefficient state under the active gem and `min_side_coeff`.
        Returns an empty dict when min_side_coeff is disabled, so the
        check stays purely level-based.
        """
        if self.min_side_coeff <= 0 or self.astro_gem is None:
            return {}
        opt = self.astro_gem.optimize
        coeff_map = DPS_COEFF if opt == "dps" else SUPPORT_COEFF
        return {
            "min_side_coeff": self.min_side_coeff,
            "side_coeff_first": coeff_map.get(state.first_effect, 0),
            "side_coeff_second": coeff_map.get(state.second_effect, 0),
            "change_dest_max_coeff": change_dest_max_coeff(
                self.astro_gem.gem_type, state.first_effect,
                state.second_effect, opt),
        }

    def prob_goal_feasible_after_click(self, state: GemState, offers: List[Option], turns_left_after: int) -> float:
        if not offers:
            return 0.0
        ok = 0
        for o in offers:
            s = state.clone()
            self.apply_option(o, s)
            if self.goal.feasible(s.will, s.chaos, turns_left_after,
                                  first=s.first, second=s.second,
                                  **self._feasibility_args(s)):
                ok += 1
        return ok / len(offers)

    def _has_progress_offer(self, offers: List[Option], state: GemState) -> bool:
        """Thin wrapper around `decision.has_progress_offer` that supplies
        the simulator's stored side-coefficient configuration.
        """
        return has_progress_offer(
            offers, state, self.goal, self.min_side_coeff,
            self._side_coeff_first, self._side_coeff_second,
        )

    def roll_offers_with_rerolls(
            self,
            state: GemState,
            turn: int,
            rng: random.Random,
            log_obj: Optional[Dict[str, Any]] = None,
    ) -> List[Option]:
        turns_left = self.turns_total - turn + 1
        turns_left_after = turns_left - 1

        offers = self.pool.generate_offers(state, turn, turns_left, rng)
        offers = self._resolve_effect_offers(offers, state, rng)

        if log_obj is not None:
            log_obj["offers_history"] = [self._offer_keys(offers)]
            log_obj["reroll_reasons_history"] = []

        while turn != 1 and state.rerolls > 0:
            forced = (self._force_reroll_active
                      and not self._has_progress_offer(offers, state))
            if forced:
                reason = "forced_no_progress"
            else:
                # DP-optimal reroll decision: the reroll-aware DP table
                # compares keep vs reroll value via backward induction.
                should = self.prob_table.should_reroll_dp(
                    state, offers, turns_left, state.rerolls)
                if not should:
                    break
                reason = "dp_reroll_optimal"

            state.rerolls -= 1
            if log_obj is not None:
                log_obj["reroll_reasons_history"].append([reason])
                log_obj.setdefault("reroll_feasible_history", []).append(0.0)

            offers = self.pool.generate_offers(state, turn, turns_left, rng)
            offers = self._resolve_effect_offers(offers, state, rng)
            if log_obj is not None:
                log_obj["offers_history"].append(self._offer_keys(offers))

        return offers

    def simulate_one(self, seed: Optional[int] = None, log: bool = False) -> RunResult:
        rng = random.Random(seed)

        # Resolve gem for this run (configured or random)
        run_gem = (self._configured_gem
                   if self._configured_gem is not None
                   else self._random_astro_gem(rng, self.optimize))
        self.astro_gem = run_gem
        self.reroll_policy.astro_gem = run_gem

        # Effect-aware DP mode: swap in per-gem-type tables so the
        # decisions account for change_effect transitions and correctly
        # enforce min_side_coeff even when the starting effects don't
        # contribute to the target side.
        if self.effect_aware and run_gem.gem_type in GEM_TYPES:
            ea_reroll, ea_reset, ea_risk = self._get_ea_tables(run_gem.gem_type)
            self.prob_table = ea_reroll
            self._reset_prob_table = ea_reset
            if self.confirm_active:
                self._risk_prob_table = ea_risk

        reset_available = bool(self.use_reset_ticket)
        extra_ticket_active = bool(self.use_extra_ticket)
        coeff = (DPS_COEFF if run_gem.optimize == "dps"
                 else SUPPORT_COEFF)
        target = (DPS_EFFECTS if run_gem.optimize == "dps"
                  else SUPPORT_EFFECTS)
        total_coeff = sum(coeff.get(e, 0)
                          for e in (run_gem.first_effect, run_gem.second_effect)
                          if e in target)
        if reset_available and self.reset_min_coeff > 0:
            if total_coeff < self.reset_min_coeff:
                reset_available = False
        if extra_ticket_active and self.reroll_min_coeff > 0:
            if total_coeff < self.reroll_min_coeff:
                extra_ticket_active = False
        self._force_reroll_active = (
            self.force_reroll_no_progress > 0
            and total_coeff >= self.force_reroll_no_progress)

        # Track whether the extra reroll ticket was disabled by coeff gating
        # but could be re-enabled mid-run by relic+ override.
        relic_reroll_pending = (
            not extra_ticket_active and self.use_extra_ticket
            and self.relic_reroll_threshold > 0.0
            and self._relic_prob_table is not None
        )

        reset_used = False

        _log_pt = self.prob_table if log else None

        run_rerolls = (self.RARITY_REROLLS[self.rarity]
                       + (1 if extra_ticket_active else 0))

        # Fresh-start probability — reset is better when current odds drop below this
        # Uses standard DP (not reroll-aware) for accurate reset value estimate.
        # EA mode: include starting effects so the lookup resolves indices;
        # reset reverts to the gem's original effects, matching this state.
        p_fresh = self._reset_prob_table.lookup(
            GemState(will=1, chaos=1, first=1, second=1,
                     first_effect=run_gem.first_effect,
                     second_effect=run_gem.second_effect),
            self.turns_total)

        # Build the per-run decision context once. Includes the latest
        # prob_table / reset_prob_table references — these may have
        # been swapped to per-gem-type EA tables above.
        ctx = self._decision_context(p_fresh=p_fresh)

        turn_log: List[Dict[str, Any]] = []
        rerolls_by_turn: Dict[int, int] = {}

        for attempt in range(1, 3):
            state = GemState(
                will=1, chaos=1, first=1, second=1,
                cost_ratio=0, rerolls=run_rerolls,
                first_effect=run_gem.first_effect,
                second_effect=run_gem.second_effect,
            )

            for turn in range(1, self.turns_total + 1):
                turns_left = self.turns_total - turn + 1

                # Relic+ override: grant the extra reroll ticket mid-run
                # when P(relic+ | current state) crosses the threshold.
                if relic_reroll_pending:
                    p_relic = self._relic_prob_table.lookup(
                        state, turns_left, rerolls=state.rerolls)
                    if p_relic >= self.relic_reroll_threshold:
                        state.rerolls += 1
                        extra_ticket_active = True
                        relic_reroll_pending = False

                if log:
                    entry: Optional[Dict[str, Any]] = {
                        "turn": turn,
                        "turns_left": turns_left,
                        "goal_prob": _log_pt.lookup(state, turns_left, rerolls=state.rerolls) if _log_pt else None,
                        "relic_prob": self._relic_prob_table.lookup(state, turns_left, rerolls=state.rerolls) if self._relic_prob_table else None,
                        "rerolls_available": state.rerolls,
                        "eff_threshold": self.reroll_policy.effective_side_threshold(state),
                    }
                else:
                    entry = None
                rerolls_before = state.rerolls
                offers = self.roll_offers_with_rerolls(state, turn, rng, entry if log else None)
                rerolls_used = rerolls_before - state.rerolls
                if rerolls_used > 0:
                    rerolls_by_turn[turn] = rerolls_used

                # Log probability info after offers are determined
                if log:
                    entry["feasible_frac"] = self.prob_goal_feasible_after_click(
                        state, offers, turns_left - 1)
                    if _log_pt is not None:
                        entry["prob_after_click"] = _log_pt.expected_prob_after_click(
                            state, offers, turns_left - 1, rerolls=state.rerolls)

                # Single decision point: shared with automation.
                # Loop because non-DP rerolls (e.g. early-finish scenario b)
                # can fire after roll_offers_with_rerolls has already
                # exhausted DP-optimal rerolls. Bounded by state.rerolls.
                while True:
                    ti = TurnInput(
                        state=state, offers=offers, turn=turn,
                        turns_left=turns_left, rerolls=state.rerolls,
                        reset_available=(reset_available and not reset_used),
                    )
                    decision = decide_post_roll(ctx, ti)
                    if decision.action != ActionKind.REROLL:
                        break
                    if state.rerolls <= 0 or turn == 1:
                        break  # defensive — shouldn't happen
                    state.rerolls -= 1
                    rerolls_by_turn[turn] = rerolls_by_turn.get(turn, 0) + 1
                    offers = self.pool.generate_offers(state, turn, turns_left, rng)
                    offers = self._resolve_effect_offers(offers, state, rng)
                    if log:
                        entry.setdefault("offers_history", []).append(
                            self._offer_keys(offers))
                        entry.setdefault(
                            "reroll_reasons_history", []).append([decision.branch])

                if log and decision.needs_confirmation:
                    entry["confirm"] = {
                        "branch": decision.branch,
                        "would_recommend": decision.action.value,
                        "choices": [a.value for a in decision.confirm_choices],
                        "metrics": dict(decision.metrics),
                    }

                if decision.action == ActionKind.RESET:
                    reset_used = True
                    if log:
                        entry["action"] = f"RESET ({decision.reason})"
                        entry["state_before_reset"] = {
                            "will": state.will, "chaos": state.chaos,
                            "first": state.first, "second": state.second,
                            "total_points": state.total_points(),
                            "rerolls": state.rerolls,
                            "first_effect": state.first_effect,
                            "second_effect": state.second_effect,
                        }
                        turn_log.append(entry)
                    break

                if decision.action == ActionKind.FAIL:
                    if log:
                        entry["action"] = f"FAIL ({decision.reason})"
                        entry["state_after"] = {
                            "will": state.will, "chaos": state.chaos,
                            "first": state.first, "second": state.second,
                            "total_points": state.total_points(),
                            "rerolls": state.rerolls,
                            "first_effect": state.first_effect,
                            "second_effect": state.second_effect,
                        }
                        turn_log.append(entry)
                    return RunResult(
                        success=False,
                        reason="forced_fail_no_feasible_path_after_click",
                        reset_used=reset_used,
                        state=state,
                        total_points=state.total_points(),
                        rerolls_left=state.rerolls,
                        extra_ticket_used=extra_ticket_active,
                        turn_log=turn_log if log else None,
                        rerolls_by_turn=rerolls_by_turn,
                    )

                if decision.action == ActionKind.FINISH:
                    success = self._goal_fully_satisfied(state)
                    if log:
                        entry["action"] = (
                            f"EARLY_FINISH ({decision.reason})"
                            if success else f"FINISH ({decision.reason})")
                        entry["state_after"] = {
                            "will": state.will, "chaos": state.chaos,
                            "first": state.first, "second": state.second,
                            "total_points": state.total_points(),
                            "rerolls": state.rerolls,
                            "first_effect": state.first_effect,
                            "second_effect": state.second_effect,
                            "goal_prob": 1.0 if success else 0.0,
                        }
                        turn_log.append(entry)
                    return RunResult(
                        success=success,
                        reason="early_finish" if success else "goal_unreachable_finish",
                        reset_used=reset_used,
                        state=state,
                        total_points=state.total_points(),
                        rerolls_left=state.rerolls,
                        extra_ticket_used=extra_ticket_active,
                        turn_log=turn_log if log else None,
                        rerolls_by_turn=rerolls_by_turn,
                    )

                # PROCESS — pick uniformly and apply
                picked = rng.choice(offers)
                self.apply_option(picked, state, rng)

                if log:
                    entry["action"] = "click"
                    entry["picked"] = picked.key
                    entry["state_after"] = {
                        "will": state.will,
                        "chaos": state.chaos,
                        "first": state.first,
                        "second": state.second,
                        "total_points": state.total_points(),
                        "rerolls": state.rerolls,
                        "first_effect": state.first_effect,
                        "second_effect": state.second_effect,
                        "goal_prob": _log_pt.lookup(state, turns_left - 1, rerolls=state.rerolls) if _log_pt else None,
                        "relic_prob": self._relic_prob_table.lookup(state, turns_left - 1, rerolls=state.rerolls) if self._relic_prob_table else None,
                    }
                    turn_log.append(entry)

            else:
                success = self.goal.satisfied(state.will, state.chaos,
                                              state.first, state.second)
                if success and self.bis_only:
                    target = (DPS_EFFECTS if run_gem.optimize == "dps"
                              else SUPPORT_EFFECTS)
                    if (state.first_effect not in target
                            or state.second_effect not in target):
                        success = False
                if success and self.min_side_coeff > 0:
                    coeff = (DPS_COEFF if run_gem.optimize == "dps"
                             else SUPPORT_COEFF)
                    t_set = (DPS_EFFECTS if run_gem.optimize == "dps"
                             else SUPPORT_EFFECTS)
                    coeff_total = 0
                    if state.first_effect in t_set:
                        coeff_total += state.first * coeff[state.first_effect]
                    if state.second_effect in t_set:
                        coeff_total += state.second * coeff[state.second_effect]
                    if coeff_total < self.min_side_coeff:
                        success = False
                return RunResult(
                    success=success,
                    reason="goal_met" if success else "goal_not_met",
                    reset_used=reset_used,
                    state=state,
                    total_points=state.total_points(),
                    rerolls_left=state.rerolls,
                    extra_ticket_used=extra_ticket_active,
                    turn_log=turn_log if log else None,
                    rerolls_by_turn=rerolls_by_turn,
                )

            # reset used on attempt 1 -> retry
            if reset_used and attempt == 1:
                continue

            return RunResult(
                success=False,
                reason="ended_unexpectedly",
                reset_used=reset_used,
                state=state,
                total_points=state.total_points(),
                rerolls_left=state.rerolls,
                extra_ticket_used=extra_ticket_active,
                turn_log=turn_log if log else None,
                rerolls_by_turn=rerolls_by_turn,
            )

        raise RuntimeError("Simulation exceeded expected attempts")
