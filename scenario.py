"""Run a specific game scenario and print how the simulator would behave.

Usage:
    source .venv/Scripts/activate
    python scenario.py
"""
from tests.test_scenarios import ScenarioHelper, LastTurnGoal

result = ScenarioHelper.evaluate(
    gem_type="order_solidity",
    first_effect="additional_damage",
    second_effect="attack_power",
    optimize="dps",
    will=5, chaos=5, first=3, second=3,
    rerolls=1,
    rarity="epic",
    turn=9,
    offer_keys=("second-1", "first+1", "first-1", "chaos-1"),
    goal=LastTurnGoal(min_will=4, min_chaos=4),
    early_finish_coeff=700,
)

ScenarioHelper.print_result(result)
