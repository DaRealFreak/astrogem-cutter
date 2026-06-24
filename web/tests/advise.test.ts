import { describe, it, expect } from 'vitest';
import { buildEngineContext, advise } from '../src/lib/engine';
import { GemState } from '../src/lib/engine/models';
import { OptionPool } from '../src/lib/engine/pool';

describe('advise()', () => {
  const pool = new OptionPool();
  const byKey = new Map(pool.pool.map(o => [o.key, o]));
  const ctx = buildEngineContext(
    { gemType: 'chaos_distortion', firstEffect: 'attack_power',
      secondEffect: 'ally_damage', optimize: 'dps' },
    { rarity: 'epic', minWill: 4, minChaos: 5 });

  it('returns a coherent advisory for a fresh gem', () => {
    const st = new GemState({ firstEffect: 'attack_power', secondEffect: 'ally_damage' });
    const offers = ['will+1', 'chaos+1', 'first+1', 'second+1'].map(k => byKey.get(k)!);
    const out = advise(ctx, { state: st, offers, turn: 1, turnsLeft: 9, rerolls: 0, resetAvailable: false });
    expect(['process','reroll','reset','finish','fail']).toContain(out.action);
    expect(out.pGoal).toBeGreaterThanOrEqual(0);
    expect(out.pGoal).toBeLessThanOrEqual(1);
    expect(out.pRelic).toBeGreaterThanOrEqual(out.pAncient); // relic+ ⊇ ancient
    expect(out.perOffer).toHaveLength(4);
  });

  it('reports goal met at the cap', () => {
    const st = new GemState({ will: 5, chaos: 5, first: 5, second: 5,
      firstEffect: 'attack_power', secondEffect: 'ally_damage' });
    const out = advise(ctx, { state: st, offers:
      ['will-1','chaos-1','first-1','second-1'].map(k => byKey.get(k)!),
      turn: 9, turnsLeft: 1, rerolls: 0, resetAvailable: false });
    expect(out.pGoal).toBe(1);
  });
});
