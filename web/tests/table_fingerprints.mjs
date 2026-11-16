// Fingerprint whole DP tables — every value, bit for bit — so a change to the
// table builds that is meant to keep the numbers (a speed-up, a refactor) can
// be proven output-identical. The parity fixtures only sample a few hundred
// states at 1e-6; this covers all of them exactly.
//
//   npx tsx tests/table_fingerprints.mjs before.json        # on the old code
//   npx tsx tests/table_fingerprints.mjs after.json before.json   # then compare
//
// Exits 1 when a table differs from the reference. A deliberate model change
// is expected to differ — regenerate the Python fixtures for that instead.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { OptionPool } from '../src/lib/engine/pool.ts';
import { GemState, LastTurnGoal } from '../src/lib/engine/models.ts';
import { GoalProbabilityTable, RealisedSuccessTable, SideValueTable } from '../src/lib/engine/probability.ts';

const pool = new OptionPool();
const sha = (table) => {
  const dp = table._dp;
  return createHash('sha256').update(new Uint8Array(dp.buffer, dp.byteOffset, dp.byteLength)).digest('hex')
    + ':' + dp.length;
};
const out = {};
const times = {};
const add = (name, make) => {
  const t0 = performance.now();
  const table = make();
  times[name] = Math.round(performance.now() - t0);
  out[name] = sha(table);
  return table;
};

// --- effect-aware goal tables, reroll-aware -------------------------------
add('goal/ea/epic/w4c5/msc2000/mr3', () => new GoalProbabilityTable(
  new LastTurnGoal({ minWill: 4, minChaos: 5 }), 9, pool,
  { sideCoeffFirst: 1000, sideCoeffSecond: 700, minSideCoeff: 2000, earlyFinish: true,
    maxRerolls: 3, effectAware: true, gemType: 'order_immutability', optimize: 'dps' }));
add('goal/ea/rare/total8/mr2', () => new GoalProbabilityTable(
  new LastTurnGoal({ minTotalWillChaos: 8 }), 7, pool,
  { earlyFinish: true, maxRerolls: 2, effectAware: true, gemType: 'order_stability', optimize: 'dps' }));
add('goal/ea/common/w5c5f3/support/mr1', () => new GoalProbabilityTable(
  new LastTurnGoal({ minWill: 5, minChaos: 5, minFirst: 3 }), 5, pool,
  { earlyFinish: true, maxRerolls: 1, effectAware: true, gemType: 'chaos_distortion', optimize: 'support' }));
add('goal/ea/epic/w4c4/msc4000/mr4/no-early-finish', () => new GoalProbabilityTable(
  new LastTurnGoal({ minWill: 4, minChaos: 4 }), 9, pool,
  { sideCoeffFirst: 400, sideCoeffSecond: 1000, minSideCoeff: 4000, earlyFinish: false,
    maxRerolls: 4, effectAware: true, gemType: 'order_fortitude', optimize: 'dps' }));
add('goal/ea/epic/relic16/mr3', () => new GoalProbabilityTable(
  new LastTurnGoal({ minTotal: 16 }), 9, pool,
  { earlyFinish: true, maxRerolls: 3, effectAware: true, gemType: 'chaos_erosion', optimize: 'dps' }));
// --- unchanged builds that share the hand model ---------------------------
add('goal/flat-state/relic16/mr3', () => new GoalProbabilityTable(
  new LastTurnGoal({ minTotal: 16 }), 9, pool, { earlyFinish: true, maxRerolls: 3 }));
add('goal/ea/flat/w4c5', () => new GoalProbabilityTable(
  new LastTurnGoal({ minWill: 4, minChaos: 5 }), 9, pool,
  { earlyFinish: true, effectAware: true, gemType: 'order_immutability', optimize: 'dps' }));

// --- side-value tables, reroll-aware --------------------------------------
const svSide = add('sv/side/epic/w4c5/msc2000/mr3', () => new SideValueTable(
  new LastTurnGoal({ minWill: 4, minChaos: 5 }), 9, pool, 'order_immutability',
  { optimize: 'dps', minSideCoeff: 2000, maxRerolls: 3 }));
const svWc = add('sv/will_chaos/epic/total8/mr4', () => new SideValueTable(
  new LastTurnGoal({ minTotalWillChaos: 8 }), 9, pool, 'order_fortitude',
  { optimize: 'dps', valueMode: 'will_chaos', maxRerolls: 4 }));
add('sv/grade_only/epic/mr3', () => new SideValueTable(
  new LastTurnGoal({}), 9, pool, 'chaos_distortion',
  { optimize: 'dps', valueMode: 'grade_only', maxRerolls: 3 }));
const svRare = add('sv/side/rare/total8/coeffs/mr2', () => new SideValueTable(
  new LastTurnGoal({ minTotalWillChaos: 8 }), 7, pool, 'order_stability',
  { optimize: 'dps', relicCoeff: 3000, ancientCoeff: 9000, maxRerolls: 2 }));
add('sv/side/common/support/mr1', () => new SideValueTable(
  new LastTurnGoal({ minWill: 3, minChaos: 3 }), 5, pool, 'chaos_collapse',
  { optimize: 'support', minSideCoeff: 1500, maxRerolls: 1 }));
add('sv/side/flat/w4c5', () => new SideValueTable(
  new LastTurnGoal({ minWill: 4, minChaos: 5 }), 9, pool, 'order_immutability',
  { optimize: 'dps', minSideCoeff: 2000 }));
add('sv/policy-eval/total8', () => new SideValueTable(
  new LastTurnGoal({ minTotalWillChaos: 8 }), 9, pool, 'order_fortitude',
  { optimize: 'dps', valueMode: 'side', policyValueMode: 'will_chaos' }));

// --- realised-success tables ----------------------------------------------
const plain = add('realised/side/plain', () => new RealisedSuccessTable(svSide));
const fresh = Math.round(plain.lookup(
  new GemState({ firstEffect: 'boss_damage', secondEffect: 'additional_damage' }), 9, 2) / 0.005) * 0.005;
add('realised/side/reset', () => new RealisedSuccessTable(svSide, { fresh }));
add('realised/side/margin500', () => new RealisedSuccessTable(svSide, { endgameRisk: 500 }));
add('realised/will_chaos/plain', () => new RealisedSuccessTable(svWc));
add('realised/rare/reset', () => new RealisedSuccessTable(svRare, { fresh: 0.31, endgameRisk: -200 }));

for (const [k, v] of Object.entries(times)) console.log(String(v).padStart(6) + ' ms  ' + k);
const [outFile, referenceFile] = process.argv.slice(2);
if (outFile) {
  writeFileSync(outFile, JSON.stringify(out, null, 1));
  console.log('wrote', Object.keys(out).length, 'table fingerprints to', outFile);
}
if (referenceFile) {
  const reference = JSON.parse(readFileSync(referenceFile, 'utf8'));
  const names = [...new Set([...Object.keys(reference), ...Object.keys(out)])];
  const different = names.filter((k) => reference[k] !== out[k]);
  console.log(`${names.length - different.length} of ${names.length} tables identical to ${referenceFile}`);
  for (const k of different) console.log('  DIFFERENT', k);
  if (different.length > 0) process.exit(1);
}
