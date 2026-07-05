import { describe, it, expect } from 'vitest';
import { buildEngineContext } from '../src/lib/engine';
import { GemState } from '../src/lib/engine/models';

// chaos_distortion pool: attack_power, boss_damage, ally_damage, ally_attack.
// DPS optimize on a gem currently holding the two support effects: the
// starting effects contribute 0 to the target side, but change_effect can
// still bring in attack_power / boss_damage — so the effect-aware DP must
// keep enforcing the minSideCoeff floor (mirrors Python `_get_ea_tables`,
// which passes min_side_coeff unguarded to effect-aware tables). Regression:
// the flat-table guard (`scf > 0 || scs > 0`) was wrongly applied here and
// silently dropped the floor, overstating P(goal) for off-target gems.
describe('minSideCoeff with off-target starting effects', () => {
  const gem = {
    gemType: 'chaos_distortion',
    firstEffect: 'ally_damage',
    secondEffect: 'ally_attack',
    optimize: 'dps' as const,
  };
  const goal = { minWill: 4, minChaos: 3 };

  it('effect-aware goal tables still price the floor', () => {
    const withFloor = buildEngineContext(gem, { rarity: 'epic', ...goal, minSideCoeff: 2000 });
    const noFloor = buildEngineContext(gem, { rarity: 'epic', ...goal });
    const st = new GemState({
      firstEffect: 'ally_damage', secondEffect: 'ally_attack',
    });
    const pWith = withFloor._decisionCtx.probTable.lookup(st, 9, 3);
    const pNo = noFloor._decisionCtx.probTable.lookup(st, 9, 3);
    // The floor is reachable via change_effect (boss_damage=1000 at level 2+,
    // attack_power=400 at level 5), so it must bind: 0 < pWith < pNo.
    expect(pWith).toBeGreaterThan(0);
    expect(pWith).toBeLessThan(pNo);
    // Same for the reset table (flat lookups take no reroll arg).
    const rWith = withFloor._decisionCtx.resetProbTable.lookup(st, 9);
    const rNo = noFloor._decisionCtx.resetProbTable.lookup(st, 9);
    expect(rWith).toBeGreaterThan(0);
    expect(rWith).toBeLessThan(rNo);
    // Two full engine contexts (reroll-aware value tables) — allow headroom
    // when the suite runs under load, like the decision parity sweep.
  }, 180_000);

  it('unknown gem type still drops the floor (flat fallback would zero out)', () => {
    const unknown = buildEngineContext(
      { gemType: '', firstEffect: 'ally_damage', secondEffect: 'ally_attack', optimize: 'dps' as const },
      { rarity: 'epic', ...goal, minSideCoeff: 2000 }
    );
    const st = new GemState({
      firstEffect: 'ally_damage', secondEffect: 'ally_attack',
    });
    // With no gem type the DP cannot model change_effect destinations; the
    // guard must keep zeroing the floor or every state would read P=0.
    expect(unknown._decisionCtx.probTable.lookup(st, 9, 3)).toBeGreaterThan(0);
  });
});
