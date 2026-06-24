import { describe, it, expect } from 'vitest';
import { classifyRunTransition, inferResetFromLog } from '../../src/lib/app/runTransition';

const id = (gemType = 'order_stability', f = 'attack_power', s = 'boss_damage') => ({ gemType, firstEffect: f, secondEffect: s });

describe('classifyRunTransition', () => {
  it('continue when same identity, turn advances', () => {
    expect(classifyRunTransition({ turn: 2, id: id() }, { turn: 3, id: id() })).toBe('continue');
  });
  it('reset when same identity but turn drops to 1', () => {
    expect(classifyRunTransition({ turn: 4, id: id() }, { turn: 1, id: id() })).toBe('reset');
  });
  it('new-gem when identity changes', () => {
    expect(classifyRunTransition({ turn: 4, id: id() }, { turn: 1, id: id('chaos_distortion') })).toBe('new-gem');
  });
  it('continue (first observation) when prev is null', () => {
    expect(classifyRunTransition(null, { turn: 1, id: id() })).toBe('continue');
  });
});

describe('inferResetFromLog', () => {
  it('auto: available until a reset is observed', () => {
    expect(inferResetFromLog(false, 'auto')).toBe(true);
    expect(inferResetFromLog(true, 'auto')).toBe(false);
  });
  it('honors always/never', () => {
    expect(inferResetFromLog(true, 'always')).toBe(true);
    expect(inferResetFromLog(false, 'never')).toBe(false);
  });
});
