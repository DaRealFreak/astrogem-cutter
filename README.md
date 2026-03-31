# AstrogemCutter

Monte Carlo simulator for the Lost Ark Astrogem (gem cutting) system. Estimates the probability of reaching specific willpower/chaos stat goals, while optimising side-node effect levels using the official in-game probability weights published by Smilegate.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (Git Bash)
source .venv/bin/activate       # Linux / macOS
```

No external dependencies required - stdlib only.

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

## Options

### Goal

| Flag | Description |
|---|---|
| `--min-will N` | Minimum willpower target |
| `--min-chaos N` | Minimum chaos target |
| `--exact-will N` | Exact willpower target |
| `--exact-chaos N` | Exact chaos target |

At least one goal flag should be set. Flags can be combined (e.g. `--min-will 4 --min-chaos 5`).

### Gem configuration

| Flag | Description |
|---|---|
| `--rarity {common,rare,epic}` | Gem rarity. Omit to run all three. Common = 5 turns, rare = 7, epic = 9. |
| `--optimize {dps,support}` | Side-node optimisation target. Default: `dps`. |
| `--gem-type TYPE` | Gem type (see table below). Omit to use a random gem each trial. |
| `--first-effect EFFECT` | First effect on the gem. Required when `--gem-type` is set. |
| `--second-effect EFFECT` | Second effect on the gem. Required when `--gem-type` is set. |

When `--gem-type` is omitted, each simulation trial randomly picks a gem type and assigns two random effects from its pool.

### Tickets & strategy

| Flag | Description |
|---|---|
| `--extra-ticket` / `--no-extra-ticket` | Use extra reroll ticket. Default: yes. |
| `--reset-ticket` / `--no-reset-ticket` | Use reset ticket. Default: run both variants. |
| `--side-threshold F` | Goal-feasibility fraction at which side-node upgrades become valued. Default: `0.5`. |
| `--prob-reset-threshold F` | Reset proactively when DP-estimated goal probability drops below this value. `0.0` = disabled (binary feasibility only). Try `0.01`-`0.03` for typical goals. Default: `0.0`. |

### Stats-only options

| Flag | Description |
|---|---|
| `--trials N` | Number of simulation trials. Default: `200000`. |
| `--seed N` | RNG seed for reproducibility. Default: `12345`. |

### Sim-only options

| Flag | Description |
|---|---|
| `--seed N` | RNG seed. Default: `42`. |

## Gem types & effects

Each gem type has 2 DPS effects and 2 support effects:

| Gem type | DPS effects | Support effects |
|---|---|---|
| `order_stability` | attack_power, additional_damage | ally_damage, brand_power |
| `order_fortitude` | attack_power, boss_damage | ally_damage, ally_attack |
| `order_immutability` | additional_damage, boss_damage | brand_power, ally_attack |
| `chaos_erosion` | attack_power, additional_damage | ally_damage, brand_power |
| `chaos_distortion` | attack_power, boss_damage | ally_damage, ally_attack |
| `chaos_collapse` | additional_damage, boss_damage | brand_power, ally_attack |

Order/chaos pairs share the same effect pools.

### Effect priority (on equal chance, higher is preferred)

**DPS:** boss_damage (coeff 1000) > additional_damage (700) > attack_power (400)

**Support:** ally_attack (coeff 1500) > brand_power (1050) > ally_damage (600)

See [`documentation/calculation.md`](documentation/calculation.md) for the full combat power formulas and core coefficients.

## Examples

```bash
# Basic: estimate probabilities for will>=4, chaos>=5 across all rarities
python -m arkgrid stats --min-will 4 --min-chaos 5

# Epic only, with reset ticket, 500k trials
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --reset-ticket --trials 500000

# Support optimisation with a specific gem
python -m arkgrid stats --min-will 3 --min-chaos 3 --optimize support \
  --gem-type order_fortitude --first-effect attack_power --second-effect ally_damage

# Exact goals, no extra ticket
python -m arkgrid stats --exact-will 5 --exact-chaos 5 --no-extra-ticket

# Probability-based early reset (resets before goal becomes impossible)
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --reset-ticket --prob-reset-threshold 0.02

# Stricter side-node threshold (only value side upgrades when >=70% of offers keep goal feasible)
python -m arkgrid stats --min-will 4 --min-chaos 5 --rarity epic --side-threshold 0.7

# Single debug run with turn log
python -m arkgrid sim --min-will 4 --min-chaos 5 --rarity epic --seed 123

# Single run with a specific gem
python -m arkgrid sim --min-will 4 --min-chaos 5 --rarity epic \
  --gem-type chaos_distortion --first-effect boss_damage --second-effect ally_attack
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Reference

The official probability data from Smilegate is documented in [`documentation/official_probability_info_en.md`](documentation/official_probability_info_en.md).
