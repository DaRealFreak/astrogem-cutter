from __future__ import annotations

from typing import List, Optional, Tuple

from arkgrid.constants import (
    DPS_EFFECTS, DPS_PRIORITY, GEM_TYPES,
    SUPPORT_EFFECTS, SUPPORT_PRIORITY,
)
from arkgrid.models import Option, LastTurnGoal, AstroGem, GemState


class RerollPolicy:
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
                 astro_gem: Optional[AstroGem] = None) -> None:
        self.goal = goal
        # When this fraction (or more) of offers keep the goal feasible,
        # also consider side-node upgrades as valuable instead of focusing
        # solely on will/chaos.  0.0 = always value side nodes,
        # 1.0+ = never value side nodes until goal is fully met.
        self.side_node_threshold = side_node_threshold
        self.astro_gem = astro_gem

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

    def _has_good_effect_change(self, keys: set, state: GemState) -> bool:
        """True if any change_effect option would improve the target priority."""
        if self.astro_gem is None:
            return False

        target = DPS_EFFECTS if self.astro_gem.optimize == "dps" else SUPPORT_EFFECTS
        prio = DPS_PRIORITY if self.astro_gem.optimize == "dps" else SUPPORT_PRIORITY
        pool = GEM_TYPES[self.astro_gem.gem_type]

        for key, cur_eff in [("change_first_effect", state.first_effect),
                             ("change_second_effect", state.second_effect)]:
            if key not in keys:
                continue
            available = [e for e in pool
                         if e != state.first_effect and e != state.second_effect]
            if not available:
                continue
            best = max(available, key=lambda e: (e in target, prio.get(e, 0)))
            cur_score = (cur_eff in target, prio.get(cur_eff, 0))
            best_score = (best in target, prio.get(best, 0))
            if best_score > cur_score:
                return True
        return False

    # ------------------------------------------------------------------

    def should_reroll(
            self,
            offers: List[Option],
            state: GemState,
            turns_left: int,
            goal_feasible_frac: float,
            goal_success_prob: Optional[float] = None,
    ) -> Tuple[bool, List[str]]:
        keys = {o.key for o in offers}
        reasons: List[str] = []
        goal_met = self.goal.satisfied(state.will, state.chaos)

        # Use DP probability for comfort/desperate mode when available,
        # otherwise fall back to binary feasibility fraction.
        comfort_signal = goal_success_prob if goal_success_prob is not None else goal_feasible_frac

        # Target-aware side-node key sets
        side_ups, side_big_ups = self._target_side_sets(state)
        good_change = self._has_good_effect_change(keys, state)

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
            has_big = bool(keys & (side_big_ups | self.GOAL_BIG_UPGRADES))

            if has_downgrade and not has_big:
                reasons.append("goal_met_downgrade_without_big_upgrade")
            if not has_positive:
                reasons.append("goal_met_no_positive_upgrade")

        elif comfort_signal >= self.side_node_threshold:
            # Comfortable -- any positive upgrade (goal or side) is acceptable
            has_any_upgrade = bool(keys & (self.GOAL_UPGRADES | side_ups)) or good_change
            has_any_downgrade = bool(keys & self.ALL_DOWNGRADES)
            has_any_big = bool(keys & (self.GOAL_BIG_UPGRADES | side_big_ups))

            if has_any_downgrade and not has_any_big:
                reasons.append("downgrade_without_any_big_upgrade")
            if not has_any_upgrade:
                reasons.append("no_useful_upgrade")

        else:
            # Desperate -- focus purely on will/chaos
            has_goal_upgrade = any(
                o.kind in ("will", "chaos") and o.delta > 0 for o in offers
            )
            has_goal_downgrade = bool(keys & self.GOAL_DOWNGRADES)
            has_goal_big = bool(keys & self.GOAL_BIG_UPGRADES)

            if has_goal_downgrade and not has_goal_big:
                reasons.append("goal_downgrade_without_big_upgrade")
            if not has_goal_upgrade:
                reasons.append("no_goal_upgrade")

        return len(reasons) > 0, reasons
