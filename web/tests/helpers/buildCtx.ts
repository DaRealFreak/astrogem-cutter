// Local DecisionContext builder for the Task 8 decision-parity test.
//
// Mirrors `tools/export_golden.py` `build_ctx()` exactly: it constructs the
// six tables (reroll-aware goal "roll" table, standard "reset" table, relic
// table, side-value table, grade-value table, optional maxed oracle) from a
// fixture `inputs` object. It reads `turns_total` and `dp_max_rerolls`
// straight from the fixture (the exporter emitted them) — it does NOT
// re-derive the reroll budget. Task 9 promotes this to engine/index.ts.

import {
  DPS_COEFF,
  DPS_EFFECTS,
  SUPPORT_COEFF,
  SUPPORT_EFFECTS,
} from '../../src/lib/engine/constants';
import { GemState, LastTurnGoal } from '../../src/lib/engine/models';
import { OptionPool } from '../../src/lib/engine/pool';
import { GoalProbabilityTable, SideValueTable } from '../../src/lib/engine/probability';
import type { DecisionContext } from '../../src/lib/engine/decision';

// LastTurnGoal field-name mapping (snake_case fixture -> camelCase model).
function goalOf(g: Record<string, number> | undefined): LastTurnGoal {
  if (!g) return new LastTurnGoal();
  return new LastTurnGoal({
    minWill: g['min_will'],
    minChaos: g['min_chaos'],
    exactWill: g['exact_will'],
    exactChaos: g['exact_chaos'],
    minTotalWillChaos: g['min_total_will_chaos'],
    exactTotalWillChaos: g['exact_total_will_chaos'],
    minFirst: g['min_first'],
    minSecond: g['min_second'],
    minTotal: g['min_total'],
  });
}

// Mirror export_golden.side_coeffs(AstroGem(gt, fe, se, opt)).
function sideCoeffs(fe: string, se: string, opt: string): [number, number] {
  const cm = opt === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
  const ts = opt === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
  const f = ts.has(fe) ? cm[fe] ?? 0 : 0;
  const s = ts.has(se) ? cm[se] ?? 0 : 0;
  return [f, s];
}

interface FixtureInputs {
  gt: string;
  fe: string;
  se: string;
  opt: string;
  g: Record<string, number>;
  rarity: string;
  config: {
    relic_coeff?: number | null;
    ancient_coeff?: number | null;
    relic_thr?: number;
    force_reroll?: number;
    min_side_coeff?: number;
    endgame_risk?: number | null;
    ignore_side?: boolean;
    extra_ticket?: boolean | null;
  };
  turns_total: number;
  dp_max_rerolls: number;
}

export function buildCtxForTest(i: FixtureInputs, pool: OptionPool): DecisionContext {
  const cfg = i.config ?? {};
  const relicCoeff = cfg.relic_coeff ?? null; // None in Python -> fusion default
  const ancientCoeff = cfg.ancient_coeff ?? null;
  const relicThr = cfg.relic_thr ?? 0.0;
  const forceReroll = cfg.force_reroll ?? 0;
  const minSideCoeff = cfg.min_side_coeff ?? 0;
  const endgameRisk = cfg.endgame_risk ?? undefined; // None -> auto-gate
  const ignoreSide = cfg.ignore_side ?? false;

  const goal = goalOf(i.g);
  const turns = i.turns_total;
  // build_ctx reads ctx.base_rerolls == mr == dp_max_rerolls from the exporter.
  const mr = i.dp_max_rerolls;
  const [scf, scs] = sideCoeffs(i.fe, i.se, i.opt);

  const roll = new GoalProbabilityTable(goal, turns, pool, {
    sideCoeffFirst: scf,
    sideCoeffSecond: scs,
    minSideCoeff,
    earlyFinish: true,
    maxRerolls: mr,
    effectAware: true,
    gemType: i.gt,
    optimize: i.opt,
  });
  const reset = new GoalProbabilityTable(goal, turns, pool, {
    sideCoeffFirst: scf,
    sideCoeffSecond: scs,
    minSideCoeff,
    earlyFinish: true,
    effectAware: true,
    gemType: i.gt,
    optimize: i.opt,
  });
  const relic = new GoalProbabilityTable(new LastTurnGoal({ minTotal: 16 }), turns, pool, {
    earlyFinish: false,
    maxRerolls: mr,
  });
  const svt = new SideValueTable(goal, turns, pool, i.gt, {
    optimize: i.opt,
    minSideCoeff,
    relicCoeff,
    ancientCoeff,
    valueMode: ignoreSide ? 'will_chaos' : 'side',
  });
  const gvt = new SideValueTable(new LastTurnGoal(), turns, pool, i.gt, {
    optimize: i.opt,
    minSideCoeff: 0,
    relicCoeff,
    ancientCoeff,
    valueMode: ignoreSide ? 'grade_only' : 'side',
  });
  const mvt = ignoreSide
    ? new SideValueTable(goal, turns, pool, i.gt, {
        optimize: i.opt,
        minSideCoeff,
        relicCoeff,
        ancientCoeff,
        valueMode: 'side',
      })
    : null;

  const pFresh = reset.lookup(
    new GemState({ firstEffect: i.fe, secondEffect: i.se }),
    turns
  );

  const ctx: DecisionContext = {
    goal,
    pool,
    optimize: i.opt,
    bisOnly: false,
    minSideCoeff,
    probResetThreshold: 0.0,
    relicRerollThreshold: relicThr,
    forceRerollNoProgress: forceReroll,
    turnsTotal: turns,
    baseRerolls: mr,
    pFresh,
    probTable: roll,
    resetProbTable: reset,
    relicProbTable: relic,
    gemType: i.gt,
    forceRerollActive: false,
    confirmActive: false,
    confirmMinCoeff: 0,
    endgameRisk,
    sideValueTable: svt,
    gradeValueTable: gvt,
    maxedValueTable: mvt,
  };
  return ctx;
}
