"""Benchmark comparing reroll strategies.

Usage:
    source .venv/Scripts/activate
    python benchmark_reroll.py [--trials 200000] [--seed 12345]
"""
from __future__ import annotations

import argparse
import math
import random
import time
from typing import Dict, List, Tuple

from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, SUPPORT_COEFF, SUPPORT_EFFECTS
from arkgrid.models import LastTurnGoal, AstroGem, GemState
from arkgrid.pool import OptionPool
from arkgrid.simulator import GemSimulator


STRATEGIES = ["baseline", "reserve", "dp_extended"]


def wilson_ci(p_hat: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    denom = 1 + z ** 2 / n
    center = (p_hat + z ** 2 / (2 * n)) / denom
    half = (z * math.sqrt((p_hat * (1 - p_hat) / n) + (z ** 2 / (4 * n ** 2)))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def run_benchmark(
    strategy: str,
    rarity: str,
    trials: int,
    seed: int,
    goal: LastTurnGoal,
    optimize: str = "dps",
    reset_min_coeff: int = 1000,
    reroll_min_coeff: int = 700,
) -> Dict[str, float]:
    pool = OptionPool()
    t0 = time.time()
    sim = GemSimulator(
        rarity=rarity,
        use_extra_ticket=True,
        use_reset_ticket=True,
        goal=goal,
        side_node_threshold=0.5,
        optimize=optimize,
        reset_min_coeff=reset_min_coeff,
        reroll_min_coeff=reroll_min_coeff,
        pool=pool,
    )
    build_time = time.time() - t0

    rng = random.Random(seed)
    total_turns = sim.turns_total

    wins = 0
    resets = 0
    sum_points = 0
    sum_side_coeff = 0

    # Reroll tracking by turn-thirds
    third_size = total_turns / 3
    rerolls_early = 0  # turns 1..third
    rerolls_mid = 0    # turns third+1..2*third
    rerolls_late = 0   # turns 2*third+1..total
    total_rerolls_used = 0

    coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
    target_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS

    t0 = time.time()
    for _ in range(trials):
        s = rng.randrange(1, 2 ** 31 - 1)
        r = sim.simulate_one(seed=s, log=False)

        wins += 1 if r.success else 0
        resets += 1 if r.reset_used else 0
        sum_points += r.total_points

        sc = 0
        if r.state.first_effect in target_set:
            sc += r.state.first * coeff_map[r.state.first_effect]
        if r.state.second_effect in target_set:
            sc += r.state.second * coeff_map[r.state.second_effect]
        sum_side_coeff += sc

        if r.rerolls_by_turn:
            for turn, count in r.rerolls_by_turn.items():
                total_rerolls_used += count
                if turn <= third_size:
                    rerolls_early += count
                elif turn <= 2 * third_size:
                    rerolls_mid += count
                else:
                    rerolls_late += count

    sim_time = time.time() - t0
    p_success = wins / trials
    lo, hi = wilson_ci(p_success, trials)

    return {
        "strategy": strategy,
        "rarity": rarity,
        "p_success": p_success,
        "ci_lo": lo,
        "ci_hi": hi,
        "avg_points": sum_points / trials,
        "avg_side_coeff": sum_side_coeff / trials,
        "reset_rate": resets / trials,
        "avg_rerolls_used": total_rerolls_used / trials,
        "rerolls_early": rerolls_early / trials,
        "rerolls_mid": rerolls_mid / trials,
        "rerolls_late": rerolls_late / trials,
        "build_time_ms": build_time * 1000,
        "sim_time_s": sim_time,
    }


def print_comparison(results: List[Dict[str, float]], rarity: str) -> None:
    print(f"\n{'='*80}")
    print(f"  Rarity: {rarity.upper()}  ({results[0].get('trials', '?')} trials)")
    print(f"{'='*80}")

    header = (f"  {'Strategy':<14} {'Success':>8} {'CI':>16} "
              f"{'Pts':>6} {'Coeff':>6} {'Resets':>7} "
              f"{'Rerolls':>7} {'Early':>6} {'Mid':>5} {'Late':>5}")
    print(header)
    print(f"  {'-'*14} {'-'*8} {'-'*16} {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*6} {'-'*5} {'-'*5}")

    baseline_p = None
    for r in results:
        if r["strategy"] == "baseline":
            baseline_p = r["p_success"]

    for r in results:
        delta = ""
        if baseline_p is not None and r["strategy"] != "baseline":
            diff = (r["p_success"] - baseline_p) * 100
            delta = f" ({'+' if diff >= 0 else ''}{diff:.2f}pp)"

        line = (
            f"  {r['strategy']:<14} "
            f"{r['p_success']*100:>7.2f}% "
            f"[{r['ci_lo']*100:.2f}-{r['ci_hi']*100:.2f}%] "
            f"{r['avg_points']:>5.1f} "
            f"{r['avg_side_coeff']:>6.0f} "
            f"{r['reset_rate']*100:>6.1f}% "
            f"{r['avg_rerolls_used']:>6.2f} "
            f"{r['rerolls_early']:>5.2f} "
            f"{r['rerolls_mid']:>5.2f} "
            f"{r['rerolls_late']:>5.2f}"
            f"{delta}"
        )
        print(line)

    print(f"\n  Build times: ", end="")
    for r in results:
        print(f"{r['strategy']}={r['build_time_ms']:.0f}ms  ", end="")
    print()
    print(f"  Sim times:   ", end="")
    for r in results:
        print(f"{r['strategy']}={r['sim_time_s']:.1f}s  ", end="")
    print()


def main():
    parser = argparse.ArgumentParser(description="Benchmark reroll strategies")
    parser.add_argument("--trials", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--rarity", nargs="+",
                        choices=["common", "rare", "epic"],
                        default=["epic", "rare"])
    parser.add_argument("--strategies", nargs="+",
                        choices=STRATEGIES, default=STRATEGIES)
    parser.add_argument("--optimize", choices=["dps", "support"], default="dps")
    parser.add_argument("--min-will", type=int, default=4)
    parser.add_argument("--min-chaos", type=int, default=5)
    parser.add_argument("--reset-min-coeff", type=int, default=1000)
    parser.add_argument("--reroll-min-coeff", type=int, default=700)
    args = parser.parse_args()

    goal = LastTurnGoal(min_will=args.min_will, min_chaos=args.min_chaos)

    print(f"Benchmark: {args.trials} trials, seed={args.seed}")
    print(f"Goal: min_will={args.min_will}, min_chaos={args.min_chaos}")
    print(f"Optimize: {args.optimize}")
    print(f"reset_min_coeff: {args.reset_min_coeff}, "
          f"reroll_min_coeff: {args.reroll_min_coeff}")
    print(f"Strategies: {', '.join(args.strategies)}")
    print(f"Rarities: {', '.join(args.rarity)}")

    for rarity in args.rarity:
        results = []
        for strategy in args.strategies:
            print(f"\n  Running {strategy} on {rarity}...", end=" ", flush=True)
            r = run_benchmark(
                strategy=strategy,
                rarity=rarity,
                trials=args.trials,
                seed=args.seed,
                goal=goal,
                optimize=args.optimize,
                reset_min_coeff=args.reset_min_coeff,
                reroll_min_coeff=args.reroll_min_coeff,
            )
            r["trials"] = args.trials
            results.append(r)
            print(f"{r['p_success']*100:.2f}% ({r['sim_time_s']:.1f}s)")

        print_comparison(results, rarity)


if __name__ == "__main__":
    main()
