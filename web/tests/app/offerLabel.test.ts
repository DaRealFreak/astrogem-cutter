import { describe, it, expect } from 'vitest';
import { offerLabel } from '../../src/lib/app/offerLabel';
import type { DetectionResult } from '../../src/lib/cv/types';

const makeDet = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: null, firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: null, secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9,
  totalSteps: 7, rarityScore: 0.9, options: [], ...over,
});

describe('offerLabel', () => {
  it('second+1 with additional_damage secondEffect → "Additional Damage +1"', () => {
    const det = makeDet({ secondEffect: 'additional_damage' });
    expect(offerLabel('second+1', det)).toBe('Additional Damage +1');
  });

  it('first+1 with attack_power firstEffect → "Attack Power +1"', () => {
    const det = makeDet({ firstEffect: 'attack_power' });
    expect(offerLabel('first+1', det)).toBe('Attack Power +1');
  });

  it('will+1 → "Willpower +1"', () => {
    expect(offerLabel('will+1', null)).toBe('Willpower +1');
  });

  it('chaos+1 → "Chaos +1"', () => {
    expect(offerLabel('chaos+1', null)).toBe('Chaos +1');
  });

  it('reroll+1 → "View other options (+1)"', () => {
    expect(offerLabel('reroll+1', null)).toBe('View other options (+1)');
  });

  it('change_first_effect → "Change 1st effect"', () => {
    expect(offerLabel('change_first_effect', null)).toBe('Change 1st effect');
  });

  it('first+1 with null det → "1st node +1"', () => {
    expect(offerLabel('first+1', null)).toBe('1st node +1');
  });
});
