"""Run a specific game scenario and print how the simulator would behave.

Usage:
    source .venv/Scripts/activate
    python scenario.py
"""
from arkgrid import GemState, GoalProbabilityTable, OptionPool
from tests.test_scenarios import ScenarioHelper, LastTurnGoal

# Reproduces the Turn 2 state from a --min-side-coeff 2000 --optimize dps
# auto-run where the gem rolled with two support effects (ally_damage +
# ally_attack). Under the standard DP, min_side_coeff is unreachable so
# every offer scores 0%, triggering an immediate reset. The effect-aware
# DP models change_effect transitions and prices in the rescue path.

GEM_TYPE = "order_fortitude"  # attack_power, boss_damage, ally_damage, ally_attack
FIRST = "ally_damage"
SECOND = "ally_attack"
GOAL = LastTurnGoal(min_will=4, min_chaos=4)
MIN_SIDE_COEFF = 2000
TURNS_TOTAL = 9
TURN = 2
RERolls = 2
OFFER_KEYS = ("first+1", "change_first_effect", "will+1", "view+2")

result = ScenarioHelper.evaluate(
    gem_type=GEM_TYPE,
    first_effect=FIRST,
    second_effect=SECOND,
    optimize="dps",
    will=1, chaos=1, first=1, second=1,
    rerolls=RERolls,
    rarity="epic",
    turn=TURN,
    offer_keys=OFFER_KEYS,
    goal=GOAL,
    min_side_coeff=MIN_SIDE_COEFF,
)

ScenarioHelper.print_result(result)

# ----- Effect-aware DP comparison -----
pool = OptionPool()
state = GemState(
    will=1, chaos=1, first=1, second=1,
    first_effect=FIRST, second_effect=SECOND,
)
turns_left = TURNS_TOTAL - TURN + 1

std = GoalProbabilityTable(
    GOAL, TURNS_TOTAL, pool,
    side_coeff_first=0, side_coeff_second=0,
    min_side_coeff=MIN_SIDE_COEFF,
    max_rerolls=3,
)
ea = GoalProbabilityTable(
    GOAL, TURNS_TOTAL, pool,
    min_side_coeff=MIN_SIDE_COEFF,
    effect_aware=True, gem_type=GEM_TYPE, optimize="dps",
    max_rerolls=3,
)

print("--- DP comparison (min_side_coeff enforced) ---")
print(f"Standard DP   : {std.lookup(state, turns_left, rerolls=RERolls):.4f}  "
      f"(side coeffs forced to 0 -> unreachable)")
print(f"Effect-aware  : {ea.lookup(state, turns_left, rerolls=RERolls):.4f}  "
      f"(change_effect rescue modeled)")

print("\nPer-offer effect-aware lookup:")
offers = ScenarioHelper.make_offers(*OFFER_KEYS)
fi = ea._effect_tuple.index(FIRST)
si = ea._effect_tuple.index(SECOND)
for o in offers:
    nw = min(5, max(1, state.will + o.delta)) if o.kind == "will" else state.will
    nc = min(5, max(1, state.chaos + o.delta)) if o.kind == "chaos" else state.chaos
    nf = min(5, max(1, state.first + o.delta)) if o.kind == "first" else state.first
    ns = min(5, max(1, state.second + o.delta)) if o.kind == "second" else state.second
    vd = o.delta if o.kind == "view" else 0
    nr = min(3, RERolls + vd)
    if o.key == "change_first_effect":
        dests = ea._change_dests[(fi, si)]
        vals = [ea._dp_lookup_ea(nw, nc, nf, ns, d, si, nr, turns_left - 1)
                for d in dests]
        avg = sum(vals) / len(vals)
        dest_names = [ea._effect_tuple[d] for d in dests]
        print(f"  {o.key:>22s} -> {avg:.4f}  (dests: {dest_names})")
    elif o.key == "change_second_effect":
        dests = ea._change_dests[(fi, si)]
        vals = [ea._dp_lookup_ea(nw, nc, nf, ns, fi, d, nr, turns_left - 1)
                for d in dests]
        avg = sum(vals) / len(vals)
        dest_names = [ea._effect_tuple[d] for d in dests]
        print(f"  {o.key:>22s} -> {avg:.4f}  (dests: {dest_names})")
    else:
        v = ea._dp_lookup_ea(nw, nc, nf, ns, fi, si, nr, turns_left - 1)
        print(f"  {o.key:>22s} -> {v:.4f}")
