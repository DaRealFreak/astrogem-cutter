import { describe, it, expect } from 'vitest';
import { initTicketLatch, observeTicketLatch } from '../../src/lib/app/ticketLatch';
import type { DetectionResult } from '../../src/lib/cv/types';

function det(over: Partial<DetectionResult> = {}): DetectionResult {
  return {
    found: true, gemType: 'order_solidity', gemTypeScore: 1,
    willpower: 1, willpowerScore: 1, chaos: 1, chaosScore: 1,
    firstEffect: 'attack_power', firstEffectScore: 1, firstLevel: 1, firstLevelScore: 1,
    secondEffect: 'boss_damage', secondEffectScore: 1, secondLevel: 1, secondLevelScore: 1,
    rerolls: '0', rerollsScore: 1, currentStep: 5, stepScore: 1, totalSteps: 7, rarityScore: 1,
    options: [], ...over,
  };
}

describe('ticketLatch', () => {
  it('latches spent when Charge is greyed with no free rerolls', () => {
    const s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false }), 0);
    expect(s.spent).toBe(true);
  });

  it('does not latch while free rerolls remain', () => {
    const s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false }), 2);
    expect(s.spent).toBe(false);
  });

  it('does not latch when Charge is still available', () => {
    const s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: true }), 0);
    expect(s.spent).toBe(false);
  });

  // REGRESSION: stateless over-lending. Spend the charge (free 0, greyed), then
  // free rerolls replenish (+N pool option) so Charge is no longer shown. The
  // latch must REMEMBER spent within the same cutting process.
  it('keeps spent after free rerolls replenish in the same run', () => {
    let s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false, currentStep: 5 }), 0);
    s = observeTicketLatch(s, det({ chargeEnabled: null, currentStep: 4 }), 2);
    expect(s.spent).toBe(true);
  });

  it('clears spent on a new gem', () => {
    let s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false, currentStep: 5 }), 0);
    s = observeTicketLatch(s, det({ gemType: 'chaos_distortion', currentStep: 7 }), 0);
    expect(s.spent).toBe(false);
  });

  it('clears spent on a reset (fresh cutting process → fresh ticket)', () => {
    let s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false, currentStep: 3 }), 0); // turn 5
    s = observeTicketLatch(s, det({ chargeEnabled: null, currentStep: 7 }), 1); // turn 1 → reset
    expect(s.spent).toBe(false);
  });
});
