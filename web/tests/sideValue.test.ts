import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { SideValueTable } from '../src/lib/engine/probability';
import { OptionPool } from '../src/lib/engine/pool';
import { LastTurnGoal, GemState } from '../src/lib/engine/models';

const recs = JSON.parse(readFileSync(
  new URL('./fixtures/side_values.json', import.meta.url), 'utf8')).records;
const close = (a: number, b: number) => expect(Math.abs(a - b)).toBeLessThan(1e-6);
const goalOf = (g: any) => new LastTurnGoal({
  minWill: g?.min_will, minChaos: g?.min_chaos,
  minTotalWillChaos: g?.min_total_will_chaos,
});

describe('SideValueTable parity', () => {
  it('matches python gem_value/lookup/evac and resolved coeffs', () => {
    const pool = new OptionPool();
    const byKey = new Map(pool.pool.map(o => [o.key, o]));
    // Cache tables by construction params to avoid redundant expensive builds.
    const tableCache = new Map<string, SideValueTable>();
    for (const r of recs) {
      const i = r.inputs; const turns = 9;
      const cacheKey = `${i.gem_type}|${i.optimize}|${i.min_side_coeff}|${i.mode}|${i.max_rerolls ?? 0}|${i.relic_coeff ?? ''}|${i.ancient_coeff ?? ''}|${i.policy_value_mode ?? ''}|${JSON.stringify(i.goal)}`;
      let t = tableCache.get(cacheKey);
      if (!t) {
        t = new SideValueTable(goalOf(i.goal), turns, pool, i.gem_type, {
          optimize: i.optimize, minSideCoeff: i.min_side_coeff, valueMode: i.mode,
          maxRerolls: i.max_rerolls ?? 0,
          relicCoeff: i.relic_coeff ?? null, ancientCoeff: i.ancient_coeff ?? null,
          policyValueMode: i.policy_value_mode ?? undefined });
        tableCache.set(cacheKey, t);
      }
      const [w, c, f, s] = i.state;
      const st = new GemState({ will: w, chaos: c, first: f, second: s,
        firstEffect: i.first_effect, secondEffect: i.second_effect });
      const offers = i.offers.map((k: string) => byKey.get(k)!);
      expect(t.relicCoeff).toBe(r.expected.relic_coeff);
      expect(t.ancientCoeff).toBe(r.expected.ancient_coeff);
      close(t.gemValue(st), r.expected.gem_value);
      close(t.lookup(st, i.turns_left, i.rerolls), r.expected.lookup);
      close(t.expectedValueAfterClick(st, offers, Math.max(0, i.turns_left - 1), i.rerolls), r.expected.evac);
    }
  });
});
