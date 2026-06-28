import { describe, it, expect } from 'vitest';
import { SideValueTable } from '../src/lib/engine/probability';
import { OptionPool } from '../src/lib/engine/pool';
import { LastTurnGoal, GemState, makeOption } from '../src/lib/engine/models';

function table(maxRerolls: number) {
  return new SideValueTable(
    new LastTurnGoal({ minTotalWillChaos: 8 }), 9, new OptionPool(),
    'order_stability',
    { optimize: 'dps', minSideCoeff: 2000, relicCoeff: null, ancientCoeff: null, maxRerolls },
  );
}
const s0 = () => new GemState({ will: 1, chaos: 1, first: 1, second: 1,
  firstEffect: 'additional_damage', secondEffect: 'attack_power' });

describe('SideValueTable reroll dimension (parity with Python)', () => {
  it('flat default unchanged', () => {
    expect(table(0).lookup(s0(), 9)).toBeCloseTo(905.0476048635622, 6);
  });

  it('lookup matches Python at each reroll budget (1e-6)', () => {
    const t = table(4);
    // Canonical values from arkgrid/probability.py (shared A&S erf), max_rerolls=4.
    const py = [1018.0660728151729, 1318.9978087873233, 1574.1415424823908,
                1798.4124326802305, 1995.5527599423413];
    py.forEach((v, r) => expect(t.lookup(s0(), 9, r)).toBeCloseTo(v, 6));
  });

  it('reroll value strictly increases', () => {
    const t = table(4);
    const v = [0, 1, 2, 3, 4].map((r) => t.lookup(s0(), 9, r));
    for (let i = 1; i < v.length; i++) expect(v[i]).toBeGreaterThan(v[i - 1]);
  });

  it('expectedValueAfterClick matches Python (1e-6)', () => {
    const t = table(4);
    const offers = [
      makeOption('will+2', 4.40, 'will', 2),
      makeOption('second+1', 11.65, 'second', 1),
      makeOption('first+4', 0.45, 'first', 4),
      makeOption('chaos+3', 1.75, 'chaos', 3),
    ];
    expect(t.expectedValueAfterClick(s0(), offers, 8, 2)).toBeCloseTo(2227.8246329374615, 6);
    expect(t.expectedValueAfterClick(s0(), offers, 8, 3)).toBeCloseTo(2498.970290621299, 6);
  });
});
