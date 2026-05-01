from __future__ import annotations

from typing import Dict, Tuple

# -----------------------------
# Gem effect definitions
# -----------------------------

DPS_EFFECTS = frozenset({"attack_power", "additional_damage", "boss_damage"})
SUPPORT_EFFECTS = frozenset({"ally_damage", "brand_power", "ally_attack"})

# Combat-power coefficient per effect level (reverse-engineered).
# Higher coefficient = more combat power per level = higher priority.
# Formula: multiplier = floor(total_level * coeff / 120 + 10000) / 10000
DPS_COEFF: Dict[str, int] = {"attack_power": 400, "additional_damage": 700, "boss_damage": 1000}
SUPPORT_COEFF: Dict[str, int] = {"ally_damage": 600, "brand_power": 1050, "ally_attack": 1500}

# Priority ordering derived from coefficients (used for tie-breaking on equal chance)
DPS_PRIORITY: Dict[str, int] = {"boss_damage": 3, "additional_damage": 2, "attack_power": 1}
SUPPORT_PRIORITY: Dict[str, int] = {"ally_attack": 3, "brand_power": 2, "ally_damage": 1}

# Each gem type's 4 available effects (2 DPS + 2 support per type)
GEM_TYPES: Dict[str, Tuple[str, ...]] = {
    "order_stability": ("attack_power", "additional_damage", "ally_damage", "brand_power"),
    "order_fortitude": ("attack_power", "boss_damage", "ally_damage", "ally_attack"),
    "order_immutability": ("additional_damage", "boss_damage", "brand_power", "ally_attack"),
    "chaos_erosion": ("attack_power", "additional_damage", "ally_damage", "brand_power"),
    "chaos_distortion": ("attack_power", "boss_damage", "ally_damage", "ally_attack"),
    "chaos_collapse": ("additional_damage", "boss_damage", "brand_power", "ally_attack"),
}


def change_dest_max_coeff(gem_type: str, first_effect: str,
                          second_effect: str, optimize: str) -> int:
    """Max optimize-side coefficient over the 2 effects either slot can
    change_*_effect to (the gem-type pool members not currently equipped).
    Returns 0 when the gem type is unknown or no destination contributes
    to the optimize side.
    """
    pool = GEM_TYPES.get(gem_type)
    if not pool:
        return 0
    coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
    return max(
        (coeff_map.get(e, 0) for e in pool
         if e != first_effect and e != second_effect),
        default=0,
    )
