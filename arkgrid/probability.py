from __future__ import annotations

import math
from typing import FrozenSet, List, Optional, Dict, Tuple

from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, GEM_TYPES, SUPPORT_COEFF, SUPPORT_EFFECTS, fusion_avg_coeff
from arkgrid.models import Option, LastTurnGoal, GemState
from arkgrid.pool import OptionPool

_SQRT2 = math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _norm_pdf(x: float) -> float:
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


def _e_max(mu: float, sd: float, t: float) -> float:
    """E[max(X, t)] for X ~ Normal(mu, sd**2)."""
    if sd <= 0.0:
        return mu if mu > t else t
    d = (mu - t) / sd
    return t + (mu - t) * _norm_cdf(d) + sd * _norm_pdf(d)


class GoalProbabilityTable:
    """Precomputed P(reach goal | will, chaos, first, second, turns_left).

    Uses backward induction with a single-draw transition approximation
    (option probability = weight / sum of eligible weights).

    Build cost ~20ms. Lookup O(1).

    When *bis_only* is True the state is extended with two booleans
    (first_is_target, second_is_target) and success requires both
    effects to be target effects. This 4x's the state space (~25k
    entries for epic) but build time stays well under 100ms.
    """

    def __init__(
        self,
        goal: LastTurnGoal,
        max_turns: int,
        pool: OptionPool,
        *,
        bis_only: bool = False,
        target_effects: Optional[FrozenSet[str]] = None,
        side_coeff_first: int = 0,
        side_coeff_second: int = 0,
        min_side_coeff: int = 0,
        early_finish: bool = False,
        max_rerolls: int = 0,
        effect_aware: bool = False,
        gem_type: str = "",
        optimize: str = "dps",
    ) -> None:
        self.goal = goal
        self.max_turns = max_turns
        self.pool = pool
        self.effect_aware = effect_aware and gem_type in GEM_TYPES
        # effect_aware takes precedence over bis_only
        self.bis_only = bis_only and not self.effect_aware
        self._target_effects = target_effects or frozenset()
        self._side_coeff_first = side_coeff_first
        self._side_coeff_second = side_coeff_second
        self._min_side_coeff = min_side_coeff
        self.early_finish = early_finish
        self._max_rerolls = max_rerolls
        self._gem_type = gem_type
        self._optimize = optimize

        # Precompute per-effect coefficient table indexed by the gem's
        # 4-effect tuple. Non-target effects contribute 0.
        if self.effect_aware:
            effects = GEM_TYPES[gem_type]
            coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
            target_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
            self._effect_tuple: Tuple[str, ...] = effects
            self._effect_coeffs: Tuple[int, ...] = tuple(
                coeff_map.get(e, 0) if e in target_set else 0 for e in effects
            )
            # Precompute change-effect destinations for each (fi, si) pair.
            self._change_dests: Dict[Tuple[int, int], Tuple[int, ...]] = {}
            for fi in range(4):
                for si in range(4):
                    if fi == si:
                        continue
                    self._change_dests[(fi, si)] = tuple(
                        i for i in range(4) if i != fi and i != si
                    )
        else:
            self._effect_tuple = ()
            self._effect_coeffs = ()
            self._change_dests = {}

        self._dp: Dict[tuple, float] = {}
        if self.effect_aware:
            if max_rerolls > 0:
                self._build_effect_aware_with_rerolls()
            else:
                self._build_effect_aware()
        elif max_rerolls > 0 and not self.bis_only:
            self._build_with_rerolls()
        elif self.bis_only:
            self._build_bis()
        else:
            self._build()

    # ------------------------------------------------------------------
    # Transition helpers (option probability assignment)
    # ------------------------------------------------------------------

    def _option_probs(self, eligible: List[Option]) -> List[float]:
        """Return per-option applied probability (single-draw approximation)."""
        total_w = sum(o.weight for o in eligible)
        return [o.weight / total_w for o in eligible]

    # ------------------------------------------------------------------
    # Non-BIS transitions and build
    # ------------------------------------------------------------------

    def _transitions(self, w: int, c: int, f: int, s: int,
                     turn: int, turns_left: int) -> Dict[Tuple[int, int, int, int], float]:
        """Return {(nw, nc, nf, ns): probability} for one turn from this state."""
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return {(w, c, f, s): 1.0}

        probs = self._option_probs(eligible)
        dest: Dict[Tuple[int, int, int, int], float] = {}
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns = w, c, f, s
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            # cost/view/other/maintain -> no stat change
            key = (nw, nc, nf, ns)
            dest[key] = dest.get(key, 0.0) + p
        return dest

    def _coeff_satisfied(self, f: int, s: int,
                         ft: int = 1, st: int = 1) -> bool:
        if self._min_side_coeff <= 0:
            return True
        coeff_total = (self._side_coeff_first * f * ft
                       + self._side_coeff_second * s * st)
        return coeff_total >= self._min_side_coeff

    def _build(self) -> None:
        dp = self._dp
        mt = self.max_turns

        # Base case: turns_left == 0
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        sat = 1.0 if (self.goal.satisfied(w, c, f, s)
                                      and self._coeff_satisfied(f, s)) else 0.0
                        dp[(w, c, f, s, 0)] = sat

        # Precompute transition tables for three turn types.
        trans_cache: Dict[str, Dict[Tuple[int, int, int, int],
                                    Dict[Tuple[int, int, int, int], float]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache: Dict[Tuple[int, int, int, int],
                        Dict[Tuple[int, int, int, int], float]] = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = self._transitions(w, c, f, s, turn, tl)
            trans_cache[label] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            if (self.early_finish
                                    and self.goal.satisfied(w, c, f, s)
                                    and self._coeff_satisfied(f, s)):
                                dp[(w, c, f, s, tl)] = 1.0
                                continue
                            val = 0.0
                            for (nw, nc, nf, ns), p in tc[(w, c, f, s)].items():
                                val += p * dp[(nw, nc, nf, ns, tl - 1)]
                            dp[(w, c, f, s, tl)] = val

    # ------------------------------------------------------------------
    # Reroll-aware transitions and build
    # ------------------------------------------------------------------

    def _transitions_reroll(
        self, w: int, c: int, f: int, s: int,
        turn: int, turns_left: int,
    ) -> List[Tuple[float, int, int, int, int, int]]:
        """Return [(prob, nw, nc, nf, ns, view_delta)] per eligible option.

        Like _transitions() but preserves per-option view deltas so the
        reroll DP can track reroll count changes from view+N options.
        """
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, w, c, f, s, 0)]

        probs = self._option_probs(eligible)
        result: List[Tuple[float, int, int, int, int, int]] = []
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns = w, c, f, s
            vd = 0
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.kind == "view":
                vd = o.delta
            # cost/other/maintain -> no stat change, no view delta
            result.append((p, nw, nc, nf, ns, vd))
        return result

    def _build_with_rerolls(self) -> None:
        """Build DP table with reroll count as extra state dimension.

        State key: (w, c, f, s, r, turns_left) where r = rerolls available.

        Transition: on turns > 1, with r > 0 rerolls available, the player
        can choose to keep the current offers or reroll.  Under the
        single-draw approximation:

            V(s, r, tl) = max(
                sum_i p_i * V(apply_i(s), r + vd_i, tl-1),   # keep
                V(s, r-1, tl)                                  # reroll
            )

        Turn 1 never allows rerolling (hardcoded game rule).
        """
        dp = self._dp
        mt = self.max_turns
        max_r = self._max_rerolls

        # Base case: turns_left == 0
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        sat = 1.0 if (self.goal.satisfied(w, c, f, s)
                                      and self._coeff_satisfied(f, s)) else 0.0
                        for r in range(0, max_r + 1):
                            dp[(w, c, f, s, r, 0)] = sat

        # Precompute transition tables (with view deltas)
        TransEntry = List[Tuple[float, int, int, int, int, int]]
        trans_cache: Dict[str, Dict[Tuple[int, int, int, int], TransEntry]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache: Dict[Tuple[int, int, int, int], TransEntry] = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = self._transitions_reroll(
                                w, c, f, s, turn, tl)
            trans_cache[label] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            trans = tc[(w, c, f, s)]
                            for r in range(0, max_r + 1):
                                if (self.early_finish
                                        and self.goal.satisfied(w, c, f, s)
                                        and self._coeff_satisfied(f, s)):
                                    dp[(w, c, f, s, r, tl)] = 1.0
                                    continue

                                # Reroll decision uses per-option max:
                                # for each possible draw, keep if better
                                # than rerolling, otherwise reroll.
                                if r > 0 and turn_number != 1:
                                    reroll_val = dp[(w, c, f, s, r - 1, tl)]
                                    val = 0.0
                                    for (p, nw, nc, nf, ns, vd) in trans:
                                        nr = min(max_r, r + vd)
                                        post = dp[(nw, nc, nf, ns, nr, tl - 1)]
                                        val += p * max(post, reroll_val)
                                    dp[(w, c, f, s, r, tl)] = val
                                else:
                                    val = 0.0
                                    for (p, nw, nc, nf, ns, vd) in trans:
                                        nr = min(max_r, r + vd)
                                        val += p * dp[(nw, nc, nf, ns, nr, tl - 1)]
                                    dp[(w, c, f, s, r, tl)] = val

    # ------------------------------------------------------------------
    # BIS-aware transitions and build
    # ------------------------------------------------------------------
    # State key: (w, c, f, s, ft, st, tl)
    # ft/st are 0 or 1 (whether first/second effect is a target effect).
    #
    # Each gem type has exactly 2 target + 2 non-target effects.
    # When change_{first,second}_effect fires, the new effect is drawn
    # uniformly from the 2 effects not on the gem.  The probability that
    # it's a target is (2 - ft - st) / 2.
    # ------------------------------------------------------------------

    def _transitions_bis(
        self, w: int, c: int, f: int, s: int, ft: int, st: int,
        turn: int, turns_left: int,
    ) -> Dict[Tuple[int, int, int, int, int, int], float]:
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return {(w, c, f, s, ft, st): 1.0}

        probs = self._option_probs(eligible)
        dest: Dict[Tuple[int, int, int, int, int, int], float] = {}

        for p, o in zip(probs, eligible):
            nw, nc, nf, ns = w, c, f, s
            nft, nst = ft, st

            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.key == "change_first_effect":
                # Probabilistic transition for ft
                p_target = (2 - ft - st) / 2.0
                if p_target > 0:
                    k1 = (nw, nc, nf, ns, 1, nst)
                    dest[k1] = dest.get(k1, 0.0) + p * p_target
                if p_target < 1:
                    k0 = (nw, nc, nf, ns, 0, nst)
                    dest[k0] = dest.get(k0, 0.0) + p * (1 - p_target)
                continue  # already added to dest
            elif o.key == "change_second_effect":
                p_target = (2 - ft - st) / 2.0
                if p_target > 0:
                    k1 = (nw, nc, nf, ns, nft, 1)
                    dest[k1] = dest.get(k1, 0.0) + p * p_target
                if p_target < 1:
                    k0 = (nw, nc, nf, ns, nft, 0)
                    dest[k0] = dest.get(k0, 0.0) + p * (1 - p_target)
                continue

            key = (nw, nc, nf, ns, nft, nst)
            dest[key] = dest.get(key, 0.0) + p

        return dest

    def _build_bis(self) -> None:
        dp = self._dp
        mt = self.max_turns

        ft_range = (0, 1)
        st_range = (0, 1)

        # Base case: turns_left == 0
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        for ft in ft_range:
                            for st in st_range:
                                # BIS: success requires targets + goal + coefficient
                                goal_sat = self.goal.satisfied(w, c, f, s)
                                sat = 1.0 if (goal_sat and ft == 1 and st == 1
                                              and self._coeff_satisfied(f, s, ft, st)) else 0.0
                                dp[(w, c, f, s, ft, st, 0)] = sat

        # Precompute transition tables
        StateKey = Tuple[int, int, int, int, int, int]
        trans_cache: Dict[str, Dict[StateKey, Dict[StateKey, float]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache: Dict[StateKey, Dict[StateKey, float]] = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            for ft in ft_range:
                                for st in st_range:
                                    cache[(w, c, f, s, ft, st)] = \
                                        self._transitions_bis(w, c, f, s, ft, st, turn, tl)
            trans_cache[label] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            for ft in ft_range:
                                for st in st_range:
                                    if (self.early_finish
                                            and self.goal.satisfied(w, c, f, s)
                                            and ft == 1 and st == 1
                                            and self._coeff_satisfied(f, s, ft, st)):
                                        dp[(w, c, f, s, ft, st, tl)] = 1.0
                                        continue
                                    val = 0.0
                                    for dest_key, p in tc[(w, c, f, s, ft, st)].items():
                                        val += p * dp[(*dest_key, tl - 1)]
                                    dp[(w, c, f, s, ft, st, tl)] = val

    # ------------------------------------------------------------------
    # Effect-aware transitions and build
    # ------------------------------------------------------------------
    # State key: (w, c, f, s, fi, si, tl[, r])
    # fi/si are indices into GEM_TYPES[gem_type], always fi != si.
    # Change_first/second_effect transitions route probabilistically
    # across the 2 effects not currently equipped (self._change_dests).
    # ------------------------------------------------------------------

    def _effect_aware_transitions(
        self, w: int, c: int, f: int, s: int,
        turn: int, turns_left: int,
    ) -> List[Tuple[float, str, str, int, int, int, int, int]]:
        """Return [(prob, option_key, option_kind, nw, nc, nf, ns, view_delta)].

        Same eligibility logic as _transitions() but preserves option key
        (for change_effect detection) and view delta (for reroll-aware DP).
        Does not apply fi/si updates — those are handled at build time
        using self._change_dests.
        """
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, "", "", w, c, f, s, 0)]

        probs = self._option_probs(eligible)
        result: List[Tuple[float, str, str, int, int, int, int, int]] = []
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns = w, c, f, s
            vd = 0
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.kind == "view":
                vd = o.delta
            result.append((p, o.key, o.kind, nw, nc, nf, ns, vd))
        return result

    def _coeff_satisfied_idx(self, f: int, s: int, fi: int, si: int) -> bool:
        if self._min_side_coeff <= 0:
            return True
        coeff_total = (self._effect_coeffs[fi] * f
                       + self._effect_coeffs[si] * s)
        return coeff_total >= self._min_side_coeff

    def _valid_effect_pairs(self) -> List[Tuple[int, int]]:
        return [(fi, si) for fi in range(4) for si in range(4) if fi != si]

    def _build_effect_aware(self) -> None:
        dp = self._dp
        mt = self.max_turns
        valid_pairs = self._valid_effect_pairs()

        # Base case: turns_left == 0
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        goal_sat = self.goal.satisfied(w, c, f, s)
                        for fi, si in valid_pairs:
                            sat = 1.0 if (goal_sat
                                          and self._coeff_satisfied_idx(
                                              f, s, fi, si)) else 0.0
                            dp[(w, c, f, s, fi, si, 0)] = sat

        # Precompute option-level transition tables (independent of fi/si)
        trans_cache: Dict[str, Dict[Tuple[int, int, int, int],
                                    List[Tuple[float, str, str,
                                               int, int, int, int, int]]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache: Dict[Tuple[int, int, int, int],
                        List[Tuple[float, str, str,
                                   int, int, int, int, int]]] = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = \
                                self._effect_aware_transitions(w, c, f, s,
                                                               turn, tl)
            trans_cache[label] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            trans = tc[(w, c, f, s)]
                            goal_sat = self.goal.satisfied(w, c, f, s)
                            for fi, si in valid_pairs:
                                if (self.early_finish and goal_sat
                                        and self._coeff_satisfied_idx(
                                            f, s, fi, si)):
                                    dp[(w, c, f, s, fi, si, tl)] = 1.0
                                    continue
                                dests = self._change_dests[(fi, si)]
                                n_dests = len(dests)  # always 2
                                val = 0.0
                                for (p, key, _kind,
                                     nw, nc, nf, ns, _vd) in trans:
                                    if key == "change_first_effect":
                                        for new_fi in dests:
                                            val += (p / n_dests) * dp[
                                                (nw, nc, nf, ns,
                                                 new_fi, si, tl - 1)]
                                    elif key == "change_second_effect":
                                        for new_si in dests:
                                            val += (p / n_dests) * dp[
                                                (nw, nc, nf, ns,
                                                 fi, new_si, tl - 1)]
                                    else:
                                        val += p * dp[(nw, nc, nf, ns,
                                                       fi, si, tl - 1)]
                                dp[(w, c, f, s, fi, si, tl)] = val

    def _build_effect_aware_with_rerolls(self) -> None:
        """Effect-aware DP extended with reroll count as extra state dim."""
        dp = self._dp
        mt = self.max_turns
        max_r = self._max_rerolls
        valid_pairs = self._valid_effect_pairs()

        # Base case: turns_left == 0
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        goal_sat = self.goal.satisfied(w, c, f, s)
                        for fi, si in valid_pairs:
                            sat = 1.0 if (goal_sat
                                          and self._coeff_satisfied_idx(
                                              f, s, fi, si)) else 0.0
                            for r in range(0, max_r + 1):
                                dp[(w, c, f, s, fi, si, r, 0)] = sat

        trans_cache: Dict[str, Dict[Tuple[int, int, int, int],
                                    List[Tuple[float, str, str,
                                               int, int, int, int, int]]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache: Dict[Tuple[int, int, int, int],
                        List[Tuple[float, str, str,
                                   int, int, int, int, int]]] = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = \
                                self._effect_aware_transitions(w, c, f, s,
                                                               turn, tl)
            trans_cache[label] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            trans = tc[(w, c, f, s)]
                            goal_sat = self.goal.satisfied(w, c, f, s)
                            for fi, si in valid_pairs:
                                dests = self._change_dests[(fi, si)]
                                n_dests = len(dests)
                                for r in range(0, max_r + 1):
                                    if (self.early_finish and goal_sat
                                            and self._coeff_satisfied_idx(
                                                f, s, fi, si)):
                                        dp[(w, c, f, s, fi, si, r, tl)] = 1.0
                                        continue

                                    # Compute keep-value: expected value
                                    # of the 4-draw-pick-1 outcome
                                    def post_val(key, nw, nc, nf, ns, nr):
                                        if key == "change_first_effect":
                                            v = 0.0
                                            for new_fi in dests:
                                                v += dp[(nw, nc, nf, ns,
                                                         new_fi, si, nr,
                                                         tl - 1)] / n_dests
                                            return v
                                        if key == "change_second_effect":
                                            v = 0.0
                                            for new_si in dests:
                                                v += dp[(nw, nc, nf, ns,
                                                         fi, new_si, nr,
                                                         tl - 1)] / n_dests
                                            return v
                                        return dp[(nw, nc, nf, ns,
                                                   fi, si, nr, tl - 1)]

                                    if r > 0 and turn_number != 1:
                                        reroll_val = dp[
                                            (w, c, f, s, fi, si, r - 1, tl)]
                                        val = 0.0
                                        for (p, key, _kind,
                                             nw, nc, nf, ns, vd) in trans:
                                            nr = min(max_r, r + vd)
                                            post = post_val(key, nw, nc,
                                                            nf, ns, nr)
                                            val += p * max(post, reroll_val)
                                        dp[(w, c, f, s, fi, si, r, tl)] = val
                                    else:
                                        val = 0.0
                                        for (p, key, _kind,
                                             nw, nc, nf, ns, vd) in trans:
                                            nr = min(max_r, r + vd)
                                            val += p * post_val(
                                                key, nw, nc, nf, ns, nr)
                                        dp[(w, c, f, s, fi, si, r, tl)] = val

    def _effect_indices(self, state: GemState) -> Optional[Tuple[int, int]]:
        """Translate state.first_effect/second_effect to (fi, si) indices."""
        try:
            fi = self._effect_tuple.index(state.first_effect)
            si = self._effect_tuple.index(state.second_effect)
        except ValueError:
            return None
        if fi == si:
            return None
        return fi, si

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(self, state: GemState, turns_left: int,
               rerolls: Optional[int] = None) -> float:
        if self.effect_aware:
            idx = self._effect_indices(state)
            if idx is None:
                return 0.0
            fi, si = idx
            w, c, f, s = (state.will, state.chaos,
                          state.first, state.second)
            if self._max_rerolls > 0:
                r = min(self._max_rerolls,
                        rerolls if rerolls is not None else 0)
                return self._dp.get(
                    (w, c, f, s, fi, si, r, turns_left), 0.0)
            return self._dp.get(
                (w, c, f, s, fi, si, turns_left), 0.0)
        if self._max_rerolls > 0 and not self.bis_only:
            r = min(self._max_rerolls, rerolls if rerolls is not None else 0)
            return self._dp.get(
                (state.will, state.chaos, state.first, state.second,
                 r, turns_left), 0.0)
        if self.bis_only:
            ft = 1 if state.first_effect in self._target_effects else 0
            st = 1 if state.second_effect in self._target_effects else 0
            return self._dp.get(
                (state.will, state.chaos, state.first, state.second,
                 ft, st, turns_left), 0.0)
        return self._dp.get(
            (state.will, state.chaos, state.first, state.second, turns_left), 0.0)

    def lookup_bis_averaged(self, turns_left: int,
                            w: int = 1, c: int = 1,
                            f: int = 1, s: int = 1) -> float:
        """Average BIS probability over all starting (ft, st) combinations.

        Weights: P(ft=1,st=1)=1/6, P(ft=1,st=0)=P(ft=0,st=1)=1/3,
        P(ft=0,st=0)=1/6.  Derived from drawing 2 effects without
        replacement from a pool of 2 target + 2 non-target.
        """
        dp = self._dp
        return (dp.get((w, c, f, s, 1, 1, turns_left), 0.0) / 6
                + dp.get((w, c, f, s, 1, 0, turns_left), 0.0) / 3
                + dp.get((w, c, f, s, 0, 1, turns_left), 0.0) / 3
                + dp.get((w, c, f, s, 0, 0, turns_left), 0.0) / 6)

    def lookup_after_effect_change(
        self, state: GemState, slot: str, turns_left: int,
    ) -> float:
        """Expected P(goal) after an effect-change option on *slot* ('first' or 'second').

        Averages over the probabilistic outcome of the new effect.
        Only meaningful when bis_only=True; otherwise identical to a no-op lookup.
        """
        if not self.bis_only:
            return self.lookup(state, turns_left)

        ft = 1 if state.first_effect in self._target_effects else 0
        st = 1 if state.second_effect in self._target_effects else 0
        p_target = (2 - ft - st) / 2.0
        w, c, f, s = state.will, state.chaos, state.first, state.second

        if slot == "first":
            p_good = self._dp.get((w, c, f, s, 1, st, turns_left), 0.0)
            p_bad = self._dp.get((w, c, f, s, 0, st, turns_left), 0.0)
        else:
            p_good = self._dp.get((w, c, f, s, ft, 1, turns_left), 0.0)
            p_bad = self._dp.get((w, c, f, s, ft, 0, turns_left), 0.0)

        return p_target * p_good + (1 - p_target) * p_bad

    def expected_prob_after_click(self, state: GemState,
                                  offers: List[Option],
                                  turns_left_after: int,
                                  rerolls: Optional[int] = None) -> float:
        """Average goal probability across the 4 offers (uniform 25% pick)."""
        if not offers:
            return 0.0
        total = 0.0
        for o in offers:
            nw = min(5, max(1, state.will + o.delta)) if o.kind == "will" else state.will
            nc = min(5, max(1, state.chaos + o.delta)) if o.kind == "chaos" else state.chaos
            nf = min(5, max(1, state.first + o.delta)) if o.kind == "first" else state.first
            ns = min(5, max(1, state.second + o.delta)) if o.kind == "second" else state.second

            if self.effect_aware:
                idx = self._effect_indices(state)
                if idx is None:
                    continue
                fi, si = idx
                r = rerolls if rerolls is not None else 0
                vd = o.delta if o.kind == "view" else 0
                nr = min(self._max_rerolls, r + vd) if self._max_rerolls > 0 else 0
                dests = self._change_dests[(fi, si)]
                n_dests = len(dests)
                if o.key == "change_first_effect":
                    v = 0.0
                    for new_fi in dests:
                        v += self._dp_lookup_ea(nw, nc, nf, ns,
                                                new_fi, si, nr,
                                                turns_left_after) / n_dests
                    total += v
                elif o.key == "change_second_effect":
                    v = 0.0
                    for new_si in dests:
                        v += self._dp_lookup_ea(nw, nc, nf, ns,
                                                fi, new_si, nr,
                                                turns_left_after) / n_dests
                    total += v
                else:
                    total += self._dp_lookup_ea(nw, nc, nf, ns,
                                                fi, si, nr,
                                                turns_left_after)
            elif self._max_rerolls > 0 and not self.bis_only:
                r = rerolls if rerolls is not None else 0
                vd = o.delta if o.kind == "view" else 0
                nr = min(self._max_rerolls, r + vd)
                total += self._dp.get(
                    (nw, nc, nf, ns, nr, turns_left_after), 0.0)
            elif self.bis_only and o.key in ("change_first_effect", "change_second_effect"):
                next_state = GemState(will=nw, chaos=nc, first=nf, second=ns,
                                      first_effect=state.first_effect,
                                      second_effect=state.second_effect)
                slot = "first" if o.key == "change_first_effect" else "second"
                total += self.lookup_after_effect_change(next_state, slot, turns_left_after)
            elif self.bis_only:
                ft = 1 if state.first_effect in self._target_effects else 0
                st = 1 if state.second_effect in self._target_effects else 0
                total += self._dp.get((nw, nc, nf, ns, ft, st, turns_left_after), 0.0)
            else:
                total += self._dp.get((nw, nc, nf, ns, turns_left_after), 0.0)
        return total / len(offers)

    def _dp_lookup_ea(self, w: int, c: int, f: int, s: int,
                      fi: int, si: int, r: int, tl: int) -> float:
        """Internal effect-aware DP lookup by indices."""
        if self._max_rerolls > 0:
            return self._dp.get((w, c, f, s, fi, si, r, tl), 0.0)
        return self._dp.get((w, c, f, s, fi, si, tl), 0.0)

    def should_reroll_dp(self, state: GemState, offers: List[Option],
                         turns_left: int, rerolls: int) -> bool:
        """DP-optimal reroll decision for reroll-aware table.

        Uses per-option comparison: for each of the 4 actual offers,
        checks if keeping (uniform 25% pick) gives higher expected
        value than rerolling.  Rerolls when the value with selective
        rejection (keeping good offers, rerolling bad ones) exceeds
        the keep-all average.

        In practice this simplifies to: reroll if the average post-click
        value of the offers is below the reroll value, since with
        uniform pick the player can't select individual offers.
        """
        if self._max_rerolls <= 0 or rerolls <= 0:
            return False
        keep_val = self.expected_prob_after_click(
            state, offers, turns_left - 1, rerolls=rerolls)
        reroll_val = self.lookup(state, turns_left,
                                 rerolls=rerolls - 1)
        return reroll_val > keep_val


class SideValueTable:
    """Expected final *gem value* under optimal finish / process play.

    A parallel DP to `GoalProbabilityTable`, consulted once the goal is met
    to decide finish-vs-continue. Effect-aware; the state key is
    `(w, c, f, s, fi, si, tl)`. The stored value is a *coefficient*, not a
    probability:

        gem_value(state) = side_coeff(state) + tier_bonus(total_points)

    with goal-broken states valued 0. Backward induction takes a max over
    finish-now vs process, so V always floors at `gem_value` — the table is
    the destination-value oracle for `_side_value_finish_decision`, not a
    value compared directly.

    There is deliberately no reroll dimension. Under the single-draw
    pool-average transition model a reroll redraws from the same pool, so
    its expected value equals the process arm — V would be identical for
    every reroll count. The decision layer still values the *current* turn's
    reroll: it compares this table's value (the pool-average continuation)
    against `expected_value_after_click` over the actual 4 offers in hand.

    Self-disables (`enabled is False`, every lookup returns 0.0) when the
    gem type is unknown, mirroring `GoalProbabilityTable`'s effect-aware
    self-disable.
    """

    def __init__(
        self,
        goal: LastTurnGoal,
        max_turns: int,
        pool: OptionPool,
        *,
        gem_type: str,
        optimize: str = "dps",
        min_side_coeff: int = 0,
        relic_coeff: Optional[int] = None,
        ancient_coeff: Optional[int] = None,
        value_mode: str = "side",
        max_rerolls: int = 0,
    ) -> None:
        self.goal = goal
        self.max_turns = max_turns
        self.pool = pool
        self._gem_type = gem_type
        self._optimize = optimize
        self._min_side_coeff = min_side_coeff
        self.value_mode = value_mode
        self._max_rerolls = max_rerolls
        self.enabled = gem_type in GEM_TYPES
        if self.enabled:
            # Default the tier weights to the fusion-derived average gem
            # coefficient for this gem type; an explicit value overrides.
            self.relic_coeff = (
                relic_coeff if relic_coeff is not None
                else fusion_avg_coeff(gem_type, optimize, "relic"))
            self.ancient_coeff = (
                ancient_coeff if ancient_coeff is not None
                else fusion_avg_coeff(gem_type, optimize, "ancient"))
        else:
            # Table self-disables when the gem type is unknown; the gate
            # never reads these, but keep them well-defined ints.
            self.relic_coeff = relic_coeff or 0
            self.ancient_coeff = ancient_coeff or 0
        if value_mode == "will_chaos":
            # will/chaos value ignores grade entirely.
            self.relic_coeff = 0
            self.ancient_coeff = 0
        self._dp: Dict[tuple, float] = {}

        if not self.enabled:
            self._effect_tuple: Tuple[str, ...] = ()
            self._effect_coeffs: Tuple[int, ...] = ()
            self._change_dests: Dict[Tuple[int, int], Tuple[int, ...]] = {}
            return

        effects = GEM_TYPES[gem_type]
        coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        target_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        self._effect_tuple = effects
        self._effect_coeffs = tuple(
            coeff_map.get(e, 0) if e in target_set else 0 for e in effects)
        self._change_dests = {}
        for fi in range(4):
            for si in range(4):
                if fi != si:
                    self._change_dests[(fi, si)] = tuple(
                        i for i in range(4) if i != fi and i != si)
        if max_rerolls > 0:
            self._build_reroll()
        else:
            self._build()

    # -- value model -------------------------------------------------

    def _tier_bonus(self, total_points: int) -> int:
        """Additive grade weight: ancient (>=19) or relic+ (>=16) or 0."""
        if total_points >= 19:
            return self.ancient_coeff
        if total_points >= 16:
            return self.relic_coeff
        return 0

    def _gem_value_idx(self, w: int, c: int, f: int, s: int,
                       fi: int, si: int) -> float:
        """Terminal gem value for an effect-indexed state.

        0 when the goal (or the `min_side_coeff` floor) is broken — a
        failed gem is worth nothing, which makes the DP price the risk of
        processing into a goal-break.
        """
        if not self.goal.satisfied(w, c, f, s):
            return 0.0
        if self.value_mode == "will_chaos":
            # New-character value: will + chaos only, no side/grade value
            # and no side-coeff floor.
            return float(w + c)
        if self.value_mode == "grade_only":
            # Dead-goal fallback under --ignore-side-node-values: value the
            # gem's grade (relic/ancient tier bonus) ONLY, ignoring the
            # side-node coefficients the player opted out of. When no higher
            # grade is reachable the value is flat across every offer, so the
            # decision finishes instead of fishing for side-node levels.
            return float(self._tier_bonus(w + c + f + s))
        coeff = self._effect_coeffs[fi] * f + self._effect_coeffs[si] * s
        if self._min_side_coeff > 0 and coeff < self._min_side_coeff:
            return 0.0
        return float(coeff + self._tier_bonus(w + c + f + s))

    def _effect_indices(self, state: GemState):
        """Translate state.first_effect/second_effect to (fi, si) indices."""
        try:
            fi = self._effect_tuple.index(state.first_effect)
            si = self._effect_tuple.index(state.second_effect)
        except ValueError:
            return None
        if fi == si:
            return None
        return fi, si

    # -- transitions (copy of GoalProbabilityTable._effect_aware_transitions,
    #    minus the reroll/view-delta bookkeeping the side-value DP omits) --

    def _transitions(self, w: int, c: int, f: int, s: int,
                     turn: int, turns_left: int):
        """Return [(prob, option_key, option_kind, nw, nc, nf, ns)].

        fi/si updates are applied at build time via self._change_dests.
        """
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, "", "", w, c, f, s)]
        total_w = sum(o.weight for o in eligible)
        result = []
        for o in eligible:
            p = o.weight / total_w
            nw, nc, nf, ns = w, c, f, s
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            # cost / view / other / maintain -> no stat change
            result.append((p, o.key, o.kind, nw, nc, nf, ns))
        return result

    def _post_val(self, key: str, nw: int, nc: int, nf: int, ns: int,
                  fi: int, si: int, dests: Tuple[int, ...], nd: int,
                  tl: int) -> float:
        """V at a transition destination, routing change_effect uniformly
        across the two non-equipped pool members."""
        if key == "change_first_effect":
            return sum(self._dp[(nw, nc, nf, ns, d, si, tl)]
                       for d in dests) / nd
        if key == "change_second_effect":
            return sum(self._dp[(nw, nc, nf, ns, fi, d, tl)]
                       for d in dests) / nd
        return self._dp[(nw, nc, nf, ns, fi, si, tl)]

    def _build(self) -> None:
        dp = self._dp
        mt = self.max_turns
        valid_pairs = [(fi, si) for fi in range(4)
                       for si in range(4) if fi != si]

        # Terminal: turns_left == 0 -> gem_value.
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        for fi, si in valid_pairs:
                            dp[(w, c, f, s, fi, si, 0)] = \
                                self._gem_value_idx(w, c, f, s, fi, si)

        # Option-level transition cache (independent of fi/si).
        trans_cache = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = self._transitions(
                                w, c, f, s, turn, tl)
            trans_cache[label] = cache

        # Backward induction: V = max(finish now, process).
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            trans = tc[(w, c, f, s)]
                            for fi, si in valid_pairs:
                                dests = self._change_dests[(fi, si)]
                                nd = len(dests)
                                finish_val = self._gem_value_idx(
                                    w, c, f, s, fi, si)
                                proc = 0.0
                                for (p, key, _kind,
                                     nw, nc, nf, ns) in trans:
                                    proc += p * self._post_val(
                                        key, nw, nc, nf, ns,
                                        fi, si, dests, nd, tl - 1)
                                dp[(w, c, f, s, fi, si, tl)] = (
                                    finish_val if finish_val > proc
                                    else proc)

    def _build_reroll(self) -> None:
        dp = self._dp
        mt = self.max_turns
        maxR = self._max_rerolls
        valid_pairs = [(fi, si) for fi in range(4)
                       for si in range(4) if fi != si]

        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        for fi, si in valid_pairs:
                            v = self._gem_value_idx(w, c, f, s, fi, si)
                            for r in range(maxR + 1):
                                dp[(w, c, f, s, fi, si, r, 0)] = v

        def transitions(w, c, f, s, turn, tl):
            state = GemState(will=w, chaos=c, first=f, second=s)
            elig = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, tl)]
            if not elig:
                return [(1.0, "", "", w, c, f, s, 0)], 0
            tot = sum(o.weight for o in elig)
            out = []
            for o in elig:
                nw, nc, nf, ns, vd = w, c, f, s, 0
                if o.kind == "will":
                    nw = min(5, max(1, w + o.delta))
                elif o.kind == "chaos":
                    nc = min(5, max(1, c + o.delta))
                elif o.kind == "first":
                    nf = min(5, max(1, f + o.delta))
                elif o.kind == "second":
                    ns = min(5, max(1, s + o.delta))
                elif o.kind == "view":
                    vd = o.delta
                out.append((o.weight / tot, o.key, o.kind, nw, nc, nf, ns, vd))
            return out, len(elig)

        trans_cache = {}
        for label, turn, tl in [("first", 1, mt), ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = transitions(w, c, f, s, turn, tl)
            trans_cache[label] = cache

        cd = self._change_dests

        def post_val(key, nw, nc, nf, ns, fi, si, nr, tl):
            if key == "change_first_effect":
                d = cd[(fi, si)]
                return sum(dp[(nw, nc, nf, ns, di, si, nr, tl)] for di in d) / len(d)
            if key == "change_second_effect":
                d = cd[(fi, si)]
                return sum(dp[(nw, nc, nf, ns, fi, di, nr, tl)] for di in d) / len(d)
            return dp[(nw, nc, nf, ns, fi, si, nr, tl)]

        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            tc = (trans_cache["first"] if turn_number == 1
                  else trans_cache["last"] if tl == 1
                  else trans_cache["middle"])
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            trans, n_elig = tc[(w, c, f, s)]
                            fpc = ((n_elig - 4) / (n_elig - 1)
                                   if n_elig > 4 else 0.0)
                            for fi, si in valid_pairs:
                                finish_val = self._gem_value_idx(w, c, f, s, fi, si)
                                for r in range(maxR + 1):
                                    xs = []
                                    for (p, key, _k, nw, nc, nf, ns, vd) in trans:
                                        nr = min(maxR, r + vd)
                                        xs.append((p, post_val(
                                            key, nw, nc, nf, ns, fi, si, nr, tl - 1)))
                                    mu = sum(p * x for p, x in xs)
                                    var = sum(p * (x - mu) ** 2 for p, x in xs)
                                    sd = math.sqrt(max(0.0, var / 4.0 * fpc))
                                    if r > 0 and turn_number != 1:
                                        rc = dp[(w, c, f, s, fi, si, r - 1, tl)]
                                        t = finish_val if finish_val > rc else rc
                                    else:
                                        t = finish_val
                                    dp[(w, c, f, s, fi, si, r, tl)] = _e_max(mu, sd, t)

    # -- public API --------------------------------------------------

    def gem_value(self, state: GemState) -> float:
        """Value of finishing the gem in its current state."""
        if not self.enabled:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        return self._gem_value_idx(state.will, state.chaos,
                                   state.first, state.second, fi, si)

    def lookup(self, state: GemState, turns_left: int, rerolls=None) -> float:
        """Expected final gem value under optimal play from this state."""
        if not self.enabled:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        w, c, f, s = state.will, state.chaos, state.first, state.second
        if self._max_rerolls > 0:
            r = min(self._max_rerolls, rerolls or 0)
            return self._dp.get((w, c, f, s, fi, si, r, turns_left), 0.0)
        return self._dp.get((w, c, f, s, fi, si, turns_left), 0.0)

    def expected_value_after_click(self, state: GemState,
                                   offers: List[Option],
                                   turns_left_after: int,
                                   rerolls=None) -> float:
        """Mean V across the 4 *actual* visible offers (uniform 25% pick).

        Mirrors `GoalProbabilityTable.expected_prob_after_click` — the
        process-EV term of the finish decision uses the real offers, not
        the pool-model single draw the table is built with.
        """
        if not self.enabled or not offers:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        dests = self._change_dests[(fi, si)]
        nd = len(dests)
        ra = self._max_rerolls > 0
        total = 0.0
        for o in offers:
            nw = (min(5, max(1, state.will + o.delta))
                  if o.kind == "will" else state.will)
            nc = (min(5, max(1, state.chaos + o.delta))
                  if o.kind == "chaos" else state.chaos)
            nf = (min(5, max(1, state.first + o.delta))
                  if o.kind == "first" else state.first)
            ns = (min(5, max(1, state.second + o.delta))
                  if o.kind == "second" else state.second)
            if ra:
                vd = o.delta if o.kind == "view" else 0
                nr = min(self._max_rerolls, (rerolls or 0) + vd)
                k = lambda a, b: (nw, nc, nf, ns, a, b, nr, turns_left_after)
            else:
                k = lambda a, b: (nw, nc, nf, ns, a, b, turns_left_after)
            if o.key == "change_first_effect":
                total += sum(self._dp.get(k(d, si), 0.0) for d in dests) / nd
            elif o.key == "change_second_effect":
                total += sum(self._dp.get(k(fi, d), 0.0) for d in dests) / nd
            else:
                total += self._dp.get(k(fi, si), 0.0)
        return total / len(offers)
