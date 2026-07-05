import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { GoalProbabilityTable } from '../src/lib/engine/probability';
import { OptionPool } from '../src/lib/engine/pool';
import { LastTurnGoal, GemState } from '../src/lib/engine/models';

const RT: Record<string, number> = { common: 5, rare: 7, epic: 9 };
const recs = JSON.parse(readFileSync(
  new URL('./fixtures/dp_lookups.json', import.meta.url), 'utf8')).records;
const goalOf = (g: any) => new LastTurnGoal({ minWill: g.min_will, minChaos: g.min_chaos,
  minTotalWillChaos: g.min_total_will_chaos, minTotal: g.min_total });
const close = (a: number, b: number) => expect(Math.abs(a - b)).toBeLessThan(1e-6);

describe('GoalProbabilityTable parity', () => {
  it('matches python lookups/epac/should_reroll', () => {
    // group records by (gem,goal,rarity) so each table is built once
    const cache = new Map<string, any>();
    const pool = new OptionPool();
    for (const r of recs) {
      const i = r.inputs;
      const ckey = JSON.stringify([i.gem_type, i.goal, i.rarity, i.min_side_coeff ?? 0]);
      if (!cache.has(ckey)) {
        const turns: number = RT[i.rarity]!;
        const mr = i.max_rerolls;  // resolved dp_max_rerolls emitted by the exporter
        const msc = i.min_side_coeff ?? 0;
        cache.set(ckey, {
          roll: new GoalProbabilityTable(goalOf(i.goal), turns, pool, {
            earlyFinish: true, maxRerolls: mr, effectAware: true, minSideCoeff: msc,
            gemType: i.gem_type, optimize: i.optimize }),
          reset: new GoalProbabilityTable(goalOf(i.goal), turns, pool, {
            earlyFinish: true, effectAware: true, minSideCoeff: msc,
            gemType: i.gem_type, optimize: i.optimize }),
          relic: new GoalProbabilityTable(new LastTurnGoal({ minTotal: 16 }), turns, pool, {
            maxRerolls: mr }),
          anc: new GoalProbabilityTable(new LastTurnGoal({ minTotal: 19 }), turns, pool, {
            maxRerolls: mr }),
        });
      }
      const t = cache.get(ckey);
      const [w, c, f, s] = i.state;
      const st = new GemState({ will: w, chaos: c, first: f, second: s,
        firstEffect: i.first_effect, secondEffect: i.second_effect });
      const byKey = new Map(pool.pool.map(o => [o.key, o]));
      const offers = i.offers.map((k: string) => byKey.get(k)!);
      close(t.roll.lookup(st, i.turns_left, i.rerolls), r.expected.lookup);
      close(t.roll.expectedProbAfterClick(st, offers, Math.max(0, i.turns_left - 1), i.rerolls), r.expected.epac);
      expect(t.roll.shouldRerollDp(st, offers, i.turns_left, i.rerolls)).toBe(r.expected.reroll);
      close(t.reset.lookup(st, i.turns_left), r.expected.reset_lookup);
      close(t.relic.lookup(st, i.turns_left, i.rerolls), r.expected.relic_lookup);
      close(t.anc.lookup(st, i.turns_left, i.rerolls), r.expected.ancient_lookup);
    }
  });
});
