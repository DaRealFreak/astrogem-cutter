from __future__ import annotations

from typing import List, Optional, Tuple

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, DPS_PRIORITY, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS, SUPPORT_PRIORITY,
)
from arkgrid.models import Option, LastTurnGoal, AstroGem, GemState


class RerollPolicy:
    """Heuristic reroll policy used as fallback when DP-based reroll
    decisions are not available (e.g. automation without a reroll-aware
    DP table).  The simulator's primary reroll path uses
    GoalProbabilityTable.should_reroll_dp() instead."""

    GOAL_UPGRADES = {"will+1", "will+2", "will+3", "will+4",
                     "chaos+1", "chaos+2", "chaos+3", "chaos+4"}
    GOAL_BIG_UPGRADES = {"will+2", "will+3", "will+4",
                         "chaos+2", "chaos+3", "chaos+4"}
    GOAL_DOWNGRADES = {"will-1", "chaos-1"}
    SIDE_UPGRADES = {"first+1", "first+2", "first+3", "first+4",
                     "second+1", "second+2", "second+3", "second+4"}
    SIDE_BIG_UPGRADES = {"first+2", "first+3", "first+4",
                         "second+2", "second+3", "second+4"}
    ALL_DOWNGRADES = {"will-1", "chaos-1", "first-1", "second-1"}

    def __init__(self, goal: LastTurnGoal, side_node_threshold: float = 0.5,
                 astro_gem: Optional[AstroGem] = None,
                 bis_only: bool = False,
                 dp_reroll_margin: float = 0.03,
                 side_quality_weight: float = 0.0) -> None:
        self.goal = goal
        # When this fraction (or more) of offers keep the goal feasible,
        # also consider side-node upgrades as valuable instead of focusing
        # solely on will/chaos.  0.0 = always value side nodes,
        # 1.0+ = never value side nodes until goal is fully met.
        self.side_node_threshold = side_node_threshold
        self.astro_gem = astro_gem
        self.bis_only = bis_only
        self.dp_reroll_margin = dp_reroll_margin
        self.side_quality_weight = side_quality_weight

    # ------------------------------------------------------------------
    # Target-aware helpers
    # ------------------------------------------------------------------

    def _target_side_sets(self, state: GemState) -> Tuple[set, set]:
        """Return (upgrades, big_upgrades) filtered to optimisation-target slots."""
        if self.astro_gem is None:
            return self.SIDE_UPGRADES, self.SIDE_BIG_UPGRADES

        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        slots: List[str] = []
        if state.first_effect in target:
            slots.append("first")
        if state.second_effect in target:
            slots.append("second")

        ups: set = set()
        big: set = set()
        for slot in slots:
            for n in range(1, 5):
                ups.add(f"{slot}+{n}")
                if n >= 2:
                    big.add(f"{slot}+{n}")
        return ups, big

    def effective_side_threshold(self, state: GemState) -> float:
        """Compute the side-node threshold scaled by target effect quality.

        High-value effects (e.g. boss_damage) keep the base threshold,
        low-value effects (e.g. attack_power) raise it so the policy
        stays in desperate mode longer.

        Formula: threshold + (1 - threshold) * (1 - quality)
        where quality = max target coeff on gem / max coeff in set.
        """
        if self.astro_gem is None:
            return self.side_node_threshold

        if self.astro_gem.optimize == "dps":
            target, coeff = DPS_EFFECTS, DPS_COEFF
        else:
            target, coeff = SUPPORT_EFFECTS, SUPPORT_COEFF

        max_coeff = max(coeff.values())
        target_coeffs = []
        if state.first_effect in target:
            target_coeffs.append(coeff[state.first_effect])
        if state.second_effect in target:
            target_coeffs.append(coeff[state.second_effect])

        if not target_coeffs:
            # No target effects on gem — side nodes have no value
            return 1.0

        quality = max(target_coeffs) / max_coeff
        return self.side_node_threshold + (1.0 - self.side_node_threshold) * (1.0 - quality)

    def _has_good_effect_change(self, offers: List[Option], state: GemState) -> bool:
        """True if any change_effect offer resolves to a target effect.

        The game pre-determines and shows the outcome, so we check the
        specific resolved effect rather than expected value.
        """
        if self.astro_gem is None:
            return False

        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        for o in offers:
            if o.resolved_effect and o.resolved_effect in target:
                return True
        return False

    def _has_bis_effects(self, state: GemState) -> bool:
        """True if both effect slots have target-type effects."""
        if self.astro_gem is None:
            return True
        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        return state.first_effect in target and state.second_effect in target

    # ------------------------------------------------------------------

    def should_reroll(
            self,
            offers: List[Option],
            state: GemState,
            turns_left: int,
            goal_feasible_frac: float,
            goal_success_prob: Optional[float] = None,
            dp_baseline: Optional[float] = None,
            rerolls_remaining: int = 0,
    ) -> Tuple[bool, List[str]]:
        keys = {o.key for o in offers}
        reasons: List[str] = []
        goal_met = self.goal.satisfied(state.will, state.chaos,
                                       state.first, state.second)

        # Use DP probability for comfort/desperate mode when available,
        # otherwise fall back to binary feasibility fraction.
        comfort_signal = goal_success_prob if goal_success_prob is not None else goal_feasible_frac

        # Target-aware side-node key sets
        side_ups, side_big_ups = self._target_side_sets(state)
        good_change = self._has_good_effect_change(offers, state)
        eff_threshold = self.effective_side_threshold(state)

        # Always reroll on last turn if goal not met
        if turns_left == 1 and not goal_met:
            reasons.append("last_turn_goal_not_met")
            return True, reasons

        # Always reroll if every offer would make goal infeasible
        if not goal_met and goal_feasible_frac == 0.0:
            reasons.append("no_offer_keeps_goal_feasible")
            return True, reasons

        if goal_met:
            # Goal achieved -- optimise side nodes, avoid any downgrades
            has_positive = (
                    any(o.delta > 0 and o.kind in ("will", "chaos", "first", "second")
                        for o in offers)
                    or good_change
            )
            has_downgrade = bool(keys & self.ALL_DOWNGRADES)
            has_big = bool(keys & (side_big_ups | self.GOAL_BIG_UPGRADES)) or good_change

            if has_downgrade and not has_big:
                reasons.append("goal_met_downgrade_without_big_upgrade")
            if not has_positive:
                reasons.append("goal_met_no_positive_upgrade")

        elif comfort_signal >= eff_threshold:
            # Comfortable -- any positive upgrade (goal or side) is acceptable
            has_any_upgrade = bool(keys & (self.GOAL_UPGRADES | side_ups)) or good_change
            has_any_downgrade = bool(keys & self.ALL_DOWNGRADES)
            has_any_big = bool(keys & (self.GOAL_BIG_UPGRADES | side_big_ups)) or good_change

            if has_any_downgrade and not has_any_big:
                reasons.append("downgrade_without_any_big_upgrade")
            if not has_any_upgrade:
                reasons.append("no_useful_upgrade")

        else:
            # Desperate -- focus purely on will/chaos
            has_goal_upgrade = any(
                o.kind in ("will", "chaos") and o.delta > 0 for o in offers
            )
            # BIS-only: treat good effect changes as upgrades when effects aren't optimal
            if self.bis_only and not self._has_bis_effects(state) and good_change:
                has_goal_upgrade = True
            has_goal_downgrade = bool(keys & self.GOAL_DOWNGRADES)
            has_goal_big = bool(keys & self.GOAL_BIG_UPGRADES)

            if has_goal_downgrade and not has_goal_big:
                reasons.append("goal_downgrade_without_big_upgrade")
            if not has_goal_upgrade:
                reasons.append("no_goal_upgrade")

        heuristic_reroll = len(reasons) > 0
        return self._dp_override(
            heuristic_reroll, reasons,
            goal_success_prob, dp_baseline,
            rerolls_remaining, turns_left,
            offers, state,
        )

    # ------------------------------------------------------------------
    # DP-based reroll override
    # ------------------------------------------------------------------

    _HARD_CONSTRAINTS = frozenset({"last_turn_goal_not_met",
                                   "no_offer_keeps_goal_feasible"})

    def _side_quality(self, offers: List[Option], state: GemState) -> float:
        """Best target-type side-node upgrade quality in [0.0, 1.0].

        Formula: (delta / 4) * (coeff / max_coeff).
        +4 boss_damage = 1.0, +2 attack_power = 0.2, +1 attack_power = 0.1.
        Returns 0.0 when side_quality_weight is 0.
        """
        if self.side_quality_weight <= 0.0:
            return 0.0
        if self.astro_gem is None:
            return 0.0

        if self.astro_gem.optimize == "dps":
            target, coeff = DPS_EFFECTS, DPS_COEFF
        else:
            target, coeff = SUPPORT_EFFECTS, SUPPORT_COEFF
        max_coeff = max(coeff.values())

        best = 0.0
        for o in offers:
            if o.kind in ("first", "second") and o.delta > 0:
                effect = (state.first_effect if o.kind == "first"
                          else state.second_effect)
                if effect in target:
                    quality = (o.delta / 4.0) * (coeff[effect] / max_coeff)
                    best = max(best, quality)
        return best

    def _dp_override(
            self,
            heuristic_reroll: bool,
            reasons: List[str],
            goal_success_prob: Optional[float],
            dp_baseline: Optional[float],
            rerolls_remaining: int,
            turns_left: int,
            offers: List[Option],
            state: GemState,
    ) -> Tuple[bool, List[str]]:
        """Override heuristic reroll decision using DP probability comparison.

        Compares the expected goal probability from the current 4 offers
        (goal_success_prob) against the baseline expected probability from
        a random draw (dp_baseline).  High-value side-node upgrades reduce
        the margin, making the policy more willing to keep offers that
        contain them even at some goal probability cost.
        """
        if goal_success_prob is None or dp_baseline is None:
            return heuristic_reroll, reasons

        # Never override hard constraints
        if self._HARD_CONSTRAINTS & set(reasons):
            return heuristic_reroll, reasons

        # Margin scales down when rerolls are surplus (won't all be used)
        effective_margin = self.dp_reroll_margin * min(
            1.0, turns_left / max(1, rerolls_remaining))

        # Side-node quality increases margin: a +4 boss_damage (quality=1.0)
        # doubles it, making the policy willing to accept offers further
        # below baseline goal probability to keep the side upgrade.
        side_q = self._side_quality(offers, state)
        side_adjustment = side_q * self.dp_reroll_margin * self.side_quality_weight
        effective_margin += side_adjustment

        if not heuristic_reroll and goal_success_prob < dp_baseline * (1.0 - effective_margin):
            reasons.append("dp_override_below_baseline")
            return True, reasons

        if heuristic_reroll and goal_success_prob >= dp_baseline * (1.0 - side_adjustment):
            return False, ["dp_override_above_baseline"]

        return heuristic_reroll, reasons
