from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple


@dataclass(frozen=True)
class Option:
    key: str
    weight: float
    kind: str  # will/chaos/first/second/view/cost/other
    delta: int = 0
    resolved_effect: str = ""  # populated for change_effect options at offer time


@dataclass(frozen=True)
class LastTurnGoal:
    # Any field left as None is ignored.
    min_will: Optional[int] = None
    min_chaos: Optional[int] = None
    exact_will: Optional[int] = None
    exact_chaos: Optional[int] = None
    min_total_will_chaos: Optional[int] = None
    exact_total_will_chaos: Optional[int] = None
    min_first: Optional[int] = None
    min_second: Optional[int] = None
    min_total: Optional[int] = None

    def satisfied(self, will: int, chaos: int,
                  first: int = 5, second: int = 5) -> bool:
        if self.exact_will is not None and will != self.exact_will:
            return False
        if self.exact_chaos is not None and chaos != self.exact_chaos:
            return False
        if self.min_will is not None and will < self.min_will:
            return False
        if self.min_chaos is not None and chaos < self.min_chaos:
            return False

        total = will + chaos
        if self.exact_total_will_chaos is not None and total != self.exact_total_will_chaos:
            return False
        if self.min_total_will_chaos is not None and total < self.min_total_will_chaos:
            return False

        if self.min_first is not None and first < self.min_first:
            return False
        if self.min_second is not None and second < self.min_second:
            return False

        if self.min_total is not None and (will + chaos + first + second) < self.min_total:
            return False

        return True

    def feasible(self, will: int, chaos: int, turns_left: int,
                 first: int = 1, second: int = 1,
                 *,
                 min_side_coeff: int = 0,
                 side_coeff_first: int = 0,
                 side_coeff_second: int = 0,
                 change_dest_coeffs: Tuple[int, int] = (0, 0)) -> bool:
        """
        Necessary feasibility check for min_will/min_chaos/min_first/min_second goals:
          - all stats capped at 5
          - one click can raise at most ONE stat by up to +4
          - for exact targets below current we return False (not handled here)

        When `min_side_coeff > 0`, also computes a conservative upper bound
        on achievable `side_coeff_first*first + side_coeff_second*second`
        in the remaining turns and rejects when the bound falls short of
        `min_side_coeff`. The bound covers change_*_effect rescues:
        `change_dest_coeffs` are the coefficients of the two non-equipped
        pool effects, and every effect arrangement reachable with k change
        turns is considered (a changed slot keeps its level, and an effect
        dropped from one slot can re-enter through the other).
        """
        target_w = self.exact_will if self.exact_will is not None else self.min_will
        target_c = self.exact_chaos if self.exact_chaos is not None else self.min_chaos

        if target_w is not None and target_w > 5:
            return False
        if target_c is not None and target_c > 5:
            return False

        if self.min_total_will_chaos is not None and self.min_total_will_chaos > 10:
            return False
        if self.exact_total_will_chaos is not None and self.exact_total_will_chaos > 10:
            return False

        if self.exact_will is not None and will > self.exact_will:
            return False
        if self.exact_chaos is not None and chaos > self.exact_chaos:
            return False

        req_w = max(0, (target_w - will)) if target_w is not None else 0
        req_c = max(0, (target_c - chaos)) if target_c is not None else 0

        if will + req_w > 5:
            return False
        if chaos + req_c > 5:
            return False

        req_f = max(0, (self.min_first - first)) if self.min_first is not None else 0
        req_s = max(0, (self.min_second - second)) if self.min_second is not None else 0

        if self.min_first is not None and self.min_first > 5:
            return False
        if self.min_second is not None and self.min_second > 5:
            return False

        turns_needed_w = math.ceil(req_w / 4) if req_w > 0 else 0
        turns_needed_c = math.ceil(req_c / 4) if req_c > 0 else 0
        turns_needed_f = math.ceil(req_f / 4) if req_f > 0 else 0
        turns_needed_s = math.ceil(req_s / 4) if req_s > 0 else 0
        if turns_needed_w + turns_needed_c + turns_needed_f + turns_needed_s > turns_left:
            return False

        # Optional total constraints (loose safe bound)
        total = will + chaos
        if self.exact_total_will_chaos is not None:
            if total > self.exact_total_will_chaos:
                return False
            req_total = self.exact_total_will_chaos - total
            if math.ceil(max(0, req_total) / 4) > turns_left:
                return False

        if self.min_total_will_chaos is not None:
            req_total = self.min_total_will_chaos - total
            if math.ceil(max(0, req_total) / 4) > turns_left:
                return False

        if self.min_total is not None:
            current_total = will + chaos + first + second
            max_possible = min(20, current_total + 4 * turns_left)
            if max_possible < self.min_total:
                return False

        if min_side_coeff > 0:
            # Upper bound on achievable side_coeff in remaining turns.
            # `available` is loose: shared between first/second leveling and
            # the change_effect option below (will/chaos turns are deducted).
            available = turns_left - turns_needed_w - turns_needed_c
            if available < 0:
                return False

            # Effect arrangements (first-slot coeff, second-slot coeff)
            # reachable after exactly k change_*_effect turns, with A/B the
            # equipped effects and C/D the two non-equipped pool members.
            # A change draws from the effects not currently equipped, so a
            # second change can pull the just-dropped effect into the other
            # slot, and a third completes the set with the full swap (B, A).
            # Each row lists only the arrangements NEW at that k: fewer
            # changes leave more levelling turns, so earlier rows dominate.
            ca, cb = side_coeff_first, side_coeff_second
            cc, cd = change_dest_coeffs
            reach = (
                ((ca, cb),),
                ((cc, cb), (cd, cb), (ca, cc), (ca, cd)),
                ((cc, ca), (cd, ca), (cc, cd), (cd, cc), (cb, cc), (cb, cd)),
                ((cb, ca),),
            )
            upper = 0
            for k in range(min(available, 3) + 1):
                rest = available - k
                lvl_first = min(5, first + 4 * rest)
                lvl_second = min(5, second + 4 * rest)
                for c1, c2 in reach[k]:
                    upper = max(upper, c1 * lvl_first + c2 * lvl_second)

            if upper < min_side_coeff:
                return False

        return True


@dataclass(frozen=True)
class AstroGem:
    gem_type: str  # key into GEM_TYPES, e.g. "chaos_distortion"
    first_effect: str  # starting first effect, e.g. "attack_power"
    second_effect: str  # starting second effect, e.g. "ally_damage"
    optimize: str  # "dps" or "support"


@dataclass
class GemState:
    will: int = 1
    chaos: int = 1
    first: int = 1
    second: int = 1
    cost_ratio: int = 0
    rerolls: int = 0
    first_effect: str = ""
    second_effect: str = ""

    def clone(self) -> "GemState":
        return GemState(
            will=self.will,
            chaos=self.chaos,
            first=self.first,
            second=self.second,
            cost_ratio=self.cost_ratio,
            rerolls=self.rerolls,
            first_effect=self.first_effect,
            second_effect=self.second_effect,
        )

    def total_points(self) -> int:
        return self.will + self.chaos + self.first + self.second


@dataclass
class RunResult:
    success: bool
    reason: str
    reset_used: bool
    state: GemState
    total_points: int
    rerolls_left: int
    extra_ticket_used: bool = True
    turn_log: Optional[List[Dict[str, Any]]] = None
    rerolls_by_turn: Optional[Dict[int, int]] = None
