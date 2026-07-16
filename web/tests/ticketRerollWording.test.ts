import { describe, it, expect } from 'vitest';
import { decidePostRoll } from '../src/lib/engine/decision';
import { buildEngineContext, ActionKind } from '../src/lib/engine';
import { OptionPool } from '../src/lib/engine/pool';
import { GemState } from '../src/lib/engine/models';

// Mirror of tests/test_decision.py::TestSideValueFinish ticket-wording tests.
// Regression (2026-07-16): the web advisor claimed "spending a free reroll"
// while the yellow Charge button was visible — i.e. 0 free rerolls, the only
// reroll in the budget being the lent gold-costing reroll ticket. The reason
// must name the ticket in that case, and only claim "free" while a genuine
// free reroll remains.
describe('reroll reason wording: lent ticket vs free reroll', () => {
  const pool = new OptionPool();
  const byKey = new Map(pool.pool.map((o) => [o.key, o]));

  const eng = buildEngineContext(
    { gemType: 'order_fortitude', firstEffect: 'boss_damage', secondEffect: 'attack_power', optimize: 'dps' },
    { rarity: 'epic', minWill: 4, minChaos: 4 },
  );

  function decide(rerolls: number, ticketLent: boolean) {
    // Goal met, gem improvable, all 4 offers are degrades -> REROLL wins.
    const st = new GemState({
      will: 4, chaos: 4, first: 3, second: 3,
      firstEffect: 'boss_damage', secondEffect: 'attack_power', rerolls,
    });
    const offers = ['will-1', 'chaos-1', 'first-1', 'second-1'].map((k) => byKey.get(k)!);
    return decidePostRoll(eng._decisionCtx, {
      state: st, offers, turn: 5, turnsLeft: 5, rerolls, resetAvailable: false, ticketLent,
    });
  }

  it('names the reroll ticket when it is the only reroll in the budget', () => {
    const d = decide(1, true);
    expect(d.action).toBe(ActionKind.REROLL);
    expect(d.reason).toContain('reroll ticket');
    expect(d.reason).not.toContain('free reroll');
  });

  it('says free while a genuine free reroll remains (ticket lent on top)', () => {
    const d = decide(2, true);
    expect(d.action).toBe(ActionKind.REROLL);
    expect(d.reason).toContain('free reroll');
  });

  it('says free when the budget is all free rerolls (no ticket lent)', () => {
    const d = decide(1, false);
    expect(d.action).toBe(ActionKind.REROLL);
    expect(d.reason).toContain('free reroll');
  });
});
