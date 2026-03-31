from __future__ import annotations

from typing import List, Optional, Dict, Tuple

from arkgrid.models import Option, LastTurnGoal, GemState
from arkgrid.pool import OptionPool


class GoalProbabilityTable:
    """Precomputed P(reach goal | will, chaos, first, second, turns_left).

    Uses backward induction with a single-draw transition approximation
    (option probability = weight / sum of eligible weights).
    Build cost ~20ms for 6,250 states.  Lookup O(1).
    """

    def __init__(self, goal: LastTurnGoal, max_turns: int, pool: OptionPool) -> None:
        self.goal = goal
        self.max_turns = max_turns
        self.pool = pool
        self._dp: Dict[Tuple[int, int, int, int, int], float] = {}
        self._build()

    # --- transition helpers ---

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

    # --- build ---

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
        # turn=1 -> view excluded;  last turn (turns_left=1) -> view+cost excluded;
        # middle -> everything eligible.
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

    # --- public API ---

    def lookup(self, state: GemState, turns_left: int) -> float:
        return self._dp.get(
            (state.will, state.chaos, state.first, state.second, turns_left), 0.0)

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
            total += self._dp.get((nw, nc, nf, ns, turns_left_after), 0.0)
        return total / len(offers)
