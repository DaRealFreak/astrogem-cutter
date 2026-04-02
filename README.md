# AstrogemCutter

Monte Carlo simulator for the Lost Ark Astrogem (gem cutting) system. Estimates the probability of reaching specific willpower/chaos/side-node stat goals, while optimising effect levels using the official in-game probability weights published by Smilegate.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash)
source .venv/bin/activate       # Linux / macOS
```

No external dependencies required for the simulator (stdlib only). Vision features (`live`, `read`) require `opencv-python`, `numpy`, and `mss`. Automation (`auto`) additionally requires Windows.

## Commands

### `stats` - Probability estimation

Run a Monte Carlo simulation and print success rates, average total points, relic/ancient rates, and reset usage.

```bash
python -m arkgrid stats [options]
```

### `sim` - Single run with turn log

Run one simulation and print the turn-by-turn log showing offers, rerolls, picks, and state changes.

```bash
python -m arkgrid sim [options]
```

### `effects` - Effect change reference table

Show all possible effect change outcomes for a gem type, including expected coefficient deltas and whether each change is worth it.

```bash
python -m arkgrid effects [--gem-type TYPE] [--optimize {dps,support}]
```

### `live` - Screenshot analysis with probabilities

Detect game state from a screenshot and show per-option goal probabilities with reroll recommendations.

```bash
python -m arkgrid live --screenshot FILE [options]
```

### `auto` - Full automation (Windows only)

Automate the gem cutting process: captures screen, detects state, makes decisions (reroll/process/reset/finish), and clicks the appropriate buttons.

```bash
python -m arkgrid auto --min-will 4 --min-chaos 4 [options]
```

Requires Lost Ark to be running and the Processing dialog to be open. Press Escape to stop at any time. Use `--dry-run` to test detection and decisions without clicking.

### `read` - Vision debug

Read the game screen (from screenshot or live capture) and print the recognized state.

```bash
python -m arkgrid read [--screenshot FILE] [--debug] [--save-debug FILE]
```

## Options

### Goal

| Flag | Description |
|---|---|
| `--min-will N` | Minimum willpower target |
| `--min-chaos N` | Minimum chaos target |
| `--exact-will N` | Exact willpower target |
| `--exact-chaos N` | Exact chaos target |
| `--min-first N` | Minimum level for first side node (1-5) |
| `--min-second N` | Minimum level for second side node (1-5) |
| `--min-side-coeff N` | Minimum coefficient-weighted level total from target side nodes. Value = `sum(level * coefficient)`. E.g. boss_damage(1000) at level 5 = 5000. Requires `--first-effect` and `--second-effect`. Default: `0`. |

At least one goal flag should be set. Flags can be combined (e.g. `--min-will 4 --min-chaos 5 --min-first 5`).

#### Side node coefficient reference

`--min-side-coeff` uses `level * coefficient` summed across target-type side nodes:

| DPS Effect | Coefficient | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|
| attack_power | 400 | 1200 | 1600 | 2000 |
| additional_damage | 700 | 2100 | 2800 | 3500 |
| boss_damage | 1000 | 3000 | 4000 | 5000 |

| Support Effect | Coefficient | Level 3 | Level 4 | Level 5 |
|---|---|---|---|---|
| ally_damage | 600 | 1800 | 2400 | 3000 |
| brand_power | 1050 | 3150 | 4200 | 5250 |
| ally_attack | 1500 | 4500 | 6000 | 7500 |

Example: boss_damage at level 5 + additional_damage at level 3 = 5000 + 2100 = 7100.

### Gem configuration

| Flag | Description |
|---|---|
| `--rarity {common,rare,epic}` | Gem rarity (one or more). Omit to run all three. Common = 5 turns, rare = 7, epic = 9. |
| `--optimize {dps,support}` | Side-node optimisation target. Default: `dps`. |
| `--gem-type TYPE` | Gem type (see [gem types](documentation/gem_types.md)). Auto-resolved from effects when unambiguous. |
| `--first-effect EFFECT` | First effect on the gem. |
| `--second-effect EFFECT` | Second effect on the gem. |

When both `--first-effect` and `--second-effect` are specified, the gem type is auto-resolved from the effect pair. Each same-type pair (both DPS or both support) maps to exactly one gem pool. Three cross-type pairs are ambiguous and require `--gem-type` to disambiguate: `attack_power + ally_damage`, `additional_damage + brand_power`, `boss_damage + ally_attack`.

When no effects are specified, each simulation trial randomly picks a gem type and assigns two random effects from its pool.

### Tickets & strategy

| Flag | Description |
|---|---|
| `--extra-ticket` / `--no-extra-ticket` | Use extra reroll ticket. Default: yes. |
| `--reset-ticket` / `--no-reset-ticket` | Use reset ticket. Default: run both variants. |
| `--side-threshold F` | Base threshold at which side-node upgrades become valued, scaled by effect coefficient (see [strategy](documentation/strategy.md#coefficient-scaled-effective-threshold)). Default: `0.5`. |
| `--prob-reset-threshold F` | Reset proactively when DP-estimated goal probability drops below this value. `0.0` = disabled (binary feasibility only). Try `0.01`-`0.03` for typical goals. Default: `0.0`. |
| `--bis-only` | Actively pursue target effects via `change_effect` offers in desperate mode. Side-node upgrades still use the coefficient-scaled threshold but are filtered to target-type slots only. In `stats`, only runs where both effects end up as target-type count as success. |
| `--reset-min-coeff N` | Only use reset ticket when the sum of starting target-effect coefficients meets this threshold (e.g. atk_power+additional_damage = 1100 passes, brand_power alone = 1050 does not). `0` = always use. Default: `0`. |
| `--reroll-min-coeff N` | Only use extra reroll ticket when the sum of starting target-effect coefficients meets this threshold. Same logic as `--reset-min-coeff` but for the extra reroll ticket. `0` = always use. Default: `0`. |
| `--dp-reroll-margin F` | Margin for DP-based reroll override. Controls how far below the baseline expected probability the current offers must be before spending a reroll. Default: `0.03`. |
| `--side-quality F` | Weight side-node quality by coefficient in reroll decisions. `0` = off (max goal probability), `2` = mild, `12` = aggressive (~40% prob drop tolerated for +4 boss_damage). Default: `0`. |
| `--early-finish-coeff N` | Risk tolerance for early finish when goal is already satisfied. `0` = always finish when met (safe). Higher values accept more risk for side upgrades. Formula: finish if `best_coeff_gain * P(miss) > N`. E.g. `750` continues for boss_damage+3 at 25% miss. `-1` = disabled. Default: `0`. |

### Stats-only options

| Flag | Description |
|---|---|
| `--trials N` | Number of simulation trials. Default: `200000`. |
| `--seed N` | RNG seed for reproducibility. Default: `12345`. |

### Sim-only options

| Flag | Description |
|---|---|
| `--seed N` | RNG seed. Default: `42`. |

### Live-only options

| Flag | Description |
|---|---|
| `--screenshot FILE` | Path to screenshot image (required). |
| `--trials N` | Monte Carlo trials from current state. `0` = DP only. Default: `0`. |
| `--seed N` | RNG seed for Monte Carlo. Default: `42`. |

### Auto-only options

| Flag | Description |
|---|---|
| `--monitor N` | Monitor index for screen capture. `1` = primary. Default: `1`. |
| `--animation-delay SECS` | Seconds to wait after each click for animation. Default: `1.0`. |
| `--dry-run` | Run full detection and decision loop without clicking. |

## Documentation

- [Gem types & effects](documentation/gem_types.md) — gem types, effect pools, and priority rankings
- [Decision-making strategy](documentation/strategy.md) — turn flow, reroll policy modes, reset logic, early finish, automation, and DP probability table
- [Combat power formulas](documentation/calculation.md) — core coefficients and combat power calculations
- [Official probability data](documentation/official_probability_info_en.md) — Smilegate's published probability disclosure

## Examples

```bash
# Basic: estimate probabilities for will>=4, chaos>=5 across all rarities
python -m arkgrid stats --min-will 4 --min-chaos 5

# Epic only, with reset ticket, 500k trials
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --reset-ticket --trials 500000

# Support optimisation with a specific gem (gem type auto-resolved)
python -m arkgrid stats --min-will 3 --min-chaos 3 --optimize support \
  --first-effect ally_damage --second-effect ally_attack

# Exact goals, no extra ticket
python -m arkgrid stats --exact-will 5 --exact-chaos 5 --no-extra-ticket

# Probability-based early reset (resets before goal becomes impossible)
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --reset-ticket --prob-reset-threshold 0.02

# Stricter side-node threshold (only value side upgrades when >=70% of offers keep goal feasible)
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --side-threshold 0.7

# BIS-only: pursue target effects, only invest in target-type side nodes
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --bis-only

# Aggressive DP reroll override (lower margin = more willing to spend rerolls)
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity rare --dp-reroll-margin 0.01

# Min-max side nodes: mild weighting (2x)
python -m arkgrid stats --min-will 4 --min-chaos 4 --rarity epic --side-quality 2 \
  --first-effect boss_damage --second-effect attack_power

# Aggressive min-max: tolerate big probability drops for +4 boss_damage
python -m arkgrid stats --min-will 4 --min-chaos 4 --rarity epic --side-quality 12 \
  --first-effect boss_damage --second-effect attack_power

# Side node level goal: require boss_damage (first slot) at level 5
python -m arkgrid stats --min-will 4 --min-chaos 5 --min-first 5 --rarity epic \
  --first-effect boss_damage --second-effect attack_power

# Coefficient-weighted side node goal: total >= 5000 (e.g. boss_damage*5)
python -m arkgrid stats --min-will 4 --min-chaos 5 --min-side-coeff 5000 --rarity epic \
  --first-effect boss_damage --second-effect additional_damage

# Combined: both side nodes at level 4+ with coefficient floor
python -m arkgrid stats --min-will 4 --min-chaos 5 --min-first 4 --min-second 4 \
  --min-side-coeff 6000 --rarity epic \
  --first-effect boss_damage --second-effect additional_damage

# Save extra reroll ticket for high-coeff gems only
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --reroll-min-coeff 1100

# Show effect change outcomes for a gem type
python -m arkgrid effects --gem-type order_stability --optimize dps

# Single debug run with turn log
python -m arkgrid sim --min-will 4 --min-chaos 5 --rarity epic --seed 123

# Single run with a specific gem and side node goal
python -m arkgrid sim --min-will 4 --min-chaos 5 --min-first 5 --rarity epic \
  --first-effect boss_damage --second-effect additional_damage

# Early finish: safe mode (default) — always finish when goal met
python -m arkgrid stats --min-will 4 --min-chaos 4 --rarity epic

# Early finish: risk tolerance 750 — continue for boss_damage+3 at 25% miss
python -m arkgrid stats --min-will 4 --min-chaos 4 --rarity epic --early-finish-coeff 750

# Early finish disabled — always play all turns (old behaviour)
python -m arkgrid stats --min-will 4 --min-chaos 4 --rarity epic --early-finish-coeff -1

# Analyse a screenshot (requires opencv-python)
python -m arkgrid live --screenshot screenshot.png --min-will 4 --min-chaos 5

# Automate gem cutting (Windows only, requires Lost Ark running)
python -m arkgrid auto --min-will 4 --min-chaos 4 --early-finish-coeff 750

# Automation dry run (no clicks, just detection and decisions)
python -m arkgrid auto --min-will 4 --min-chaos 4 --dry-run

# Automation with exact DP and aggressive side quality
python -m arkgrid auto --min-will 4 --min-chaos 4 --exact-dp --side-quality 2 \
  --early-finish-coeff 1000
```

## Tests

```bash
python -m unittest discover -s tests -v
```
