import { describe, it, expect, beforeEach } from 'vitest';
import { computeAdvice, resetAdviceCache } from '../../src/lib/app/computeAdvice';
import { DEFAULT_CONFIG } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';
import { ActionKind } from '../../src/lib/engine';

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

describe('computeAdvice', () => {
  beforeEach(() => resetAdviceCache());

  it('gates incomplete detections', () => {
    expect(computeAdvice({ ...complete, found: false }, DEFAULT_CONFIG).ready).toBe(false);
  });

  it('produces a coherent recommendation for a complete detection', () => {
    const { ready, output } = computeAdvice(complete, DEFAULT_CONFIG);
    expect(ready).toBe(true);
    expect(output).not.toBeNull();
    expect(Object.values(ActionKind)).toContain(output!.action);
    for (const p of [output!.pGoal, output!.pRelic, output!.pAncient]) {
      expect(p).toBeGreaterThanOrEqual(0); expect(p).toBeLessThanOrEqual(1);
    }
    expect(output!.perOffer).toHaveLength(4);
  });

  it('is deterministic across repeated calls (cache reuse)', () => {
    const a = computeAdvice(complete, DEFAULT_CONFIG).output!;
    const b = computeAdvice(complete, DEFAULT_CONFIG).output!;
    expect(b.action).toBe(a.action);
    expect(b.pGoal).toBeCloseTo(a.pGoal, 12);
  });

  it('resetObserved=false (default) makes reset available under auto override', () => {
    // With resetOverride='auto' and resetObserved=false, reset should be available
    const { output } = computeAdvice(complete, DEFAULT_CONFIG);
    expect(output!.actions.reset).not.toBeNull();
  });

  it('resetObserved=true makes reset unavailable under auto override', () => {
    // With resetOverride='auto' and resetObserved=true, reset ticket is spent
    const { output } = computeAdvice(complete, DEFAULT_CONFIG, true);
    expect(output!.actions.reset).toBeNull();
  });

  it('resetOverride=always forces reset available even when resetObserved=true', () => {
    const { output } = computeAdvice(complete, { ...DEFAULT_CONFIG, resetOverride: 'always' }, true);
    expect(output!.actions.reset).not.toBeNull();
  });

  it('resetOverride=never forces reset unavailable even when resetObserved=false', () => {
    const { output } = computeAdvice(complete, { ...DEFAULT_CONFIG, resetOverride: 'never' }, false);
    expect(output!.actions.reset).toBeNull();
  });

  it('detected resetEnabled=false locks reset under auto, even with resetObserved=false', () => {
    // Brightness says the button is greyed → reset unavailable, despite the log
    // heuristic (resetObserved=false) implying it is still available.
    const det = { ...complete, resetEnabled: false };
    const { output } = computeAdvice(det, DEFAULT_CONFIG, false);
    expect(output!.actions.reset).toBeNull();
  });

  it('detected resetEnabled=true keeps reset available under auto, even with resetObserved=true', () => {
    const det = { ...complete, resetEnabled: true };
    const { output } = computeAdvice(det, DEFAULT_CONFIG, true);
    expect(output!.actions.reset).not.toBeNull();
  });

  it('reset coeff gate suppresses reset when the gem is below the bar', () => {
    // complete gem coeff = attack_power(400)+boss_damage(1000) = 1400
    const det = { ...complete, resetEnabled: true };
    expect(computeAdvice(det, { ...DEFAULT_CONFIG, resetMinCoeff: 1000 }, false).output!.actions.reset).not.toBeNull();
    expect(computeAdvice(det, { ...DEFAULT_CONFIG, resetMinCoeff: 5000 }, false).output!.actions.reset).toBeNull();
  });

  it('reset rarity gate suppresses reset below the rarity bar', () => {
    // complete is a rare gem (totalSteps 7)
    const det = { ...complete, resetEnabled: true };
    expect(computeAdvice(det, { ...DEFAULT_CONFIG, resetTicketRarity: 'epic' }, false).output!.actions.reset).toBeNull();
  });
});
