import { describe, it, expect } from 'vitest';
import { classifyRunTransition, inferResetFromLog, resolveResetAvailable, turnFromDetection } from '../../src/lib/app/runTransition';
import type { DetectionResult } from '../../src/lib/cv/types';

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

describe('resolveResetAvailable', () => {
  it('detected brightness is authoritative under auto, overriding the log heuristic', () => {
    // log heuristic would say available (resetObserved=false) but detection says locked
    expect(resolveResetAvailable(false, false, 'auto')).toBe(false);
    // log heuristic would say unavailable (resetObserved=true) but detection says available
    expect(resolveResetAvailable(true, true, 'auto')).toBe(true);
  });
  it('falls back to the log heuristic when no detected value is present', () => {
    expect(resolveResetAvailable(undefined, false, 'auto')).toBe(true);
    expect(resolveResetAvailable(null, true, 'auto')).toBe(false);
  });
  it('manual override wins over detection', () => {
    expect(resolveResetAvailable(false, false, 'always')).toBe(true);
    expect(resolveResetAvailable(true, false, 'never')).toBe(false);
  });
});

describe('turnFromDetection', () => {
  const base = { totalSteps: 9, currentStep: 8 } as unknown as DetectionResult;
  it('maps step 8/9 to turn 2', () => {
    expect(turnFromDetection(base)).toBe(2);
  });
  it('maps step total/total to turn 1 (run start / post-reset)', () => {
    expect(turnFromDetection({ totalSteps: 7, currentStep: 7 } as unknown as DetectionResult)).toBe(1);
  });
  it('treats missing steps as 0 → turn 1', () => {
    expect(turnFromDetection({} as DetectionResult)).toBe(1);
  });
});
