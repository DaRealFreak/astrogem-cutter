import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { LastTurnGoal } from '../src/lib/engine/models';

const load = (n: string) =>
  JSON.parse(readFileSync(new URL(`./fixtures/${n}.json`, import.meta.url), 'utf8')).records;

const goal = (g: any) => new LastTurnGoal({
  minWill: g.min_will, minChaos: g.min_chaos, exactWill: g.exact_will,
  exactChaos: g.exact_chaos, minTotalWillChaos: g.min_total_will_chaos,
  exactTotalWillChaos: g.exact_total_will_chaos, minFirst: g.min_first,
  minSecond: g.min_second, minTotal: g.min_total,
});

describe('satisfied parity', () => {
  it('matches python for every record', () => {
    for (const r of load('satisfied')) {
      const i = r.inputs;
      expect(goal(i.goal).satisfied(i.will, i.chaos, i.first, i.second)).toBe(r.expected);
    }
  });
});

describe('feasible parity', () => {
  it('matches python for every record', () => {
    for (const r of load('feasibility')) {
      const i = r.inputs;
      expect(goal(i.goal).feasible(i.will, i.chaos, i.turns_left, i.first, i.second, {
        minSideCoeff: i.min_side_coeff, sideCoeffFirst: i.side_coeff_first,
        sideCoeffSecond: i.side_coeff_second, changeDestMaxCoeff: i.change_dest_max_coeff,
      })).toBe(r.expected);
    }
  });
});
