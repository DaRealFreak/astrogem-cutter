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

When `--bis-only` is enabled:

- Good `change_effect` offers (ones that resolve to a target effect) are treated as goal upgrades in desperate mode, actively pursuing optimal effects.
- In `stats` mode, success requires **both** effect slots to be target-type at the end of the run (not just meeting the will/chaos goal). Runs that meet the goal but have non-target effects count as failures.

The coefficient-scaled threshold applies normally regardless of whether effects are BIS. Side-node upgrades are always filtered by `_target_side_sets` to only target-type slots — so if one slot has a DPS effect and the other has a support effect (with `--optimize dps`), only the DPS slot's upgrades are valued in comfortable mode.

The effective threshold is shown as `threshold=` in the `sim` turn log.

### Forced rerolls (always, before mode selection)

- **Last turn, goal not met**: always reroll — nothing to lose.
- **No offer keeps goal feasible** (feasibility fraction = 0%): always reroll — every option would make the goal unreachable.

### Goal-met mode (goal already satisfied)

Activated when all goal constraints are satisfied — willpower, chaos, and any side-node level requirements (`--min-first`, `--min-second`). Focus shifts entirely to maximising total points via side-node upgrades.

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

### DP-based reroll override (`--dp-reroll-margin`)

After the heuristic makes its reroll decision, a DP-based override layer can adjust it. This compares the expected goal probability from the current 4 offers against the baseline expected probability from a random draw:

- **p_current** = average of `dp[state_after_each_offer, turns_left - 1]` across the 4 offers (25% each)
- **p_baseline** = `dp[state, turns_left]` — the DP recurrence value, which is the weighted average over all possible single-option draws

The override works bidirectionally:

1. **Heuristic says don't reroll, but offers are below baseline**: If `p_current < p_baseline * (1 - margin)`, override to reroll. This catches cases like `[maintain, view+1, cost+100, will+1]` where only 1 of 4 options provides stat progress.

2. **Heuristic says reroll, but offers are above baseline**: If `p_current >= p_baseline`, override to NOT reroll. This prevents wasting rerolls when the heuristic is too picky but the offers are actually better than average.

**Hard constraints are never overridden**: the forced rerolls for `last_turn_goal_not_met` and `no_offer_keeps_goal_feasible` always take priority.

The margin accounts for the opportunity cost of spending a reroll token (can't use it on a future bad draw). It scales with the reroll/turn ratio: `effective_margin = margin * min(1.0, turns_left / rerolls_remaining)`. When rerolls are surplus (more rerolls than turns remaining), the margin shrinks — surplus rerolls have lower marginal value, so the policy is more willing to spend them.

#### Side-node quality adjustment (`--side-quality`)

When `--side-quality` is set to a value > 0 and an astro gem is configured, the margin is further adjusted by the best target-type side-node upgrade in the current offers. The value controls the multiplier: `side_adjustment = quality * margin * weight`. Default `0` = off (max goal probability). Use higher values for min-maxing specific gems on mains. The quality formula is `(delta / 4) * (coeff / max_coeff)`, producing a value in [0.0, 1.0]:

| Offer | Quality | Weight=2 margin adj. | Weight=12 margin adj. |
|---|---|---|---|
| +4 boss_damage (1000) | 1.0 | +0.06 → 0.09 | +0.36 → 0.39 |
| +2 boss_damage | 0.5 | +0.03 → 0.06 | +0.18 → 0.21 |
| +4 attack_power (400) | 0.4 | +0.024 → 0.054 | +0.144 → 0.174 |
| +2 attack_power | 0.2 | +0.012 → 0.042 | +0.072 → 0.102 |
| +1 attack_power | 0.1 | +0.006 → 0.036 | +0.036 → 0.066 |

Higher margin = lower reroll threshold = more tolerant of below-baseline goal probability. At weight=12, a +4 boss_damage makes the policy tolerate a ~40% probability drop to keep the upgrade. At weight=2, the tolerance is ~9%.

The same side quality also lowers the bar for case 2 (suppressing heuristic rerolls).

Default margin is `0.03` (3%).

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

The reset ticket allows one full restart to initial state (will=1, chaos=1, first=1, second=1) if the run goes badly. **Effects are also restored to their original starting values** — any effects acquired via `change_effect` during the run are lost. This means resetting a gem that changed from `attack_power + ally_damage` to `attack_power + boss_damage` would lose the boss_damage.

The reset triggers on (in priority order):

1. **Last-turn fresh-start comparison**: on the final turn, after exhausting all rerolls, if P(goal after clicking) < P(goal from initial state with full turns), resetting gives better odds. This is always checked — no flag needed. Rerolls are used first to find the best possible offers before comparing.
2. **Probability threshold** (`--prob-reset-threshold`): on any turn, if P(goal) drops below the configured threshold, reset proactively.
3. **Binary infeasibility**: on any turn, if the goal is mathematically unreachable, reset.

After a reset, the run restarts from turn 1 with the same gem but fresh stats. The reset ticket can only be used once per run.

### Minimum coefficient gate (`--reset-min-coeff`)

When using random gems, `--reset-min-coeff` controls whether the reset ticket is used based on the gem's starting effects. The sum of target-effect coefficients for the starting effects must meet or exceed the threshold. If not, the reset ticket is disabled for that run — it's not worth resetting back to bad starting effects.

Example with DPS optimization:

| Starting effects | Sum | Resets at 1051? |
|---|---|---|
| attack_power (400) alone | 400 | no |
| boss_damage (1000) alone | 1000 | no |
| attack_power + additional_damage | 1100 | yes |
| attack_power + boss_damage | 1400 | yes |
| additional_damage + boss_damage | 1700 | yes |

Default is `0` (always use reset ticket).

The `sim` turn log shows both attempts when a reset occurs.

## Side node goals

Two types of side-node constraints can be added to the goal:

### Per-slot level minimums (`--min-first`, `--min-second`)

Requires the first/second side node to reach at least the specified level. The DP and feasibility checks account for the extra turns needed.

Example: `--min-first 5` with `--first-effect boss_damage` means "boss_damage must reach level 5."

### Coefficient-weighted total (`--min-side-coeff`)

Requires `sum(level * coefficient)` across target-type side nodes to meet a threshold. Only target-type effects (matching `--optimize`) contribute. Requires a configured gem (`--gem-type` + `--first/second-effect`).

The DP base case evaluates this from the known starting coefficients. In BIS mode with effect changes, the check uses the starting effect's coefficient as an approximation.

Example: `--min-side-coeff 5000` with boss_damage(1000) as first effect requires boss_damage at level 5 (1000*5=5000), or boss_damage at 3 + additional_damage(700) at 3 = 3000+2100=5100 also passes.

## DP probability table

A backward-induction probability table is precomputed once at startup (~20ms). It stores P(reach goal | will, chaos, first, second, turns_left) for all 6,250 possible states. When side-node goals are set (`--min-first`, `--min-second`, `--min-side-coeff`), the terminal success condition includes those constraints without expanding the state space. This table drives:
- The comfort signal for the reroll policy (comfortable vs desperate mode)
- The DP-based reroll override (comparing current offers against baseline)
- Probability-based early resets (when `--prob-reset-threshold` > 0)
- The `P(goal)` and `P(click)` values shown in `sim` output

The table uses single-draw transition probabilities (option weight / total eligible weight) as an approximation, since the actual 4-draw-without-replacement mechanic would make the state space too large.
