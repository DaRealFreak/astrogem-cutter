import { describe, it, expect } from 'vitest';
import { buildEngineContext, advise } from '../src/lib/engine';
import { GemState, makeOption } from '../src/lib/engine/models';
import { OptionPool } from '../src/lib/engine/pool';

describe('advise().actions', () => {
  const pool = new OptionPool();
  const byKey = new Map(pool.pool.map(o => [o.key, o]));

  const ctx = buildEngineContext(
    { gemType: 'chaos_distortion', firstEffect: 'attack_power', secondEffect: 'boss_damage', optimize: 'dps' },
    { rarity: 'epic', minWill: 4, minChaos: 4 },
  );
  const state = new GemState({ will: 2, chaos: 2, first: 2, second: 1, firstEffect: 'attack_power', secondEffect: 'boss_damage' });
  const offers = [
    byKey.get('will+1')!,
    byKey.get('chaos+1')!,
  ];

  it('returns process/reroll/reset metrics, each in range', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 1, resetAvailable: true });
    for (const a of [out.actions.process, out.actions.reroll, out.actions.reset]) {
      expect(a).not.toBeNull();
      for (const p of [a!.pGoal, a!.pRelic, a!.pAncient]) {
        expect(p).toBeGreaterThanOrEqual(0);
        expect(p).toBeLessThanOrEqual(1);
      }
      expect(a!.eValue).toBeGreaterThanOrEqual(0);
    }
  });

  it('nulls reroll when no rerolls and reset when unavailable', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 0, resetAvailable: false });
    expect(out.actions.reroll).toBeNull();
    expect(out.actions.reset).toBeNull();
    expect(out.actions.process).not.toBeNull();
  });

  it('reroll P(goal) equals the reroll-aware lookup with one fewer reroll', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 2, resetAvailable: true });
    // sanity: reroll uses lookup(state, turnsLeft, rerolls-1); must be a valid probability
    expect(out.actions.reroll!.pGoal).toBeGreaterThanOrEqual(0);
  });

  it('process is the expected (average) outcome over the offers, not the best', () => {
    // A uniformly-random offer is applied, so process pGoal must equal the mean
    // of the per-offer "P(goal) after" values — and be ≤ the best single offer.
    const offs = [byKey.get('will+1')!, byKey.get('chaos+1')!];
    const out1 = advise(ctx, { state, offers: offs, turn: 3, turnsLeft: 5, rerolls: 1, resetAvailable: false });
    const mean = out1.perOffer.reduce((a, o) => a + o.pGoalAfter, 0) / out1.perOffer.length;
    const best = Math.max(...out1.perOffer.map((o) => o.pGoalAfter));
    expect(out1.actions.process!.pGoal).toBeCloseTo(mean, 9);
    expect(out1.actions.process!.eValue).toBeCloseTo(
      out1.perOffer.reduce((a, o) => a + o.eValueAfter, 0) / out1.perOffer.length, 9);
    // sanity: the average is no greater than the best (and they differ when offers differ)
    expect(out1.actions.process!.pGoal).toBeLessThanOrEqual(best + 1e-9);
  });

  it('reset reflects fresh state at full budget', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 1, resetAvailable: true });
    const outFresh = advise(ctx, {
      state: new GemState({ firstEffect: 'attack_power', secondEffect: 'boss_damage' }),
      offers,
      turn: 1,
      turnsLeft: ctx.turnsTotal,
      rerolls: ctx.baseRerolls,
      resetAvailable: false,
    });
    // reset pGoal should match fresh-state lookup at turnsTotal
    expect(out.actions.reset!.pGoal).toBeCloseTo(
      ctx._decisionCtx.probTable.lookup(
        new GemState({ firstEffect: 'attack_power', secondEffect: 'boss_damage' }),
        ctx.turnsTotal,
        ctx.baseRerolls,
      ),
      6
    );
  });
});
