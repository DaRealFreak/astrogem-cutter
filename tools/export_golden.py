"""Export golden vectors for the TS engine parity suite.

Run from repo root:  python tools/export_golden.py
Writes web/tests/fixtures/*.json. Commit the output.
"""
from __future__ import annotations
import itertools
import json
import os
import random
import subprocess
import sys

# Run as `python tools/export_golden.py` from the project root:
# add the project root to sys.path so `arkgrid` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from arkgrid.constants import (
    DPS_COEFF, SUPPORT_COEFF, DPS_EFFECTS, SUPPORT_EFFECTS, GEM_TYPES,
)
from arkgrid.models import LastTurnGoal, GemState, AstroGem
from arkgrid.pool import OptionPool
from arkgrid.probability import (
    GoalProbabilityTable, RealisedSuccessTable, SideValueTable,
    _hand_moments, hand_atoms, hand_context,
)
from arkgrid.simulator import REALISED_FRESH_STEP
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
    # High floor: only reachable by changing BOTH side effects.
    {"min_will": 1, "min_side_coeff": 6000},
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
                    # Side-coeff arrangements (only matter under a floor):
                    # on-target pair, off-target pair needing two changes,
                    # and an effect that can migrate into the levelled slot.
                    arrangements = [(1000, 700, (1500, 0))]
                    if g.get("min_side_coeff", 0) > 0:
                        arrangements += [(0, 0, (1000, 700)),
                                         (1000, 0, (700, 0))]
                    for scf, scs, dests in arrangements:
                        kw = dict(min_side_coeff=g.get("min_side_coeff", 0),
                                  side_coeff_first=scf, side_coeff_second=scs,
                                  change_dest_coeffs=dests)
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
         {"min_will": 4, "min_chaos": 5}, "epic", 0),
        ("order_stability", "additional_damage", "brand_power", "dps",
         {"min_total_will_chaos": 8}, "rare", 0),
        # Off-target starting effects + side-coeff floor: pins the
        # effect-aware min_side_coeff pricing (change_effect rescue).
        ("chaos_distortion", "ally_damage", "ally_attack", "dps",
         {"min_will": 4, "min_chaos": 4}, "epic", 2000),
    ]
    for gt, fe, se, opt, g, rarity, msc in cases:
        goal = LastTurnGoal(**g)
        turns = RARITY_TURNS[rarity]
        mr = dp_max_rerolls(rarity, None, 0.0, False)
        scf, scs = side_coeffs(AstroGem(gt, fe, se, opt))
        roll = GoalProbabilityTable(goal, turns, pool, early_finish=True,
            min_side_coeff=msc,
            max_rerolls=mr, effect_aware=True, gem_type=gt, optimize=opt)
        reset = GoalProbabilityTable(goal, turns, pool, early_finish=True,
            min_side_coeff=msc,
            effect_aware=True, gem_type=gt, optimize=opt)
        relic = GoalProbabilityTable(LastTurnGoal(min_total=16), turns, pool,
            early_finish=True, max_rerolls=mr)
        anc = GoalProbabilityTable(LastTurnGoal(min_total=19), turns, pool,
            early_finish=True, max_rerolls=mr)
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
                        "min_side_coeff": msc,
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
    # Policy-evaluation records (will_chaos policy, side display value) — the
    # web display eValue under --ignore-side-node-values. order_fortitude is
    # the user's order_solidity gem (ally_attack + boss_damage); exercise the
    # bare and min_side_coeff-floored variants.
    gt3, fe3, se3, opt3 = "order_fortitude", "ally_attack", "boss_damage", "dps"
    goal3 = LastTurnGoal(min_total_will_chaos=8)
    for msc3 in (0, 2000):
        t3 = SideValueTable(goal3, turns, pool, gem_type=gt3, optimize=opt3,
                            min_side_coeff=msc3, value_mode="side",
                            policy_value_mode="will_chaos")
        for w, c, f, s in [(1, 1, 1, 1), (4, 4, 1, 1), (5, 5, 3, 2)]:
            st = GemState(will=w, chaos=c, first=f, second=s,
                          first_effect=fe3, second_effect=se3)
            for tl in (1, 5, turns):
                offers = _offers(pool, st, turns - tl + 1, tl)
                recs.append({"inputs": {"mode": "side", "gem_type": gt3,
                    "first_effect": fe3, "second_effect": se3, "optimize": opt3,
                    "goal": _goal_dict(goal3), "min_side_coeff": msc3,
                    "policy_value_mode": "will_chaos",
                    "state": [w, c, f, s], "turns_left": tl,
                    "offers": [o.key for o in offers]},
                  "expected": {"relic_coeff": t3.relic_coeff,
                    "ancient_coeff": t3.ancient_coeff,
                    "gem_value": t3.gem_value(st), "lookup": t3.lookup(st, tl),
                    "evac": t3.expected_value_after_click(st, offers, max(0, tl - 1))}})
    dump("side_values", recs)


# ---------------------------------------------------------------------------
# Step 6: export_decisions
# ---------------------------------------------------------------------------

def build_ctx(gt, fe, se, opt, g, rarity, *, relic_coeff=None, ancient_coeff=None,
              relic_thr=0.0, force_reroll=0, min_side_coeff=0,
              endgame_risk=None, ignore_side=False, extra_ticket=None,
              reset_keep_grade=None, ticket_min_goal_gain=0.0,
              ticket_min_value_gain=0.0):
    pool = OptionPool()
    goal = LastTurnGoal(**g)
    turns = RARITY_TURNS[rarity]
    gra = False  # goal_reroll not exercised in Plan 1
    mr = dp_max_rerolls(rarity, extra_ticket, relic_thr, gra)
    scf, scs = side_coeffs(AstroGem(gt, fe, se, opt))
    roll = GoalProbabilityTable(goal, turns, pool, side_coeff_first=scf,
        side_coeff_second=scs, min_side_coeff=min_side_coeff, early_finish=True,
        max_rerolls=mr, effect_aware=True, gem_type=gt, optimize=opt)
    relic = GoalProbabilityTable(LastTurnGoal(min_total=16), turns, pool,
        early_finish=True, max_rerolls=mr)
    svt = SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
        min_side_coeff=min_side_coeff, relic_coeff=relic_coeff,
        ancient_coeff=ancient_coeff,
        value_mode=("will_chaos" if ignore_side else "side"), max_rerolls=mr)
    # Dead-goal table is always grade_only: a goal-missing gem won't be
    # equipped, so only its fusion grade matters (mirrors simulator/automation).
    gvt = SideValueTable(LastTurnGoal(), turns, pool, gem_type=gt, optimize=opt,
        min_side_coeff=0, relic_coeff=relic_coeff, ancient_coeff=ancient_coeff,
        value_mode="grade_only", max_rerolls=mr)
    mvt = (SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
        min_side_coeff=min_side_coeff, relic_coeff=relic_coeff,
        ancient_coeff=ancient_coeff, value_mode="side", max_rerolls=mr)
        if ignore_side else None)
    # ctx.base_rerolls mirrors the simulator/web semantics: rarity free
    # rerolls + the owned reroll ticket — WITHOUT the +1 DP-sizing headroom
    # the tables get for the relic/goal ticket look-ahead (`mr`). The web
    # reset row reads ctx.baseRerolls as the fresh-start budget.
    base_rerolls = RARITY_REROLLS[rarity] + (1 if extra_ticket is not False else 0)
    ctx = D.DecisionContext(goal=goal, pool=pool, optimize=opt, bis_only=False,
        min_side_coeff=min_side_coeff, prob_reset_threshold=0.0,
        relic_reroll_threshold=relic_thr, force_reroll_no_progress=force_reroll,
        turns_total=turns, base_rerolls=base_rerolls,
        # Fresh-start value: reroll-aware table, with the rerolls a fresh
        # process is granted (mirrors GemSimulator.fresh_start_prob).
        p_fresh=roll.lookup(
            GemState(first_effect=fe, second_effect=se), turns,
            rerolls=RARITY_REROLLS[rarity] + (1 if extra_ticket is True else 0)),
        prob_table=roll, relic_prob_table=relic,
        gem_type=gt, force_reroll_active=False, confirm_active=False,
        confirm_min_coeff=0, endgame_risk=endgame_risk, side_value_table=svt,
        grade_value_table=gvt, maxed_value_table=mvt,
        reset_keep_points={None: 0, "relic": 16, "ancient": 19}[reset_keep_grade],
        ticket_min_goal_gain=ticket_min_goal_gain,
        ticket_min_value_gain=ticket_min_value_gain)
    return ctx, pool, fe, se, mr


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
        # Off-target starting effects + side-coeff floor: the effect-aware
        # goal tables must keep pricing the floor (change_effect rescue) —
        # pins the web dpMinSideCoeff guard fix numerically.
        dict(gt="chaos_distortion", fe="ally_damage", se="ally_attack",
             opt="dps", g={"min_will": 4, "min_chaos": 4}, rarity="epic",
             min_side_coeff=2000),
        # Opt-in spending gates: the reroll-ticket spend gate (goal and value
        # bars) and reset protection for a gem already holding relic grade.
        dict(gt="order_immutability", fe="boss_damage", se="additional_damage",
             opt="dps", g={"min_will": 4, "min_chaos": 5}, rarity="epic",
             ticket_min_goal_gain=0.01, ticket_min_value_gain=200,
             reset_keep_grade="relic"),
    ]
    for cfg in configs:
        ctx, pool, fe, se, mr = build_ctx(**cfg)
        gated = "ticket_min_goal_gain" in cfg
        states = [(1, 1, 1, 1), (4, 5, 3, 2), (5, 5, 5, 5), (4, 4, 1, 1), (5, 5, 2, 2)]
        if gated:
            # mid-game goal chase, goal-met value chase, dead goal at relic
            # grade, dead goal below it
            states += [(2, 3, 2, 2), (3, 4, 2, 3), (3, 5, 4, 5), (3, 5, 3, 3),
                       (4, 5, 2, 2)]
        for w, c, f, s in states:
            st = GemState(will=w, chaos=c, first=f, second=s,
                          first_effect=fe, second_effect=se)
            turns = (1, 2, 6, ctx.turns_total) if gated else (1, 2, ctx.turns_total)
            for turn in turns:
                tl = ctx.turns_total - turn + 1
                for r in (0, 1):
                    for reset_av in (False, True):
                        # The ticket is the last reroll of the budget: only a
                        # gated config exercises it.
                        for lent in ((False, True) if gated and r == 1 else (False,)):
                            hands = [_offers(pool, st, turn, tl)]
                            if gated:
                                elig = [o for o in pool.pool
                                        if pool.eligible(o, st, turn, tl)]
                                hands.append(elig[-4:])
                            for offers in hands:
                                st.rerolls = r
                                ti = D.TurnInput(state=st.clone(), offers=offers,
                                    turn=turn, turns_left=tl, rerolls=r,
                                    reset_available=reset_av, ticket_lent=lent)
                                d = D.decide_post_roll(ctx, ti)
                                recs.append({"inputs": {**{k: cfg[k] for k in
                                    ("gt", "fe", "se", "opt", "g", "rarity")},
                                    "config": {k: cfg[k] for k in cfg if k not in
                                        ("gt", "fe", "se", "opt", "g", "rarity")},
                                    "turns_total": ctx.turns_total,
                                    "dp_max_rerolls": mr,
                                    "state": [w, c, f, s], "turn": turn, "turns_left": tl,
                                    "rerolls": r, "reset_available": reset_av,
                                    "ticket_lent": lent,
                                    "offers": [o.key for o in offers]},
                                  "expected": {"action": d.action.value,
                                    "branch": d.branch,
                                    "ticket_held": bool(d.metrics.get("ticket_held")),
                                    "reset_kept": bool(d.metrics.get("reset_kept"))}})
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

    `pBot` (realised success of the advisor's own policy) reads the decision
    value table's `RealisedSuccessTable`: process/reroll use the reset-aware
    table while the reset is available (`pBot`) and the plain one otherwise
    (`pBotNoReset`); the reset row is the plain table at a fresh start.
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
        # ignore_side: the displayed eValue is a POLICY EVALUATION of the
        # will+chaos policy (flat, coupled DP) — pins the web
        # _displayValueTable semantics under --ignore-side-node-values.
        dict(gt="order_fortitude", fe="ally_attack", se="boss_damage",
             opt="dps", g={"min_total_will_chaos": 8}, rarity="epic",
             ignore_side=True),
    ]
    for cfg in cases:
        gt, fe, se, opt, g, rarity = cfg["gt"], cfg["fe"], cfg["se"], cfg["opt"], cfg["g"], cfg["rarity"]
        ignore_side = cfg.get("ignore_side", False)
        goal = LastTurnGoal(**g)
        turns = RARITY_TURNS[rarity]
        mr = dp_max_rerolls(rarity, None, 0.0, False)
        base_rerolls = mr  # same as dp_max_rerolls when no relic_thr

        roll = GoalProbabilityTable(goal, turns, pool, early_finish=True,
            max_rerolls=mr, effect_aware=True, gem_type=gt, optimize=opt)
        relic = GoalProbabilityTable(LastTurnGoal(min_total=16), turns, pool,
            early_finish=True, max_rerolls=mr)
        anc = GoalProbabilityTable(LastTurnGoal(min_total=19), turns, pool,
            early_finish=True, max_rerolls=mr)
        # eValue rows mirror the web _displayValueTable: reroll-aware "side"
        # value table normally; a flat will_chaos policy evaluation under
        # ignore_side (the realistic expected coefficient).
        if ignore_side:
            svt = SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
                min_side_coeff=0, value_mode="side",
                policy_value_mode="will_chaos")
        else:
            svt = SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
                min_side_coeff=0, max_rerolls=mr)
        fresh = GemState(first_effect=fe, second_effect=se)
        # Realised success follows the DECISION value table (will_chaos under
        # ignore_side), not the displayed one. No ticket enabler is
        # configured in these cases, so a fresh process starts on the
        # rarity's free rerolls.
        dec_svt = (SideValueTable(goal, turns, pool, gem_type=gt, optimize=opt,
                                  min_side_coeff=0, value_mode="will_chaos",
                                  max_rerolls=mr) if ignore_side else svt)
        bot_plain, bot_reset, _fresh, bot_fresh = _realised_pair(
            dec_svt, fresh, turns, RARITY_REROLLS[rarity])

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
                            "pBot": bot_reset.expected_after_click(st, offers, tl_after, rerolls=r),
                            "pBotNoReset": bot_plain.expected_after_click(st, offers, tl_after, rerolls=r),
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
                            "pBot": bot_reset.lookup(st, tl, rerolls=r - 1),
                            "pBotNoReset": bot_plain.lookup(st, tl, rerolls=r - 1),
                        }
                    else:
                        reroll_rec = None

                    # reset = lookup(fresh, turns_total, base_rerolls)
                    reset_rec = {
                        "pGoal": roll.lookup(fresh, turns, rerolls=base_rerolls),
                        "pRelic": relic.lookup(fresh, turns, rerolls=base_rerolls),
                        "pAncient": anc.lookup(fresh, turns, rerolls=base_rerolls),
                        "eValue": svt.lookup(fresh, turns, rerolls=base_rerolls),
                        "pBot": bot_fresh,
                    }

                    recs.append({"inputs": {
                        "gt": gt, "fe": fe, "se": se, "opt": opt, "goal": g, "rarity": rarity,
                        "ignore_side": ignore_side,
                        "turns_total": turns, "base_rerolls": base_rerolls,
                        "state": [w, c, f, s], "turn": turn, "turns_left": tl,
                        "rerolls": r, "offers": offer_keys},
                      "expected": {
                        "process": process_rec,
                        "reroll": reroll_rec,
                        "reset": reset_rec}})
    dump("actions", recs)


# ---------------------------------------------------------------------------
# Realised success (P(bot)): hand atoms, table lookups, per-hand average
# ---------------------------------------------------------------------------

def _realised_pair(svt, start, turns, fresh_rerolls, endgame_risk=None):
    """(plain, reset-aware, fresh) — mirrors simulator.realised_tables."""
    plain = RealisedSuccessTable(svt, endgame_risk=endgame_risk)
    exact = plain.lookup(start, turns, rerolls=fresh_rerolls)
    fresh = round(exact / REALISED_FRESH_STEP) * REALISED_FRESH_STEP
    return plain, RealisedSuccessTable(svt, endgame_risk=endgame_risk,
                                       fresh=fresh), fresh, exact


def export_realised():
    pool = OptionPool()
    recs = []
    rng = random.Random(20261116)

    # 1. The hand-mean distribution behind every keep-vs-alternative choice.
    hand_states = [
        (GemState(will=2, chaos=3, first=1, second=4), 3, 7),
        (GemState(will=5, chaos=5, first=5, second=2), 9, 1),
        (GemState(will=1, chaos=1, first=1, second=1, cost_ratio=100), 2, 8),
        (GemState(will=5, chaos=5, first=5, second=5), 5, 5),
    ]
    for st, turn, tl in hand_states:
        elig = [o for o in pool.pool if pool.eligible(o, st, turn, tl)]
        weights = [o.weight for o in elig]
        ctx = hand_context(weights)
        for kind in ("smooth", "lumpy", "hit_or_miss", "single_out",
                     "constant"):
            if kind == "smooth":
                posts = [rng.random() for _ in elig]
            elif kind == "lumpy":
                posts = [rng.random() ** 6 for _ in elig]
            elif kind == "hit_or_miss":
                posts = [float(rng.random() < 0.25) for _ in elig]
            elif kind == "single_out":
                posts = [0.0] * len(elig)
                posts[rng.randrange(len(elig))] = 1.0
            else:
                posts = [0.375] * len(elig)
            mom = _hand_moments(ctx, posts)
            recs.append({"inputs": {"kind": "atoms", "case": kind,
                                    "weights": weights, "posts": posts},
                         "expected": {"moments": list(mom),
                                      "atoms": [list(a)
                                                for a in hand_atoms(*mom)]}})

    # 2. Tables: auto grade gate, an explicit finish margin, and the
    #    will_chaos value mode (holds the will/chaos cap).
    cases = [
        dict(gt="order_immutability", fe="boss_damage", se="additional_damage",
             opt="dps", g={"min_will": 4, "min_chaos": 5}, msc=2000, turns=9,
             mr=3, fresh_rerolls=2, endgame_risk=None, mode="side"),
        dict(gt="order_stability", fe="additional_damage", se="attack_power",
             opt="dps", g={"min_total_will_chaos": 8}, msc=0, turns=7,
             mr=2, fresh_rerolls=1, endgame_risk=500.0, mode="side"),
        dict(gt="order_fortitude", fe="ally_attack", se="boss_damage",
             opt="dps", g={"min_total_will_chaos": 8}, msc=0, turns=9,
             mr=3, fresh_rerolls=2, endgame_risk=None, mode="will_chaos"),
    ]
    for cfg in cases:
        gt, turns, mr = cfg["gt"], cfg["turns"], cfg["mr"]
        svt = SideValueTable(LastTurnGoal(**cfg["g"]), turns, pool, gem_type=gt,
                             optimize=cfg["opt"], min_side_coeff=cfg["msc"],
                             value_mode=cfg["mode"], max_rerolls=mr)
        start = GemState(first_effect=cfg["fe"], second_effect=cfg["se"])
        plain, with_reset, fresh, _exact = _realised_pair(
            svt, start, turns, cfg["fresh_rerolls"], cfg["endgame_risk"])
        effects = GEM_TYPES[gt]
        samples = [(start, turns, cfg["fresh_rerolls"])]
        for i in range(44):
            lo = 3 if i % 2 else 1     # half the samples near the goal
            fe, se = rng.sample(effects, 2)
            samples.append((GemState(
                will=rng.randint(lo, 5), chaos=rng.randint(lo, 5),
                first=rng.randint(1, 5), second=rng.randint(1, 5),
                cost_ratio=rng.choice((0, 0, 100)),
                first_effect=fe, second_effect=se),
                rng.randint(0, turns), rng.randint(0, mr)))
        for st, tl, r in samples:
            offers = []
            if tl >= 1:
                elig = [o for o in pool.pool
                        if pool.eligible(o, st, turns - tl + 1, tl)]
                if len(elig) >= 4:
                    offers = rng.sample(elig, 4)
            for table, fresh_val in ((plain, None), (with_reset, fresh)):
                recs.append({"inputs": {
                    "kind": "table", "gem_type": gt, "optimize": cfg["opt"],
                    "goal": cfg["g"], "min_side_coeff": cfg["msc"],
                    "turns": turns, "max_rerolls": mr, "mode": cfg["mode"],
                    "endgame_risk": cfg["endgame_risk"], "fresh": fresh_val,
                    "state": [st.will, st.chaos, st.first, st.second],
                    "cost_ratio": st.cost_ratio,
                    "first_effect": st.first_effect,
                    "second_effect": st.second_effect,
                    "turns_left": tl, "rerolls": r,
                    "offers": [o.key for o in offers]},
                  "expected": {
                    "lookup": table.lookup(st, tl, rerolls=r),
                    "after_click": (table.expected_after_click(
                        st, offers, tl - 1, rerolls=r) if offers else None)}})
    dump("realised", recs)


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
    export_realised()
