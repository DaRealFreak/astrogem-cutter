import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { OptionPool } from '../src/lib/engine/pool';
import { GemState } from '../src/lib/engine/models';

const data = JSON.parse(readFileSync(
  new URL('./fixtures/pool.json', import.meta.url), 'utf8')).records;
const snapshot = data[0].snapshot as Array<{key:string;weight:number;kind:string;delta:number}>;
const elig = data.slice(1);

describe('pool', () => {
  const pool = new OptionPool();
  it('matches the python pool snapshot exactly', () => {
    expect(pool.pool.map(o => ({ key: o.key, weight: o.weight, kind: o.kind, delta: o.delta })))
      .toEqual(snapshot);
  });
  it('eligibility matches python for every record', () => {
    const byKey = new Map(pool.pool.map(o => [o.key, o]));
    for (const r of elig) {
      const i = r.inputs;
      const st = new GemState({ will: i.state.will, chaos: i.state.chaos,
        first: i.state.first, second: i.state.second, costRatio: i.state.cost_ratio });
      expect(pool.eligible(byKey.get(i.key)!, st, i.turn, i.turns_left)).toBe(r.expected);
    }
  });
});
