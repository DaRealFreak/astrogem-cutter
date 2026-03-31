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

The policy operates in three modes, selected by a **comfort signal**. The comfort signal is the DP-estimated probability of reaching the goal from the current state (falling back to binary feasibility fraction if no DP table is available). The `--side-threshold` parameter controls the base boundary between comfortable and desperate modes.

### Coefficient-scaled effective threshold

The base `--side-threshold` is scaled by the combat power coefficient of the gem's best target-side effect. High-value effects (e.g. boss_damage, coeff 1000) keep the base threshold unchanged, while low-value effects (e.g. attack_power, coeff 400) raise it — making the policy stay in desperate mode longer since investing turns in a weak side effect is less worthwhile.

Formula: `effective = threshold + (1 - threshold) * (1 - quality)`, where `quality = max target coeff on gem / max coeff in set`.

With `--side-threshold 0.5` and DPS optimization:

| Best target effect on gem | Coeff | Quality | Effective threshold |
|---|---|---|---|
| boss_damage | 1000 | 1.0 | 50% |
| additional_damage | 700 | 0.7 | 65% |
| attack_power | 400 | 0.4 | 80% |

With `--side-threshold 0.5` and support optimization:

| Best target effect on gem | Coeff | Quality | Effective threshold |
|---|---|---|---|
| ally_attack | 1500 | 1.0 | 50% |
| brand_power | 1050 | 0.7 | 65% |
| ally_damage | 600 | 0.4 | 80% |

If the gem has no target-type effects at all (e.g. both slots are support on a DPS-optimized gem), the effective threshold is 100% — side nodes are never valued.

### BIS-only mode (`--bis-only`)

When `--bis-only` is enabled, the effective threshold is forced to 100% unless **both** effect slots have target-type effects (both DPS for `--optimize dps`, both support for `--optimize support`). Since each gem has exactly 2 DPS and 2 support effects, this means the gem must have its 2 DPS effects (or 2 support effects) to be considered BIS.

While effects aren't BIS, the policy:
- Never enters comfortable mode (threshold = 100%, side-node upgrades ignored)
- Still values good `change_effect` offers in desperate mode (ones that resolve to a target effect), actively pursuing BIS effects

Once both effects are target, the coefficient-scaled threshold applies normally and side-node upgrades are valued.

The effective threshold is shown as `threshold=` in the `sim` turn log.

### Forced rerolls (always, before mode selection)

- **Last turn, goal not met**: always reroll — nothing to lose.
- **No offer keeps goal feasible** (feasibility fraction = 0%): always reroll — every option would make the goal unreachable.

### Goal-met mode (goal already satisfied)

Activated when willpower and chaos already meet or exceed the goal targets. Focus shifts entirely to maximising total points via side-node upgrades.

Reroll if:
- Any offer contains a downgrade (will-1, chaos-1, first-1, second-1) **and** no big upgrade (+2/+3/+4) is available
- No offer provides any positive stat change or beneficial effect change

### Comfortable mode (comfort signal >= effective threshold)

Activated when the goal probability is at or above the effective threshold. The policy values **both** goal upgrades and side-node upgrades, accepting any positive progress.

Reroll if:
- Any downgrade is present **and** no big upgrade (goal or side) compensates
- No useful upgrade exists at all (no goal upgrade, no side upgrade, no good effect change)

Side-node upgrades are filtered by `--optimize`: only effects matching the DPS or support target are valued. For example, with `--optimize dps`, upgrading a support-effect slot doesn't count as useful.

### Desperate mode (comfort signal < effective threshold)

Activated when the goal probability drops below the effective threshold. The policy ignores side nodes entirely and focuses purely on willpower and chaos upgrades.

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

When a `change_first_effect` or `change_second_effect` option appears, the game **pre-determines** the new effect (randomly drawn from the available pool) and **shows it to the player**. Each gem type has 4 effects, and with 2 already assigned, 2 remain with equal (50%) probability each.

The simulator models this by resolving effect changes at offer generation time. The resolved outcome is shown in the `sim` log (e.g. `change_first_effect->boss_damage`).

The reroll policy checks the specific resolved outcome: a change is "good" if the new effect belongs to the optimisation target set (DPS or support). No coefficient weighting — just target membership.

In **BIS-only mode** (`--bis-only`), good effect changes are valued even in desperate mode when the gem doesn't yet have 2 target effects. This makes the policy actively pursue optimal effects rather than ignoring change_effect offers.

Use `python -m arkgrid effects` to see the full table of possible outcomes for any gem type.

## Reset ticket

The reset ticket allows one full restart to initial state (will=1, chaos=1, first=1, second=1) if the run goes badly. It triggers on (in priority order):

1. **Last-turn fresh-start comparison**: on the final turn, after exhausting all rerolls, if P(goal after clicking) < P(goal from initial state with full turns), resetting gives better odds. This is always checked — no flag needed. Rerolls are used first to find the best possible offers before comparing.
2. **Probability threshold** (`--prob-reset-threshold`): on any turn, if P(goal) drops below the configured threshold, reset proactively.
3. **Binary infeasibility**: on any turn, if the goal is mathematically unreachable, reset.

After a reset, the run restarts from turn 1 with the same gem but fresh stats. The reset ticket can only be used once per run.

The `sim` turn log shows both attempts when a reset occurs.

## DP probability table

A backward-induction probability table is precomputed once at startup (~20ms). It stores P(reach goal | will, chaos, first, second, turns_left) for all 6,250 possible states. This table drives:
- The comfort signal for the reroll policy (comfortable vs desperate mode)
- Probability-based early resets (when `--prob-reset-threshold` > 0)
- The `P(goal)` and `P(click)` values shown in `sim` output

The table uses single-draw transition probabilities (option weight / total eligible weight) as an approximation, since the actual 4-draw-without-replacement mechanic would make the state space too large.
