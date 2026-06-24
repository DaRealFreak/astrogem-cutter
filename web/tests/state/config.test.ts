import { describe, it, expect } from 'vitest';
import { DEFAULT_CONFIG, effectiveConfig } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';

const det = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9,
  totalSteps: 7, rarityScore: 0.9, options: [], ...over,
});

describe('DEFAULT_CONFIG', () => {
  it('uses Python defaults for behavioral knobs', () => {
    expect(DEFAULT_CONFIG.relicCoeff).toBeNull();         // fusion-default resolved in engine
    expect(DEFAULT_CONFIG.ancientCoeff).toBeNull();
    expect(DEFAULT_CONFIG.relicRerollThreshold).toBe(0);
    expect(DEFAULT_CONFIG.forceRerollNoProgress).toBe(0);
    expect(DEFAULT_CONFIG.endgameRisk).toBeNull();        // null → engine auto-gate
    expect(DEFAULT_CONFIG.ignoreSideNodeValues).toBe(false);
    expect(DEFAULT_CONFIG.extraTicket).toBeNull();        // off-but-armed
    expect(DEFAULT_CONFIG.optimizeOverride).toBe('auto');
    expect(DEFAULT_CONFIG.rarityOverride).toBe('auto');
    expect(DEFAULT_CONFIG.resetOverride).toBe('auto');
  });
});

describe('effectiveConfig', () => {
  it('derives rarity from detected totalSteps when rarity is auto', () => {
    expect(effectiveConfig(DEFAULT_CONFIG, det({ totalSteps: 7 })).advisorConfig.rarity).toBe('rare');
    expect(effectiveConfig(DEFAULT_CONFIG, det({ totalSteps: 9 })).advisorConfig.rarity).toBe('epic');
  });
  it('honors a manual rarity override', () => {
    expect(effectiveConfig({ ...DEFAULT_CONFIG, rarityOverride: 'common' }, det()).advisorConfig.rarity).toBe('common');
  });
  it('auto-resolves optimize from detected effects', () => {
    expect(effectiveConfig(DEFAULT_CONFIG, det()).optimize).toBe('dps');
  });
  it('maps null endgameRisk to undefined (engine auto-gate)', () => {
    expect(effectiveConfig(DEFAULT_CONFIG, det()).advisorConfig.endgameRisk).toBeUndefined();
  });
});

describe('goalMode', () => {
  it("defaults to separate (today's behavior)", () => {
    expect(DEFAULT_CONFIG.goalMode).toBe('separate');
  });
  it('separate sets minWill/minChaos and leaves minTotalWillChaos undefined', () => {
    const ac = effectiveConfig({ ...DEFAULT_CONFIG, goalMode: 'separate', minWill: 4, minChaos: 5, minWillChaosTotal: 8 }, det()).advisorConfig;
    expect(ac.minWill).toBe(4);
    expect(ac.minChaos).toBe(5);
    expect(ac.minTotalWillChaos).toBeUndefined();
  });
  it('combined sets minTotalWillChaos and leaves minWill/minChaos undefined', () => {
    const ac = effectiveConfig({ ...DEFAULT_CONFIG, goalMode: 'combined', minWill: 4, minChaos: 5, minWillChaosTotal: 8 }, det()).advisorConfig;
    expect(ac.minTotalWillChaos).toBe(8);
    expect(ac.minWill).toBeUndefined();
    expect(ac.minChaos).toBeUndefined();
  });
});
