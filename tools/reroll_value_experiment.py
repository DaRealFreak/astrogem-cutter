"""Does the extra reroll raise the *expected gem value* (eValue)?

Investigation for the web-advisor observation that `withoutTicket.eValue ==
withTicket.eValue`. The displayed eValue comes from `SideValueTable`, which has
NO reroll dimension; the goal/relic/ancient probabilities come from reroll-aware
tables and DO move with the ticket.

This script settles the question empirically for the user's exact scenario:

  order_stability gem, dps, first=additional_damage L1, second=attack_power L1,
  will=1 chaos=1, epic (9 turns), goal = min(will+chaos) >= 8 AND min_side_coeff
  >= 2000, relic/ancient coeff = fusion defaults.

It compares three value estimates as a function of the starting reroll budget r:

  1. flat_dp(r)      -- the current SideValueTable.lookup(); reroll-independent.
  2. peropt_dp(r)    -- a reroll-AWARE value DP built the way GoalProbabilityTable
                        prices rerolls (per-option keep-vs-reroll max). Upper-ish
                        bound: it lets you decline at single-option granularity.
  3. mc(r)           -- Monte Carlo of the REAL scenario: 4-offer hands, process
                        applies a uniform-random one of the 4 (rng.choice), reroll
                        redraws the whole hand. Value-greedy policy driven by the
                        flat SideValueTable (the production value oracle). Ground
                        truth for "what an extra reroll is actually worth."

Run from project root:  python tools/reroll_value_experiment.py
"""
from __future__ import annotations

import math
import os
import random
import sys
from typing import Dict, Tuple

# Run as `python tools/reroll_value_experiment.py`: add the project root to
# sys.path so `arkgrid` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid.models import AstroGem, GemState, LastTurnGoal, Option
from arkgrid.probability import SideValueTable
from arkgrid.simulator import GemSimulator

# --------------------------------------------------------------------------
# Scenario (verbatim from the web-advisor JSON)
# --------------------------------------------------------------------------
GEM_TYPE = "order_stability"
OPTIMIZE = "dps"
FIRST_EFFECT = "additional_damage"
SECOND_EFFECT = "attack_power"
RARITY = "epic"            # 9 turns
TURNS = 9
GOAL = LastTurnGoal(min_total_will_chaos=8)
MIN_SIDE_COEFF = 2000
BUDGETS = [0, 1, 2, 3, 4]
N_TRIALS = 200_000


def fresh_state(rerolls: int = 0) -> GemState:
    return GemState(will=1, chaos=1, first=1, second=1, rerolls=rerolls,
                    first_effect=FIRST_EFFECT, second_effect=SECOND_EFFECT)


# --------------------------------------------------------------------------
# Reroll-AWARE value DP (per-option keep-vs-reroll max, effect-aware).
# Mirrors GoalProbabilityTable._build_effect_aware_with_rerolls, but the stored
# value is gem value (side_coeff + tier_bonus) instead of a probability, and
# finish-now is always an option (max with finish_val).
# --------------------------------------------------------------------------
class RerollAwareSideValueTable:
    def __init__(self, base: SideValueTable, max_rerolls: int) -> None:
        # Reuse the flat table's resolved value model + effect bookkeeping.
        self._b = base
        self._max_rerolls = max_rerolls
        self._dp: Dict[tuple, float] = {}
        self._build()

    def _gem_value_idx(self, w, c, f, s, fi, si) -> float:
        return self._b._gem_value_idx(w, c, f, s, fi, si)

    def _build(self) -> None:
        b = self._b
        dp = self._dp
        mt = b.max_turns
        maxR = self._max_rerolls
        valid_pairs = [(fi, si) for fi in range(4) for si in range(4) if fi != si]

        # Terminal tl == 0: finish value, all reroll counts equal.
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        for fi, si in valid_pairs:
                            v = self._gem_value_idx(w, c, f, s, fi, si)
                            for r in range(maxR + 1):
                                dp[(w, c, f, s, fi, si, r, 0)] = v

        # Option-level transition cache, view-delta aware (reuse pool eligibility).
        # entry: (prob, key, kind, nw, nc, nf, ns, view_delta)
        def transitions(w, c, f, s, turn, tl):
            state = GemState(will=w, chaos=c, first=f, second=s)
            elig = [o for o in b.pool.pool if b.pool.eligible(o, state, turn, tl)]
            if not elig:
                return [(1.0, "", "", w, c, f, s, 0)]
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
            return out

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
                            trans = tc[(w, c, f, s)]
                            for fi, si in valid_pairs:
                                finish_val = self._gem_value_idx(w, c, f, s, fi, si)
                                for r in range(maxR + 1):
                                    # reroll arm (same state/turn, one fewer reroll)
                                    reroll_val = (dp[(w, c, f, s, fi, si, r - 1, tl)]
                                                  if (r > 0 and turn_number != 1)
                                                  else None)
                                    proc = 0.0
                                    for (p, key, _k, nw, nc, nf, ns, vd) in trans:
                                        nr = min(maxR, r + vd)
                                        pv = post_val(key, nw, nc, nf, ns, fi, si, nr, tl - 1)
                                        if reroll_val is not None:
                                            pv = pv if pv > reroll_val else reroll_val
                                        proc += p * pv
                                    dp[(w, c, f, s, fi, si, r, tl)] = (
                                        finish_val if finish_val > proc else proc)

    def lookup(self, state: GemState, turns_left: int, rerolls: int) -> float:
        idx = self._b._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        r = min(self._max_rerolls, rerolls)
        return self._dp.get(
            (state.will, state.chaos, state.first, state.second, fi, si, r, turns_left),
            0.0)


# --------------------------------------------------------------------------
# Monte Carlo of the real scenario
# --------------------------------------------------------------------------
def run_mc(sim: GemSimulator, side: SideValueTable, rerolls0: int,
           n_trials: int, seed_base: int) -> Tuple[float, float]:
    pool = sim.pool
    total = 0.0
    total_sq = 0.0

    for t in range(n_trials):
        rng = random.Random(seed_base * 1_000_003 + t)
        state = fresh_state(rerolls0)

        for turn in range(1, TURNS + 1):
            turns_left = TURNS - turn + 1
            tl_after = turns_left - 1
            offers = pool.generate_offers(state, turn, turns_left, rng)
            offers = sim._resolve_effect_offers(offers, state, rng)

            # value-greedy reroll loop (reroll a below-average hand)
            while turn != 1 and state.rerolls > 0:
                keep = side.expected_value_after_click(state, offers, tl_after)
                cont = side.lookup(state, turns_left)  # pool-avg continuation
                if cont > keep:
                    state.rerolls -= 1
                    offers = pool.generate_offers(state, turn, turns_left, rng)
                    offers = sim._resolve_effect_offers(offers, state, rng)
                else:
                    break

            # finish vs process: stop if locking in now beats processing
            finish_val = side.gem_value(state)
            proc_val = side.expected_value_after_click(state, offers, tl_after)
            if finish_val >= proc_val:
                break

            picked = rng.choice(offers)
            sim.apply_option(picked, state, rng)

        v = side.gem_value(state)
        total += v
        total_sq += v * v

    mean = total / n_trials
    var = max(0.0, total_sq / n_trials - mean * mean)
    sem = math.sqrt(var / n_trials)
    return mean, sem


def main() -> None:
    gem = AstroGem(GEM_TYPE, FIRST_EFFECT, SECOND_EFFECT, OPTIMIZE)
    sim = GemSimulator(
        rarity=RARITY,
        use_extra_ticket=None,
        use_reset_ticket=False,
        goal=GOAL,
        astro_gem=gem,
        optimize=OPTIMIZE,
        min_side_coeff=MIN_SIDE_COEFF,
        relic_coeff=None,
        ancient_coeff=None,
    )
    side = sim._get_side_value_table(GEM_TYPE)

    # ---- cross-check against the web-advisor JSON numbers -----------------
    s0 = fresh_state(0)
    print("=== cross-check vs web-advisor JSON (turn 1) ===")
    print(f"flat lookup(s0, tl=9)            = {side.lookup(s0, 9):8.2f}   "
          f"(JSON reroll eValue = 905.05)")
    json_offers = [
        Option("will+2", 4.40, "will", 2),
        Option("second+1", 11.65, "second", 1),
        Option("first+4", 0.45, "first", 4),
        Option("chaos+3", 1.75, "chaos", 3),
    ]
    proc = side.expected_value_after_click(s0, json_offers, 8)
    print(f"E[value | the 4 JSON offers]     = {proc:8.2f}   "
          f"(JSON process eValue = 1383.34)")
    print(f"relic_coeff={side.relic_coeff:.2f}  ancient_coeff={side.ancient_coeff:.2f}")
    print()

    # ---- reroll-aware DP (per-option max) --------------------------------
    maxR = max(BUDGETS)
    peropt = RerollAwareSideValueTable(side, maxR)

    flat_v = side.lookup(s0, 9)  # reroll-independent

    print(f"=== expected gem value vs starting reroll budget "
          f"(N={N_TRIALS:,} per budget) ===")
    print(f"{'budget r':>9} | {'flat_dp':>9} | {'peropt_dp':>10} | "
          f"{'MC (truth)':>12} | {'95% CI':>16}")
    print("-" * 70)
    mc_by_r: Dict[int, Tuple[float, float]] = {}
    for r in BUDGETS:
        mc_mean, mc_sem = run_mc(sim, side, r, N_TRIALS, seed_base=r + 1)
        mc_by_r[r] = (mc_mean, mc_sem)
        ci = 1.96 * mc_sem
        print(f"{r:>9} | {flat_v:>9.2f} | {peropt.lookup(s0, 9, r):>10.2f} | "
              f"{mc_mean:>12.2f} | [{mc_mean - ci:>7.2f},{mc_mean + ci:>7.2f}]")

    print()
    # ---- the with/without-ticket comparison the user asked about ---------
    m2, s2 = mc_by_r[2]
    m3, s3 = mc_by_r[3]
    diff = m3 - m2
    diff_sem = math.sqrt(s2 * s2 + s3 * s3)
    print("=== withoutTicket (r=2) vs withTicket (r=3) ===")
    print(f"flat_dp:    {flat_v:8.2f}  vs  {flat_v:8.2f}   (delta 0.00  <- what the web shows)")
    print(f"peropt_dp:  {peropt.lookup(s0, 9, 2):8.2f}  vs  {peropt.lookup(s0, 9, 3):8.2f}   "
          f"(delta {peropt.lookup(s0, 9, 3) - peropt.lookup(s0, 9, 2):+.2f})")
    print(f"MC truth:   {m2:8.2f}  vs  {m3:8.2f}   "
          f"(delta {diff:+.2f} +/- {1.96 * diff_sem:.2f})")


if __name__ == "__main__":
    main()
