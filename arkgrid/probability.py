from __future__ import annotations

from typing import FrozenSet, List, Optional, Dict, Tuple

from arkgrid.models import Option, LastTurnGoal, GemState
from arkgrid.pool import OptionPool


class GoalProbabilityTable:
    """Precomputed P(reach goal | will, chaos, first, second, turns_left).

    Uses backward induction with a single-draw transition approximation
    (option probability = weight / sum of eligible weights).
    Build cost ~20ms for 6,250 states.  Lookup O(1).

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
    ) -> None:
        self.goal = goal
        self.max_turns = max_turns
        self.pool = pool
        self.bis_only = bis_only
        self._target_effects = target_effects or frozenset()
        self._dp: Dict[tuple, float] = {}
        if bis_only:
            self._build_bis()
        else:
            self._build()

    # ------------------------------------------------------------------
    # Non-BIS build (original)
    # ------------------------------------------------------------------

    def _transitions(self, w: int, c: int, f: int, s: int,
                     turn: int, turns_left: int) -> Dict[Tuple[int, int, int, int], float]:
        """Return {(nw, nc, nf, ns): probability} for one turn from this state."""
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        total_w = sum(o.weight for o in eligible)
        if total_w == 0.0:
            return {(w, c, f, s): 1.0}

        dest: Dict[Tuple[int, int, int, int], float] = {}
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
            # cost/view/other/maintain -> no stat change
            key = (nw, nc, nf, ns)
            dest[key] = dest.get(key, 0.0) + p
        return dest

    def _build(self) -> None:
        dp = self._dp
        mt = self.max_turns

        # Base case: turns_left == 0
        for w in range(1, 6):
            for c in range(1, 6):
                sat = 1.0 if self.goal.satisfied(w, c) else 0.0
                for f in range(1, 6):
                    for s in range(1, 6):
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
                            val = 0.0
                            for (nw, nc, nf, ns), p in tc[(w, c, f, s)].items():
                                val += p * dp[(nw, nc, nf, ns, tl - 1)]
                            dp[(w, c, f, s, tl)] = val

    # ------------------------------------------------------------------
    # BIS-aware build
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
        total_w = sum(o.weight for o in eligible)
        if total_w == 0.0:
            return {(w, c, f, s, ft, st): 1.0}

        dest: Dict[Tuple[int, int, int, int, int, int], float] = {}

        for o in eligible:
            p = o.weight / total_w
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
                wc_sat = self.goal.satisfied(w, c)
                for f in range(1, 6):
                    for s in range(1, 6):
                        for ft in ft_range:
                            for st in st_range:
                                # BIS: success requires targets + will/chaos goal
                                sat = 1.0 if (wc_sat and ft == 1 and st == 1) else 0.0
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
                                    val = 0.0
                                    for dest_key, p in tc[(w, c, f, s, ft, st)].items():
                                        val += p * dp[(*dest_key, tl - 1)]
                                    dp[(w, c, f, s, ft, st, tl)] = val

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(self, state: GemState, turns_left: int) -> float:
        if self.bis_only:
            ft = 1 if state.first_effect in self._target_effects else 0
            st = 1 if state.second_effect in self._target_effects else 0
            return self._dp.get(
                (state.will, state.chaos, state.first, state.second,
                 ft, st, turns_left), 0.0)
        return self._dp.get(
            (state.will, state.chaos, state.first, state.second, turns_left), 0.0)

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
                                  turns_left_after: int) -> float:
        """Average goal probability across the 4 offers (uniform 25% pick)."""
        if not offers:
            return 0.0
        total = 0.0
        for o in offers:
            nw = min(5, max(1, state.will + o.delta)) if o.kind == "will" else state.will
            nc = min(5, max(1, state.chaos + o.delta)) if o.kind == "chaos" else state.chaos
            nf = min(5, max(1, state.first + o.delta)) if o.kind == "first" else state.first
            ns = min(5, max(1, state.second + o.delta)) if o.kind == "second" else state.second

            if self.bis_only and o.key in ("change_first_effect", "change_second_effect"):
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
