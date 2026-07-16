import { describe, it, expect } from 'vitest';
import { TurnStateLatch } from '../../src/lib/app/turnStateLatch';
import type { DetectionResult } from '../../src/lib/cv/types';

// A settled turn-2 reading of an epic order gem (step counts down: 8/9 = turn 2).
const base: DetectionResult = {
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 1, willpowerScore: 0.9,
  chaos: 1, chaosScore: 0.9, firstEffect: 'additional_damage', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'attack_power', secondEffectScore: 0.9, secondLevel: 2,
  secondLevelScore: 0.9, rerolls: '2', rerollsScore: 0.9, resetEnabled: true, resetScore: 0.08,
  currentStep: 8, stepScore: 0.9, totalSteps: 9, rarityScore: 0.9,
  options: [
    { nameKey: 'will', nameScore: 0.9, deltaKey: '2_line_+3', deltaScore: 0.9 },
    { nameKey: 'additional_damage', nameScore: 0.9, deltaKey: '2_line_lvl+3', deltaScore: 0.9 },
    { nameKey: 'attack_power', nameScore: 0.9, deltaKey: '1_line_lvl+3', deltaScore: 0.9 },
    { nameKey: 'attack_power', nameScore: 0.9, deltaKey: '1_line_effect_changed', deltaScore: 0.9 },
  ],
};

describe('TurnStateLatch', () => {
  it('accepts and pins the first reading of a turn', () => {
    expect(new TurnStateLatch().accept(base)).toBe(true);
  });

  it('rejects a same-turn reading whose stats differ (hover preview)', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    // hovering "attack_power Lv.+3" at Lv.2 previews the side node as Lv.5
    expect(latch.accept({ ...base, secondLevel: 5 })).toBe(false);
    // hovering "will +3" previews willpower 4
    expect(latch.accept({ ...base, willpower: 4 })).toBe(false);
    // the un-hovered true state keeps passing
    expect(latch.accept(base)).toBe(true);
  });

  it('rejects a same-turn offer change without a reroll spend (cursor on a card)', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    const corrupted = {
      ...base,
      options: [{ ...base.options[0], deltaKey: '2_line_+1' }, ...base.options.slice(1)],
    };
    expect(latch.accept(corrupted)).toBe(false);
  });

  it('accepts a same-turn offer change when the reroll count moved (real reroll)', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    const rerolled = {
      ...base,
      rerolls: '1',
      options: [{ ...base.options[0], deltaKey: '2_line_+1' }, ...base.options.slice(1)],
    };
    expect(latch.accept(rerolled)).toBe(true);
    // and the rerolled hand is now the pinned state
    expect(latch.accept({ ...rerolled, secondLevel: 5 })).toBe(false);
  });

  it('re-pins on a step change (processing applied)', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    const nextTurn = { ...base, currentStep: 7, secondLevel: 5, rerolls: '2' };
    expect(latch.accept(nextTurn)).toBe(true);
    expect(latch.accept({ ...nextTurn, secondLevel: 2 })).toBe(false);
  });

  it('re-pins on a new gem (identity change) even at the same turn number', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    const newGem = { ...base, gemType: 'chaos_corrosion', willpower: 3 };
    expect(latch.accept(newGem)).toBe(true);
  });

  it('re-pins on a reset (same identity, turn back to 1)', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    const afterReset = { ...base, currentStep: 9, willpower: 1, chaos: 1, secondLevel: 1 };
    expect(latch.accept(afterReset)).toBe(true);
  });

  it('reset() forgets the pin', () => {
    const latch = new TurnStateLatch();
    latch.accept(base);
    latch.reset();
    expect(latch.accept({ ...base, secondLevel: 5 })).toBe(true);
  });
});
