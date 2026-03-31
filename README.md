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
python arkgrid.py stats [options]
```

### `sim` - Single run with turn log

Run one simulation and print the turn-by-turn log showing offers, rerolls, picks, and state changes.

```bash
python arkgrid.py sim [options]
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

**DPS:** boss_damage > additional_damage > attack_power

**Support:** ally_attack > brand_power > ally_damage

## Examples

```bash
# Basic: estimate probabilities for will>=4, chaos>=5 across all rarities
python arkgrid.py stats --min-will 4 --min-chaos 5

# Epic only, with reset ticket, 500k trials
python arkgrid.py stats --min-will 4 --min-chaos 5 --rarity epic --reset-ticket --trials 500000

# Support optimisation with a specific gem
python arkgrid.py stats --min-will 3 --min-chaos 3 --optimize support \
  --gem-type order_fortitude --first-effect attack_power --second-effect ally_damage

# Exact goals, no extra ticket
python arkgrid.py stats --exact-will 5 --exact-chaos 5 --no-extra-ticket

# Single debug run with turn log
python arkgrid.py sim --min-will 4 --min-chaos 5 --rarity epic --seed 123

# Single run with a specific gem
python arkgrid.py sim --min-will 4 --min-chaos 5 --rarity epic \
  --gem-type chaos_distortion --first-effect boss_damage --second-effect ally_attack
```

## Tests

```bash
python -m unittest test_arkgrid -v
```

## Reference

The official probability data from Smilegate is documented in [`documentation/official_probability_info_en.md`](documentation/official_probability_info_en.md).
