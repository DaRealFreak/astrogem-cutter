"""Validate the engine's reroll / hand model against the real 4-offer mechanics.

The DP prices "see the hand, then keep it or take the alternative (redraw /
finish)" with `arkgrid.probability.hand_e_max`. Two independent checks tell
whether that model — or any change to it — is right:

1. **One step, exact.** At states actually reached in play, compare the
   model's `E[max(hand mean, alternative)]` with the exact value from
   enumerating every C(n, 4) hand. Reported as the error in the *option
   value* (what seeing the hand adds over deciding blind).
2. **End to end.** Build a table, play its OWN policy under the real
   mechanics, and compare the table's prediction with what was achieved.

Run both: errors that cancel end to end (they did, for an earlier model that
was only right on hard goals) show up in the one-step check.

Run from the project root:
    python tools/validate_hand_model.py              # all scenarios
    python tools/validate_hand_model.py --trials 20000 --states 100
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import random
import sys
import time
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid.constants import DPS_COEFF, GEM_TYPES
from arkgrid.models import GemState, LastTurnGoal
from arkgrid.pool import OptionPool
from arkgrid.probability import (
    GoalProbabilityTable, SideValueTable, _hand_moments, _hand_turn_value,
    hand_context,
)

POOL = OptionPool()
TURNS = 9            # epic
MAX_REROLLS = 4

# ---------------------------------------------------------------------------
# Exact enumeration of the 4-offer hand
# ---------------------------------------------------------------------------

_PERM_SUM: Dict[Tuple[Tuple[float, ...], float], float] = {}


def _hand_probability(ws: List[float], total: float) -> float:
    """P(these 4 options form the hand), summed over the 24 draw orders."""
    key = (tuple(sorted(ws)), total)
    h = _PERM_SUM.get(key)
    if h is None:
        h = sum(1.0 / (total * (total - a) * (total - a - b)
                       * (total - a - b - c))
                for a, b, c, _d in itertools.permutations(ws))
        _PERM_SUM[key] = h
    return ws[0] * ws[1] * ws[2] * ws[3] * h


def exact_hand_e_max(weights: List[float], values: List[float],
                     alt: float) -> float:
    total = sum(weights)
    out = 0.0
    for idx in itertools.combinations(range(len(weights)), 4):
        p = _hand_probability([weights[i] for i in idx], total)
        h = (values[idx[0]] + values[idx[1]]
             + values[idx[2]] + values[idx[3]]) / 4
        out += p * (h if h > alt else alt)
    return out


# ---------------------------------------------------------------------------
# Real-mechanics play
# ---------------------------------------------------------------------------

def _apply(st: GemState, o, gem_type: str, rng: random.Random) -> int:
    """Apply offer `o`; returns the reroll delta (view offers)."""
    if o.kind in ("will", "chaos", "first", "second"):
        setattr(st, o.kind, min(5, max(1, getattr(st, o.kind) + o.delta)))
    elif o.kind == "view":
        return o.delta
    elif o.kind == "cost":
        st.cost_ratio = (min(100, st.cost_ratio + 100) if o.key == "cost+100"
                         else max(-100, st.cost_ratio - 100))
    elif o.key in ("change_first_effect", "change_second_effect") and gem_type:
        dest = rng.choice([e for e in GEM_TYPES[gem_type]
                           if e != st.first_effect and e != st.second_effect])
        if o.key == "change_first_effect":
            st.first_effect = dest
        else:
            st.second_effect = dest
    return 0


class GoalScenario:
    """A goal table played by pure goal chasing: stop once the goal is met,
    reroll whenever the table says a redraw beats the hand."""
    kind = "goal"

    def __init__(self, name, goal, gem_type="", first="", second="",
                 min_side_coeff=0):
        self.name, self.goal = name, goal
        self.gem_type, self.first, self.second = gem_type, first, second
        self.min_side_coeff = min_side_coeff
        self.table = GoalProbabilityTable(
            goal, TURNS, POOL, min_side_coeff=min_side_coeff,
            early_finish=True, max_rerolls=MAX_REROLLS,
            effect_aware=bool(gem_type), gem_type=gem_type, optimize="dps")

    def start(self) -> GemState:
        return GemState(first_effect=self.first, second_effect=self.second)

    def predict(self, rerolls: int) -> float:
        return self.table.lookup(self.start(), TURNS, rerolls=rerolls)

    def _met(self, st: GemState) -> bool:
        if not self.goal.satisfied(st.will, st.chaos, st.first, st.second):
            return False
        if self.min_side_coeff > 0:
            coeff = (DPS_COEFF.get(st.first_effect, 0) * st.first
                     + DPS_COEFF.get(st.second_effect, 0) * st.second)
            return coeff >= self.min_side_coeff
        return True

    def play(self, rerolls, trials, rng, visits=None) -> float:
        wins = 0
        for _ in range(trials):
            st, r = self.start(), rerolls
            for turn in range(1, TURNS + 1):
                tl = TURNS - turn + 1
                if self._met(st):
                    break
                if visits is not None and turn != 1 and r > 0:
                    visits.append((st.clone(), r, tl, turn))
                while True:
                    offers = POOL.generate_offers(st, turn, tl, rng)
                    if (turn == 1 or r <= 0 or not self.table.should_reroll_dp(
                            st, offers, tl, r)):
                        break
                    r -= 1
                r += _apply(st, rng.choice(offers), self.gem_type, rng)
            wins += self._met(st)
        return wins / trials

    def turn_inputs(self, st, r, tl, turn):
        elig = [o for o in POOL.pool if POOL.eligible(o, st, turn, tl)]
        posts = [self.table.prob_after_option(st, o, tl - 1, rerolls=r)
                 for o in elig]
        return ([o.weight for o in elig], posts,
                self.table.lookup(st, tl, rerolls=r - 1))


class ValueScenario:
    """A side-value table played by its own policy: finish / reroll / process,
    whichever it values highest."""
    kind = "value"

    def __init__(self, name, goal, gem_type, first, second,
                 min_side_coeff=0, value_mode="side"):
        self.name = name
        self.gem_type, self.first, self.second = gem_type, first, second
        self.table = SideValueTable(
            goal, TURNS, POOL, gem_type=gem_type, optimize="dps",
            min_side_coeff=min_side_coeff, value_mode=value_mode,
            max_rerolls=MAX_REROLLS)

    def start(self) -> GemState:
        return GemState(first_effect=self.first, second_effect=self.second)

    def predict(self, rerolls: int) -> float:
        return self.table.lookup(self.start(), TURNS, rerolls=rerolls)

    def play(self, rerolls, trials, rng, visits=None) -> float:
        svt, total = self.table, 0.0
        for _ in range(trials):
            st, r, value = self.start(), rerolls, None
            for turn in range(1, TURNS + 1):
                tl = TURNS - turn + 1
                if visits is not None:
                    visits.append((st.clone(), r, tl, turn))
                while True:
                    offers = POOL.generate_offers(st, turn, tl, rng)
                    fin = svt.gem_value(st)
                    keep = svt.expected_value_after_click(
                        st, offers, tl - 1, rerolls=r)
                    if turn != 1 and r > 0:
                        redraw = svt.lookup(st, tl, rerolls=r - 1)
                        if redraw > keep and redraw > fin + 1e-9:
                            r -= 1
                            continue
                    break
                if fin >= keep:
                    value = fin
                    break
                r += _apply(st, rng.choice(offers), self.gem_type, rng)
            total += svt.gem_value(st) if value is None else value
        return total / trials

    def turn_inputs(self, st, r, tl, turn):
        elig = [o for o in POOL.pool if POOL.eligible(o, st, turn, tl)]
        posts = [self.table.expected_value_after_click(
            st, [o], tl - 1, rerolls=r) for o in elig]
        alt = self.table.gem_value(st)
        if r > 0 and turn != 1:
            alt = max(alt, self.table.lookup(st, tl, rerolls=r - 1))
        return [o.weight for o in elig], posts, alt


# ---------------------------------------------------------------------------
# The two checks
# ---------------------------------------------------------------------------

def one_step(scn, visits, states: int, rng: random.Random) -> Tuple[float, float]:
    """(option-value error, mean |value error|) of the model vs exact."""
    model_gain = exact_gain = abs_err = 0.0
    n = 0
    for st, r, tl, turn in rng.sample(visits, min(states, len(visits))):
        weights, posts, alt = scn.turn_inputs(st, r, tl, turn)
        ctx = hand_context(weights)
        model = _hand_turn_value(ctx, posts, alt)
        exact = exact_hand_e_max(weights, posts, alt)
        if exact <= 1e-12:
            continue
        blind = max(_hand_moments(ctx, posts)[0], alt)
        model_gain += model - blind
        exact_gain += exact - blind
        abs_err += abs(model - exact) / exact
        n += 1
    if n == 0 or exact_gain <= 0:
        return 0.0, 0.0
    return model_gain / exact_gain - 1.0, abs_err / n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trials", type=int, default=40000,
                    help="games per end-to-end check (default 40000)")
    ap.add_argument("--states", type=int, default=150,
                    help="visited states per one-step check (default 150)")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    hard = LastTurnGoal(min_will=4, min_chaos=5)
    easy = LastTurnGoal(min_total_will_chaos=8)
    imm = ("order_immutability", "boss_damage", "additional_damage")
    stab = ("order_stability", "additional_damage", "attack_power")
    scenarios = [
        lambda: GoalScenario("goal: will>=4 chaos>=5 + coeff 2000", hard, *imm,
                             min_side_coeff=2000),
        lambda: GoalScenario("goal: will>=3 chaos>=4",
                             LastTurnGoal(min_will=3, min_chaos=4)),
        lambda: GoalScenario("goal: relic (total >= 16)",
                             LastTurnGoal(min_total=16)),
        lambda: ValueScenario("value: will>=4 chaos>=5 + coeff 2000", hard,
                              *imm, min_side_coeff=2000),
        lambda: ValueScenario("value: easy goal + coeff 2000", easy, *stab,
                              min_side_coeff=2000),
        lambda: ValueScenario("value: dead-goal grade chase", LastTurnGoal(),
                              *imm, value_mode="grade_only"),
    ]
    print(f"{'scenario':40s} {'rerolls':>7s} {'predicted':>10s} "
          f"{'achieved':>10s} {'bias':>7s} | one-step: option value, |value|")
    for make in scenarios:
        t0 = time.time()
        scn = make()
        rng = random.Random(args.seed)
        visits: list = []
        for rerolls in (2, 3):
            achieved = scn.play(rerolls, args.trials, rng,
                                visits if rerolls == 2 else None)
            predicted = scn.predict(rerolls)
            bias = (predicted - achieved) / achieved if achieved else 0.0
            extra = ""
            if rerolls == 3:
                ov, av = one_step(scn, visits, args.states, rng)
                extra = f" | {ov:+7.1%} {av:7.2%}  [{time.time() - t0:.0f}s]"
            fmt = ".4f" if scn.kind == "goal" else ".1f"
            print(f"{scn.name:40s} {rerolls:7d} {predicted:10{fmt}} "
                  f"{achieved:10{fmt}} {bias:+7.1%}{extra}", flush=True)
    print("\nbias: table prediction vs what its own policy achieved "
          f"(MC noise ~{1 / math.sqrt(args.trials) * 100 * 2.5:.1f}% at "
          "these trial counts).\none-step: model vs exact enumeration of all "
          "C(n,4) hands at visited states.")


if __name__ == "__main__":
    main()
