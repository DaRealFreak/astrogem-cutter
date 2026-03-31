# Decision-making process

Each turn follows a fixed pipeline of checks and decisions. The simulator never looks ahead manually — it relies on a precomputed DP probability table and a heuristic reroll policy.

## Turn flow

```
For each turn:
  1. Pre-turn checks (can reset or fail before seeing offers)
  2. Generate 4 offers from the weighted pool
  3. Reroll decision (may spend rerolls to re-draw offers)
  4. Post-offer checks (can reset or fail after seeing final offers)
  5. Pick one of the 4 offers uniformly at random (25% each)
```

## Pre-turn checks

Before any offers are drawn, two checks run in order:

1. **Probability-based early reset** (soft, only when `--prob-reset-threshold` > 0): If the DP-estimated goal probability from the current state drops below the threshold and a reset ticket is available, reset immediately. This catches doomed runs before they waste more turns.

2. **Binary feasibility check** (hard): If the goal is mathematically unreachable (e.g. need will+6 but only 2 turns left), reset if a ticket is available, otherwise fail the run immediately.

## Offer generation and rerolls

The pool generates 4 unique offers via weighted sampling without replacement, drawn from 27 possible options matching [Smilegate's official rates](official_probability_info_en.md). Some options are excluded by turn constraints:
- **Turn 1**: view (reroll) options excluded
- **Last turn**: view and cost options excluded
- **Stat at cap (5)**: corresponding +N options excluded
- **Stat at floor (1)**: corresponding -1 option excluded

Rerolls are never used on turn 1 (since no prior state exists to judge). On subsequent turns, the **reroll policy** decides whether to spend a reroll based on the current offers. Rerolls re-draw all 4 offers from the pool.

## Reroll policy

The policy operates in three modes, selected by a **comfort signal**. The comfort signal is the DP-estimated probability of reaching the goal from the current state (falling back to binary feasibility fraction if no DP table is available). The `--side-threshold` parameter controls the boundary between comfortable and desperate modes.

### Forced rerolls (always, before mode selection)

- **Last turn, goal not met**: always reroll — nothing to lose.
- **No offer keeps goal feasible** (feasibility fraction = 0%): always reroll — every option would make the goal unreachable.

### Goal-met mode (goal already satisfied)

Activated when willpower and chaos already meet or exceed the goal targets. Focus shifts entirely to maximising total points via side-node upgrades.

Reroll if:
- Any offer contains a downgrade (will-1, chaos-1, first-1, second-1) **and** no big upgrade (+2/+3/+4) is available
- No offer provides any positive stat change or beneficial effect change

### Comfortable mode (comfort signal >= side threshold)

Activated when the goal probability is at or above the `--side-threshold` value (default 0.5). The policy values **both** goal upgrades and side-node upgrades, accepting any positive progress.

Reroll if:
- Any downgrade is present **and** no big upgrade (goal or side) compensates
- No useful upgrade exists at all (no goal upgrade, no side upgrade, no good effect change)

Side-node upgrades are filtered by `--optimize`: only effects matching the DPS or support target are valued. For example, with `--optimize dps`, upgrading a support-effect slot doesn't count as useful.

### Desperate mode (comfort signal < side threshold)

Activated when the goal probability drops below the threshold. The policy ignores side nodes entirely and focuses purely on willpower and chaos upgrades.

Reroll if:
- A goal downgrade (will-1 or chaos-1) is present **and** no big goal upgrade compensates
- No goal upgrade (will+N or chaos+N) exists in the offers

## Post-offer checks

After the final set of offers is determined (after all rerolls), two more checks run:

1. **Probability-based early reset** (soft, only when `--prob-reset-threshold` > 0): If the expected goal probability *after clicking* (averaged across all 4 offers) drops below the threshold, reset.

2. **Binary feasibility check** (hard): If no offer keeps the goal feasible (feasibility = 0%), reset if available, otherwise fail.

## Pick resolution

If all checks pass, one of the 4 offers is picked **uniformly at random** (25% each). The simulator does not choose the "best" offer — this models the in-game mechanic where you select a face-down option without knowing which is which.

## Effect changes

When a `change_first_effect` or `change_second_effect` option is picked, the simulator resolves it deterministically based on `--optimize`:
- Pick the available effect that belongs to the target set (DPS or support)
- Among equals, prefer higher priority (boss_damage > additional_damage > attack_power for DPS)

## Reset ticket

The reset ticket allows one full restart to initial state (will=1, chaos=1, first=1, second=1) if the run goes badly. It triggers on:
- Binary infeasibility (goal mathematically unreachable)
- Probability dropping below `--prob-reset-threshold`

After a reset, the run restarts from turn 1 with the same gem but fresh stats. The reset ticket can only be used once per run.

## DP probability table

A backward-induction probability table is precomputed once at startup (~20ms). It stores P(reach goal | will, chaos, first, second, turns_left) for all 6,250 possible states. This table drives:
- The comfort signal for the reroll policy (comfortable vs desperate mode)
- Probability-based early resets (when `--prob-reset-threshold` > 0)
- The `P(goal)` and `P(click)` values shown in `sim` output

The table uses single-draw transition probabilities (option weight / total eligible weight) as an approximation, since the actual 4-draw-without-replacement mechanic would make the state space too large.
