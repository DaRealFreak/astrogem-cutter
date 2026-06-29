"""Phase B A/B: does the reroll-aware decision gate actually improve decisions?

Runs the production GemSimulator with the FLAT value gate vs the REROLL-AWARE
gate (``reroll_aware_value``) on IDENTICAL RNG seeds, across several scenarios,
and compares with a single fixed scoring oracle so both policies are judged on
the same yardstick:

  - goal success rate         (PRIMARY CONSTRAINT: must not regress)
  - E[goal-conditioned value] (the gate's OWN objective: side_coeff+tier_bonus
                               if goal met & side-coeff floor cleared, else 0)
  - E[raw gem value]          (side_coeff+tier_bonus regardless of goal)
  - relic+ (>=16) / ancient (>=19) rates

Improvement = goal-conditioned value UP and goal success NOT down. Paired by
seed (common random numbers) for a tighter delta estimate.

Run from project root:  python tools/reroll_phaseB_ab.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid.models import AstroGem, GemState, LastTurnGoal
from arkgrid.pool import OptionPool
from arkgrid.probability import SideValueTable
from arkgrid.simulator import GemSimulator

N_TRIALS = 60_000

# Each scenario: a dict of GemSimulator kwargs (minus reroll_aware_value) + a
# label. astro_gem fixes the gem so the comparison is on one gem type.
# Goal-difficulty sweep on a value-rich gem (no side-coeff floor, so value =
# side_coeff + grade). Lower will/chaos goal => met sooner => MORE pure-value
# turns where the side-value gate is the dominant decision-maker. This is the
# high-end regime: the user's hypothesis is that the reroll-aware gate helps
# more as the goal gets easier (more value-driven, less goal-driven).
def _vd(label, wc):
    return dict(label=label,
                gem=("order_stability", "additional_damage", "attack_power"),
                goal=LastTurnGoal(min_total_will_chaos=wc), rarity="epic",
                min_side_coeff=0, relic_reroll_threshold=0.1,
                reroll_min_coeff=700, use_extra_ticket=None,
                use_reset_ticket=True)

SCENARIOS = [
    _vd("value-driven: goal wc>=2 (met at start, pure value)", 2),
    _vd("value-driven: goal wc>=4 (easy)", 4),
    _vd("mixed: goal wc>=6", 6),
    _vd("goal-driven: goal wc>=8 (hard)", 8),
]


def build_sim(sc: dict, reroll_aware: bool) -> GemSimulator:
    gt, fe, se = sc["gem"]
    gem = AstroGem(gt, fe, se, "dps")
    return GemSimulator(
        rarity=sc["rarity"], use_extra_ticket=sc["use_extra_ticket"],
        use_reset_ticket=sc["use_reset_ticket"], goal=sc["goal"],
        astro_gem=gem, optimize="dps", min_side_coeff=sc["min_side_coeff"],
        relic_reroll_threshold=sc["relic_reroll_threshold"],
        reroll_min_coeff=sc["reroll_min_coeff"],
        relic_coeff=None, ancient_coeff=None,
        reroll_aware_value=reroll_aware,
    )


def scorers(sc: dict):
    gt, fe, se = sc["gem"]
    pool = OptionPool()
    turns = {"common": 5, "rare": 7, "epic": 9}[sc["rarity"]]
    goal_scorer = SideValueTable(sc["goal"], turns, pool, gem_type=gt,
        optimize="dps", min_side_coeff=sc["min_side_coeff"], value_mode="side")
    raw_scorer = SideValueTable(LastTurnGoal(), turns, pool, gem_type=gt,
        optimize="dps", min_side_coeff=0, value_mode="side")
    return goal_scorer, raw_scorer


def run(sc: dict):
    goal_scorer, raw_scorer = scorers(sc)
    sims = {"flat": build_sim(sc, False), "ra": build_sim(sc, True)}
    agg = {k: dict(succ=0, gval=0.0, gval_sq=0.0, raw=0.0,
                   relic=0, ancient=0) for k in sims}
    paired = []  # ra_gval - flat_gval per seed

    for i in range(N_TRIALS):
        per = {}
        for k, sim in sims.items():
            r = sim.simulate_one(seed=i)
            st = r.state
            gv = goal_scorer.gem_value(st)
            tot = st.total_points()
            a = agg[k]
            a["succ"] += 1 if r.success else 0
            a["gval"] += gv
            a["gval_sq"] += gv * gv
            a["raw"] += raw_scorer.gem_value(st)
            a["relic"] += 1 if tot >= 16 else 0
            a["ancient"] += 1 if tot >= 19 else 0
            per[k] = gv
        paired.append(per["ra"] - per["flat"])

    return agg, paired


def fmt(a: dict, n: int) -> str:
    succ = a["succ"] / n
    gval = a["gval"] / n
    var = max(0.0, a["gval_sq"] / n - gval * gval)
    sem = math.sqrt(var / n)
    return (f"succ={succ*100:6.2f}%  Egoalval={gval:8.2f}(+-{1.96*sem:5.2f})  "
            f"Eraw={a['raw']/n:8.2f}  relic={a['relic']/n*100:5.2f}%  "
            f"ancient={a['ancient']/n*100:5.2f}%")


def main():
    print(f"Phase B A/B - flat gate vs reroll-aware gate  (N={N_TRIALS:,}/cell, paired seeds)\n")
    for sc in SCENARIOS:
        agg, paired = run(sc)
        n = N_TRIALS
        print(f"### {sc['label']}")
        print(f"  flat : {fmt(agg['flat'], n)}")
        print(f"  RA   : {fmt(agg['ra'], n)}")
        # paired delta on goal-conditioned value
        md = sum(paired) / n
        vd = max(0.0, sum(d * d for d in paired) / n - md * md)
        sd = math.sqrt(vd / n)
        d_succ = (agg['ra']['succ'] - agg['flat']['succ']) / n * 100
        print(f"  delta: goal-value {md:+.2f} (+-{1.96*sd:.2f}, 95% CI)   "
              f"goal-success {d_succ:+.2f}pp   "
              f"relic {(agg['ra']['relic']-agg['flat']['relic'])/n*100:+.2f}pp   "
              f"ancient {(agg['ra']['ancient']-agg['flat']['ancient'])/n*100:+.2f}pp")
        verdict = ("IMPROVEMENT" if md > 2 * sd and d_succ > -0.3
                   else "NEUTRAL" if abs(md) <= 2 * sd
                   else "REGRESSION?" )
        print(f"  >>> {verdict}\n")


if __name__ == "__main__":
    main()
