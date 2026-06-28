"""Export golden vectors for the TS engine parity suite.

Run from repo root:  python tools/export_golden.py
Writes web/tests/fixtures/*.json. Commit the output.
"""
from __future__ import annotations
import json, subprocess, itertools, os, sys

# Run as `python tools/export_golden.py` from the project root:
# add the project root to sys.path so `arkgrid` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from arkgrid.constants import GEM_TYPES, DPS_COEFF, SUPPORT_COEFF, DPS_EFFECTS, SUPPORT_EFFECTS
from arkgrid.models import Option, LastTurnGoal, GemState, AstroGem
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable, SideValueTable
from arkgrid import decision as D

FIX = Path("web/tests/fixtures")
SCHEMA_VERSION = 1
RARITY_TURNS = {"common": 5, "rare": 7, "epic": 9}
RARITY_REROLLS = {"common": 0, "rare": 1, "epic": 2}


def side_coeffs(gem: AstroGem):
    cm = DPS_COEFF if gem.optimize == "dps" else SUPPORT_COEFF
    ts = DPS_EFFECTS if gem.optimize == "dps" else SUPPORT_EFFECTS
    f = cm[gem.first_effect] if gem.first_effect in ts else 0
    s = cm[gem.second_effect] if gem.second_effect in ts else 0
    return f, s


def dp_max_rerolls(rarity, extra_ticket, relic_thr, goal_reroll_active):
    base = RARITY_REROLLS[rarity] + (1 if extra_ticket is not False else 0)
    return base + (1 if (relic_thr > 0.0 or goal_reroll_active) else 0)


def _sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def dump(name, records):
    FIX.mkdir(parents=True, exist_ok=True)
    payload = {"meta": {"schema": SCHEMA_VERSION, "arkgrid_sha": _sha()},
               "records": records}
    (FIX / f"{name}.json").write_text(json.dumps(payload, indent=1))
    print(f"wrote {name}.json ({len(records)} records)")


# ---------------------------------------------------------------------------
# Step 2: export_satisfied / export_feasibility
# ---------------------------------------------------------------------------

GOALS = [
    {"min_will": 4, "min_chaos": 5},
    {"min_will": 5, "min_chaos": 5},
    {"min_total_will_chaos": 8},
    {"min_first": 4}, {"min_second": 5}, {"min_total": 16},
    {"min_will": 4, "min_chaos": 4, "min_side_coeff": 4000},
    {},  # trivial
]


def export_satisfied():
    recs = []
    for g in GOALS:
        # min_side_coeff is not a LastTurnGoal field; strip it before constructing
        goal_kwargs = {k: v for k, v in g.items() if k != "min_side_coeff"}
        goal = LastTurnGoal(**goal_kwargs)
        for w, c, f, s in itertools.product((1, 3, 5), (1, 3, 5), (1, 3, 5), (1, 3, 5)):
            recs.append({"inputs": {"goal": g, "will": w, "chaos": c,
                                    "first": f, "second": s},
                         "expected": goal.satisfied(w, c, f, s)})
    dump("satisfied", recs)


def export_feasibility():
    recs = []
    for g in GOALS:
        goal_kwargs = {k: v for k, v in g.items() if k != "min_side_coeff"}
        goal = LastTurnGoal(**goal_kwargs)
        for w, c in itertools.product((1, 3, 5), (1, 3, 5)):
            for tl in (1, 3, 5, 7, 9):
                for f, s in ((1, 1), (3, 2), (5, 5)):
                    kw = dict(min_side_coeff=g.get("min_side_coeff", 0),
                              side_coeff_first=1000, side_coeff_second=700,
                              change_dest_max_coeff=1500)
                    recs.append({"inputs": {"goal": g, "will": w, "chaos": c,
                                            "turns_left": tl, "first": f,
                                            "second": s, **kw},
                                 "expected": goal.feasible(w, c, tl, f, s, **kw)})
    dump("feasibility", recs)


# ---------------------------------------------------------------------------
# Step 3: export_pool
# ---------------------------------------------------------------------------

def export_pool():
    pool = OptionPool()
    snapshot = [{"key": o.key, "weight": o.weight, "kind": o.kind,
                 "delta": o.delta} for o in pool.pool]
    elig = []
    for o in pool.pool:
        for w, c, f, s, cost in [(1, 1, 1, 1, 0), (5, 5, 5, 5, 100), (2, 1, 5, 3, -100),
                                  (1, 5, 1, 1, 0), (5, 1, 1, 5, 100)]:
            st = GemState(will=w, chaos=c, first=f, second=s, cost_ratio=cost)
            for turn, tl in [(1, 5), (2, 4), (3, 1), (5, 1), (4, 2)]:
                elig.append({"inputs": {"key": o.key, "state":
                                {"will": w, "chaos": c, "first": f, "second": s, "cost_ratio": cost},
                                "turn": turn, "turns_left": tl},
                             "expected": pool.eligible(o, st, turn, tl)})
    dump("pool", [{"snapshot": snapshot}, *elig])


# ---------------------------------------------------------------------------
# Step 4: export_dp_lookups
# ---------------------------------------------------------------------------

def _offers(pool, state, turn, tl):
    # deterministic 4-offer hands (no RNG): take first eligible 4 by pool order
    elig = [o for o in pool.pool if pool.eligible(o, state, turn, tl)]
    return elig[:4]


def export_dp_lookups():
    pool = OptionPool()
    recs = []
    cases = [
        ("chaos_distortion", "attack_power", "ally_damage", "dps",
         {"min_will": 4, "min_chaos": 5}, "epic"),
        ("order_stability", "additional_damage", "brand_power", "dps",
         {"min_total_will_chaos": 8}, "rare"),
    ]
    for gt, fe, se, opt, g, rarity in cases:
        goal = LastTurnGoal(**g)
        turns = RARITY_TURNS[rarity]
        mr = dp_max_rerolls(rarity, None, 0.0, False)
        scf, scs = side_coeffs(AstroGem(gt, fe, se, opt))
        roll = GoalProbabilityTable(goal, turns, pool, early_finish=True,
            max_rerolls=mr, effect_aware=True, gem_type=gt, optimize=opt)
        reset = GoalProbabilityTable(goal, turns, pool, early_finish=True,
            effect_aware=True, gem_type=gt, optimize=opt)
        relic = GoalProbabilityTable(LastTurnGoal(min_total=16), turns, pool,
            early_finish=False, max_rerolls=mr)
        anc = GoalProbabilityTable(LastTurnGoal(min_total=19), turns, pool,
            early_finish=False, max_rerolls=mr)
        for w, c, f, s in [(1, 1, 1, 1), (4, 5, 3, 2), (5, 5, 5, 5), (4, 4, 1, 1)]:
            st = GemState(will=w, chaos=c, first=f, second=s,
                          first_effect=fe, second_effect=se)
            for tl in (1, 2, turns):
                for r in (0, 1, min(mr, 2)):
                    offers = _offers(pool, st, turns - tl + 1, tl)
                    okeys = [o.key for o in offers]
                    recs.append({"inputs": {
                        "table": "roll", "gem_type": gt, "first_effect": fe,
                        "second_effect": se, "optimize": opt, "goal": g,
                        "rarity": rarity, "max_rerolls": mr,
                        "state": [w, c, f, s], "turns_left": tl,
                        "rerolls": r, "offers": okeys},
                      "expected": {
                        "lookup": roll.lookup(st, tl, rerolls=r),
                        "epac": roll.expected_prob_after_click(st, offers, max(0, tl - 1), rerolls=r),
                        "reroll": roll.should_reroll_dp(st, offers, tl, r),
                        "reset_lookup": reset.lookup(st, tl),
                        "relic_lookup": relic.lookup(st, tl, rerolls=r),
                        "ancient_lookup": anc.lookup(st, tl, rerolls=r)}})
    dump("dp_lookups", recs)


# ---------------------------------------------------------------------------
# Step 5: export_side_values
# ---------------------------------------------------------------------------

def _goal_dict(goal: LastTurnGoal) -> dict:
    """Turn a LastTurnGoal into its dict of non-None fields."""
    fields = (
        "min_will", "min_chaos", "exact_will", "exact_chaos",
        "min_total_will_chaos", "exact_total_will_chaos",
        "min_first", "min_second", "min_total",
    )
    return {f: getattr(goal, f) for f in fields if getattr(goal, f) is not None}


def export_side_values():
    pool = OptionPool()
    recs = []
    gt, fe, se, opt = "chaos_distortion", "attack_power", "ally_damage", "dps"
    goal = LastTurnGoal(min_will=4, min_chaos=5)
    turns = 9
    for mode, g, msc in [("side", goal, 0),
                         ("will_chaos", goal, 0),
                         ("grade_only", LastTurnGoal(), 0)]:
        t = SideValueTable(g, turns, pool, gem_type=gt, optimize=opt,
                           min_side_coeff=msc, value_mode=mode)
        for w, c, f, s in [(1, 1, 1, 1), (5, 5, 3, 2), (4, 5, 5, 5)]:
            st = GemState(will=w, chaos=c, first=f, second=s,
                          first_effect=fe, second_effect=se)
            for tl in (1, 3, turns):
                offers = _offers(pool, st, turns - tl + 1, tl)
                recs.append({"inputs": {"mode": mode, "gem_type": gt,
                    "first_effect": fe, "second_effect": se, "optimize": opt,
                    "goal": _goal_dict(g), "min_side_coeff": msc,
                    "state": [w, c, f, s], "turns_left": tl,
                    "offers": [o.key for o in offers]},
                  "expected": {"relic_coeff": t.relic_coeff,
                    "ancient_coeff": t.ancient_coeff,
                    "gem_value": t.gem_value(st), "lookup": t.lookup(st, tl),
                    "evac": t.expected_value_after_click(st, offers, max(0, tl - 1))}})
    # Reroll-dimension records (exercise the reroll-aware display value table).
    gt2, fe2, se2, opt2 = "order_stability", "additional_damage", "attack_power", "dps"
    goal2 = LastTurnGoal(min_total_will_chaos=8)
    msc2 = 2000
    mr2 = 3
    t2 = SideValueTable(goal2, turns, pool, gem_type=gt2, optimize=opt2,
                        min_side_coeff=msc2, value_mode="side", max_rerolls=mr2)
    for w, c, f, s in [(1, 1, 1, 1), (2, 1, 2, 1), (4, 4, 3, 2)]:
        st = GemState(will=w, chaos=c, first=f, second=s,
                      first_effect=fe2, second_effect=se2)
        for tl in (3, turns):
            offers = _offers(pool, st, turns - tl + 1, tl)
            for r in (0, 2, 3):
                recs.append({"inputs": {"mode": "side", "gem_type": gt2,
                    "first_effect": fe2, "second_effect": se2, "optimize": opt2,
                    "goal": _goal_dict(goal2), "min_side_coeff": msc2,
                    "max_rerolls": mr2, "rerolls": r,
                    "state": [w, c, f, s], "turns_left": tl,
                    "offers": [o.key for o in offers]},
                  "expected": {"relic_coeff": t2.relic_coeff,
                    "ancient_coeff": t2.ancient_coeff,
                    "gem_value": t2.gem_value(st),
                    "lookup": t2.lookup(st, tl, rerolls=r),
                    "evac": t2.expected_value_after_click(st, offers, max(0, tl - 1), rerolls=r)}})
    dump("side_values", recs)


# ---------------------------------------------------------------------------
# Step 6: export_decisions
# ---------------------------------------------------------------------------

def build_ctx(gt, fe, se, opt, g, rarity, *, relic_coeff=None, ancient_coeff=None,
              relic_thr=0.0, force_reroll=0, min_side_coeff=0,
              endgame_risk=None, ignore_side=False, extra_ticket=None):
    pool = OptionPool()
    goal = LastTurnGoal(**g)
    turns = RARITY_TURNS[rarity]
    gra = False  # goal_reroll not exercised in Plan 1
    mr = dp_max_rerolls(rarity, extra_ticket, relic_thr, gra)
    scf, scs = side_coeffs(AstroGem(gt, fe, se, opt))
    roll = GoalProbabilityTable(goal, turns, pool, side_coeff_first=scf,
        side_coeff_second=scs, min_side_coeff=min_side_coeff, early_finish=True,
        max_rerolls=mr, effect_aware=True, gem_type=gt, optimize=opt)
    reset = GoalProbabilityTable(goal, turns, pool, side_coeff_first=scf,
        side_coeff_second=scs, min_side_coeff=min_side_coeff, early_finish=True,
        effect_aware=True, gem_type=gt, optimize=opt)
    relic = GoalProbabilityTable(LastTurnGoal(min_total=16), turns, pool,
        early_finish=False, max_rerolls=mr)
    svt = SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
        min_side_coeff=min_side_coeff, relic_coeff=relic_coeff,
        ancient_coeff=ancient_coeff,
        value_mode=("will_chaos" if ignore_side else "side"))
    gvt = SideValueTable(LastTurnGoal(), turns, pool, gem_type=gt, optimize=opt,
        min_side_coeff=0, relic_coeff=relic_coeff, ancient_coeff=ancient_coeff,
        value_mode=("grade_only" if ignore_side else "side"))
    mvt = (SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
        min_side_coeff=min_side_coeff, relic_coeff=relic_coeff,
        ancient_coeff=ancient_coeff, value_mode="side") if ignore_side else None)
    ctx = D.DecisionContext(goal=goal, pool=pool, optimize=opt, bis_only=False,
        min_side_coeff=min_side_coeff, prob_reset_threshold=0.0,
        relic_reroll_threshold=relic_thr, force_reroll_no_progress=force_reroll,
        turns_total=turns, base_rerolls=mr, p_fresh=reset.lookup(
            GemState(first_effect=fe, second_effect=se), turns),
        prob_table=roll, reset_prob_table=reset, relic_prob_table=relic,
        gem_type=gt, force_reroll_active=False, confirm_active=False,
        confirm_min_coeff=0, endgame_risk=endgame_risk, side_value_table=svt,
        grade_value_table=gvt, maxed_value_table=mvt)
    return ctx, pool, fe, se


def export_decisions():
    recs = []
    configs = [
        dict(gt="chaos_distortion", fe="attack_power", se="ally_damage",
             opt="dps", g={"min_will": 4, "min_chaos": 5}, rarity="epic"),
        dict(gt="order_stability", fe="additional_damage", se="brand_power",
             opt="dps", g={"min_total_will_chaos": 8}, rarity="rare",
             relic_thr=0.3),
        dict(gt="chaos_distortion", fe="attack_power", se="ally_damage",
             opt="dps", g={"min_will": 5, "min_chaos": 5}, rarity="epic",
             ignore_side=True),
    ]
    for cfg in configs:
        ctx, pool, fe, se = build_ctx(**cfg)
        for w, c, f, s in [(1, 1, 1, 1), (4, 5, 3, 2), (5, 5, 5, 5), (4, 4, 1, 1), (5, 5, 2, 2)]:
            st = GemState(will=w, chaos=c, first=f, second=s,
                          first_effect=fe, second_effect=se)
            for turn in (1, 2, ctx.turns_total):
                tl = ctx.turns_total - turn + 1
                for r in (0, 1):
                    for reset_av in (False, True):
                        offers = _offers(pool, st, turn, tl)
                        st.rerolls = r
                        ti = D.TurnInput(state=st.clone(), offers=offers,
                            turn=turn, turns_left=tl, rerolls=r,
                            reset_available=reset_av)
                        d = D.decide_post_roll(ctx, ti)
                        recs.append({"inputs": {**{k: cfg[k] for k in
                            ("gt", "fe", "se", "opt", "g", "rarity")},
                            "config": {k: cfg[k] for k in cfg if k not in
                                ("gt", "fe", "se", "opt", "g", "rarity")},
                            "turns_total": ctx.turns_total,
                            "dp_max_rerolls": ctx.base_rerolls,
                            "state": [w, c, f, s], "turn": turn, "turns_left": tl,
                            "rerolls": r, "reset_available": reset_av,
                            "offers": [o.key for o in offers]},
                          "expected": {"action": d.action.value,
                            "branch": d.branch}})
    dump("decisions", recs)


# ---------------------------------------------------------------------------
# Step 7: export_actions
# ---------------------------------------------------------------------------

def export_actions():
    """Export per-action (process/reroll/reset) metrics for a handful of cases.

    Mirrors the TS actions projection in advise():
      - process: expected outcome of clicking — a uniformly-random offer is
        applied (simulator.py rng.choice), so this is the AVERAGE over the
        offers (expected_prob_after_click / expected_value_after_click on the
        full offer set), not the best single offer.
      - reroll: lookup(state, turnsLeft, rerolls-1); eValue = lookup(state, turnsLeft)
        (unchanged because reroll doesn't change state/turnsLeft).
      - reset: lookup(fresh_state, turns_total, base_rerolls) across all tables.
    """
    pool = OptionPool()
    recs = []
    cases = [
        dict(gt="chaos_distortion", fe="attack_power", se="ally_damage",
             opt="dps", g={"min_will": 4, "min_chaos": 5}, rarity="epic"),
        dict(gt="order_stability", fe="additional_damage", se="brand_power",
             opt="dps", g={"min_total_will_chaos": 8}, rarity="rare"),
        dict(gt="chaos_distortion", fe="attack_power", se="boss_damage",
             opt="dps", g={"min_will": 4, "min_chaos": 4}, rarity="epic"),
    ]
    for cfg in cases:
        gt, fe, se, opt, g, rarity = cfg["gt"], cfg["fe"], cfg["se"], cfg["opt"], cfg["g"], cfg["rarity"]
        goal = LastTurnGoal(**g)
        turns = RARITY_TURNS[rarity]
        mr = dp_max_rerolls(rarity, None, 0.0, False)
        base_rerolls = mr  # same as dp_max_rerolls when no relic_thr

        roll = GoalProbabilityTable(goal, turns, pool, early_finish=True,
            max_rerolls=mr, effect_aware=True, gem_type=gt, optimize=opt)
        relic = GoalProbabilityTable(LastTurnGoal(min_total=16), turns, pool,
            early_finish=False, max_rerolls=mr)
        anc = GoalProbabilityTable(LastTurnGoal(min_total=19), turns, pool,
            early_finish=False, max_rerolls=mr)
        svt = SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
            min_side_coeff=0, max_rerolls=mr)
        fresh = GemState(first_effect=fe, second_effect=se)

        for w, c, f, s in [(2, 2, 2, 1), (4, 4, 3, 2), (5, 5, 3, 2)]:
            st = GemState(will=w, chaos=c, first=f, second=s,
                          first_effect=fe, second_effect=se)
            for turn, tl in [(3, turns - 2), (turns, 1)]:
                for r in (0, 1, min(mr, 2)):
                    offers = _offers(pool, st, turn, tl)
                    offer_keys = [o.key for o in offers]

                    tl_after = max(0, tl - 1)

                    # process = expected outcome of clicking (a uniformly-random
                    # offer is applied) → average over the offers, not the best.
                    if offers:
                        process_rec = {
                            "pGoal": roll.expected_prob_after_click(st, offers, tl_after, rerolls=r),
                            "pRelic": relic.expected_prob_after_click(st, offers, tl_after, rerolls=r),
                            "pAncient": anc.expected_prob_after_click(st, offers, tl_after, rerolls=r),
                            "eValue": svt.expected_value_after_click(st, offers, tl_after, rerolls=r),
                        }
                    else:
                        process_rec = None

                    # reroll = lookup(state, turnsLeft, rerolls-1)
                    if r > 0:
                        reroll_rec = {
                            "pGoal": roll.lookup(st, tl, rerolls=r - 1),
                            "pRelic": relic.lookup(st, tl, rerolls=r - 1),
                            "pAncient": anc.lookup(st, tl, rerolls=r - 1),
                            "eValue": svt.lookup(st, tl, rerolls=r - 1),
                        }
                    else:
                        reroll_rec = None

                    # reset = lookup(fresh, turns_total, base_rerolls)
                    reset_rec = {
                        "pGoal": roll.lookup(fresh, turns, rerolls=base_rerolls),
                        "pRelic": relic.lookup(fresh, turns, rerolls=base_rerolls),
                        "pAncient": anc.lookup(fresh, turns, rerolls=base_rerolls),
                        "eValue": svt.lookup(fresh, turns, rerolls=base_rerolls),
                    }

                    recs.append({"inputs": {
                        "gt": gt, "fe": fe, "se": se, "opt": opt, "goal": g, "rarity": rarity,
                        "turns_total": turns, "base_rerolls": base_rerolls,
                        "state": [w, c, f, s], "turn": turn, "turns_left": tl,
                        "rerolls": r, "offers": offer_keys},
                      "expected": {
                        "process": process_rec,
                        "reroll": reroll_rec,
                        "reset": reset_rec}})
    dump("actions", recs)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    export_satisfied()
    export_feasibility()
    export_pool()
    export_dp_lookups()
    export_side_values()
    export_decisions()
    export_actions()
