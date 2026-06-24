import { describe, it, expect } from 'vitest';
import { drawDetectionOverlay } from '../../src/lib/app/overlay';
import type { DetectionResult } from '../../src/lib/cv/types';

function stubCtx() {
  const calls: string[] = [];
  return {
    calls,
    strokeRect: () => calls.push('strokeRect'),
    fillText: () => calls.push('fillText'),
    set strokeStyle(_v: any) {}, set fillStyle(_v: any) {}, set font(_v: any) {}, set lineWidth(_v: any) {},
  } as any;
}
const det = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1, firstLevelScore: 0.9,
  secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1, secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9,
  currentStep: 5, stepScore: 0.9, totalSteps: 7, rarityScore: 0.9, anchor: { x: 895, y: 43 }, options: [], ...over,
});

describe('drawDetectionOverlay', () => {
  it('draws boxes + labels when an anchor is present', () => {
    const ctx = stubCtx(); drawDetectionOverlay(ctx, det(), 1);
    expect(ctx.calls.filter((c: string) => c === 'strokeRect').length).toBeGreaterThan(3);
    expect(ctx.calls).toContain('fillText');
  });
  it('no-ops without an anchor', () => {
    const ctx = stubCtx(); drawDetectionOverlay(ctx, det({ anchor: null }), 1);
    expect(ctx.calls.length).toBe(0);
  });
});
