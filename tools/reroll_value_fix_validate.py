"""Validate a variance-aware, reroll-AWARE value DP against Monte Carlo.

Follow-up to tools/reroll_value_experiment.py, which showed the flat
SideValueTable cannot price the extra reroll (eValue identical with/without the
ticket) even though MC proves the ticket is worth ~+200 expected gem value.

This builds a candidate FIX -- a reroll-aware value table -- and checks whether
it is an accurate, fast (O(1) lookup) predictor before anyone wires it into the
Python/web engines.

Model (per turn, hand-aware):
    handEV   = mean of the 4 offers' destination values (process applies a
               uniform-random one of the 4).
    Approx   handEV ~ Normal(mu, var/4 * fpc), where
                 mu  = pool-average single-draw value  (== the flat process arm)
                 var = per-option value variance        (thrown away by the flat
                                                          pool-average)
                 fpc = (N-4)/(N-1) finite-population correction (N eligible opts)
    V(s,tl,r) = E[ max(handEV, T) ],   T = max(finishVal, V(s,tl,r-1) if r>0)
    using the closed form  E[max(N(mu,sd^2), T)] = T + (mu-T)Phi(d) + sd*phi(d),
    d = (mu-T)/sd.

Validation: compare the DP's predicted V(s,tl,r) against an MC that FOLLOWS the
DP's own reroll/finish policy on real 4-offer hands (self-consistency = normal
approximation quality), across several states and reroll budgets.

Run from project root:  python tools/reroll_value_fix_validate.py
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid.models import AstroGem, GemState, LastTurnGoal, Option
from arkgrid.probability import SideValueTable
from arkgrid.simulator import GemSimulator

GEM_TYPE = "order_stability"
OPTIMIZE = "dps"
FIRST_EFFECT = "additional_damage"
SECOND_EFFECT = "attack_power"
RARITY = "epic"
TURNS = 9
GOAL = LastTurnGoal(min_total_will_chaos=8)
MIN_SIDE_COEFF = 2000
MAX_R = 4
N_TRIALS = 100_000

SQRT2 = math.sqrt(2.0)
INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def _Phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def _phi(x: float) -> float:
    return INV_SQRT_2PI * math.exp(-0.5 * x * x)


def _e_max(mu: float, sd: float, T: float) -> float:
    """E[max(X, T)] for X ~ Normal(mu, sd**2)."""
    if sd <= 0.0:
        return mu if mu > T else T
    d = (mu - T) / sd
    return T + (mu - T) * _Phi(d) + sd * _phi(d)


class GaussianRerollValueTable:
    """Variance-aware, reroll-aware value DP. Reuses a flat SideValueTable's
    resolved value model (gem_value, effect indices, change destinations)."""

    def __init__(self, base: SideValueTable, max_rerolls: int) -> None:
        self._b = base
        self.maxR = max_rerolls
        self._dp: Dict[tuple, float] = {}
        self._build()

    # delegate the terminal value model to the flat table
    def gem_value(self, state: GemState) -> float:
        return self._b.gem_value(state)

    def _build(self) -> None:
        b = self._b
        dp = self._dp
        mt = b.max_turns
        maxR = self.maxR
        valid_pairs = [(fi, si) for fi in range(4) for si in range(4) if fi != si]

        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        for fi, si in valid_pairs:
                            v = b._gem_value_idx(w, c, f, s, fi, si)
                            for r in range(maxR + 1):
                                dp[(w, c, f, s, fi, si, r, 0)] = v

        # transitions with view deltas + eligible count
        def transitions(w, c, f, s, turn, tl):
            state = GemState(will=w, chaos=c, first=f, second=s)
            elig = [o for o in b.pool.pool if b.pool.eligible(o, state, turn, tl)]
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

        trans_cache: Dict[str, Dict[tuple, tuple]] = {}
        for label, turn, tl in [("first", 1, mt), ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = transitions(w, c, f, s, turn, tl)
            trans_cache[label] = cache

        change_dests = b._change_dests

        def post_val(key, nw, nc, nf, ns, fi, si, nr, tl):
            if key == "change_first_effect":
                d = change_dests[(fi, si)]
                return sum(dp[(nw, nc, nf, ns, di, si, nr, tl)] for di in d) / len(d)
            if key == "change_second_effect":
                d = change_dests[(fi, si)]
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
                                finish_val = b._gem_value_idx(w, c, f, s, fi, si)
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
                                        T = finish_val if finish_val > rc else rc
                                    else:
                                        T = finish_val
                                    dp[(w, c, f, s, fi, si, r, tl)] = _e_max(mu, sd, T)

    def lookup(self, state: GemState, turns_left: int, rerolls: int) -> float:
        idx = self._b._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        r = min(self.maxR, rerolls)
        return self._dp.get(
            (state.will, state.chaos, state.first, state.second, fi, si, r, turns_left),
            0.0)

    def hand_ev(self, state: GemState, offers: List[Option],
                tl_after: int, rerolls: int) -> float:
        """Mean over the actual offers of the reroll-aware destination value."""
        idx = self._b._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        dests = self._b._change_dests[(fi, si)]
        nd = len(dests)
        dp = self._dp
        total = 0.0
        for o in offers:
            nw = min(5, max(1, state.will + o.delta)) if o.kind == "will" else state.will
            nc = min(5, max(1, state.chaos + o.delta)) if o.kind == "chaos" else state.chaos
            nf = min(5, max(1, state.first + o.delta)) if o.kind == "first" else state.first
            ns = min(5, max(1, state.second + o.delta)) if o.kind == "second" else state.second
            vd = o.delta if o.kind == "view" else 0
            nr = min(self.maxR, rerolls + vd)
            if o.key == "change_first_effect":
                total += sum(dp[(nw, nc, nf, ns, di, si, nr, tl_after)] for di in dests) / nd
            elif o.key == "change_second_effect":
                total += sum(dp[(nw, nc, nf, ns, fi, di, nr, tl_after)] for di in dests) / nd
            else:
                total += dp[(nw, nc, nf, ns, fi, si, nr, tl_after)]
        return total / len(offers)


# --------------------------------------------------------------------------
# Generic MC: play `oracle` policy on real hands, score with true gem_value.
#   oracle.cont(state, tl, r)            -> value of rerolling now (r rerolls)
#   oracle.keep(state, offers, tla, r)   -> value of processing this hand
#   oracle.finish(state)                 -> value of stopping now
# --------------------------------------------------------------------------
def run_mc(oracle, base: SideValueTable, sim: GemSimulator,
           make_state: Callable[[], GemState], start_turn: int,
           n_trials: int, seed_base: int) -> Tuple[float, float]:
    pool = sim.pool
    total = 0.0
    total_sq = 0.0
    for t in range(n_trials):
        rng = random.Random(seed_base * 1_000_003 + t)
        state = make_state()
        for turn in range(start_turn, TURNS + 1):
            turns_left = TURNS - turn + 1
            tla = turns_left - 1
            offers = sim._resolve_effect_offers(
                pool.generate_offers(state, turn, turns_left, rng), state, rng)
            while turn != 1 and state.rerolls > 0:
                keep = oracle.keep(state, offers, tla, state.rerolls)
                cont = oracle.cont(state, turns_left, state.rerolls)
                if cont > keep:
                    state.rerolls -= 1
                    offers = sim._resolve_effect_offers(
                        pool.generate_offers(state, turn, turns_left, rng), state, rng)
                else:
                    break
            fin = oracle.finish(state)
            proc = oracle.keep(state, offers, tla, state.rerolls)
            if fin >= proc:
                break
            sim.apply_option(rng.choice(offers), state, rng)
        v = base.gem_value(state)
        total += v
        total_sq += v * v
    mean = total / n_trials
    var = max(0.0, total_sq / n_trials - mean * mean)
    return mean, math.sqrt(var / n_trials)


class FlatOracle:
    def __init__(self, side: SideValueTable):
        self.s = side

    def cont(self, state, tl, r):
        return self.s.lookup(state, tl)  # reroll-independent

    def keep(self, state, offers, tla, r):
        return self.s.expected_value_after_click(state, offers, tla)

    def finish(self, state):
        return self.s.gem_value(state)


class GaussOracle:
    def __init__(self, g: GaussianRerollValueTable):
        self.g = g

    def cont(self, state, tl, r):
        return self.g.lookup(state, tl, r - 1)

    def keep(self, state, offers, tla, r):
        return self.g.hand_ev(state, offers, tla, r)

    def finish(self, state):
        return self.g.gem_value(state)


def state_factory(will, chaos, first, second, rerolls):
    def make():
        return GemState(will=will, chaos=chaos, first=first, second=second,
                        rerolls=rerolls, first_effect=FIRST_EFFECT,
                        second_effect=SECOND_EFFECT)
    return make


def main() -> None:
    gem = AstroGem(GEM_TYPE, FIRST_EFFECT, SECOND_EFFECT, OPTIMIZE)
    sim = GemSimulator(
        rarity=RARITY, use_extra_ticket=None, use_reset_ticket=False,
        goal=GOAL, astro_gem=gem, optimize=OPTIMIZE,
        min_side_coeff=MIN_SIDE_COEFF, relic_coeff=None, ancient_coeff=None)
    side = sim._get_side_value_table(GEM_TYPE)
    gauss = GaussianRerollValueTable(side, MAX_R)
    flat_oracle = FlatOracle(side)
    gauss_oracle = GaussOracle(gauss)

    # ---- Table 1: scenario start (1,1,1,1) tl=9, budgets 0..4 -------------
    print(f"=== scenario start (1,1,1,1), tl=9  (N={N_TRIALS:,}) ===")
    print(f"{'r':>3} | {'flat_dp':>9} | {'gauss_dp':>9} | "
          f"{'gauss_mc (truth for gauss policy)':>34} | {'flat_mc':>9}")
    print("-" * 86)
    s0 = GemState(will=1, chaos=1, first=1, second=1,
                  first_effect=FIRST_EFFECT, second_effect=SECOND_EFFECT)
    flat_v = side.lookup(s0, 9)
    for r in range(MAX_R + 1):
        mk = state_factory(1, 1, 1, 1, r)
        g_mean, g_sem = run_mc(gauss_oracle, side, sim, mk, 1, N_TRIALS, seed_base=100 + r)
        f_mean, _ = run_mc(flat_oracle, side, sim, mk, 1, N_TRIALS, seed_base=500 + r)
        g_dp = gauss.lookup(s0, 9, r)
        ci = 1.96 * g_sem
        print(f"{r:>3} | {flat_v:>9.2f} | {g_dp:>9.2f} | "
              f"{g_mean:>10.2f}  [{g_mean - ci:>7.2f},{g_mean + ci:>7.2f}] "
              f"err={g_dp - g_mean:>+7.2f} | {f_mean:>9.2f}")

    # ---- Table 2: other states, gauss_dp vs gauss_mc ----------------------
    print()
    print(f"=== gauss_dp vs gauss_mc at other states (N={N_TRIALS:,}) ===")
    print(f"{'state (w,c,f,s) tl, r':>26} | {'gauss_dp':>9} | "
          f"{'gauss_mc':>10} | {'95% CI':>18} | {'err':>8}")
    print("-" * 86)
    cases = [
        (2, 1, 2, 1, 7, 2), (2, 1, 2, 1, 7, 3),
        (3, 2, 2, 2, 5, 2), (3, 2, 2, 2, 5, 3),
        (4, 3, 3, 2, 3, 2), (4, 3, 3, 2, 3, 3),
        (3, 3, 1, 1, 5, 2), (3, 3, 1, 1, 5, 3),
    ]
    for (w, c, f, s, tl, r) in cases:
        turn = TURNS - tl + 1
        st = GemState(will=w, chaos=c, first=f, second=s,
                      first_effect=FIRST_EFFECT, second_effect=SECOND_EFFECT)
        g_dp = gauss.lookup(st, tl, r)
        mk = state_factory(w, c, f, s, r)
        g_mean, g_sem = run_mc(gauss_oracle, side, sim, mk, turn, N_TRIALS,
                               seed_base=900 + w * 100 + c * 10 + r)
        ci = 1.96 * g_sem
        label = f"({w},{c},{f},{s}) tl={tl} r={r}"
        print(f"{label:>26} | {g_dp:>9.2f} | {g_mean:>10.2f} | "
              f"[{g_mean - ci:>7.2f},{g_mean + ci:>7.2f}] | {g_dp - g_mean:>+8.2f}")


if __name__ == "__main__":
    main()
