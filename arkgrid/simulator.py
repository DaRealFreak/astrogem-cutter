from __future__ import annotations

import random
from typing import List, Optional, Dict, Any

from arkgrid.constants import (
    DPS_EFFECTS, DPS_PRIORITY, GEM_TYPES,
    SUPPORT_EFFECTS, SUPPORT_PRIORITY,
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
    ) -> None:
        self.rarity = rarity
        self.goal = goal
        self._configured_gem = astro_gem
        self.optimize = optimize
        self.bis_only = bis_only
        # Active gem/policy are set per-run in simulate_one;
        # initialize with the configured gem (or None) for direct method calls.
        self.astro_gem = astro_gem
        self.side_node_threshold = side_node_threshold
        self.reroll_policy = RerollPolicy(
            goal, side_node_threshold, astro_gem, bis_only,
            dp_reroll_margin=dp_reroll_margin,
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
        self.prob_table = GoalProbabilityTable(goal, self.turns_total, self.pool)

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

    def prob_goal_feasible_after_click(self, state: GemState, offers: List[Option], turns_left_after: int) -> float:
        if not offers:
            return 0.0
        ok = 0
        for o in offers:
            s = state.clone()
            self.apply_option(o, s)
            if self.goal.feasible(s.will, s.chaos, turns_left_after):
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
        reset_used = False

        _log_pt = self.prob_table if log else None

        # Fresh-start probability — reset is better when current odds drop below this
        p_fresh = self.prob_table.lookup(
            GemState(will=1, chaos=1, first=1, second=1), self.turns_total)

        turn_log: List[Dict[str, Any]] = []

        for attempt in range(1, 3):
            state = GemState(
                will=1, chaos=1, first=1, second=1,
                cost_ratio=0, rerolls=self.base_rerolls,
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
                if not self.goal.feasible(state.will, state.chaos, turns_left):
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
                success = self.goal.satisfied(state.will, state.chaos)
                return RunResult(
                    success=success,
                    reason="goal_met" if success else "goal_not_met",
                    reset_used=reset_used,
                    state=state,
                    total_points=state.total_points(),
                    rerolls_left=state.rerolls,
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
                turn_log=turn_log if log else None,
            )

        raise RuntimeError("Simulation exceeded expected attempts")
