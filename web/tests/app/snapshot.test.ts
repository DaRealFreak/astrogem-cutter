import { describe, it, expect } from 'vitest';
import { buildAdvisorSnapshot } from '../../src/lib/app/snapshot';
import { computeAdvice, resetAdviceCache } from '../../src/lib/app/computeAdvice';
import { DEFAULT_CONFIG } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';

const complete: DetectionResult = {
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9,
  totalSteps: 7, rarityScore: 0.9,
  options: [
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'chaos', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+2', deltaScore: 0.9 },
    { nameKey: 'view', nameScore: 0.9, deltaKey: 'reroll+1', deltaScore: 0.9 },
  ],
};

describe('buildAdvisorSnapshot', () => {
  it('produces a curated, serializable snapshot', () => {
    resetAdviceCache();
    const out = computeAdvice(complete, DEFAULT_CONFIG).output!;
    const snap = buildAdvisorSnapshot(complete, DEFAULT_CONFIG, out, []) as any;
    expect(snap.gem.gemType).toBe('order_stability');
    expect(snap.gem.first.effect).toBe('attack_power');
    expect(snap.gem.first.level).toBe(1);
    expect(snap.gem.freeRerolls).toBe(1);
    expect(snap.advice.action).toBe(out.action);
    expect(snap.advice.headline.pGoal).toBe(out.pGoal);
    expect(snap.advice.perOffer).toHaveLength(4);
    expect(snap.turnLog).toEqual([]);
    expect(() => JSON.stringify(snap)).not.toThrow();
  });
});
