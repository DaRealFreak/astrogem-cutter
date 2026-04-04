# Decision-making process

Each turn follows a fixed pipeline of checks and decisions. The simulator uses a precomputed DP probability table with two layers: a **reroll-aware DP** (for optimal reroll timing) and a **standard DP** (for reset decisions and probability display).

## Turn flow

```
For each turn:
  1. Pre-turn checks (can reset or fail before seeing offers)
  2. Generate 4 offers from the weighted pool
  3. Reroll decision (may spend rerolls to re-draw offers)
  4. Early finish check (goal already met? risk vs side gain)
  5. Post-offer checks (can reset or fail after seeing final offers)
  6. Pick one of the 4 offers uniformly at random (25% each)
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

Rerolls are never used on turn 1 (since no prior state exists to judge). On subsequent turns, the **reroll-aware DP table** decides whether to spend a reroll based on the current offers. Rerolls re-draw all 4 offers from the pool.

## Reroll strategy: DP-optimal reroll timing

The simulator uses a reroll-aware DP table that extends the standard DP state with the number of available rerolls. At each state `(will, chaos, first, second, rerolls, turns_left)`, the DP computes the optimal keep-vs-reroll decision via backward induction.

### How it works

The reroll-aware DP uses a **per-option keep-vs-reroll max** during backward induction:

```
V(state, rerolls, turns_left) =
  for each eligible option i with probability p_i:
    post_click_value = V(apply(state, option_i), rerolls + view_delta_i, turns_left - 1)
    reroll_value = V(state, rerolls - 1, turns_left)
    contribution = p_i * max(post_click_value, reroll_value)
  V = sum of contributions
```

This captures the variance-based value of rerolls: for each possible draw, you keep it if its value exceeds the reroll value, otherwise reroll. This naturally produces optimal reroll timing — rerolls are saved for later turns where they have higher marginal value (protecting against negative nodes like will-1, chaos-1).

At runtime, `should_reroll_dp()` compares the expected value of keeping the current 4 offers (uniform 25% pick) against the value of rerolling (same state, one fewer reroll). Reroll if rerolling is strictly better.

### Why two DP tables

The simulator builds two DP tables:

1. **Reroll-aware DP** (`prob_table`): State includes reroll count. Used for reroll decisions via `should_reroll_dp()`. Build time: ~50ms single-draw, ~1s exact-draw.

2. **Standard DP** (`_reset_prob_table`): State does not include rerolls. Used for reset decisions and `p_fresh` comparison.

The reroll-aware DP slightly **overestimates** the value of rerolls because the per-option max treats each option draw as an independent accept/reject decision, while the actual game draws 4 options together with uniform random pick. This overestimation inflates the fresh-start probability (`p_fresh`), which would cause excessive resets if used for reset decisions. The standard DP gives accurate reset value estimates.

### Reroll distribution

With the DP-optimal strategy, rerolls are distributed heavily toward late turns:

| Turn range (epic, 9 turns) | Avg rerolls used (baseline heuristic) | Avg rerolls used (DP-optimal) |
|---|---|---|
| Early (turns 1-3) | 1.87 | 0.14 |
| Mid (turns 4-6) | 1.14 | 0.60 |
| Late (turns 7-9) | 0.38 | 1.90 |

This produces higher success rates across all rarities and lower reset usage.

### Fallback: heuristic reroll policy

When the reroll-aware DP is not available (e.g. in automation before the table is built), the `RerollPolicy` heuristic serves as a fallback. It operates in three modes selected by a **comfort signal** (DP-estimated goal probability):

- **Goal-met mode**: optimise side nodes, avoid downgrades
- **Comfortable mode** (comfort signal >= effective threshold): accept any positive upgrade
- **Desperate mode** (comfort signal < threshold): focus purely on will/chaos upgrades

A DP-based override layer can adjust the heuristic decision by comparing offer quality against baseline. See `policy.py` for details.

## Post-offer checks

After the final set of offers is determined (after all rerolls), checks run in this order:

1. **Early finish** (when `--early-finish-coeff` >= 0): If the goal is already satisfied and the risk of losing it outweighs the potential side gains, finish early instead of clicking. See [Early finish](#early-finish) below.

2. **Probability-based early reset** (soft, only when `--prob-reset-threshold` > 0): If the expected goal probability *after clicking* (averaged across all 4 offers) drops below the threshold, reset.

3. **Binary feasibility check** (hard): If no offer keeps the goal feasible (feasibility = 0%), reset if available, otherwise fail.

4. **Last-turn fresh-start comparison**: On the final turn, if P(goal after clicking) < P(goal from initial state with full turns), resetting gives better odds. Checked only when reset ticket is still available.

## Pick resolution

If all checks pass, one of the 4 offers is picked **uniformly at random** (25% each). The simulator does not choose the "best" offer — this models the in-game mechanic where you select a face-down option without knowing which is which.

## Early finish

When the goal is already satisfied mid-run, continuing risks losing it via stat decreases (will-1, chaos-1). The `--early-finish-coeff` parameter controls whether to finish early or continue for side-node upgrades.

### Decision formula

Given the 4 current offers:

1. Compute **P(miss)** = fraction of offers that would break goal satisfaction (e.g. 1 of 4 = 25%)
2. Compute **best_coeff_gain** = highest `delta * effect_coefficient` among side-node upgrades in the offers (e.g. additional_damage+3 = 3 × 700 = 2100)
3. Compute **risk_score** = `best_coeff_gain * P(miss)`

**Finish early** if `P(miss) > 0` AND either:
- No side-node upgrade exists (`best_coeff_gain == 0`) — risk with no upside
- `risk_score > threshold` — upside doesn't justify the risk

**Continue** if `P(miss) == 0` (no risk) OR `risk_score <= threshold` (acceptable risk).

### Examples

| Offers | P(miss) | Best gain | Risk score | Coeff=0 | Coeff=750 |
|---|---|---|---|---|---|
| [will-1, boss_dmg+3, maintain, chaos-1] | 50% | 3000 | 1500 | finish | finish |
| [will-1, add_dmg+3, maintain, chaos-1] | 25% | 2100 | 525 | finish | continue |
| [will-1, boss_dmg+3, maintain, chaos+1] | 25% | 3000 | 750 | finish | continue |
| [will+1, boss_dmg+2, maintain, chaos+1] | 0% | 2000 | 0 | continue | continue |
| [will-1, maintain, cost+100, chaos-1] | 50% | 0 | 0 | finish | finish |

### DP integration

When early finish is enabled (coeff >= 0), the DP probability table sets P(success) = 1.0 for any state where the goal is already satisfied, regardless of turns remaining. This is correct because the player always has the *option* to stop — the threshold only controls the runtime decision.

This increases the DP probability compared to the no-early-finish baseline. For example, `--min-will 3 --min-chaos 3 --rarity epic` might show 46.2% with early finish vs 43.6% without.

### Parameter values

| `--early-finish-coeff` | Behaviour |
|---|---|
| `0` (default) | Safe — always finish when goal met and any risk exists |
| `750` | Continue for boss_damage+3 at 25% miss (3000×0.25=750) |
| `2000` | Continue for boss_damage+4 at 50% miss (4000×0.50=2000) |
| `-1` | Disabled — never finish early, always play all turns |

## Effect changes

When a `change_first_effect` or `change_second_effect` option appears, the game **pre-determines** the new effect (randomly drawn from the available pool) and **shows it to the player**. Each gem type has 4 effects, and with 2 already assigned, 2 remain with equal (50%) probability each.

The simulator models this by resolving effect changes at offer generation time. The resolved outcome is shown in the `sim` log (e.g. `change_first_effect->boss_damage`).

The reroll policy checks the specific resolved outcome: a change is "good" if the new effect belongs to the optimisation target set (DPS or support). No coefficient weighting — just target membership.

In **BIS-only mode** (`--bis-only`), good effect changes are valued even in desperate mode when the gem doesn't yet have 2 target effects. This makes the policy actively pursue optimal effects rather than ignoring change_effect offers.

Use `python -m arkgrid effects` to see the full table of possible outcomes for any gem type.

## Reset ticket

The reset ticket allows one full restart to initial state (will=1, chaos=1, first=1, second=1) if the run goes badly. **Effects are also restored to their original starting values** — any effects acquired via `change_effect` during the run are lost. This means resetting a gem that changed from `attack_power + ally_damage` to `attack_power + boss_damage` would lose the boss_damage.

The reset triggers on (in priority order):

1. **Binary infeasibility** (pre-turn): if the goal is mathematically unreachable before offers are drawn, reset immediately.
2. **Probability threshold** (`--prob-reset-threshold`, pre-turn): if the DP-estimated goal probability drops below the threshold, reset proactively.
3. **Post-offer zero feasibility**: if no offer keeps the goal feasible after rerolls, reset.
4. **Post-offer probability threshold**: if expected P(goal after clicking) drops below the threshold, reset.
5. **Last-turn fresh-start comparison**: on the final turn, after exhausting all rerolls, if P(goal after clicking) < P(goal from initial state with full turns), resetting gives better odds.

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

## DP probability tables

Two backward-induction probability tables are precomputed once at startup:

### Reroll-aware DP (primary)

State: `(will, chaos, first, second, rerolls, turns_left)` — ~25,000 entries for epic with 3 rerolls. Build time: ~50ms single-draw, ~1s exact-draw. This table drives:
- **Optimal reroll timing** via `should_reroll_dp()` — compares keep-vs-reroll value at each state
- The `P(goal)` and `P(click)` values shown in `sim`, `live`, and `auto` output

The per-option max model captures the value of selective rejection (keep good draws, reroll bad ones), naturally saving rerolls for late turns where they protect against negative nodes.

### Standard DP (for reset decisions)

State: `(will, chaos, first, second, turns_left)` — 6,250 entries for epic. Build time: ~20ms single-draw, ~1s exact-draw. This table drives:
- Probability-based early resets (when `--prob-reset-threshold` > 0)
- Fresh-start probability (`p_fresh`) for last-turn reset comparison
- Early finish decisions (P=1.0 at goal-satisfied states when enabled)
- The fallback comfort signal for the heuristic `RerollPolicy`

The standard DP is used for reset decisions because the reroll-aware DP overestimates `p_fresh` (fresh start with full rerolls appears ~2x more valuable than it actually is, due to the per-option max approximation vs actual 4-draw-pick-1 mechanics).

Both tables use single-draw transition probabilities (option weight / total eligible weight) as a base approximation, with exact PPSWOR(4) inclusion probabilities available via `--exact-dp`. When side-node goals are set (`--min-first`, `--min-second`, `--min-side-coeff`), the terminal success condition includes those constraints without expanding the state space.

## Automation (`auto` command)

The `auto` command runs a full automation loop: capture screen → detect state → decide → click → wait → repeat. It uses all the same decision logic described above, with these additions:

### Screen detection

Each iteration captures the game screen via `mss` and runs template matching (`template_recognizer.detect()`) to extract the current state: gem type, stats, effects, reroll count, turn/step, and 4 option cards. If detection fails (e.g. during animations), it retries up to 5 times with 0.5s delays.

### Decision pipeline

Per iteration, the automation checks (in order):

1. **Early finish**: goal satisfied + risk exceeds tolerance → click Finish
2. **Goal infeasibility**: goal unreachable → click Reset (if available)
3. **Probability threshold**: P(goal) below threshold → click Reset
4. **Zero feasibility**: no offer keeps goal feasible → click Reset
5. **Last-turn comparison**: fresh start has better odds → click Reset
6. **Reroll**: `GoalProbabilityTable.should_reroll_dp()` (DP-optimal) → click Reroll
7. **Process** (default): → click Process

### Button positions (at 1920×1080)

| Button | Position | When clicked |
|---|---|---|
| Process | (1068, 765) | Accept current offers (random pick) |
| Reroll | (1254, 595) | Re-draw all 4 offers |
| Reset | (962, 255) | Use reset ticket to restart |
| Finish | (831, 764) | Finish early when goal is met |
| Ticket confirm | (906, 666) | Confirm ticket usage (0.5s after reset/ticket reroll) |

Coordinates are scaled to actual monitor resolution for non-1080p displays.

### Reroll tracking

Reroll count is tracked internally rather than relying solely on OCR:
- On new turns (after process or reset): seed from OCR detection
- After rerolls: decrement internal counter

This handles the edge case where a `view+1` or `view+2` option is randomly picked, adding rerolls that OCR might not immediately reflect.

### Safety features

- **Escape key**: stops automation at any time (polled each iteration)
- **Focus check**: pauses when Lost Ark loses focus, resumes when it regains focus
- **3-second countdown**: before first click, with Escape to abort
- **`--dry-run`**: runs the full detection and decision loop without clicking
- **Ticket gating**: `--reset-min-coeff` / `--reroll-min-coeff` disable tickets for low-coefficient gems
