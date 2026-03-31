# Gem types & effects

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

## Effect priority (on equal chance, higher is preferred)

**DPS:** boss_damage (coeff 1000) > additional_damage (700) > attack_power (400)

**Support:** ally_attack (coeff 1500) > brand_power (1050) > ally_damage (600)

See [`calculation.md`](calculation.md) for the full combat power formulas and core coefficients.
