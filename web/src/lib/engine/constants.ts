// Gem effect definitions

export const DPS_EFFECTS: ReadonlySet<string> = new Set([
  "attack_power",
  "additional_damage",
  "boss_damage",
]);

export const SUPPORT_EFFECTS: ReadonlySet<string> = new Set([
  "ally_damage",
  "brand_power",
  "ally_attack",
]);

// Combat-power coefficient per effect level (reverse-engineered).
// Higher coefficient = more combat power per level = higher priority.
// Formula: multiplier = floor(total_level * coeff / 120 + 10000) / 10000
export const DPS_COEFF: Readonly<Record<string, number>> = {
  attack_power: 400,
  additional_damage: 700,
  boss_damage: 1000,
};

export const SUPPORT_COEFF: Readonly<Record<string, number>> = {
  ally_damage: 600,
  brand_power: 1050,
  ally_attack: 1500,
};

// Priority ordering derived from coefficients (used for tie-breaking on equal chance)
export const DPS_PRIORITY: Readonly<Record<string, number>> = {
  boss_damage: 3,
  additional_damage: 2,
  attack_power: 1,
};

export const SUPPORT_PRIORITY: Readonly<Record<string, number>> = {
  ally_attack: 3,
  brand_power: 2,
  ally_damage: 1,
};

// Each gem type's 4 available effects (2 DPS + 2 support per type)
export const GEM_TYPES: Readonly<Record<string, readonly string[]>> = {
  order_stability: [
    "attack_power",
    "additional_damage",
    "ally_damage",
    "brand_power",
  ],
  order_fortitude: ["attack_power", "boss_damage", "ally_damage", "ally_attack"],
  order_immutability: [
    "additional_damage",
    "boss_damage",
    "brand_power",
    "ally_attack",
  ],
  chaos_erosion: ["attack_power", "additional_damage", "ally_damage", "brand_power"],
  chaos_distortion: ["attack_power", "boss_damage", "ally_damage", "ally_attack"],
  chaos_collapse: [
    "additional_damage",
    "boss_damage",
    "brand_power",
    "ally_attack",
  ],
};

// Expected total gem points per grade, from the processed-fusion point
// distribution in documentation/official_probability_info_en.md
// (Gem Fusion: Processed Gems -> Gem Points). Recipe-independent: the
// doc states points are determined by the result grade.
//   legendary: 4-15 pts   relic: 16(80%)/17(15%)/18(5%)   ancient: 19(95%)/20(5%)
export const FUSION_E_POINTS: Readonly<Record<"legendary" | "relic" | "ancient", number>> = {
  legendary: 9.62,
  relic: 16.25,
  ancient: 19.05,
};

/**
 * Python 3 banker's rounding (round-half-to-even).
 * When exactly halfway between two integers, rounds to the nearest even number.
 */
export function pyRound(x: number): number {
  const f = Math.floor(x);
  const diff = x - f;
  if (diff < 0.5) return f;
  if (diff > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;  // exactly .5 → nearest even
}

/**
 * Average side coefficient of a fused gem of `grade` for `gem_type`.
 *
 * Closed form derived from the processed-fusion mechanic: a gem of a
 * given grade has `FUSION_E_POINTS[grade]` total points spread uniformly
 * over the 4 options (each option averages E[points]/4 by exchange-
 * ability), and 2 effects drawn uniformly from the gem type's 4-effect
 * pool (each pool member is a given slot with probability 1/4). This
 * reduces to `pool_coeff_sum * E[points|grade] / 8`, where pool_coeff_sum
 * sums the optimize-side coefficients over the gem type's 4 effects
 * (non-target effects contribute 0).
 *
 * Returns 0 when the gem type is unknown.
 */
export function fusionAvgCoeff(gemType: string, optimize: string, grade: string): number {
  const pool = GEM_TYPES[gemType];
  if (!pool) {
    return 0;
  }
  const coeffMap = optimize === "dps" ? DPS_COEFF : SUPPORT_COEFF;
  const poolSum = pool.reduce((sum, effect) => sum + (coeffMap[effect] ?? 0), 0);
  const ePoints = FUSION_E_POINTS[grade as keyof typeof FUSION_E_POINTS] ?? 0;
  return pyRound(poolSum * ePoints / 8);
}

/**
 * Max optimize-side coefficient over the 2 effects either slot can
 * change_*_effect to (the gem-type pool members not currently equipped).
 * Returns 0 when the gem type is unknown or no destination contributes
 * to the optimize side.
 */
export function changeDestMaxCoeff(
  gemType: string,
  firstEffect: string,
  secondEffect: string,
  optimize: string
): number {
  const pool = GEM_TYPES[gemType];
  if (!pool) {
    return 0;
  }
  const coeffMap = optimize === "dps" ? DPS_COEFF : SUPPORT_COEFF;
  const maxCoeff = Math.max(
    ...pool
      .filter((e) => e !== firstEffect && e !== secondEffect)
      .map((e) => coeffMap[e] ?? 0),
    0
  );
  return maxCoeff;
}
