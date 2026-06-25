import { describe, it, expect } from 'vitest';
import { decidePostRoll } from '../src/lib/engine/decision';
import { buildEngineContext, ActionKind } from '../src/lib/engine';
import { OptionPool } from '../src/lib/engine/pool';
import { GemState } from '../src/lib/engine/models';

// Mirror of tests/test_decision.py::TestRelicRerollThresholdTicketOnly.
// `relicRerollThreshold` gates only the gold-costing extra ticket (its arming),
// never free rerolls. A dead gem with free rerolls that can still reach relic+
// must keep chasing, not finish.
describe('relicRerollThreshold gates only the extra ticket', () => {
  const pool = new OptionPool();
  const byKey = new Map(pool.pool.map((o) => [o.key, o]));

  function decide(relicRerollThreshold: number): ActionKind {
    // order_fortitude (epic): pool holds both equipped effects. Goal needs
    // will+chaos >= 10, impossible from 6 in one turn -> dead. first=1 can still
    // reach relic+ (first+4 -> total 16) with a free reroll, but P(relic+) is
    // well below 0.1.
    const eng = buildEngineContext(
      { gemType: 'order_fortitude', firstEffect: 'ally_damage', secondEffect: 'ally_attack', optimize: 'dps' },
      { rarity: 'epic', minTotalWillChaos: 10, relicRerollThreshold },
    );
    const st = new GemState({
      will: 3, chaos: 3, first: 1, second: 5,
      firstEffect: 'ally_damage', secondEffect: 'ally_attack', rerolls: 3,
    });
    const offers = ['chaos+2', 'first+1', 'will+1', 'first+2'].map((k) => byKey.get(k)!);
    return decidePostRoll(eng._decisionCtx, {
      state: st, offers, turn: 9, turnsLeft: 1, rerolls: 3, resetAvailable: false,
    }).action;
  }

  it('does not finish a dead gem below threshold while free rerolls can chase relic+', () => {
    expect(decide(0.1)).toBe(ActionKind.REROLL);
  });

  it('decides identically with the threshold set or unset (no force-finish)', () => {
    expect(decide(0.1)).toBe(decide(0));
  });
});
