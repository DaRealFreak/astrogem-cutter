import { describe, it, expect } from 'vitest';
import { buildEngineContext, advise } from '../src/lib/engine';
import { GemState } from '../src/lib/engine/models';
import { OptionPool } from '../src/lib/engine/pool';

// Regression: under ignoreSideNodeValues the DECISION optimizes will+chaos
// only, but the DISPLAYED eValue must still be a real expected side
// coefficient — not the will+chaos sum (~2-10). Two bugs were fixed here:
//   (1) the display table was aliased to the decision table, so under
//       ignoreSide it ran in 'will_chaos' mode and the eValue collapsed to ~4
//       (w+c) instead of the boss_damage-driven coefficient (~hundreds);
//   (2) the first fix showed the value-ITERATION coefficient (identical with
//       ignore on/off) — an optimistic upper bound that assumes you chase the
//       side node. The display is now a POLICY EVALUATION of the will+chaos
//       policy, so under ignoreSide (where the bot doesn't chase the side node)
//       the realistic expected coefficient is LOWER than non-ignore.
// Mirrors the user's reported order_solidity gem (aliases to order_fortitude:
// boss_damage + ally_attack).
describe('display eValue under ignoreSideNodeValues', () => {
  const gem = { gemType: 'order_fortitude', firstEffect: 'ally_attack',
    secondEffect: 'boss_damage', optimize: 'dps' };
  const baseCfg = { rarity: 'epic', minTotalWillChaos: 8,
    relicRerollThreshold: 0.1, optimize: 'dps' };

  const pool = new OptionPool();
  const byKey = new Map(pool.pool.map(o => [o.key, o]));
  const offers = ['will+1', 'chaos+1', 'first+1', 'second+1'].map(k => byKey.get(k)!);
  const state = () => new GemState({ will: 1, chaos: 1, first: 1, second: 1,
    firstEffect: 'ally_attack', secondEffect: 'boss_damage' });

  const ignoreCtx = buildEngineContext(gem as any, { ...baseCfg, ignoreSideNodeValues: true } as any);
  const keepCtx = buildEngineContext(gem as any, { ...baseCfg, ignoreSideNodeValues: false } as any);

  const adviseAt = (ctx: ReturnType<typeof buildEngineContext>) => advise(ctx, {
    state: state(), offers, turn: 1, turnsLeft: 9, rerolls: 2, resetAvailable: false });

  it('process-row eValue is a coefficient, not the will+chaos sum', () => {
    // boss_damage (coeff 1000) drives the side value: a fresh gem's expected
    // side coefficient is in the hundreds. The will_chaos sum was ~4, so >100
    // cleanly distinguishes a real coefficient from the will+chaos sum.
    const e = adviseAt(ignoreCtx).actions.process!.eValue;
    expect(e).toBeGreaterThan(100);
  });

  it('ignoreSideNodeValues shows a LOWER coefficient than non-ignore', () => {
    // Policy evaluation: under ignoreSide the bot optimizes will+chaos and the
    // side node only rides along, so the realistic expected coefficient is
    // below the value-iteration figure non-ignore reports (which assumes the
    // side node is actively chased).
    const ignore = adviseAt(ignoreCtx).actions.process!.eValue;
    const keep = adviseAt(keepCtx).actions.process!.eValue;
    expect(ignore).toBeLessThan(keep);
  });
});
