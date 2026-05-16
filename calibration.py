"""Calibration script: confirms the gap between the reroll-aware DP probability
(used for decision-making) and the realised Monte Carlo success rate.

The reroll-aware GoalProbabilityTable models each turn as a single weighted
draw the player keeps-or-rerolls. The real mechanic is 4-draw-uniform-pick.
This single-draw-with-rejection approximation tends to overestimate true
success when rerolls are available, and the gap scales with reroll count
(epic + 3 rerolls ≈ +15pp). However, at 0 rerolls the approximation can go
either way — the common/no-ticket row typically shows a small under-estimate
(MC landing above the reroll-aware DP value), so neither DP value is a strict
mathematical bound.

The no-reroll DP (max_rerolls=0) is always <= the reroll-aware DP by
construction. MC typically lands between the two DP estimates but not always,
because the single-draw transition approximation can under-estimate as well as
over-estimate. These are estimates, not guaranteed bounds.

Note on the ``max_rerolls=0`` row: the simulator's base rerolls per rarity
(common=0, rare=1, epic=2) are separate from the extra ticket reroll.  For
this row the simulator is configured with ``use_extra_ticket=False`` and
the rarity-native base rerolls apply, so the MC rate is NOT a zero-reroll
run — it is the baseline (no extra ticket) game play.  The no-reroll DP
(``DP (no-rl)``) models zero rerolls of any kind and is always <= the
reroll-aware DP, but may still be above or below the MC rate.

Run manually (not part of the unit suite):
    python calibration.py
"""

import random

from arkgrid.models import LastTurnGoal
from arkgrid.simulator import GemSimulator
from arkgrid.cli import _compute_dp_prob

GOAL = LastTurnGoal(min_will=4, min_chaos=4)
SEED = 99999
TRIALS = 5000
OPTIMIZE = "dps"

RARITIES = ["common", "rare", "epic"]
RARITY_BASE_REROLLS = GemSimulator.RARITY_REROLLS  # {common:0, rare:1, epic:2}


def mc_success_rate(rarity: str, use_extra_ticket: bool, seed: int, trials: int) -> float:
    """Run Monte Carlo trials and return the success rate."""
    rng = random.Random(seed)
    sim = GemSimulator(
        rarity=rarity,
        use_extra_ticket=use_extra_ticket,
        use_reset_ticket=False,
        goal=GOAL,
        optimize=OPTIMIZE,
        early_finish_coeff=0,
        effect_aware=True,
    )
    wins = 0
    for _ in range(trials):
        s = rng.randrange(1, 2 ** 31 - 1)
        r = sim.simulate_one(seed=s, log=False)
        wins += 1 if r.success else 0
    return wins / trials


def main() -> None:
    print(f"Goal: min_will={GOAL.min_will}, min_chaos={GOAL.min_chaos}")
    print(f"Trials: {TRIALS}  Seed: {SEED}  Optimize: {OPTIMIZE}")
    print()
    fmt = "{:<8} {:<12} {:>13} {:>13} {:>10} {:>12}"
    print(fmt.format("rarity", "extra_ticket", "DP (reroll~)", "DP (no-rl)", "MC", "gap(rl~-MC)"))
    print("-" * 75)

    for rarity in RARITIES:
        base = RARITY_BASE_REROLLS[rarity]
        for use_extra in (False, True):
            total_rerolls = base + (1 if use_extra else 0)
            dp_reroll = _compute_dp_prob(
                GOAL, rarity, None, OPTIMIZE, False, 0,
                early_finish=True, max_rerolls=total_rerolls,
            )
            dp_no_reroll = _compute_dp_prob(
                GOAL, rarity, None, OPTIMIZE, False, 0,
                early_finish=True, max_rerolls=0,
            )
            mc = mc_success_rate(rarity, use_extra, SEED, TRIALS)
            gap = dp_reroll - mc
            in_range = dp_no_reroll <= mc <= dp_reroll
            marker = "" if in_range else "  <-- MC outside DP estimates"
            print(fmt.format(
                rarity,
                "yes" if use_extra else "no",
                f"{dp_reroll:.2%}",
                f"{dp_no_reroll:.2%}",
                f"{mc:.2%}",
                f"{gap:+.2%}",
            ) + marker)
        print()

    print("Legend:")
    print("  DP (reroll~) — reroll-aware DP; displayed as optimistic estimate in sim/live/auto")
    print("  DP (no-rl)   — no-reroll DP (max_rerolls=0); displayed as conservative estimate in stats")
    print("  MC           — Monte Carlo realised rate; typically between the two DP estimates, but not guaranteed")
    print("  gap          — DP (reroll~) minus MC; positive means DP overestimates")
    print()
    print("  Base rerolls per rarity: common=0, rare=1, epic=2 (from game mechanics)")
    print("  extra_ticket=yes adds 1 more reroll via the extra-ticket item")


if __name__ == "__main__":
    main()
