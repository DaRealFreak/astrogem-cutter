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

  it('P(bot): a finished gem is certain, a locked-in goal reads 100%', () => {
    // Maxed gem, every offer is a downgrade: the advice is to finish, and a
    // finished goal-meeting gem is a success for certain.
    const st = new GemState({ will: 5, chaos: 5, first: 5, second: 5,
      firstEffect: 'attack_power', secondEffect: 'ally_damage' });
    const out = advise(ctx, { state: st, offers:
      ['will-1','chaos-1','first-1','second-1'].map(k => byKey.get(k)!),
      turn: 9, turnsLeft: 1, rerolls: 0, resetAvailable: false });
    expect(out.action).toBe('finish');
    expect(out.pBot).toBe(1);
  });

  it('P(bot): below P(goal) without a reset ticket, far above it with one', () => {
    const st = new GemState({ firstEffect: 'attack_power', secondEffect: 'ally_damage' });
    const offers = ['will+1', 'chaos+1', 'first+1', 'second+1'].map(k => byKey.get(k)!);
    const base = { state: st, offers, turn: 1, turnsLeft: 9, rerolls: 2 };
    const plain = advise(ctx, { ...base, resetAvailable: false });
    const withReset = advise(ctx, { ...base, resetAvailable: true });
    // Stop-when-met is the most success any policy can have (no reset).
    expect(plain.actions.process!.pBot).toBeLessThan(plain.actions.process!.pGoal);
    expect(plain.actions.process!.pBot).toBeGreaterThan(plain.actions.process!.pGoal - 0.03);
    // The reset ticket is a second cutting process.
    expect(withReset.actions.process!.pBot).toBeGreaterThan(plain.actions.process!.pBot + 0.03);
    // The reset row itself has no further reset to fall back on.
    expect(withReset.actions.reset!.pBot).toBeLessThan(withReset.actions.process!.pBot);
  });

  it('headline equals the recommended action row (process/reroll/reset)', () => {
    const st = new GemState({ firstEffect: 'attack_power', secondEffect: 'ally_damage' });
    const offers = ['will+1', 'chaos+1', 'first+1', 'second+1'].map(k => byKey.get(k)!);
    const out = advise(ctx, { state: st, offers, turn: 1, turnsLeft: 9, rerolls: 1, resetAvailable: false });
    const row = out.action === 'process' ? out.actions.process
      : out.action === 'reroll' ? out.actions.reroll
      : out.action === 'reset' ? out.actions.reset : null;
    if (row) {
      expect(out.pGoal).toBe(row.pGoal);
      expect(out.pRelic).toBe(row.pRelic);
      expect(out.pAncient).toBe(row.pAncient);
      expect(out.eValue).toBe(row.eValue);
      expect(out.pBot).toBe(row.pBot);
    } else {
      // FINISH/FAIL: headline falls back to the position value (>= 0)
      expect(out.pGoal).toBeGreaterThanOrEqual(0);
    }
  });
});
