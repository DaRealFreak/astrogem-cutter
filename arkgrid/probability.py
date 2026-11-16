from __future__ import annotations

import math
from typing import FrozenSet, List, Optional, Dict, Tuple

from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, GEM_TYPES, SUPPORT_COEFF, SUPPORT_EFFECTS, fusion_avg_coeff
from arkgrid.models import Option, LastTurnGoal, GemState
from arkgrid.pool import OptionPool

# Exact hand statistics per weight class, keyed by the sorted eligible weights
# (a few hundred distinct multisets exist across all states):
#   (class index by weight, applied prob per class, pair-inclusion matrix).
_HAND_STATS: Dict[Tuple[float, ...],
                  Tuple[Dict[float, int], List[float], List[List[float]]]] = {}


def _hand_stats(key: Tuple[float, ...]):
    """Exact statistics of the 4-offer hand for one eligible-weight multiset.

    The game draws 4 distinct offers by successive weighted sampling without
    replacement. Options sharing a weight are exchangeable, so the enumeration
    runs over ordered draws of weight *classes* (<= 8 classes, <= 8**4 paths).
    Returns, per class: the probability one of its options is the APPLIED one
    (hand-inclusion probability / 4), and `pair[a][b]`, the probability that
    two given distinct options of classes a and b are in the hand together.
    """
    stats = _HAND_STATS.get(key)
    if stats is None:
        classes = sorted(set(key))
        counts = [key.count(c) for c in classes]
        n = len(classes)
        # expected[i] = E[number of class-i options in the hand]
        expected = [0.0] * n
        # joint[a][b] = E[number of slot pairs (earlier, later) holding
        # classes (a, b)]
        joint = [[0.0] * n for _ in range(n)]
        used = [0] * n
        path: List[int] = []

        def draw(depth: int, p: float, remaining: float) -> None:
            for i, c in enumerate(classes):
                k = counts[i] - used[i]
                if k <= 0:
                    continue
                q = p * k * c / remaining
                expected[i] += q
                for j in path:
                    joint[j][i] += q
                if depth < 3:
                    used[i] += 1
                    path.append(i)
                    draw(depth + 1, q, remaining - c)
                    path.pop()
                    used[i] -= 1

        draw(0, 1.0, sum(key))
        applied = [expected[i] / counts[i] / 4.0 for i in range(n)]
        pair = [[0.0] * n for _ in range(n)]
        for a in range(n):
            for b in range(n):
                if a != b:
                    pair[a][b] = ((joint[a][b] + joint[b][a])
                                  / (counts[a] * counts[b]))
                elif counts[a] >= 2:
                    pair[a][a] = (2.0 * joint[a][a]
                                  / (counts[a] * (counts[a] - 1)))
        stats = ({c: i for i, c in enumerate(classes)}, applied, pair)
        _HAND_STATS[key] = stats
    return stats


def applied_probs(weights: List[float]) -> List[float]:
    """Exact probability that each option is the one APPLIED by a click.

    The game draws 4 distinct offers by successive weighted sampling without
    replacement and applies one of them uniformly, so an option's applied
    probability is its hand-inclusion probability / 4 — not `weight / total`.
    A heavy option can only fill one of the four slots: the +1 options are
    applied ~10% less often than their weight share and the rare ones
    10-20% more, which a single-draw model turns into a 3-13% underestimate
    of P(goal) (30% for relic with 5 turns left).

    With <= 4 eligible options every one is offered and the pick is uniform.
    """
    n = len(weights)
    if n <= 4:
        return [1.0 / n] * n if n else []
    index, applied, _pair = _hand_stats(tuple(sorted(weights)))
    return [applied[index[w]] for w in weights]


# hand_context() results, keyed by the (ordered) eligible weights.
_HAND_CONTEXTS: Dict[Tuple[float, ...], tuple] = {}


def hand_context(weights: List[float]) -> tuple:
    """Everything `_hand_turn_value` needs to know about a state's eligible
    options (in pool order): `(probs, cls, diag, off, n_classes)`.

    `probs` are the applied probabilities, `cls` each option's weight-class
    index, and `diag` / `off` the pair-inclusion coefficients that turn
    per-class sums into the exact variance of the hand mean. `cls` is None
    when <= 4 options are eligible (the hand is then the whole set).
    """
    key = tuple(weights)
    ctx = _HAND_CONTEXTS.get(key)
    if ctx is None:
        n = len(weights)
        if n <= 4:
            ctx = ([1.0 / n] * n if n else [], None, (), (), 0)
        else:
            index, applied, pair = _hand_stats(tuple(sorted(weights)))
            cls = [index[w] for w in weights]
            nc = len(applied)
            diag = tuple((a, pair[a][a]) for a in range(nc)
                         if pair[a][a] != 0.0)
            off = tuple((a, b, 2.0 * pair[a][b])
                        for a in range(nc) for b in range(a + 1, nc))
            ctx = ([applied[a] for a in cls], cls, diag, off, nc)
        _HAND_CONTEXTS[key] = ctx
    return ctx


# Multinomial(4; 3 atoms): (n1, n2, n3, coefficient).
_HAND_TRINOM = tuple(
    (n1, n2, 4 - n1 - n2,
     24.0 / (math.factorial(n1) * math.factorial(n2)
             * math.factorial(4 - n1 - n2)))
    for n1 in range(5) for n2 in range(5 - n1))
_TWO_THIRDS_PI = 2.0 * math.pi / 3.0


def _hand_e_max2(mu: float, m2: float, m3: float, rho: float,
                 t: float) -> float:
    """`hand_e_max` when the offers take only two distinct values (hit or
    miss — the last turn of a goal table).

    The hand mean is then `lo + (hi - lo) * K / 4`, K = number of "hit"
    offers in the hand, so only K's distribution is needed. Its mean (4q)
    and variance (`4 q (1-q) rho`, exact) are matched by Binomial(n, 4q/n):
    n = 4 is four independent draws, n = 1 a single hit option that is
    either in the hand or not (exact). A fractional n mixes the two
    neighbouring integers.
    """
    sd = math.sqrt(m2)
    g = m3 / (m2 * sd)                     # skewness
    r = math.sqrt(4.0 + g * g)
    # P(hit) = (1 - g/r) / 2, written to avoid cancellation.
    q = 2.0 / (r * (r + g)) if g >= 0.0 else 1.0 - 2.0 / (r * (r - g))
    lo = mu - sd * math.sqrt(q / (1.0 - q))
    step = (mu + sd * math.sqrt((1.0 - q) / q) - lo) / 4.0
    mean_k = 4.0 * q
    denom = 1.0 - (1.0 - q) * rho
    n = mean_k / denom if denom > mean_k / 4.0 else 4.0
    floor_n = 1.0 if mean_k < 1.0 else mean_k   # Binomial(n, 4q/n) needs n >= 4q
    if n < floor_n:
        n = floor_n
    n_lo = int(n)
    if n_lo >= 4:
        parts = ((4, 1.0),)
    elif n_lo < mean_k:                     # only the upper neighbour is valid
        parts = ((n_lo + 1, 1.0),)
    else:
        lam = (1.0 / n - 1.0 / (n_lo + 1)) / (1.0 / n_lo - 1.0 / (n_lo + 1))
        parts = ((n_lo, lam), (n_lo + 1, 1.0 - lam))
    total = 0.0
    for n_j, share in parts:
        if share <= 0.0:
            continue
        q_j = mean_k / n_j
        for k in range(n_j + 1):
            h = lo + step * k
            total += (share * math.comb(n_j, k) * q_j ** k
                      * (1.0 - q_j) ** (n_j - k) * (h if h > t else t))
    return total


def hand_e_max(mu: float, m2: float, m3: float, m4: float, m5: float,
               rho: float, t: float) -> float:
    """E[max(H, t)], where H is the mean value of a 4-offer hand.

    A reroll rejects the whole hand, never a single offer, so the value of
    holding a reroll is `E[max(hand mean, reroll value)]`. Inputs are the
    single-offer value distribution's mean and central moments `m2..m5`, and
    `rho` = (exact variance of the hand mean) / (m2 / 4).

    Two things have to be right, and each alone is off by 15-25% of the
    reroll's value in one regime:

    * **Lumpy values.** The offers are a bulk of similar values plus a few
      rare big ones. The distribution is replaced by its 3-node Gauss
      quadrature (the 3-point distribution matching `mu, m2..m5`) and the
      hand is 4 draws from it (15 values, multinomial weights). A 2-point fit
      loses the bulk's own spread — it read low on hard goals, where the
      rare offers carry the value.
    * **Distinct offers.** The hand holds 4 DIFFERENT options, so its mean
      varies less than 4 independent draws would — much less when the spread
      comes from the common +1 offers (easy goals, grade chase), barely when
      it comes from rare ones. Every deviation is scaled by `sqrt(rho)` so
      the hand variance is exact; without it easy goals read 15-25% high.

    Against exact enumeration of all C(n, 4) hands at visited states the
    error is within ~2% of the reroll's value in both regimes, and tables
    built with it predict what their own policy achieves within ~2%
    (measurement noise) for hard and easy goals alike. Offers that take
    only two distinct values (hit or miss: the last turn of a goal table)
    are handled by `_hand_e_max2`.
    """
    scale = mu * mu if mu * mu > t * t else t * t
    if m2 <= 1e-12 * (scale if scale > 1.0 else 1.0):
        return mu if mu > t else t
    sd = math.sqrt(m2)
    g = m3 / (m2 * sd)                     # skewness
    k = m4 / (m2 * m2)                     # kurtosis
    h5 = m5 / (m2 * m2 * sd)
    det = k - g * g - 1.0                  # 0 for a two-valued distribution
    if det <= 1e-9 * (k if k > 1.0 else 1.0):
        return _hand_e_max2(mu, m2, m3, rho, t)
    # Monic degree-3 orthogonal polynomial z^3 + c2 z^2 + c1 z + c0 of the
    # standardized distribution; its roots are the quadrature nodes.
    c2 = (g + g * k - h5) / det
    c1 = -k - g * c2
    c0 = -g - c2
    p = c1 - c2 * c2 / 3.0
    if p >= 0.0:
        return _hand_e_max2(mu, m2, m3, rho, t)
    q = 2.0 * c2 * c2 * c2 / 27.0 - c2 * c1 / 3.0 + c0
    amp = 2.0 * math.sqrt(-p / 3.0)
    arg = 3.0 * q / (p * amp)
    arg = 1.0 if arg > 1.0 else (-1.0 if arg < -1.0 else arg)
    phi = math.acos(arg) / 3.0
    shift = c2 / 3.0
    z1 = amp * math.cos(phi) - shift
    z2 = amp * math.cos(phi - _TWO_THIRDS_PI) - shift
    z3 = amp * math.cos(phi - 2.0 * _TWO_THIRDS_PI) - shift
    w1 = (1.0 + z2 * z3) / ((z1 - z2) * (z1 - z3))
    w2 = (1.0 + z1 * z3) / ((z2 - z1) * (z2 - z3))
    w3 = 1.0 - w1 - w2
    if not (w1 > 0.0 and w2 > 0.0 and w3 > 0.0):
        return _hand_e_max2(mu, m2, m3, rho, t)
    s = sd * math.sqrt(rho) * 0.25
    a1 = s * z1
    a2 = s * z2
    a3 = s * z3
    p1 = (1.0, w1, w1 * w1, w1 * w1 * w1, w1 * w1 * w1 * w1)
    p2 = (1.0, w2, w2 * w2, w2 * w2 * w2, w2 * w2 * w2 * w2)
    p3 = (1.0, w3, w3 * w3, w3 * w3 * w3, w3 * w3 * w3 * w3)
    total = 0.0
    for n1, n2, n3, coef in _HAND_TRINOM:
        h = mu + n1 * a1 + n2 * a2 + n3 * a3
        total += coef * p1[n1] * p2[n2] * p3[n3] * (h if h > t else t)
    return total


def _hand_moments(ctx: tuple, posts: List[float]):
    """`(mu, m2, m3, m4, m5, rho)` of a hand over `ctx`'s options with
    post-click values `posts`: the single-offer mean and central moments,
    and `rho`, the exact variance of the 4-distinct-offer hand mean relative
    to 4 independent draws (`m2 / 4`)."""
    probs, cls, diag, off, nc = ctx
    mu = 0.0
    for p, x in zip(probs, posts):
        mu += p * x
    if cls is None:
        return mu, 0.0, 0.0, 0.0, 0.0, 0.0
    m2 = m3 = m4 = m5 = 0.0
    sums = [0.0] * nc           # per class: sum of deviations
    squares = [0.0] * nc        # per class: sum of squared deviations
    for p, x, a in zip(probs, posts, cls):
        d = x - mu
        d2 = d * d
        sums[a] += d
        squares[a] += d2
        pd = p * d2
        m2 += pd
        m3 += pd * d
        m4 += pd * d2
        m5 += pd * d2 * d
    if m2 <= 0.0:
        return mu, 0.0, 0.0, 0.0, 0.0, 0.0
    # 16 Var(hand mean) = sum_i pi_i d_i^2 + sum_{i != j} pi_ij d_i d_j,
    # with pi_i = 4 p_i; the cross term by class sums.
    cross = 0.0
    for a, coef in diag:
        cross += coef * (sums[a] * sums[a] - squares[a])
    for a, b, coef in off:
        cross += coef * sums[a] * sums[b]
    rho = 1.0 + cross / (4.0 * m2)
    return mu, m2, m3, m4, m5, (rho if rho > 0.0 else 0.0)


def _hand_turn_value(ctx: tuple, posts: List[float], alt: float) -> float:
    """Value of a turn whose 4-offer hand (options described by `ctx`, see
    `hand_context`; post-click values `posts`) is kept when its mean beats
    `alt` — the value of the alternative (redraw, or finishing) — and given
    up for that alternative otherwise."""
    mu, m2, m3, m4, m5, rho = _hand_moments(ctx, posts)
    if m2 <= 0.0:
        # Certain hand: <= 4 eligible options, or all offers worth the same.
        return mu if mu > alt else alt
    return hand_e_max(mu, m2, m3, m4, m5, rho, alt)


def _hand_contexts(pool: OptionPool, max_turns: int) -> dict:
    """`hand_context` per (turn label, cost state) and state625 — the same
    three-turn-type layout as the builds' transition caches."""
    out = {}
    for label, turn, tl in (("first", 1, max_turns),
                            ("last", max_turns, 1),
                            ("middle", 2,
                             max_turns - 1 if max_turns > 2 else 2)):
        for cs in (0, 1):
            ctxs = [None] * 625
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            state = GemState(will=w, chaos=c, first=f,
                                             second=s,
                                             cost_ratio=100 if cs else 0)
                            ctxs[_s625(w, c, f, s)] = hand_context(
                                [o.weight for o in pool.pool
                                 if pool.eligible(o, state, turn, tl)])
            out[(label, cs)] = ctxs
    return out


def _s625(w: int, c: int, f: int, s: int) -> int:
    """Dense 0..624 index over the 4 stat levels (each 1..5).

    The DP lives in flat lists indexed arithmetically — the dense state
    space makes tuple-keyed dicts needlessly slow (tuple hashing used to
    dominate the build time; the flat layout cut builds ~10x).
    """
    return (((w - 1) * 5 + (c - 1)) * 5 + (f - 1)) * 5 + (s - 1)


class GoalProbabilityTable:
    """Precomputed P(reach goal | will, chaos, first, second, turns_left).

    Uses backward induction over the exact per-option applied probabilities
    (`applied_probs`: hand-inclusion probability / 4). Reroll-aware tables
    price a reroll on the whole 4-offer hand (`hand_e_max`).

    Lookup O(1).

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

        # Flat DP storage. Index layout: (state625, cs, ea, r, tl) where
        # ea = fi*4+si (effect-aware), ft*2+st (BIS), or 0 (standard).
        if self.effect_aware:
            self._ea_dim = 16
        elif self.bis_only:
            self._ea_dim = 4
        else:
            self._ea_dim = 1
        reroll_dimensioned = max_rerolls > 0 and (self.effect_aware
                                                  or not self.bis_only)
        self._r_dim = max_rerolls + 1 if reroll_dimensioned else 1
        self._tl_dim = max_turns + 1
        # Unwritten slots stay 0.0, matching the old dict's .get(key, 0.0).
        self._dp: List[float] = [0.0] * (
            625 * 2 * self._ea_dim * self._r_dim * self._tl_dim)
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

    def _idx(self, st: int, cs: int, ea: int, r: int, tl: int) -> int:
        """Flat-list index; see the layout note in __init__."""
        return (((st * 2 + cs) * self._ea_dim + ea)
                * self._r_dim + r) * self._tl_dim + tl

    # ------------------------------------------------------------------
    # Transition helpers (option probability assignment)
    # ------------------------------------------------------------------

    def _option_probs(self, eligible: List[Option]) -> List[float]:
        """Return the exact per-option applied probability (`applied_probs`)."""
        return applied_probs([o.weight for o in eligible])

    # ------------------------------------------------------------------
    # Non-BIS transitions and build
    # ------------------------------------------------------------------

    def _transitions(self, w: int, c: int, f: int, s: int, cs: int,
                     turn: int, turns_left: int) -> List[List[float]]:
        """Return [[prob, nw, nc, nf, ns, ncs], ...] for one turn, with
        duplicate destinations merged in first-occurrence order (same float
        summation order as the old dict aggregation).

        `cs` is the cost-saturation flag (1 when cost_ratio is at ±100).
        The two saturated states are symmetric — each excludes one of the
        two weight-1.75 cost options and a cost pick returns to 0 — so a
        single flag models the cost dimension exactly. A cost pick toggles
        it: 0 -> 1 (ratio moves to ±100), 1 -> 0 (the only eligible cost
        option moves the ratio back to 0).
        """
        state = GemState(will=w, chaos=c, first=f, second=s,
                         cost_ratio=100 if cs else 0)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [[1.0, w, c, f, s, cs]]

        probs = self._option_probs(eligible)
        result: List[List[float]] = []
        seen: Dict[int, int] = {}
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns, ncs = w, c, f, s, cs
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.kind == "cost":
                ncs = 1 - cs
            # view/other/maintain -> no state change
            packed = _s625(nw, nc, nf, ns) * 2 + ncs
            at = seen.get(packed)
            if at is not None:
                result[at][0] += p
            else:
                seen[packed] = len(result)
                result.append([p, nw, nc, nf, ns, ncs])
        return result

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
                        st = _s625(w, c, f, s)
                        for cs in (0, 1):
                            dp[self._idx(st, cs, 0, 0, 0)] = sat

        # Precompute transition tables for three turn types x cost states,
        # indexed by state625.
        trans_cache: Dict[Tuple[str, int], List[List[List[float]]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache: List[List[List[float]]] = [None] * 625  # type: ignore[list-item]
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = self._transitions(
                                    w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            st = _s625(w, c, f, s)
                            if (self.early_finish
                                    and self.goal.satisfied(w, c, f, s)
                                    and self._coeff_satisfied(f, s)):
                                for cs in (0, 1):
                                    dp[self._idx(st, cs, 0, 0, tl)] = 1.0
                                continue
                            for cs in (0, 1):
                                val = 0.0
                                for p, nw, nc, nf, ns, ncs in trans_cache[(label, cs)][st]:
                                    val += p * dp[self._idx(
                                        _s625(nw, nc, nf, ns), ncs, 0, 0, tl - 1)]
                                dp[self._idx(st, cs, 0, 0, tl)] = val

    # ------------------------------------------------------------------
    # Reroll-aware transitions and build
    # ------------------------------------------------------------------

    def _transitions_reroll(
        self, w: int, c: int, f: int, s: int, cs: int,
        turn: int, turns_left: int,
    ) -> List[Tuple[float, int, int, int, int, int, int]]:
        """Return [(prob, nw, nc, nf, ns, ncs, view_delta)] per eligible option.

        Like _transitions() but preserves per-option view deltas so the
        reroll DP can track reroll count changes from view+N options.
        """
        state = GemState(will=w, chaos=c, first=f, second=s,
                         cost_ratio=100 if cs else 0)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, w, c, f, s, cs, 0)]

        probs = self._option_probs(eligible)
        result: List[Tuple[float, int, int, int, int, int, int]] = []
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns, ncs = w, c, f, s, cs
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
            elif o.kind == "cost":
                ncs = 1 - cs
            # other/maintain -> no state change, no view delta
            result.append((p, nw, nc, nf, ns, ncs, vd))
        return result

    def _build_with_rerolls(self) -> None:
        """Build DP table with reroll count as extra state dimension.

        State key: (w, c, f, s, r, turns_left) where r = rerolls available.

        Transition: on turns > 1, with r > 0 rerolls available, the player
        sees the 4-offer hand and either keeps it (a uniformly random offer
        is applied) or rerolls the whole hand:

            V(s, r, tl) = E_hand[ max(
                mean_{i in hand} V(apply_i(s), r + vd_i, tl-1),   # keep
                V(s, r-1, tl)                                       # reroll
            ) ]

        evaluated with the hand model (`hand_e_max`). A per-option
        max (accept/reject each offer on its own) would overstate the value
        of a reroll by 30-60% on epic gems.

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
                        st = _s625(w, c, f, s)
                        for cs in (0, 1):
                            for r in range(0, max_r + 1):
                                dp[self._idx(st, cs, 0, r, 0)] = sat

        # Precompute transition tables (with view deltas) per cost state,
        # indexed by state625.
        TransEntry = List[Tuple[float, int, int, int, int, int, int]]
        trans_cache: Dict[Tuple[str, int], List[TransEntry]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache: List[TransEntry] = [None] * 625  # type: ignore[list-item]
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = self._transitions_reroll(
                                    w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        hand_cache = _hand_contexts(self.pool, mt)

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            st = _s625(w, c, f, s)
                            for cs in (0, 1):
                                trans = trans_cache[(label, cs)][st]
                                hand = hand_cache[(label, cs)][st]
                                for r in range(0, max_r + 1):
                                    if (self.early_finish
                                            and self.goal.satisfied(w, c, f, s)
                                            and self._coeff_satisfied(f, s)):
                                        dp[self._idx(st, cs, 0, r, tl)] = 1.0
                                        continue

                                    # Reroll decision is made on the whole
                                    # 4-offer hand: keep it when its mean
                                    # beats a redraw, otherwise reroll.
                                    if r > 0 and turn_number != 1:
                                        reroll_val = dp[self._idx(st, cs, 0, r - 1, tl)]
                                        posts = [
                                            dp[self._idx(
                                                _s625(nw, nc, nf, ns), ncs, 0,
                                                min(max_r, r + vd), tl - 1)]
                                            for (_p, nw, nc, nf, ns, ncs, vd) in trans]
                                        dp[self._idx(st, cs, 0, r, tl)] = (
                                            _hand_turn_value(hand, posts, reroll_val))
                                    else:
                                        val = 0.0
                                        for (p, nw, nc, nf, ns, ncs, vd) in trans:
                                            nr = min(max_r, r + vd)
                                            val += p * dp[self._idx(
                                                _s625(nw, nc, nf, ns), ncs, 0, nr, tl - 1)]
                                        dp[self._idx(st, cs, 0, r, tl)] = val

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
        self, w: int, c: int, f: int, s: int, cs: int, ft: int, st: int,
        turn: int, turns_left: int,
    ) -> List[List[float]]:
        """Return [[prob, nw, nc, nf, ns, ncs, nft, nst], ...] with duplicate
        destinations merged in first-occurrence order."""
        state = GemState(will=w, chaos=c, first=f, second=s,
                         cost_ratio=100 if cs else 0)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [[1.0, w, c, f, s, cs, ft, st]]

        probs = self._option_probs(eligible)
        result: List[List[float]] = []
        seen: Dict[int, int] = {}

        def add(p: float, nw: int, nc: int, nf: int, ns: int,
                ncs: int, nft: int, nst: int) -> None:
            packed = ((_s625(nw, nc, nf, ns) * 2 + ncs) * 2 + nft) * 2 + nst
            at = seen.get(packed)
            if at is not None:
                result[at][0] += p
            else:
                seen[packed] = len(result)
                result.append([p, nw, nc, nf, ns, ncs, nft, nst])

        for p, o in zip(probs, eligible):
            nw, nc, nf, ns, ncs = w, c, f, s, cs
            nft, nst = ft, st

            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.kind == "cost":
                ncs = 1 - cs
            elif o.key == "change_first_effect":
                # Probabilistic transition for ft
                p_target = (2 - ft - st) / 2.0
                if p_target > 0:
                    add(p * p_target, nw, nc, nf, ns, ncs, 1, nst)
                if p_target < 1:
                    add(p * (1 - p_target), nw, nc, nf, ns, ncs, 0, nst)
                continue  # already added
            elif o.key == "change_second_effect":
                p_target = (2 - ft - st) / 2.0
                if p_target > 0:
                    add(p * p_target, nw, nc, nf, ns, ncs, nft, 1)
                if p_target < 1:
                    add(p * (1 - p_target), nw, nc, nf, ns, ncs, nft, 0)
                continue

            add(p, nw, nc, nf, ns, ncs, nft, nst)

        return result

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
                        stx = _s625(w, c, f, s)
                        for ft in ft_range:
                            for st in st_range:
                                # BIS: success requires targets + goal + coefficient
                                goal_sat = self.goal.satisfied(w, c, f, s)
                                sat = 1.0 if (goal_sat and ft == 1 and st == 1
                                              and self._coeff_satisfied(f, s, ft, st)) else 0.0
                                for cs in (0, 1):
                                    dp[self._idx(stx, cs, ft * 2 + st, 0, 0)] = sat

        # Precompute transition tables per cost state, indexed by
        # state625 * 4 + ft*2+st.
        trans_cache: Dict[Tuple[str, int], List[List[List[float]]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache: List[List[List[float]]] = [None] * (625 * 4)  # type: ignore[list-item]
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                for ft in ft_range:
                                    for st in st_range:
                                        cache[_s625(w, c, f, s) * 4 + ft * 2 + st] = \
                                            self._transitions_bis(
                                                w, c, f, s, cs, ft, st, turn, tl)
                trans_cache[(label, cs)] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            stx = _s625(w, c, f, s)
                            for cs in (0, 1):
                                tc = trans_cache[(label, cs)]
                                for ft in ft_range:
                                    for st in st_range:
                                        if (self.early_finish
                                                and self.goal.satisfied(w, c, f, s)
                                                and ft == 1 and st == 1
                                                and self._coeff_satisfied(f, s, ft, st)):
                                            dp[self._idx(stx, cs, ft * 2 + st, 0, tl)] = 1.0
                                            continue
                                        val = 0.0
                                        for (p, nw, nc, nf, ns,
                                             ncs, nft, nst) in tc[stx * 4 + ft * 2 + st]:
                                            val += p * dp[self._idx(
                                                _s625(nw, nc, nf, ns), ncs,
                                                nft * 2 + nst, 0, tl - 1)]
                                        dp[self._idx(stx, cs, ft * 2 + st, 0, tl)] = val

    # ------------------------------------------------------------------
    # Effect-aware transitions and build
    # ------------------------------------------------------------------
    # State key: (w, c, f, s, fi, si, tl[, r])
    # fi/si are indices into GEM_TYPES[gem_type], always fi != si.
    # Change_first/second_effect transitions route probabilistically
    # across the 2 effects not currently equipped (self._change_dests).
    # ------------------------------------------------------------------

    def _effect_aware_transitions(
        self, w: int, c: int, f: int, s: int, cs: int,
        turn: int, turns_left: int,
    ) -> List[Tuple[float, str, str, int, int, int, int, int, int]]:
        """Return [(prob, option_key, option_kind, nw, nc, nf, ns, ncs, view_delta)].

        Same eligibility logic as _transitions() but preserves option key
        (for change_effect detection) and view delta (for reroll-aware DP).
        Does not apply fi/si updates — those are handled at build time
        using self._change_dests.
        """
        state = GemState(will=w, chaos=c, first=f, second=s,
                         cost_ratio=100 if cs else 0)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, "", "", w, c, f, s, cs, 0)]

        probs = self._option_probs(eligible)
        result: List[Tuple[float, str, str, int, int, int, int, int, int]] = []
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns, ncs = w, c, f, s, cs
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
            elif o.kind == "cost":
                ncs = 1 - cs
            result.append((p, o.key, o.kind, nw, nc, nf, ns, ncs, vd))
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
                        st = _s625(w, c, f, s)
                        for fi, si in valid_pairs:
                            sat = 1.0 if (goal_sat
                                          and self._coeff_satisfied_idx(
                                              f, s, fi, si)) else 0.0
                            for cs in (0, 1):
                                dp[self._idx(st, cs, fi * 4 + si, 0, 0)] = sat

        # Precompute option-level transition tables (independent of fi/si),
        # indexed by state625.
        trans_cache: Dict[Tuple[str, int],
                          List[List[Tuple[float, str, str,
                                          int, int, int, int, int, int]]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache: List[List[Tuple[float, str, str,
                                       int, int, int, int, int, int]]] = \
                    [None] * 625  # type: ignore[list-item]
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = \
                                    self._effect_aware_transitions(
                                        w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            goal_sat = self.goal.satisfied(w, c, f, s)
                            st = _s625(w, c, f, s)
                            for cs in (0, 1):
                                trans = trans_cache[(label, cs)][st]
                                for fi, si in valid_pairs:
                                    if (self.early_finish and goal_sat
                                            and self._coeff_satisfied_idx(
                                                f, s, fi, si)):
                                        dp[self._idx(st, cs, fi * 4 + si, 0, tl)] = 1.0
                                        continue
                                    dests = self._change_dests[(fi, si)]
                                    n_dests = len(dests)  # always 2
                                    val = 0.0
                                    for (p, key, _kind,
                                         nw, nc, nf, ns, ncs, _vd) in trans:
                                        nst = _s625(nw, nc, nf, ns)
                                        if key == "change_first_effect":
                                            for new_fi in dests:
                                                val += (p / n_dests) * dp[self._idx(
                                                    nst, ncs, new_fi * 4 + si,
                                                    0, tl - 1)]
                                        elif key == "change_second_effect":
                                            for new_si in dests:
                                                val += (p / n_dests) * dp[self._idx(
                                                    nst, ncs, fi * 4 + new_si,
                                                    0, tl - 1)]
                                        else:
                                            val += p * dp[self._idx(
                                                nst, ncs, fi * 4 + si, 0, tl - 1)]
                                    dp[self._idx(st, cs, fi * 4 + si, 0, tl)] = val

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
                        st = _s625(w, c, f, s)
                        for fi, si in valid_pairs:
                            sat = 1.0 if (goal_sat
                                          and self._coeff_satisfied_idx(
                                              f, s, fi, si)) else 0.0
                            for cs in (0, 1):
                                for r in range(0, max_r + 1):
                                    dp[self._idx(st, cs, fi * 4 + si, r, 0)] = sat

        trans_cache: Dict[Tuple[str, int],
                          List[List[Tuple[float, str, str,
                                          int, int, int, int, int, int]]]] = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache: List[List[Tuple[float, str, str,
                                       int, int, int, int, int, int]]] = \
                    [None] * 625  # type: ignore[list-item]
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = \
                                    self._effect_aware_transitions(
                                        w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        hand_cache = _hand_contexts(self.pool, mt)

        # Backward induction
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            goal_sat = self.goal.satisfied(w, c, f, s)
                            st = _s625(w, c, f, s)
                            for cs in (0, 1):
                                trans = trans_cache[(label, cs)][st]
                                hand = hand_cache[(label, cs)][st]
                                for fi, si in valid_pairs:
                                    dests = self._change_dests[(fi, si)]
                                    n_dests = len(dests)
                                    ea = fi * 4 + si

                                    # Keep-value: expected value of the
                                    # 4-draw-pick-1 outcome
                                    def post_val(key, nst, ncs, nr):
                                        if key == "change_first_effect":
                                            v = 0.0
                                            for new_fi in dests:
                                                v += dp[self._idx(
                                                    nst, ncs, new_fi * 4 + si,
                                                    nr, tl - 1)] / n_dests
                                            return v
                                        if key == "change_second_effect":
                                            v = 0.0
                                            for new_si in dests:
                                                v += dp[self._idx(
                                                    nst, ncs, fi * 4 + new_si,
                                                    nr, tl - 1)] / n_dests
                                            return v
                                        return dp[self._idx(
                                            nst, ncs, ea, nr, tl - 1)]

                                    for r in range(0, max_r + 1):
                                        if (self.early_finish and goal_sat
                                                and self._coeff_satisfied_idx(
                                                    f, s, fi, si)):
                                            dp[self._idx(st, cs, ea, r, tl)] = 1.0
                                            continue

                                        if r > 0 and turn_number != 1:
                                            reroll_val = dp[self._idx(
                                                st, cs, ea, r - 1, tl)]
                                            posts = [
                                                post_val(
                                                    key, _s625(nw, nc, nf, ns),
                                                    ncs, min(max_r, r + vd))
                                                for (_p, key, _kind, nw, nc,
                                                     nf, ns, ncs, vd) in trans]
                                            dp[self._idx(st, cs, ea, r, tl)] = (
                                                _hand_turn_value(
                                                    hand, posts, reroll_val))
                                        else:
                                            val = 0.0
                                            for (p, key, _kind,
                                                 nw, nc, nf, ns, ncs, vd) in trans:
                                                nr = min(max_r, r + vd)
                                                val += p * post_val(
                                                    key, _s625(nw, nc, nf, ns),
                                                    ncs, nr)
                                            dp[self._idx(st, cs, ea, r, tl)] = val

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
        if turns_left < 0 or turns_left >= self._tl_dim:
            return 0.0
        cs = 1 if state.cost_ratio != 0 else 0
        stx = _s625(state.will, state.chaos, state.first, state.second)
        if self.effect_aware:
            idx = self._effect_indices(state)
            if idx is None:
                return 0.0
            fi, si = idx
            r = (min(self._max_rerolls, rerolls if rerolls is not None else 0)
                 if self._max_rerolls > 0 else 0)
            return self._dp[self._idx(stx, cs, fi * 4 + si, r, turns_left)]
        if self._max_rerolls > 0 and not self.bis_only:
            r = min(self._max_rerolls, rerolls if rerolls is not None else 0)
            return self._dp[self._idx(stx, cs, 0, r, turns_left)]
        if self.bis_only:
            ft = 1 if state.first_effect in self._target_effects else 0
            st = 1 if state.second_effect in self._target_effects else 0
            return self._dp[self._idx(stx, cs, ft * 2 + st, 0, turns_left)]
        return self._dp[self._idx(stx, cs, 0, 0, turns_left)]

    def lookup_bis_averaged(self, turns_left: int,
                            w: int = 1, c: int = 1,
                            f: int = 1, s: int = 1) -> float:
        """Average BIS probability over all starting (ft, st) combinations.

        Weights: P(ft=1,st=1)=1/6, P(ft=1,st=0)=P(ft=0,st=1)=1/3,
        P(ft=0,st=0)=1/6.  Derived from drawing 2 effects without
        replacement from a pool of 2 target + 2 non-target.
        """
        if turns_left < 0 or turns_left >= self._tl_dim:
            return 0.0
        dp = self._dp
        stx = _s625(w, c, f, s)
        return (dp[self._idx(stx, 0, 3, 0, turns_left)] / 6
                + dp[self._idx(stx, 0, 2, 0, turns_left)] / 3
                + dp[self._idx(stx, 0, 1, 0, turns_left)] / 3
                + dp[self._idx(stx, 0, 0, 0, turns_left)] / 6)

    def lookup_after_effect_change(
        self, state: GemState, slot: str, turns_left: int,
    ) -> float:
        """Expected P(goal) after an effect-change option on *slot* ('first' or 'second').

        Averages over the probabilistic outcome of the new effect.
        Only meaningful when bis_only=True; otherwise identical to a no-op lookup.
        """
        if not self.bis_only:
            return self.lookup(state, turns_left)

        if turns_left < 0 or turns_left >= self._tl_dim:
            return 0.0
        ft = 1 if state.first_effect in self._target_effects else 0
        st = 1 if state.second_effect in self._target_effects else 0
        p_target = (2 - ft - st) / 2.0
        stx = _s625(state.will, state.chaos, state.first, state.second)
        cs = 1 if state.cost_ratio != 0 else 0

        if slot == "first":
            p_good = self._dp[self._idx(stx, cs, 2 + st, 0, turns_left)]
            p_bad = self._dp[self._idx(stx, cs, st, 0, turns_left)]
        else:
            p_good = self._dp[self._idx(stx, cs, ft * 2 + 1, 0, turns_left)]
            p_bad = self._dp[self._idx(stx, cs, ft * 2, 0, turns_left)]

        return p_target * p_good + (1 - p_target) * p_bad

    def prob_after_option(self, state: GemState, o: Option,
                          turns_left_after: int,
                          rerolls: Optional[int] = None) -> float:
        """Post-click P(goal) for a single offer.

        Destination-blind by design: the change-effect card does not reveal
        its destination in-game, so change offers are valued as the average
        over the 2 non-equipped destinations (matching the transition model)
        — `Option.resolved_effect` is never consulted here.
        """
        if turns_left_after < 0 or turns_left_after >= self._tl_dim:
            return 0.0
        nw = min(5, max(1, state.will + o.delta)) if o.kind == "will" else state.will
        nc = min(5, max(1, state.chaos + o.delta)) if o.kind == "chaos" else state.chaos
        nf = min(5, max(1, state.first + o.delta)) if o.kind == "first" else state.first
        ns = min(5, max(1, state.second + o.delta)) if o.kind == "second" else state.second
        cs = 1 if state.cost_ratio != 0 else 0
        ncs = (1 - cs) if o.kind == "cost" else cs
        nst = _s625(nw, nc, nf, ns)

        if self.effect_aware:
            idx = self._effect_indices(state)
            if idx is None:
                return 0.0
            fi, si = idx
            r = rerolls if rerolls is not None else 0
            vd = o.delta if o.kind == "view" else 0
            nr = min(self._max_rerolls, r + vd) if self._max_rerolls > 0 else 0
            dests = self._change_dests[(fi, si)]
            n_dests = len(dests)
            if o.key == "change_first_effect":
                v = 0.0
                for new_fi in dests:
                    v += self._dp[self._idx(nst, ncs, new_fi * 4 + si, nr,
                                            turns_left_after)] / n_dests
                return v
            if o.key == "change_second_effect":
                v = 0.0
                for new_si in dests:
                    v += self._dp[self._idx(nst, ncs, fi * 4 + new_si, nr,
                                            turns_left_after)] / n_dests
                return v
            return self._dp[self._idx(nst, ncs, fi * 4 + si, nr,
                                      turns_left_after)]
        if self._max_rerolls > 0 and not self.bis_only:
            r = rerolls if rerolls is not None else 0
            vd = o.delta if o.kind == "view" else 0
            nr = min(self._max_rerolls, r + vd)
            return self._dp[self._idx(nst, ncs, 0, nr, turns_left_after)]
        if self.bis_only and o.key in ("change_first_effect", "change_second_effect"):
            next_state = GemState(will=nw, chaos=nc, first=nf, second=ns,
                                  cost_ratio=state.cost_ratio,
                                  first_effect=state.first_effect,
                                  second_effect=state.second_effect)
            slot = "first" if o.key == "change_first_effect" else "second"
            return self.lookup_after_effect_change(next_state, slot, turns_left_after)
        if self.bis_only:
            ft = 1 if state.first_effect in self._target_effects else 0
            st = 1 if state.second_effect in self._target_effects else 0
            return self._dp[self._idx(nst, ncs, ft * 2 + st, 0, turns_left_after)]
        return self._dp[self._idx(nst, ncs, 0, 0, turns_left_after)]

    def expected_prob_after_click(self, state: GemState,
                                  offers: List[Option],
                                  turns_left_after: int,
                                  rerolls: Optional[int] = None) -> float:
        """Average goal probability across the 4 offers (uniform 25% pick)."""
        if not offers:
            return 0.0
        return sum(self.prob_after_option(state, o, turns_left_after,
                                          rerolls=rerolls)
                   for o in offers) / len(offers)

    def _dp_lookup_ea(self, w: int, c: int, f: int, s: int, cs: int,
                      fi: int, si: int, r: int, tl: int) -> float:
        """Internal effect-aware DP lookup by indices (`r` ignored when the
        table is flat)."""
        if tl < 0 or tl >= self._tl_dim:
            return 0.0
        nr = r if self._max_rerolls > 0 else 0
        return self._dp[self._idx(_s625(w, c, f, s), cs, fi * 4 + si, nr, tl)]

    def should_reroll_dp(self, state: GemState, offers: List[Option],
                         turns_left: int, rerolls: int) -> bool:
        """DP-optimal reroll decision for reroll-aware table.

        Rerolls when the average post-click value of the 4 actual offers
        (uniform 25% pick — the player can't select individual offers) is
        below the value of redrawing with one fewer reroll. This is the same
        hand-level rule the table's backward induction prices.
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
    `(w, c, f, s, fi, si, tl)`, or `(w, c, f, s, fi, si, r, tl)` when
    reroll-aware. The stored value is a *coefficient*, not a probability:

        gem_value(state) = side_coeff(state) + tier_bonus(total_points)

    with goal-broken states valued 0. Backward induction takes a max over
    finish-now vs process, so V always floors at `gem_value` — the table is
    the destination-value oracle for `_side_value_finish_decision`, not a
    value compared directly.

    Reroll dimension (`max_rerolls > 0`, Phase A/B): the state carries the
    reroll count and `_build_reroll` prices a per-turn keep-vs-reroll choice.
    A naive *pool-average* reroll DP would be a no-op — a reroll redraws from
    the same pool, so its mean equals the process arm. The fix models the
    *spread* of the 4-offer hand: the value of a turn is
    `E[max(hand mean, keep_or_finish_threshold)]`, evaluated with the same
    hand model as the goal table (`hand_e_max`). Because a redraw
    is a fresh sample, the chance to draw above the mean has real value, so V
    *does* rise with the reroll count. (A Gaussian hand model was used here
    first; it read up to 13% high on hard goals, where the gem's value hinges
    on a few rare offers.) `max_rerolls == 0` builds the flat
    table (byte-identical to the pre-Phase-A table). The decision layer
    threads the live reroll budget into every lookup / `expected_value_after_click`.

    Policy-evaluation mode (`policy_value_mode="will_chaos"`): instead of
    value-iteration (which reports the *best achievable* side value if you
    chased it), the table reports the side value *expected under the will+chaos
    decision policy*. A coupled flat DP tracks the will_chaos policy value
    alongside the side accumulator and, at each state, follows the policy's
    finish-vs-continue choice — so under `--ignore-side-node-values`, where the
    bot optimizes will+chaos and the side node only rides along, the reported
    coefficient is realistically lower than the value-iteration upper bound.
    The web advisor uses this for its displayed eValue under that flag.

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
        policy_value_mode: Optional[str] = None,
    ) -> None:
        self.goal = goal
        self.max_turns = max_turns
        self.pool = pool
        self._gem_type = gem_type
        self._optimize = optimize
        self._min_side_coeff = min_side_coeff
        self.value_mode = value_mode
        self._policy_value_mode = policy_value_mode
        # Policy-evaluation tables are flat: the will_chaos policy they follow
        # has a discrete per-state finish-vs-continue choice, which the
        # variance-aware reroll model (a continuous E[max]) does not expose.
        self._max_rerolls = 0 if policy_value_mode is not None else max_rerolls
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
        # Flat DP storage, index layout (state625, cs, fi*4+si, r, tl) —
        # see GoalProbabilityTable._idx. Unwritten slots stay 0.0.
        self._r_dim = self._max_rerolls + 1 if self._max_rerolls > 0 else 1
        self._tl_dim = max_turns + 1
        self._dp: List[float] = (
            [0.0] * (625 * 2 * 16 * self._r_dim * self._tl_dim)
            if self.enabled else [])

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
        if policy_value_mode is not None:
            self._build_policy_eval()
        elif max_rerolls > 0:
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

    def _transitions(self, w: int, c: int, f: int, s: int, cs: int,
                     turn: int, turns_left: int):
        """Return [(prob, option_key, option_kind, nw, nc, nf, ns, ncs)].

        fi/si updates are applied at build time via self._change_dests.
        `cs`/`ncs` is the cost-saturation flag (see
        GoalProbabilityTable._transitions).
        """
        state = GemState(will=w, chaos=c, first=f, second=s,
                         cost_ratio=100 if cs else 0)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, "", "", w, c, f, s, cs)]
        probs = applied_probs([o.weight for o in eligible])
        result = []
        for p, o in zip(probs, eligible):
            nw, nc, nf, ns, ncs = w, c, f, s, cs
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.kind == "cost":
                ncs = 1 - cs
            # view / other / maintain -> no state change
            result.append((p, o.key, o.kind, nw, nc, nf, ns, ncs))
        return result

    def _idx(self, st: int, cs: int, ea: int, r: int, tl: int) -> int:
        """Flat-list index (state625, cs, fi*4+si, r, tl)."""
        return (((st * 2 + cs) * 16 + ea) * self._r_dim + r) * self._tl_dim + tl

    def _post_val_in(self, dpd: List[float], key: str,
                     nst: int, ncs: int,
                     fi: int, si: int,
                     dests: Tuple[int, ...], nd: int, tl: int) -> float:
        """V at a transition destination *in list `dpd`*, routing
        change_effect uniformly across the two non-equipped pool members.
        Parameterizing the list lets the policy-evaluation build read its two
        coupled tables (policy value, display value) with the same routing."""
        if key == "change_first_effect":
            return sum(dpd[self._idx(nst, ncs, d * 4 + si, 0, tl)]
                       for d in dests) / nd
        if key == "change_second_effect":
            return sum(dpd[self._idx(nst, ncs, fi * 4 + d, 0, tl)]
                       for d in dests) / nd
        return dpd[self._idx(nst, ncs, fi * 4 + si, 0, tl)]

    def _post_val(self, key: str, nst: int, ncs: int,
                  fi: int, si: int, dests: Tuple[int, ...], nd: int,
                  tl: int) -> float:
        """V at a transition destination, routing change_effect uniformly
        across the two non-equipped pool members."""
        return self._post_val_in(self._dp, key, nst, ncs,
                                 fi, si, dests, nd, tl)

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
                        st = _s625(w, c, f, s)
                        for fi, si in valid_pairs:
                            v = self._gem_value_idx(w, c, f, s, fi, si)
                            for cs in (0, 1):
                                dp[self._idx(st, cs, fi * 4 + si, 0, 0)] = v

        # Option-level transition cache (independent of fi/si), indexed by
        # state625.
        trans_cache = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache = [None] * 625
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = self._transitions(
                                    w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        # Backward induction: V = max(finish now, process).
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            st = _s625(w, c, f, s)
                            for cs in (0, 1):
                                trans = trans_cache[(label, cs)][st]
                                for fi, si in valid_pairs:
                                    dests = self._change_dests[(fi, si)]
                                    nd = len(dests)
                                    finish_val = self._gem_value_idx(
                                        w, c, f, s, fi, si)
                                    proc = 0.0
                                    for (p, key, _kind,
                                         nw, nc, nf, ns, ncs) in trans:
                                        proc += p * self._post_val(
                                            key, _s625(nw, nc, nf, ns), ncs,
                                            fi, si, dests, nd, tl - 1)
                                    dp[self._idx(st, cs, fi * 4 + si, 0, tl)] = (
                                        finish_val if finish_val > proc
                                        else proc)

    def _build_policy_eval(self) -> None:
        """Flat coupled DP: side display value under the will+chaos policy.

        Two dicts share the state space and transitions. `dp_w` is the
        will_chaos *policy* value (`w+c` on goal-met states, else 0 — what the
        decision layer maximizes under --ignore-side-node-values). `dp_s`
        (== self._dp, returned by lookups) is the side *display* value, but
        accumulated along whichever finish-vs-continue branch the policy picks,
        not the side-optimal branch. So the policy chases will+chaos and locks
        in when it is satisfied; the side node only rides along — yielding the
        realistic expected coefficient instead of the value-iteration upper
        bound `_build()` produces.

        Process is the pool-average continuation (the policy's reroll arm is
        folded into process; flat, no reroll dimension).
        """
        dp_s = self._dp
        dp_w: List[float] = [0.0] * len(dp_s)
        mt = self.max_turns
        valid_pairs = [(fi, si) for fi in range(4)
                       for si in range(4) if fi != si]

        def wc_finish(w: int, c: int, f: int, s: int) -> float:
            return float(w + c) if self.goal.satisfied(w, c, f, s) else 0.0

        # Terminal: turns_left == 0.
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        fw = wc_finish(w, c, f, s)
                        st = _s625(w, c, f, s)
                        for fi, si in valid_pairs:
                            v = self._gem_value_idx(w, c, f, s, fi, si)
                            for cs in (0, 1):
                                dp_w[self._idx(st, cs, fi * 4 + si, 0, 0)] = fw
                                dp_s[self._idx(st, cs, fi * 4 + si, 0, 0)] = v

        # Option-level transition cache (same three-turn-type strategy as
        # _build), indexed by state625.
        trans_cache = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache = [None] * 625
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = self._transitions(
                                    w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        # Backward induction: follow the will_chaos finish-vs-continue choice.
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                label = "first"
            elif tl == 1:
                label = "last"
            else:
                label = "middle"

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            st = _s625(w, c, f, s)
                            for cs in (0, 1):
                                trans = trans_cache[(label, cs)][st]
                                for fi, si in valid_pairs:
                                    dests = self._change_dests[(fi, si)]
                                    nd = len(dests)
                                    finish_w = wc_finish(w, c, f, s)
                                    finish_s = self._gem_value_idx(
                                        w, c, f, s, fi, si)
                                    proc_w = 0.0
                                    proc_s = 0.0
                                    for (p, key, _kind,
                                         nw, nc, nf, ns, ncs) in trans:
                                        nst = _s625(nw, nc, nf, ns)
                                        proc_w += p * self._post_val_in(
                                            dp_w, key, nst, ncs,
                                            fi, si, dests, nd, tl - 1)
                                        proc_s += p * self._post_val_in(
                                            dp_s, key, nst, ncs,
                                            fi, si, dests, nd, tl - 1)
                                    ea = fi * 4 + si
                                    if finish_w >= proc_w:
                                        dp_w[self._idx(st, cs, ea, 0, tl)] = finish_w
                                        dp_s[self._idx(st, cs, ea, 0, tl)] = finish_s
                                    else:
                                        dp_w[self._idx(st, cs, ea, 0, tl)] = proc_w
                                        dp_s[self._idx(st, cs, ea, 0, tl)] = proc_s

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
                        st = _s625(w, c, f, s)
                        for fi, si in valid_pairs:
                            v = self._gem_value_idx(w, c, f, s, fi, si)
                            for cs in (0, 1):
                                for r in range(maxR + 1):
                                    dp[self._idx(st, cs, fi * 4 + si, r, 0)] = v

        def transitions(w, c, f, s, cs, turn, tl):
            state = GemState(will=w, chaos=c, first=f, second=s,
                             cost_ratio=100 if cs else 0)
            elig = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, tl)]
            if not elig:
                return [(1.0, "", "", w, c, f, s, cs, 0)]
            probs = applied_probs([o.weight for o in elig])
            out = []
            for p, o in zip(probs, elig):
                nw, nc, nf, ns, ncs, vd = w, c, f, s, cs, 0
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
                elif o.kind == "cost":
                    ncs = 1 - cs
                out.append((p, o.key, o.kind, nw, nc, nf, ns, ncs, vd))
            return out

        trans_cache = {}
        for label, turn, tl in [("first", 1, mt), ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            for cs in (0, 1):
                cache = [None] * 625
                for w in range(1, 6):
                    for c in range(1, 6):
                        for f in range(1, 6):
                            for s in range(1, 6):
                                cache[_s625(w, c, f, s)] = transitions(
                                    w, c, f, s, cs, turn, tl)
                trans_cache[(label, cs)] = cache

        hand_cache = _hand_contexts(self.pool, mt)
        cd = self._change_dests

        def post_val(key, nst, ncs, fi, si, nr, tl):
            if key == "change_first_effect":
                d = cd[(fi, si)]
                return sum(dp[self._idx(nst, ncs, di * 4 + si, nr, tl)]
                           for di in d) / len(d)
            if key == "change_second_effect":
                d = cd[(fi, si)]
                return sum(dp[self._idx(nst, ncs, fi * 4 + di, nr, tl)]
                           for di in d) / len(d)
            return dp[self._idx(nst, ncs, fi * 4 + si, nr, tl)]

        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            label = ("first" if turn_number == 1
                     else "last" if tl == 1
                     else "middle")
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            st = _s625(w, c, f, s)
                            for cs in (0, 1):
                                trans = trans_cache[(label, cs)][st]
                                hand = hand_cache[(label, cs)][st]
                                for fi, si in valid_pairs:
                                    finish_val = self._gem_value_idx(w, c, f, s, fi, si)
                                    ea = fi * 4 + si
                                    for r in range(maxR + 1):
                                        posts = [
                                            post_val(
                                                key, _s625(nw, nc, nf, ns), ncs,
                                                fi, si, min(maxR, r + vd), tl - 1)
                                            for (_p, key, _k, nw, nc, nf, ns,
                                                 ncs, vd) in trans]
                                        # The hand is weighed against the best
                                        # alternative: finishing now, or (with
                                        # a reroll in hand) redrawing.
                                        if r > 0 and turn_number != 1:
                                            rc = dp[self._idx(st, cs, ea, r - 1, tl)]
                                            t = finish_val if finish_val > rc else rc
                                        else:
                                            t = finish_val
                                        dp[self._idx(st, cs, ea, r, tl)] = (
                                            _hand_turn_value(hand, posts, t))

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
        if turns_left < 0 or turns_left >= self._tl_dim:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        stx = _s625(state.will, state.chaos, state.first, state.second)
        cs = 1 if state.cost_ratio != 0 else 0
        r = min(self._max_rerolls, rerolls or 0) if self._max_rerolls > 0 else 0
        return self._dp[self._idx(stx, cs, fi * 4 + si, r, turns_left)]

    def expected_value_after_click(self, state: GemState,
                                   offers: List[Option],
                                   turns_left_after: int,
                                   rerolls=None) -> float:
        """Mean V across the 4 *actual* visible offers (uniform 25% pick).

        Mirrors `GoalProbabilityTable.expected_prob_after_click` — the
        process-EV term of the finish decision uses the real offers, not
        the pool-wide expectation the table is built with.
        """
        if not self.enabled or not offers:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        if turns_left_after < 0 or turns_left_after >= self._tl_dim:
            return 0.0
        fi, si = idx
        dests = self._change_dests[(fi, si)]
        nd = len(dests)
        ra = self._max_rerolls > 0
        cs = 1 if state.cost_ratio != 0 else 0
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
            ncs = (1 - cs) if o.kind == "cost" else cs
            nst = _s625(nw, nc, nf, ns)
            if ra:
                vd = o.delta if o.kind == "view" else 0
                nr = min(self._max_rerolls, (rerolls or 0) + vd)
            else:
                nr = 0
            if o.key == "change_first_effect":
                total += sum(self._dp[self._idx(nst, ncs, d * 4 + si, nr,
                                                turns_left_after)]
                             for d in dests) / nd
            elif o.key == "change_second_effect":
                total += sum(self._dp[self._idx(nst, ncs, fi * 4 + d, nr,
                                                turns_left_after)]
                             for d in dests) / nd
            else:
                total += self._dp[self._idx(nst, ncs, fi * 4 + si, nr,
                                            turns_left_after)]
        return total / len(offers)
