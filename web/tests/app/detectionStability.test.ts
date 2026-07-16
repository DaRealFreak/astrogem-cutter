import { describe, it, expect } from 'vitest';
import { DetectionStabilizer, detectionSignature, STABILITY_FRAMES } from '../../src/lib/app/detectionStability';
import type { DetectionResult } from '../../src/lib/cv/types';

const base: DetectionResult = {
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, resetEnabled: true, resetScore: 0.08,
  currentStep: 5, stepScore: 0.9, totalSteps: 7, rarityScore: 0.9,
  options: [
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'chaos', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+2', deltaScore: 0.9 },
    { nameKey: 'view', nameScore: 0.9, deltaKey: 'reroll+1', deltaScore: 0.9 },
  ],
};

describe('detectionSignature', () => {
  it('ignores cosmetic score/anchor jitter', () => {
    const jittered: DetectionResult = {
      ...base, gemTypeScore: 0.71, willpowerScore: 0.5, resetScore: 0.07,
      anchor: { x: 895, y: 43 },
      options: base.options.map((o) => ({ ...o, nameScore: 0.6, deltaScore: 0.6 })),
    };
    expect(detectionSignature(jittered)).toBe(detectionSignature(base));
  });

  it('changes when an advice-relevant field changes', () => {
    expect(detectionSignature({ ...base, willpower: 4 })).not.toBe(detectionSignature(base));
    expect(detectionSignature({ ...base, resetEnabled: false })).not.toBe(detectionSignature(base));
    expect(detectionSignature({ ...base, currentStep: 4 })).not.toBe(detectionSignature(base));
    // chargeEnabled drives the ticket-spent latch — a one-frame brightness blip
    // must not commit (it falsely latched "ticket already used this gem").
    expect(detectionSignature({ ...base, chargeEnabled: false }))
      .not.toBe(detectionSignature({ ...base, chargeEnabled: true }));
  });

  it('changes when an offer changes', () => {
    const rerolled = {
      ...base,
      options: [{ nameKey: 'first', nameScore: 0.9, deltaKey: '1_line_lvl2', deltaScore: 0.9 }, ...base.options.slice(1)],
    };
    expect(detectionSignature(rerolled)).not.toBe(detectionSignature(base));
  });
});

describe('DetectionStabilizer', () => {
  it('commits exactly once after the signature holds for STABILITY_FRAMES', () => {
    const s = new DetectionStabilizer();
    const sig = detectionSignature(base);
    const results = [];
    for (let i = 0; i < 5; i++) results.push(s.push(sig));
    // false until the 3rd identical reading, true once, then false again
    expect(results).toEqual([false, false, true, false, false]);
    expect(STABILITY_FRAMES).toBe(3);
  });

  it('restarts the streak when the signature changes (filters transient misreads)', () => {
    const s = new DetectionStabilizer();
    const a = detectionSignature(base);
    const b = detectionSignature({ ...base, willpower: 4 });
    expect(s.push(a)).toBe(false);
    expect(s.push(a)).toBe(false);
    // a transient misread on frame 3 resets the streak — no commit
    expect(s.push(b)).toBe(false);
    expect(s.push(a)).toBe(false); // back to a, streak restarted at 1
    expect(s.push(a)).toBe(false);
    expect(s.push(a)).toBe(true);  // now 3 consecutive a's
  });

  it('a settled signature commits a second time only after another full streak', () => {
    const s = new DetectionStabilizer();
    const a = detectionSignature(base);
    const b = detectionSignature({ ...base, willpower: 5 });
    expect([s.push(a), s.push(a), s.push(a)]).toEqual([false, false, true]);
    // switch to b and settle → second commit
    expect([s.push(b), s.push(b), s.push(b)]).toEqual([false, false, true]);
  });

  it('null signature resets the streak', () => {
    const s = new DetectionStabilizer();
    const sig = detectionSignature(base);
    s.push(sig);
    s.push(sig);
    expect(s.push(null)).toBe(false); // incomplete/off-screen frame
    expect(s.push(sig)).toBe(false);  // streak restarted
    expect(s.push(sig)).toBe(false);
    expect(s.push(sig)).toBe(true);
  });

  it('honors a custom frame threshold', () => {
    const s = new DetectionStabilizer(2);
    const sig = detectionSignature(base);
    expect([s.push(sig), s.push(sig), s.push(sig)]).toEqual([false, true, false]);
  });
});
