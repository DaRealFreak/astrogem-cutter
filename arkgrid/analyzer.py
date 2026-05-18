from __future__ import annotations

import math
import random
from typing import Dict, Tuple

from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, SUPPORT_COEFF, SUPPORT_EFFECTS
from arkgrid.simulator import GemSimulator


class GemAnalyzer:
    @staticmethod
    def wilson_ci(p_hat: float, n: int, z: float = 1.96) -> Tuple[float, float]:
        if n == 0:
            return (0.0, 1.0)
        denom = 1 + z ** 2 / n
        center = (p_hat + z ** 2 / (2 * n)) / denom
        half = (z * math.sqrt((p_hat * (1 - p_hat) / n) + (z ** 2 / (4 * n ** 2)))) / denom
        return (max(0.0, center - half), min(1.0, center + half))

    @staticmethod
    def _side_coeff(state, optimize: str) -> int:
        coeff = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        target = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        total = 0
        if state.first_effect in target:
            total += state.first * coeff[state.first_effect]
        if state.second_effect in target:
            total += state.second * coeff[state.second_effect]
        return total

    @staticmethod
    def estimate_summary(
            trials: int,
            simulator: GemSimulator,
            relic_threshold: int = 16,
            ancient_threshold: int = 19,
            seed: int = 12345,
    ) -> Dict[str, float]:
        rng = random.Random(seed)
        optimize = simulator.optimize

        wins = 0
        resets = 0
        extra_tickets = 0
        sum_points = 0
        sum_side_coeff = 0
        relic_plus = 0
        ancient = 0

        # `--trials 0` is a documented DP-only mode (no Monte Carlo). Return a
        # fully-keyed zeroed summary so callers can consume all keys safely.
        if trials <= 0:
            # Keep keys in sync with the normal-path summary dict below.
            return {
                "p_success": 0.0,
                "p_success_ci_lo": 0.0,
                "p_success_ci_hi": 1.0,
                "avg_total_points": 0.0,
                "avg_side_coeff": 0.0,
                "p_relic_plus": 0.0,
                "p_ancient": 0.0,
                "reset_rate": 0.0,
                "extra_ticket_available_rate": 0.0,
            }

        for _ in range(trials):
            s = rng.randrange(1, 2 ** 31 - 1)
            r = simulator.simulate_one(seed=s, log=False)

            wins += 1 if r.success else 0
            resets += 1 if r.reset_used else 0
            extra_tickets += 1 if r.extra_ticket_used else 0

            sum_points += r.total_points
            sum_side_coeff += GemAnalyzer._side_coeff(r.state, optimize)
            relic_plus += 1 if r.total_points >= relic_threshold else 0
            ancient += 1 if r.total_points >= ancient_threshold else 0

        p_success = wins / trials
        lo, hi = GemAnalyzer.wilson_ci(p_success, trials)

        return {
            "p_success": p_success,
            "p_success_ci_lo": lo,
            "p_success_ci_hi": hi,
            "avg_total_points": sum_points / trials,
            "avg_side_coeff": sum_side_coeff / trials,
            "p_relic_plus": relic_plus / trials,
            "p_ancient": ancient / trials,
            "reset_rate": resets / trials,
            "extra_ticket_available_rate": extra_tickets / trials,
        }


def pprint_result(title: str, result: Dict[str, float]) -> None:
    print(title)
    if "dp_prob" in result:
        line = f"  DP probability (reroll-aware, optimistic): {result['dp_prob'] * 100:.2f}%"
        print(line)
    if "dp_prob_no_reroll" in result:
        print(f"  DP probability (no-reroll, conservative):  {result['dp_prob_no_reroll'] * 100:.2f}%")
    if "relic_dp_prob" in result:
        print(f"  DP relic+ (>=16): {result['relic_dp_prob'] * 100:.2f}%")
    if "ancient_dp_prob" in result:
        print(f"  DP ancient (>=19): {result['ancient_dp_prob'] * 100:.2f}%")
    if "p_success" in result:
        print(
            f"  Success rate: {result['p_success'] * 100:.2f}% "
            f"(CI: {result['p_success_ci_lo'] * 100:.2f}% - "
            f"{result['p_success_ci_hi'] * 100:.2f}%)")
        print(f"  Average total points: {result['avg_total_points']:.3f}")
        print(f"  Average side coefficient: {result['avg_side_coeff']:.0f}")
        print(f"  Relic+ rate (>=16): {result['p_relic_plus'] * 100:.2f}%")
        print(f"  Ancient rate (>=19): {result['p_ancient'] * 100:.2f}%")
        print(f"  Reset usage rate: {result['reset_rate'] * 100:.2f}%")
        print(f"  Extra ticket available rate: {result['extra_ticket_available_rate'] * 100:.2f}%")
    print("")
