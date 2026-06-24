import { describe, it, expect } from 'vitest';
import { detectionToEngineInputs, parseViewDelta } from '../../src/lib/cv/adapter';
import type { DetectionResult } from '../../src/lib/cv/recognizer';

const baseDet = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'chaos_distortion', gemTypeScore: 1,
  willpower: 3, willpowerScore: 1, chaos: 2, chaosScore: 1,
  firstEffect: 'attack_power', firstEffectScore: 1, firstLevel: 2, firstLevelScore: 1,
  secondEffect: 'ally_damage', secondEffectScore: 1, secondLevel: 1, secondLevelScore: 1,
  rerolls: '1', rerollsScore: 1, currentStep: 4, stepScore: 1, totalSteps: 9, rarityScore: 1,
  options: [
    { nameKey: 'will', nameScore: 1, deltaKey: '1_line_lvl+2', deltaScore: 1 },
    { nameKey: 'attack_power', nameScore: 1, deltaKey: '1_line_lvl+3', deltaScore: 1 },
    { nameKey: 'view', nameScore: 1, deltaKey: 'reroll+1', deltaScore: 1 },
    { nameKey: 'cost', nameScore: 1, deltaKey: 'cost+100', deltaScore: 1 },
  ], ...over,
});

describe('adapter', () => {
  it('parseViewDelta', () => {
    expect(parseViewDelta('reroll+1')).toBe(1);
    expect(parseViewDelta('reroll+2')).toBe(2);
    expect(parseViewDelta(null)).toBe(0);
  });

  it('maps turns via turnsLeft = currentStep', () => {
    const i = detectionToEngineInputs(baseDet(), { optimize: 'dps' });
    expect(i.turnsLeft).toBe(4);
    expect(i.turnsTotal).toBe(9);
    expect(i.turn).toBe(6);            // 9 - 4 + 1
  });

  it('domain-maps the gem type and builds state', () => {
    const i = detectionToEngineInputs(baseDet({ gemType: 'order_solidity' }), { optimize: 'dps' });
    expect(i.gem.gemType).toBe('order_fortitude');
    expect(i.state.will).toBe(3); expect(i.state.chaos).toBe(2);
    expect(i.state.first).toBe(2); expect(i.state.second).toBe(1);
    expect(i.state.firstEffect).toBe('attack_power');
  });

  it('builds offers with the right keys/kinds/deltas', () => {
    const i = detectionToEngineInputs(baseDet(), { optimize: 'dps' });
    const byKind = Object.fromEntries(i.offers.map((o) => [o.kind, o]));
    expect(byKind['will']).toMatchObject({ key: 'will+2', delta: 2 });
    expect(byKind['first']).toMatchObject({ key: 'first+3', delta: 3 });  // attack_power == firstEffect
    expect(byKind['view']).toMatchObject({ delta: 1 });
    expect(byKind['cost']).toMatchObject({ key: 'cost+100', delta: 0 });
    expect(i.offers).toHaveLength(4);
  });

  it('rerolls from parseRerolls', () => {
    expect(detectionToEngineInputs(baseDet({ rerolls: '2' }), { optimize: 'dps' }).rerolls).toBe(2);
  });
});
