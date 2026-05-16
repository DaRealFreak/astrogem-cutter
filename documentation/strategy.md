# Decision-making process

Each turn follows a fixed pipeline of checks and decisions. The simulator uses a precomputed DP probability table with two layers: a **reroll-aware DP** (for optimal reroll timing) and a **standard DP** (for reset decisions and probability display).

## Turn flow

```
For each turn:
  1. Pre-turn checks (can reset or fail before seeing offers)
  2. Relic+ reroll ticket check (grant extra ticket mid-run if P(relic+) crosses threshold)
  3. Generate 4 offers from the weighted pool
  4. Reroll decision (may spend rerolls to re-draw offers)
  5. Early finish check (goal already met? risk vs side gain; relic+ can override)
  6. Post-offer checks (can reset or fail after seeing final offers)
  7. Pick one of the 4 offers uniformly at random (25% each)
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

1. **Reroll-aware DP** (`prob_table`): State includes reroll count. Used for reroll decisions via `should_reroll_dp()`. Build time: ~50ms.

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

### Forced reroll on no-progress turns

Flag: `--force-reroll-no-progress N` (coefficient threshold; `0` disables).

The DP's reroll decision is myopic in a specific way: it compares the keep-value of the *actual 4 offers* (uniform pick) against the value of rerolling. When none of the 4 options advances the goal (no positive will/chaos, no positive side level that's needed, no side-coefficient gain), the DP still sometimes favours `process` because the four "useless" offers can marginally increase DP value through **pool-dilution effects** — e.g. a `first+2` on an irrelevant side effect narrows the future eligible pool (fewer `first+N` options remain eligible in later turns) and concentrates draw weight on chaos/will options. That upside, while real, comes at the cost of a turn that contributed nothing to the goal directly.

The `--force-reroll-no-progress` heuristic overrides this. Before calling the DP, it checks: **does any offer increase a stat the goal still needs?** If not, and a reroll is available, it forces a reroll immediately.

#### Coefficient gating

The threshold is compared against the sum of the gem's **starting** target-effect coefficients (`DPS_COEFF` or `SUPPORT_COEFF` depending on `--optimize`). The rationale: on gems with good side nodes, hitting the main goal matters more than accumulating relic+ / total-points upside, so skip "free" side progression on irrelevant turns. On gems with weak side nodes, the DP's default (keep the pool-dilution upside) is preferred.

Typical thresholds:

- `1050` on support (any gem with `brand_power` or `ally_attack`)
- `1500` on support (any gem with `ally_attack`)
- `1400+` on DPS (any gem with `boss_damage` or `additional_damage`)

#### Trade-off (MC, 100k trials, epic + extra ticket, random support gem, goal = will 4 + chaos 4)

| Threshold | Success | Relic+ | Avg total | Avg coeff |
|---|---|---|---|---|
| 0 (off) | 46.49% | 24.47% | 13.81 | 3282 |
| 1050 | **48.14%** (+1.65pp) | 21.65% | 13.62 | 3180 |
| 1500 | 47.59% | 22.63% | 13.69 | 3214 |
| 2000 | 46.79% | 23.93% | 13.78 | 3260 |
| 2500 | 46.64% | 24.18% | 13.79 | 3268 |

Higher thresholds preserve more relic+ upside at the cost of less main-goal gain. Pick based on priority: if relic+ doesn't matter to you, go with the lowest threshold that matches "acceptable" gems.

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

### Relic+ override

When `--relic-no-early-finish F` is set, the early finish decision is checked against P(relic+ >=16) from the current state. If P(relic+) exceeds the threshold, early finish is suppressed regardless of the risk calculation. This allows chasing 16+ total points even when the primary goal is already met and at risk. See [Relic+ tracking and overrides](#relic-tracking-and-overrides) for details.

## Relic+ tracking and overrides

A separate DP table computes P(total_points >= 16) — the probability of achieving relic+ grade — from the current state at each turn. This enables two optional overrides controlled by independent thresholds.

### Display

P(relic+) is shown alongside P(goal) in:
- `sim` turn log headers and state lines (as `P(r+)=X%`)
- `live` analysis output (as `P(relic+): X%`)
- `auto` turn headers and state lines
- `stats` output (as `DP relic+ (>=16): X%`)

### Early finish override (`--relic-no-early-finish F`)

When the primary goal is satisfied and early finish would normally trigger (risky offers, safe mode), this override checks P(relic+ >=16) from the current state. If P(relic+) exceeds the threshold, early finish is suppressed — the simulator continues playing to chase 16+ total points.

This intentionally accepts risk to the primary goal in exchange for a shot at relic+. The threshold should be set high enough that the trade-off is worthwhile.

| `--relic-no-early-finish` | Behaviour |
|---|---|
| `0.0` (default) | Disabled — early finish is not affected |
| `0.3` | Continue if P(relic+) > 30% — moderate relic+ chase |
| `0.5` | Continue if P(relic+) > 50% — conservative, only chase when likely |

### Extra reroll ticket override (`--relic-reroll-threshold F`)

The `--reroll-min-coeff` flag disables the extra reroll ticket for gems whose starting effect coefficients are too low. This override re-enables the ticket mid-run when P(relic+ >=16) from the current state crosses the threshold.

Unlike the initial coefficient gate (checked once at run start), the relic+ check is evaluated **each turn**. The extra reroll is granted the first turn that P(relic+) meets the threshold — this means a gem that starts with low-value effects can still benefit from the extra reroll once it's on track for relic+.

| `--relic-reroll-threshold` | Behaviour |
|---|---|
| `0.0` (default) | Disabled — reroll ticket gating is not affected |
| `0.1` | Re-enable at P(relic+) > 10% — early grant, most epic runs benefit |
| `0.25` | Re-enable at P(relic+) > 25% — moderate, grants mid-run when on track |

### DP table cost

The relic+ DP table uses `LastTurnGoal(min_total=16)` with no side coefficients, BIS awareness, or reroll tracking. State space is `5^4 * max_turns` = 5,625 entries for epic. Build time: ~20ms. Negligible compared to the primary tables.

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

Requires `sum(level * coefficient)` across target-type side nodes to meet a threshold. Only target-type effects (matching `--optimize`) contribute.

When a gem is configured (`--first-effect` + `--second-effect`), the DP base case evaluates this from the known starting coefficients. In BIS mode with effect changes, the check uses the starting effect's coefficient as an approximation.

When no gem is configured (random gems), the DP probability is averaged over all possible effect assignments (gem type x effect slot permutations, grouped by unique coefficient pairs using first/second symmetry). The MC simulation uses each trial's randomly assigned gem for the actual success check, so MC results are always correct. The DP tables used for reroll/reset decisions within the simulator don't include the side coefficient constraint for random gems (since coefficients vary per trial), so decisions are guided by the base goal only — slightly suboptimal but the MC success rate remains accurate.

Example: `--min-side-coeff 5000` with boss_damage(1000) as first effect requires boss_damage at level 5 (1000*5=5000), or boss_damage at 3 + additional_damage(700) at 3 = 3000+2100=5100 also passes.

## DP probability vs MC success rate

The `stats` command shows both a **DP probability** and an **MC success rate**. The DP probability is the analytical probability of reaching the goal from the initial state through plain turn-by-turn transitions — it does **not** model rerolls, reset tickets, extra reroll tickets, or any smart policy decisions. It represents the baseline "how likely is this goal with pure luck?"

The MC success rate is typically higher because each simulated trial benefits from:
- **Rerolls** (epic has 2 base + 1 extra = 3 rerolls) — re-draw bad offers
- **Reset ticket** — full restart when the run goes badly
- **DP-optimal reroll timing** — save rerolls for late turns where they protect against negative nodes
- **Early finish** — lock in a satisfied goal instead of risking it
- **Relic+ overrides** — re-enable tickets mid-run when on track for 16+ points

For example, a goal showing 5% DP probability might show 10% MC success rate — the extra mechanics roughly double the odds. The gap depends on the goal difficulty and which tickets/options are enabled.

## DP probability tables

Two backward-induction probability tables are precomputed once at startup:

### Reroll-aware DP (primary)

State: `(will, chaos, first, second, rerolls, turns_left)` — ~25,000 entries for epic with 3 rerolls. Build time: ~50ms. This table drives:
- **Optimal reroll timing** via `should_reroll_dp()` — compares keep-vs-reroll value at each state
- The `P(goal)` and `P(click)` values shown in `sim`, `live`, and `auto` output

The per-option max model captures the value of selective rejection (keep good draws, reroll bad ones), naturally saving rerolls for late turns where they protect against negative nodes.

### Standard DP (for reset decisions)

State: `(will, chaos, first, second, turns_left)` — 6,250 entries for epic. Build time: ~20ms. This table drives:
- Probability-based early resets (when `--prob-reset-threshold` > 0)
- Fresh-start probability (`p_fresh`) for last-turn reset comparison
- Early finish decisions (P=1.0 at goal-satisfied states when enabled)
- The fallback comfort signal for the heuristic `RerollPolicy`

The standard DP is used for reset decisions because the reroll-aware DP overestimates `p_fresh` (fresh start with full rerolls appears ~2x more valuable than it actually is, due to the per-option max approximation vs actual 4-draw-pick-1 mechanics).

Both tables use single-draw transition probabilities (option weight / total eligible weight). When side-node goals are set (`--min-first`, `--min-second`, `--min-side-coeff`), the terminal success condition includes those constraints without expanding the state space.

### Relic+ DP (optional)

State: `(will, chaos, first, second, turns_left)` — same as standard DP. Goal: `min_total=16` (will+chaos+first+second >= 16). Built when `--relic-no-early-finish` or `--relic-reroll-threshold` is set. No reroll awareness, no side coefficients — purely tracks the probability of achieving 16+ total points. Used for relic+ display and the two relic+ overrides (early finish suppression, extra reroll ticket gating). Build time: ~20ms.

## Effect-aware DP

Effect-aware + reroll-aware DP is the default mode used at runtime (it self-disables only when no gem type is known). It correctly prices `--min-side-coeff` goals by tracking effect identity in the DP state and modelling `change_effect` transitions.

A simpler DP that treats each gem's `first_effect` and `second_effect` as fixed scalars at construction time (via `side_coeff_first` / `side_coeff_second`) would not model `change_first_effect` / `change_second_effect` as state transitions — those options would be treated as no-ops in the transition function. This creates two related issues:

1. **False 0% on wrong-side gems.** If the starting effects don't belong to the optimize side (e.g. `ally_damage + ally_attack` under `--optimize dps`), both side coefficients are 0. With `--min-side-coeff 2000`, the terminal success check `coeff_first*f + coeff_second*s >= 2000` can never pass. The DP reports 0% for every state, and automation triggers an early reset on turn 2 as soon as rule 3 (`no offer keeps goal feasible`) fires.

2. **Workaround in the simulator.** To avoid the false 0% cascade, the MC simulator strips `min_side_coeff` from its internal DP when both side coeffs are 0 (see `simulator.py`). This keeps runs progressing but drops the side-coefficient signal entirely — decisions are made on will/chaos alone, and the run only learns it failed at the final success check.

The effect-aware DP fixes both by tracking effect identity in the DP state.

### How it works

State extension: `(will, chaos, first, second, first_idx, second_idx, turns_left [, rerolls])` where `first_idx` and `second_idx` are indices into `GEM_TYPES[gem_type]` (the gem's 4-effect pool), with `first_idx != second_idx` always. This gives 12 valid effect-pair combinations per (w,c,f,s) state — a 12× state blow-up versus the standard DP.

Change-effect transitions: when `change_first_effect` fires, the game draws a new effect uniformly from the 2 non-equipped pool members. The DP models this as `P(first_idx = new_fi) = 0.5` for each of the two destinations. `change_second_effect` works symmetrically on `second_idx`. Stat levels are preserved across effect changes (matching the in-game mechanic).

Coefficient check: `effect_coeffs[first_idx] * first + effect_coeffs[second_idx] * second >= min_side_coeff`, where `effect_coeffs` is the optimize-filtered coefficient table (non-target effects contribute 0).

### Build cost

| Mode | States | Build time |
|---|---|---|
| Non-reroll | ~68k (epic) | ~160ms |
| Reroll-aware | ~270k (epic, 3 rerolls) | ~1.3s |

Tables are cached per gem type. In `--all` automation or `stats` with random gems, a single table per gem type (6 types total) is reused across all runs of that type.

### When to use

- **Random-gem stats with `--min-side-coeff`.** Significant success-rate lift: the MC simulator uses the effect-aware DP for reroll and reset decisions, correctly identifying wrong-side gems and resetting them aggressively.
- **`auto --all` with `--min-side-coeff` and `--reset-ticket`.** Avoids the premature reset cascade on turn 2 described in issue 1 above; trades those early resets for informed mid-run resets when the DP genuinely says the gem is cooked.
- **Configured-gem runs where you expect change-effect rescues.** EA DP prices in the probability that a change-effect card flips a wrong-side slot to a target effect.

### Trade-off example

Stats at 20k trials, random epic gem, `--min-will 4 --min-chaos 5 --min-side-coeff 5000 --reset-ticket --optimize dps`:

| | Standard DP | Effect-aware DP |
|---|---|---|
| Success rate | 3.12% | **5.69%** (+2.57pp, +82%) |
| Avg side coefficient | 2,161 | 2,501 |
| Reset usage | 59.6% | 92.4% |
| Relic+ rate | 24.9% | 19.4% |

The effect-aware DP trades more reset tickets for a higher main-goal success rate. The relic+ drop reflects that aggressive resets abandon gems that would have organically reached ≥16 points. If relic+ matters to you, combine with `--relic-reroll-threshold` / `--relic-no-early-finish` to preserve the upside.

### Caveats

- Effect-aware mode takes precedence over `--bis-only` when both are set. Effect identity is already tracked, so BIS-style target-effect constraints can be expressed via `--min-side-coeff` + `--optimize` without needing the binary BIS state.
- The single-draw approximation is slightly different from the standard DP because change-effect is no longer a no-op — on gems that start with target-side effects, the EA DP is marginally *lower* (~1-4pp) since it correctly models the downside of a change-effect routing to a non-target.
- Each `auto --all` run of a new gem type pays the one-time build cost on first encounter; subsequent gems of the same type reuse the cached table.

## Automation (`auto` command)

The `auto` command runs a full automation loop: capture screen → detect state → decide → click → wait → repeat. It uses all the same decision logic described above, with these additions:

### Screen detection

Each iteration captures the game screen via `mss` and runs template matching (`template_recognizer.detect()`) to extract the current state: gem type, stats, effects, reroll count, turn/step, and 4 option cards. If detection fails (e.g. during animations), it retries up to 5 times with 0.5s delays.

### Decision pipeline

Per iteration, the automation checks (in order):

0. **Relic+ reroll ticket**: if `--relic-reroll-threshold` is set and P(relic+) from current state crosses threshold, re-enable extra reroll ticket
1. **Early finish**: goal satisfied + risk exceeds tolerance → click Finish (suppressed if `--relic-no-early-finish` and P(relic+) exceeds threshold)
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
- **Ticket gating**: `--reset-min-coeff` / `--reroll-min-coeff` disable tickets for low-coefficient gems. `--relic-reroll-threshold` can re-enable the extra reroll ticket mid-run when P(relic+) crosses the threshold
