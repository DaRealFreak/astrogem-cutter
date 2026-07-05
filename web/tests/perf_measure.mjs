// Scratch measurement: per-table build cost inside buildEngineContext.
// Run: npx tsx tests/perf_measure.mjs   (or via vite-node)
import { OptionPool } from '../src/lib/engine/pool.ts';
import { LastTurnGoal } from '../src/lib/engine/models.ts';
import { GoalProbabilityTable, SideValueTable } from '../src/lib/engine/probability.ts';
import { buildEngineContext } from '../src/lib/engine/index.ts';

const pool = new OptionPool();
const goal = new LastTurnGoal({ minWill: 4, minChaos: 5 });

function time(label, fn) {
  const t0 = performance.now();
  const r = fn();
  console.log(label.padEnd(38), (performance.now() - t0).toFixed(0) + ' ms');
  return r;
}

time('goal EA+reroll (mr=3)', () => new GoalProbabilityTable(goal, 9, pool,
  { earlyFinish: true, maxRerolls: 3, effectAware: true, gemType: 'chaos_distortion', optimize: 'dps' }));
time('goal EA flat (reset)', () => new GoalProbabilityTable(goal, 9, pool,
  { earlyFinish: true, effectAware: true, gemType: 'chaos_distortion', optimize: 'dps' }));
time('relic (flat-state, mr=3)', () => new GoalProbabilityTable(new LastTurnGoal({ minTotal: 16 }), 9, pool,
  { maxRerolls: 3 }));
time('sideValue reroll (mr=3)', () => new SideValueTable(goal, 9, pool, 'chaos_distortion',
  { optimize: 'dps', maxRerolls: 3 }));
time('sideValue policy-eval', () => new SideValueTable(goal, 9, pool, 'chaos_distortion',
  { optimize: 'dps', valueMode: 'side', policyValueMode: 'will_chaos' }));

const gem = { gemType: 'chaos_distortion', firstEffect: 'attack_power', secondEffect: 'ally_damage', optimize: 'dps' };
time('buildEngineContext (cold)', () => buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5 }));
time('buildEngineContext (identical)', () => buildEngineContext(gem, { rarity: 'epic', minWill: 4, minChaos: 5 }));
time('buildEngineContext (goal change)', () => buildEngineContext(gem, { rarity: 'epic', minWill: 5, minChaos: 5 }));
time('buildEngineContext (non-table knob)', () => buildEngineContext(gem, { rarity: 'epic', minWill: 5, minChaos: 5, endgameRisk: 100 }));
