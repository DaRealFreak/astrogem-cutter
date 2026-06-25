import { describe, it, expect } from 'vitest';
import { buildEngineContext, type AdvisorConfig } from '../src/lib/engine';
import { ticketEnabled } from '../src/lib/engine/decision';
import { GemState } from '../src/lib/engine/models';

// Mirror of tests/test_decision.py::TestTicketEnabled. The extra ticket is
// re-evaluated every frame, OR-ing the enablers (relic/goal use the free+1
// look-ahead; coeff is reroll-independent and goal-conditioned).
function ctxFor(config: AdvisorConfig) {
  return buildEngineContext(
    { gemType: 'order_fortitude', firstEffect: 'attack_power', secondEffect: 'boss_damage', optimize: 'dps' },
    config,
  )._decisionCtx;
}
const live = () => new GemState({
  will: 3, chaos: 2, first: 2, second: 2,
  firstEffect: 'attack_power', secondEffect: 'boss_damage',
});

describe('ticketEnabled', () => {
  it('false when no enabler is set', () => {
    const ctx = ctxFor({ rarity: 'epic', minTotalWillChaos: 7 });
    expect(ticketEnabled(ctx, live(), 5, 2)).toBe(false);
  });

  it('extraTicket force-on => always true', () => {
    const ctx = ctxFor({ rarity: 'epic', minTotalWillChaos: 7, extraTicket: true });
    expect(ticketEnabled(ctx, live(), 1, 0)).toBe(true);
  });

  it('relic threshold enables when P(relic+) clears the bar, not otherwise', () => {
    expect(ticketEnabled(
      ctxFor({ rarity: 'epic', minTotalWillChaos: 7, relicRerollThreshold: 1e-6 }),
      live(), 5, 2)).toBe(true);
    expect(ticketEnabled(
      ctxFor({ rarity: 'epic', minTotalWillChaos: 7, relicRerollThreshold: 0.999 }),
      live(), 5, 2)).toBe(false);
  });

  it('coeff enabler requires a live goal', () => {
    const liveCtx = ctxFor({ rarity: 'epic', minWill: 4, minChaos: 3, rerollMinCoeff: 1 });
    const stLive = new GemState({
      will: 3, chaos: 2, first: 3, second: 3,
      firstEffect: 'attack_power', secondEffect: 'boss_damage',
    });
    expect(ticketEnabled(liveCtx, stLive, 6, 2)).toBe(true);

    // will=4,chaos=4, 1 turn left, goal needs 5/5 -> dead -> expected coeff ~0.
    const deadCtx = ctxFor({ rarity: 'epic', minWill: 5, minChaos: 5, rerollMinCoeff: 1 });
    const stDead = new GemState({
      will: 4, chaos: 4, first: 5, second: 5,
      firstEffect: 'attack_power', secondEffect: 'boss_damage',
    });
    expect(ticketEnabled(deadCtx, stDead, 1, 2)).toBe(false);
  });
});
