from __future__ import annotations

import random
from typing import List, Optional, Dict, Any

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS,
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
            dp_reroll_margin: float = 0.03,
            side_quality_weight: float = 0.0,
            reset_min_coeff: int = 0,
            reroll_min_coeff: int = 0,
            min_side_coeff: int = 0,
            exact_draw: bool = False,
            early_finish_coeff: int = 0,
    ) -> None:
        self.rarity = rarity
        self.goal = goal
        self._configured_gem = astro_gem
        self.optimize = optimize
        self.bis_only = bis_only
        self.min_side_coeff = min_side_coeff
        # Active gem/policy are set per-run in simulate_one;
        # initialize with the configured gem (or None) for direct method calls.
        self.astro_gem = astro_gem
        self.side_node_threshold = side_node_threshold
        self.reroll_policy = RerollPolicy(
            goal, side_node_threshold, astro_gem, bis_only,
            dp_reroll_margin=dp_reroll_margin,
            side_quality_weight=side_quality_weight,
        )

        self.use_extra_ticket = use_extra_ticket
        self.use_reset_ticket = use_reset_ticket

        self.base_rerolls = self.RARITY_REROLLS[rarity] + (1 if use_extra_ticket else 0)
        self.turns_total = self.RARITY_TURNS[rarity]
        self.pool = pool or OptionPool()

        # DP probability table (built once, reused across all trials)
        # Always built so the reroll policy can use DP probability as
        # its comfort signal instead of binary feasibility fraction.
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

        self.prob_table = GoalProbabilityTable(
            goal, self.turns_total, self.pool,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=min_side_coeff,
            exact_draw=exact_draw,
            early_finish=early_finish_coeff >= 0,
        )

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

    def should_early_finish(self, state: GemState, offers: List[Option]) -> bool:
        """Decide whether to finish early when goal is already satisfied.

        Returns True if we should finish (stop processing turns).
        Uses the early_finish_coeff threshold:
          0 = finish if any risk, >0 = tolerate risk up to that level.
        """
        if self.early_finish_coeff < 0:
            return False
        if not self._goal_fully_satisfied(state):
            return False

        # Compute P(miss) = fraction of offers that would break the goal
        miss_count = 0
        for o in offers:
            s = state.clone()
            self.apply_option(o, s)
            if not self._goal_fully_satisfied(s):
                miss_count += 1
        p_miss = miss_count / len(offers) if offers else 0.0

        if p_miss == 0.0:
            return False  # no risk, continue

        # Compute best coefficient gain from side upgrades
        best_coeff_gain = 0
        if self.astro_gem:
            coeff_map = (DPS_COEFF if self.astro_gem.optimize == "dps"
                         else SUPPORT_COEFF)
            t_set = (DPS_EFFECTS if self.astro_gem.optimize == "dps"
                     else SUPPORT_EFFECTS)
            for o in offers:
                if o.kind in ("first", "second"):
                    eff = getattr(state, f"{o.kind}_effect")
                    if eff in t_set and o.delta > 0:
                        gain = o.delta * coeff_map[eff]
                        best_coeff_gain = max(best_coeff_gain, gain)

        if best_coeff_gain == 0:
            return True  # risk but no side gain, finish

        return best_coeff_gain * p_miss > self.early_finish_coeff

    def prob_goal_feasible_after_click(self, state: GemState, offers: List[Option], turns_left_after: int) -> float:
        if not offers:
            return 0.0
        ok = 0
        for o in offers:
            s = state.clone()
            self.apply_option(o, s)
            if self.goal.feasible(s.will, s.chaos, turns_left_after,
                                  first=s.first, second=s.second):
                ok += 1
        return ok / len(offers)

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
            goal_feasible_frac = self.prob_goal_feasible_after_click(state, offers, turns_left_after)
            goal_success_prob: Optional[float] = None
            dp_baseline: Optional[float] = None
            if self.prob_table is not None:
                goal_success_prob = self.prob_table.expected_prob_after_click(
                    state, offers, turns_left_after)
                dp_baseline = self.prob_table.lookup(state, turns_left)
            should, reasons = self.reroll_policy.should_reroll(
                offers, state, turns_left, goal_feasible_frac,
                goal_success_prob=goal_success_prob,
                dp_baseline=dp_baseline,
                rerolls_remaining=state.rerolls)

            if not should:
                break

            state.rerolls -= 1
            if log_obj is not None:
                log_obj["reroll_reasons_history"].append(reasons)
                log_obj.setdefault("reroll_feasible_history", []).append(goal_feasible_frac)

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

        reset_available = bool(self.use_reset_ticket)
        extra_ticket_active = bool(self.use_extra_ticket)
        if reset_available or (extra_ticket_active and self.reroll_min_coeff > 0):
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
        reset_used = False

        _log_pt = self.prob_table if log else None

        # Fresh-start probability — reset is better when current odds drop below this
        p_fresh = self.prob_table.lookup(
            GemState(will=1, chaos=1, first=1, second=1), self.turns_total)

        turn_log: List[Dict[str, Any]] = []

        run_rerolls = (self.RARITY_REROLLS[self.rarity]
                       + (1 if extra_ticket_active else 0))

        for attempt in range(1, 3):
            state = GemState(
                will=1, chaos=1, first=1, second=1,
                cost_ratio=0, rerolls=run_rerolls,
                first_effect=run_gem.first_effect,
                second_effect=run_gem.second_effect,
            )

            for turn in range(1, self.turns_total + 1):
                turns_left = self.turns_total - turn + 1

                # Probability-based early reset (soft -- only triggers reset, never hard fail)
                if (self.prob_reset_threshold > 0.0
                        and reset_available and not reset_used):
                    p_goal = self.prob_table.lookup(state, turns_left)
                    if p_goal < self.prob_reset_threshold:
                        reset_used = True
                        if log:
                            turn_log.append({
                                "turn": turn,
                                "turns_left": turns_left,
                                "goal_prob": p_goal,
                                "rerolls_available": state.rerolls,
                                "action": f"RESET (goal prob {p_goal:.4f} < threshold {self.prob_reset_threshold})",
                                "state_before_reset": {
                                    "will": state.will,
                                    "chaos": state.chaos,
                                    "first": state.first,
                                    "second": state.second,
                                    "total_points": state.total_points(),
                                    "rerolls": state.rerolls,
                                    "first_effect": state.first_effect,
                                    "second_effect": state.second_effect,
                                    "goal_prob": p_goal,
                                },
                            })
                        break

                # Binary feasibility check (hard -- can trigger fail)
                if not self.goal.feasible(state.will, state.chaos, turns_left,
                                         first=state.first, second=state.second):
                    if reset_available and not reset_used:
                        reset_used = True
                        if log:
                            turn_log.append({
                                "turn": turn,
                                "turns_left": turns_left,
                                "goal_prob": _log_pt.lookup(state, turns_left) if _log_pt else None,
                                "rerolls_available": state.rerolls,
                                "action": "RESET (goal infeasible before rolling)",
                                "state_before_reset": {
                                    "will": state.will,
                                    "chaos": state.chaos,
                                    "first": state.first,
                                    "second": state.second,
                                    "total_points": state.total_points(),
                                    "rerolls": state.rerolls,
                                    "first_effect": state.first_effect,
                                    "second_effect": state.second_effect,
                                },
                            })
                        break
                    return RunResult(
                        success=False,
                        reason="impossible_no_reset_available",
                        reset_used=reset_used,
                        state=state,
                        total_points=state.total_points(),
                        rerolls_left=state.rerolls,
                        extra_ticket_used=extra_ticket_active,
                        turn_log=turn_log if log else None,
                    )

                if log:
                    entry: Optional[Dict[str, Any]] = {
                        "turn": turn,
                        "turns_left": turns_left,
                        "goal_prob": _log_pt.lookup(state, turns_left) if _log_pt else None,
                        "rerolls_available": state.rerolls,
                        "eff_threshold": self.reroll_policy.effective_side_threshold(state),
                    }
                else:
                    entry = None
                offers = self.roll_offers_with_rerolls(state, turn, rng, entry if log else None)

                # Log probability info after offers are determined
                if log:
                    entry["feasible_frac"] = self.prob_goal_feasible_after_click(
                        state, offers, turns_left - 1)
                    if _log_pt is not None:
                        entry["prob_after_click"] = _log_pt.expected_prob_after_click(
                            state, offers, turns_left - 1)

                # Early finish: goal already satisfied, risk not worth it
                # Never early finish while rerolls remain — use them first
                if state.rerolls <= 0 and self.should_early_finish(state, offers):
                    if log:
                        entry["action"] = "EARLY_FINISH"
                        entry["state_after"] = {
                            "will": state.will,
                            "chaos": state.chaos,
                            "first": state.first,
                            "second": state.second,
                            "total_points": state.total_points(),
                            "rerolls": state.rerolls,
                            "first_effect": state.first_effect,
                            "second_effect": state.second_effect,
                            "goal_prob": 1.0,
                        }
                        turn_log.append(entry)
                    return RunResult(
                        success=True,
                        reason="early_finish",
                        reset_used=reset_used,
                        state=state,
                        total_points=state.total_points(),
                        rerolls_left=state.rerolls,
                        extra_ticket_used=extra_ticket_active,
                        turn_log=turn_log if log else None,
                    )

                # after rerolls: probability-based early reset
                if (self.prob_reset_threshold > 0.0
                        and reset_available and not reset_used):
                    p_after = self.prob_table.expected_prob_after_click(
                        state, offers, turns_left - 1)
                    if p_after < self.prob_reset_threshold:
                        reset_used = True
                        if log:
                            entry["action"] = (
                                f"RESET (post-click prob {p_after:.4f} "
                                f"< threshold {self.prob_reset_threshold})")
                            entry["state_before_reset"] = {
                                "will": state.will,
                                "chaos": state.chaos,
                                "first": state.first,
                                "second": state.second,
                                "total_points": state.total_points(),
                                "rerolls": state.rerolls,
                                "first_effect": state.first_effect,
                                "second_effect": state.second_effect,
                                "goal_prob": p_after,
                            }
                            turn_log.append(entry)
                        break

                # after rerolls: binary feasibility -- hard reset/fail
                p_feasible_after = self.prob_goal_feasible_after_click(state, offers, turns_left - 1)
                if p_feasible_after == 0.0:
                    if reset_available and not reset_used:
                        reset_used = True
                        if log:
                            entry["action"] = "RESET (no feasible path after click)"
                            entry["state_before_reset"] = {
                                "will": state.will,
                                "chaos": state.chaos,
                                "first": state.first,
                                "second": state.second,
                                "total_points": state.total_points(),
                                "rerolls": state.rerolls,
                                "first_effect": state.first_effect,
                                "second_effect": state.second_effect,
                            }
                            turn_log.append(entry)
                        break

                    if log:
                        entry["action"] = "FAIL (no feasible path after click)"
                        entry["state_after"] = {
                            "will": state.will,
                            "chaos": state.chaos,
                            "first": state.first,
                            "second": state.second,
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
                    )

                # Last turn after rerolls: reset if fresh start has better odds
                if (turns_left == 1 and reset_available and not reset_used):
                    p_after = self.prob_table.expected_prob_after_click(
                        state, offers, turns_left - 1)
                    if p_after < p_fresh:
                        reset_used = True
                        if log:
                            entry["action"] = (
                                f"RESET (last turn post-reroll prob {p_after:.4f}"
                                f" < fresh start {p_fresh:.4f})")
                            entry["state_before_reset"] = {
                                "will": state.will,
                                "chaos": state.chaos,
                                "first": state.first,
                                "second": state.second,
                                "total_points": state.total_points(),
                                "rerolls": state.rerolls,
                                "first_effect": state.first_effect,
                                "second_effect": state.second_effect,
                                "goal_prob": p_after,
                            }
                            turn_log.append(entry)
                        break

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
                        "goal_prob": _log_pt.lookup(state, turns_left - 1) if _log_pt else None,
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
            )

        raise RuntimeError("Simulation exceeded expected attempts")
