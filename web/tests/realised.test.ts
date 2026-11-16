import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  RealisedSuccessTable, SideValueTable, handAtoms, handContext, handEMax, handMoments,
} from '../src/lib/engine/probability';
import { OptionPool } from '../src/lib/engine/pool';
import { GemState, LastTurnGoal } from '../src/lib/engine/models';

// Golden vectors from arkgrid/probability.py (tools/export_golden.py::export_realised).
const fixture = JSON.parse(readFileSync(
  new URL('./fixtures/realised.json', import.meta.url), 'utf8'));

type AtomsRec = {
  inputs: { kind: 'atoms'; case: string; weights: number[]; posts: number[] };
  expected: { moments: number[]; atoms: [number, number][] };
};
type TableRec = {
  inputs: {
    kind: 'table'; gem_type: string; optimize: string; goal: Record<string, number>;
    min_side_coeff: number; turns: number; max_rerolls: number;
    mode: 'side' | 'will_chaos'; endgame_risk: number | null; fresh: number | null;
    state: [number, number, number, number]; cost_ratio: number;
    first_effect: string; second_effect: string;
    turns_left: number; rerolls: number; offers: string[];
  };
  expected: { lookup: number; after_click: number | null };
};
const atomRecs: AtomsRec[] = fixture.records.filter((r: AtomsRec) => r.inputs.kind === 'atoms');
const tableRecs: TableRec[] = fixture.records.filter((r: TableRec) => r.inputs.kind === 'table');

describe('handAtoms (parity with Python hand_atoms)', () => {
  it('has fixture coverage for every shape of offer distribution', () => {
    expect(new Set(atomRecs.map((r) => r.inputs.case))).toEqual(
      new Set(['smooth', 'lumpy', 'hit_or_miss', 'single_out', 'constant']));
  });

  it('reproduces the moments and the atoms', () => {
    for (const rec of atomRecs) {
      const mom = handMoments(handContext(rec.inputs.weights), rec.inputs.posts);
      rec.expected.moments.forEach((v, i) => expect(mom[i]).toBeCloseTo(v, 12));
      const atoms = handAtoms(...mom);
      expect(atoms.length).toBe(rec.expected.atoms.length);
      rec.expected.atoms.forEach(([h, p], i) => {
        expect(atoms[i]![0]).toBeCloseTo(h, 9);
        expect(atoms[i]![1]).toBeCloseTo(p, 9);
      });
    }
  });

  it('is the distribution handEMax prices', () => {
    for (const rec of atomRecs) {
      const mom = handMoments(handContext(rec.inputs.weights), rec.inputs.posts);
      if (mom[1] <= 0) continue;
      const atoms = handAtoms(...mom);
      for (const t of [0, mom[0] * 0.7, mom[0], mom[0] * 1.3]) {
        const viaAtoms = atoms.reduce((acc, [h, p]) => acc + p * Math.max(h, t), 0);
        expect(viaAtoms).toBeCloseTo(handEMax(...mom, t), 10);
      }
    }
  });
});

describe('RealisedSuccessTable (parity with Python)', () => {
  const pool = new OptionPool();
  const byKey = new Map(pool.pool.map((o) => [o.key, o]));
  const svtCache = new Map<string, SideValueTable>();
  const tableCache = new Map<string, RealisedSuccessTable>();

  function tableFor(i: TableRec['inputs']): RealisedSuccessTable {
    const svtKey = JSON.stringify([i.gem_type, i.optimize, i.goal, i.min_side_coeff,
      i.turns, i.max_rerolls, i.mode]);
    let svt = svtCache.get(svtKey);
    if (!svt) {
      svt = new SideValueTable(
        new LastTurnGoal({
          minWill: i.goal['min_will'], minChaos: i.goal['min_chaos'],
          minTotalWillChaos: i.goal['min_total_will_chaos'],
        }),
        i.turns, pool, i.gem_type,
        { optimize: i.optimize, minSideCoeff: i.min_side_coeff, valueMode: i.mode,
          maxRerolls: i.max_rerolls });
      svtCache.set(svtKey, svt);
    }
    const key = JSON.stringify([svtKey, i.endgame_risk, i.fresh]);
    let t = tableCache.get(key);
    if (!t) {
      t = new RealisedSuccessTable(svt, { endgameRisk: i.endgame_risk, fresh: i.fresh });
      tableCache.set(key, t);
    }
    return t;
  }

  it('covers plain and reset-aware tables, an explicit margin and the will_chaos mode', () => {
    expect(tableRecs.length).toBeGreaterThan(200);
    expect(tableRecs.some((r) => r.inputs.fresh === null)).toBe(true);
    expect(tableRecs.some((r) => r.inputs.fresh !== null)).toBe(true);
    expect(tableRecs.some((r) => r.inputs.endgame_risk !== null)).toBe(true);
    expect(tableRecs.some((r) => r.inputs.mode === 'will_chaos')).toBe(true);
    expect(tableRecs.some((r) => r.inputs.cost_ratio !== 0)).toBe(true);
  });

  it('lookup and expectedAfterClick match Python within 1e-6 for every record', () => {
    for (const rec of tableRecs) {
      const i = rec.inputs;
      const t = tableFor(i);
      const [w, c, f, s] = i.state;
      const state = new GemState({
        will: w, chaos: c, first: f, second: s, costRatio: i.cost_ratio,
        firstEffect: i.first_effect, secondEffect: i.second_effect,
      });
      expect(t.lookup(state, i.turns_left, i.rerolls)).toBeCloseTo(rec.expected.lookup, 6);
      if (rec.expected.after_click !== null) {
        const offers = i.offers.map((k) => byKey.get(k)!);
        expect(t.expectedAfterClick(state, offers, i.turns_left - 1, i.rerolls))
          .toBeCloseTo(rec.expected.after_click, 6);
      }
    }
  });

  it('a reset ticket in hand never lowers the number', () => {
    for (const rec of tableRecs) {
      if (rec.inputs.fresh === null) continue;
      const i = rec.inputs;
      const withReset = tableFor(i);
      const plain = tableFor({ ...i, fresh: null });
      const [w, c, f, s] = i.state;
      const state = new GemState({
        will: w, chaos: c, first: f, second: s, costRatio: i.cost_ratio,
        firstEffect: i.first_effect, secondEffect: i.second_effect,
      });
      expect(withReset.lookup(state, i.turns_left, i.rerolls))
        .toBeGreaterThanOrEqual(plain.lookup(state, i.turns_left, i.rerolls) - 1e-12);
    }
  });

  it('is disabled for an unknown gem type', () => {
    const svt = new SideValueTable(new LastTurnGoal({ minWill: 4 }), 9, pool, '');
    const t = new RealisedSuccessTable(svt);
    expect(t.enabled).toBe(false);
    expect(t.lookup(new GemState({}), 9, 2)).toBe(0);
  });
});
