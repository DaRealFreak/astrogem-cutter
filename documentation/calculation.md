# Astrogem Combat Power Calculation

Extracted values from the [arkgrid-gem-locator-v2](https://github.com/Airplaner/lostark-arkgrid-gem-locator-v2) project. These describe how gem stats translate into actual combat power multipliers.

## Gem Option Level Coefficients

Each gem effect has a coefficient that scales with the accumulated level across all equipped gems. The combat power contribution per effect is:

```
effect_multiplier = floor(total_level * coeff / 120) + 10000) / 10000
```

Where `total_level` is the sum of that effect's levels across all gems on the ark grid (not just one gem).

### DPS effects

| Effect | Coefficient | Per-level (approx) |
|---|---|---|
| Attack Power | 400 | ~0.033% per level |
| Additional Damage | 700 | ~0.058% per level |
| Boss Damage | 1000 | ~0.083% per level |

### Support effects

| Effect | Coefficient | Per-level (approx) |
|---|---|---|
| Ally Damage Enhancement | 600 | ~0.050% per level |
| Brand Power | 1050 | ~0.088% per level |
| Ally Attack Enhancement | 1500 | ~0.125% per level |

This confirms the priority ordering used in the simulator:
- **DPS**: Boss Damage (1000) > Additional Damage (700) > Attack Power (400)
- **Support**: Ally Attack Enh. (1500) > Brand Power (1050) > Ally Damage Enh. (600)

## Core (Willpower/Chaos) Point Coefficients

Core coefficients depend on core type, attribute, grade, and tier. Values represent the bonus at each point threshold (units: 1/10000 of a multiplier).

### DPS cores

| Core | p10 | p14 | p17 | p18 | p19 | p20 |
|---|---|---|---|---|---|---|
| Order Sun/Moon | 150 | 400 | 750 | 767 | 783 | 800 |
| Order Star | 100 | 250 | 450 | 467 | 483 | 500 |
| Chaos Sun/Moon T0 | 50 | 100 | 250 | 267 | 283 | 300 |
| Chaos Sun/Moon T1 | 0 | 50 | 150 | 167 | 183 | 200 |
| Chaos Star T0 (Attack) | 50 | 100 | 250 | 267 | 283 | 300 |
| Chaos Star T1 (Weapon) | *weapon-dependent* | | | | | |

Core multiplier formula: `(coeff + 10000) / 10000`

Example: Order Sun at p17 = `(750 + 10000) / 10000 = 1.075` (7.5% bonus)

### Support cores

| Core | p10 | p14 | p17 | p18 | p19 | p20 |
|---|---|---|---|---|---|---|
| Order Sun/Moon | 120 | 120 | 780 | 798 | 810 | 822 |
| Order Star | 0 | 60 | 210 | 220 | 230 | 240 |
| Chaos Sun/Moon T0 | 60 | 120 | 360 | 378 | 396 | 420 |
| Chaos Moon T1 | 60 | 60 | 180 | 180 | 180 | 180 |
| Chaos Sun T1 | 0 | 48 | 132 | 148 | 164 | 180 |

Ancient grade cores (grade = Ancient, p17+) receive additional coefficients on top of the base values listed above:
- DPS: +100 across the board
- Support Order Sun/Moon: +120
- Support Order Star: +90
- Support Chaos Sun/Moon T0: +180
- Support Chaos Sun/Moon T1: +120

## Gem Grades & Point Requirements

### Base point requirements per gem type

| Gem Type | Base Req |
|---|---|
| Stability / Erosion | 8 |
| Fortitude / Distortion | 9 |
| Immutability / Collapse | 10 |

### Grade determination

Total points = `base_req - remaining_req + willpower_points + option1_level + option2_level`

| Total Points | Grade |
|---|---|
| < 16 | Legendary |
| 16-18 | Relic |
| >= 19 | Ancient |

### Core energy by grade

| Grade | Energy |
|---|---|
| Epic | 9 |
| Legendary | 12 |
| Relic | 15 |
| Ancient | 17 |

### Core goal point by grade

| Grade | Goal Point | Max Point |
|---|---|---|
| Epic | 10 | 10 |
| Legendary | 14 | 14 |
| Relic | 17 | 20 |
| Ancient | 17 | 20 |

## Final Combat Power Formula

The total combat power multiplier for a complete ark grid is:

```
score = core_product * atk_multiplier * skill_multiplier * boss_multiplier
```

Where:
- `core_product` = product of all 6 core multipliers (3 order + 3 chaos)
- `atk_multiplier` = `(floor(total_atk * coeff[0] / 120) + 10000) / 10000`
- `skill_multiplier` = `(floor(total_skill * coeff[1] / 120) + 10000) / 10000`
- `boss_multiplier` = `(floor(total_boss * coeff[2] / 120) + 10000) / 10000`

With `coeff = [400, 700, 1000]` for DPS or `[600, 1050, 1500]` for support.
