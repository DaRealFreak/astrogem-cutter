import { describe, it, expect } from 'vitest';
import { GEM_TYPES, DPS_COEFF, fusionAvgCoeff, changeDestMaxCoeff, pyRound } from '../src/lib/engine/constants';

describe('constants', () => {
  it('matches gem-type pools and coeffs', () => {
    expect(GEM_TYPES['chaos_distortion']).toEqual(
      ['attack_power', 'boss_damage', 'ally_damage', 'ally_attack']);
    expect(DPS_COEFF['boss_damage']).toBe(1000);
  });
  it('pyRound uses banker rounding', () => {
    expect(pyRound(0.5)).toBe(0);   // Python round(0.5) == 0
    expect(pyRound(1.5)).toBe(2);
    expect(pyRound(2.5)).toBe(2);
  });
  it('fusionAvgCoeff: chaos_distortion dps relic', () => {
    // pool dps coeffs: attack_power 400 + boss_damage 1000 = 1400 (ally_* are support → 0)
    // 1400 * 16.25 / 8 = 2843.75 → pyRound → 2844
    expect(fusionAvgCoeff('chaos_distortion', 'dps', 'relic')).toBe(2844);
    expect(fusionAvgCoeff('unknown', 'dps', 'relic')).toBe(0);
  });
  it('changeDestMaxCoeff excludes equipped effects', () => {
    // pool: attack_power(400), boss_damage(1000), ally_damage(0 for dps), ally_attack(0)
    // equipped first=attack_power, second=ally_damage → dests boss_damage(1000), ally_attack(0) → 1000
    expect(changeDestMaxCoeff('chaos_distortion', 'attack_power', 'ally_damage', 'dps')).toBe(1000);
  });
});
