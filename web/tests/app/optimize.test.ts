import { describe, it, expect } from 'vitest';
import { resolveOptimize, inferResetAvailable, isCompleteDetection } from '../../src/lib/app/optimize';
import type { DetectionResult } from '../../src/lib/cv/types';

const complete = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9,
  willpower: 3, willpowerScore: 0.9, chaos: 2, chaosScore: 0.9,
  firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1, firstLevelScore: 0.9,
  secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1, secondLevelScore: 0.9,
  rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9, totalSteps: 7, rarityScore: 0.9,
  options: Array.from({ length: 4 }, () => ({ nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 })),
  ...over,
});

describe('resolveOptimize', () => {
  it('honors an explicit override', () => { expect(resolveOptimize('attack_power', 'boss_damage', 'support')).toBe('support'); });
  it('returns dps for DPS effects', () => { expect(resolveOptimize('attack_power', 'boss_damage', 'auto')).toBe('dps'); });
  it('returns support for support effects', () => { expect(resolveOptimize('ally_damage', 'brand_power', 'auto')).toBe('support'); });
});

describe('inferResetAvailable', () => {
  it('auto → available only on turn 1', () => {
    expect(inferResetAvailable(1)).toBe(true);
    expect(inferResetAvailable(2)).toBe(false);
  });
  it('honors always/never', () => {
    expect(inferResetAvailable(5, 'always')).toBe(true);
    expect(inferResetAvailable(1, 'never')).toBe(false);
  });
});

describe('isCompleteDetection', () => {
  it('passes a full confident detection', () => { expect(isCompleteDetection(complete())).toBe(true); });
  it('rejects unfound / missing fields / low score / wrong option count', () => {
    expect(isCompleteDetection(complete({ found: false }))).toBe(false);
    expect(isCompleteDetection(complete({ gemType: null }))).toBe(false);
    expect(isCompleteDetection(complete({ willpower: null }))).toBe(false);
    expect(isCompleteDetection(complete({ totalSteps: null }))).toBe(false);
    expect(isCompleteDetection(complete({ gemTypeScore: 0.1 }))).toBe(false);
    expect(isCompleteDetection(complete({ options: [] }))).toBe(false);
  });
});
