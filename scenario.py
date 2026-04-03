"""Run a specific game scenario and print how the simulator would behave.

Usage:
    source .venv/Scripts/activate
    python scenario.py
"""
from tests.test_scenarios import ScenarioHelper, LastTurnGoal

result = ScenarioHelper.evaluate(
    gem_type="order_immutability",
    first_effect="boss_damage",
    second_effect="brand_power",
    optimize="dps",
    will=4, chaos=5, first=1, second=1,
    rerolls=2,
    rarity="epic",
    turn=8,
    offer_keys=("will-1", "chaos-1", "first+3", "cost-100"),
    goal=LastTurnGoal(min_will=4, min_chaos=5),
    min_side_coeff=3000,
    early_finish_coeff=700,
)

ScenarioHelper.print_result(result)
