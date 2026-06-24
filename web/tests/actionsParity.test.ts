import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildEngineContext, advise } from '../src/lib/engine';
import { GemState } from '../src/lib/engine/models';
import { OptionPool } from '../src/lib/engine/pool';

const fixture = JSON.parse(readFileSync(
  new URL('./fixtures/actions.json', import.meta.url), 'utf8'));
const recs: Array<{
  inputs: {
    gt: string; fe: string; se: string; opt: string;
    goal: Record<string, number>; rarity: string;
    turns_total: number; base_rerolls: number;
    state: [number, number, number, number];
    turn: number; turns_left: number; rerolls: number;
    offers: string[];
  };
  expected: {
    process: { pGoal: number; pRelic: number; pAncient: number; eValue: number; bestOfferKey: string } | null;
    reroll: { pGoal: number; pRelic: number; pAncient: number; eValue: number } | null;
    reset: { pGoal: number; pRelic: number; pAncient: number; eValue: number };
  };
}> = fixture.records;

function goalFieldsFromFixture(g: Record<string, number>) {
  return {
    minWill: g['min_will'],
    minChaos: g['min_chaos'],
    minFirst: g['min_first'],
    minSecond: g['min_second'],
    minTotalWillChaos: g['min_total_will_chaos'],
    minTotal: g['min_total'],
  };
}

describe('advise().actions parity', () => {
  it('matches python process/reroll/reset metrics within 1e-6 for every record', () => {
    const pool = new OptionPool();
    const byKey = new Map(pool.pool.map(o => [o.key, o]));
    const ctxCache = new Map<string, ReturnType<typeof buildEngineContext>>();

    for (const rec of recs) {
      const i = rec.inputs;
      const ckey = JSON.stringify([i.gt, i.fe, i.se, i.opt, i.goal, i.rarity]);
      if (!ctxCache.has(ckey)) {
        ctxCache.set(ckey, buildEngineContext(
          { gemType: i.gt, firstEffect: i.fe, secondEffect: i.se, optimize: i.opt as 'dps' | 'support' },
          { rarity: i.rarity as 'common' | 'rare' | 'epic', ...goalFieldsFromFixture(i.goal) }
        ));
      }
      const ctx = ctxCache.get(ckey)!;

      const [w, c, f, s] = i.state;
      const state = new GemState({ will: w, chaos: c, first: f, second: s, firstEffect: i.fe, secondEffect: i.se });
      const offers = i.offers.map(k => byKey.get(k)!);

      const out = advise(ctx, {
        state,
        offers,
        turn: i.turn,
        turnsLeft: i.turns_left,
        rerolls: i.rerolls,
        resetAvailable: true,
      });

      const TOLS = 1e-6;

      // process
      if (rec.expected.process !== null) {
        expect(out.actions.process).not.toBeNull();
        expect(out.actions.process!.pGoal).toBeCloseTo(rec.expected.process.pGoal, 6);
        expect(out.actions.process!.pRelic).toBeCloseTo(rec.expected.process.pRelic, 6);
        expect(out.actions.process!.pAncient).toBeCloseTo(rec.expected.process.pAncient, 6);
        expect(out.actions.process!.eValue).toBeCloseTo(rec.expected.process.eValue, 6);
      }

      // reroll
      if (rec.expected.reroll !== null) {
        expect(out.actions.reroll).not.toBeNull();
        expect(out.actions.reroll!.pGoal).toBeCloseTo(rec.expected.reroll.pGoal, 6);
        expect(out.actions.reroll!.pRelic).toBeCloseTo(rec.expected.reroll.pRelic, 6);
        expect(out.actions.reroll!.pAncient).toBeCloseTo(rec.expected.reroll.pAncient, 6);
        expect(out.actions.reroll!.eValue).toBeCloseTo(rec.expected.reroll.eValue, 6);
      } else {
        // rerolls === 0 in this record
        expect(out.actions.reroll).toBeNull();
      }

      // reset (always present in the fixture since resetAvailable=true above)
      expect(out.actions.reset).not.toBeNull();
      expect(out.actions.reset!.pGoal).toBeCloseTo(rec.expected.reset.pGoal, 6);
      expect(out.actions.reset!.pRelic).toBeCloseTo(rec.expected.reset.pRelic, 6);
      expect(out.actions.reset!.pAncient).toBeCloseTo(rec.expected.reset.pAncient, 6);
      expect(out.actions.reset!.eValue).toBeCloseTo(rec.expected.reset.eValue, 6);
    }
  });
});
