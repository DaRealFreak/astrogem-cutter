import { describe, it, expect } from 'vitest';
import { buildEngineContext } from '../src/lib/engine';

// DP tables are immutable after construction, so buildEngineContext caches
// them by build parameters: an identical config reuses every table, and a
// goal change must NOT rebuild the goal-independent tables (relic/ancient/
// grade) — that's most of the advisor's recompute cost.
describe('engine table cache', () => {
  const gem = {
    gemType: 'chaos_distortion',
    firstEffect: 'attack_power',
    secondEffect: 'ally_damage',
    optimize: 'dps' as const,
  };

  it('reuses every table for an identical config', () => {
    const a = buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5 });
    const b = buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5 });
    expect(b._decisionCtx.probTable).toBe(a._decisionCtx.probTable);
    expect(b._decisionCtx.resetProbTable).toBe(a._decisionCtx.resetProbTable);
    expect(b._decisionCtx.sideValueTable).toBe(a._decisionCtx.sideValueTable);
    expect(b._relicProbTable).toBe(a._relicProbTable);
    expect(b._ancientProbTable).toBe(a._ancientProbTable);
  });

  it('keeps goal-independent tables across a goal change', () => {
    const a = buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5 });
    const b = buildEngineContext(gem, { rarity: 'epic', minWill: 5, minChaos: 5 });
    // goal-dependent tables rebuild...
    expect(b._decisionCtx.probTable).not.toBe(a._decisionCtx.probTable);
    expect(b._decisionCtx.sideValueTable).not.toBe(a._decisionCtx.sideValueTable);
    // ...but the goal-independent ones are reused.
    expect(b._relicProbTable).toBe(a._relicProbTable);
    expect(b._ancientProbTable).toBe(a._ancientProbTable);
    expect(b._decisionCtx.gradeValueTable).toBe(a._decisionCtx.gradeValueTable);
  });

  it('distinguishes configs that change table semantics', () => {
    const a = buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5 });
    const b = buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5, minSideCoeff: 2000 });
    expect(b._decisionCtx.probTable).not.toBe(a._decisionCtx.probTable);
    const c = buildEngineContext(gem, { rarity: 'rare', minWill: 4, minChaos: 5 });
    expect(c._relicProbTable).not.toBe(a._relicProbTable);
  });
});
