// Engine entry point: buildEngineContext + advise.
//
// Mirrors arkgrid/simulator.py:120-277,378-415 (table assembly) and
// tools/export_golden.py build_ctx() — the same tables in the same order.
// Adds an ANCIENT DP table (LastTurnGoal({minTotal:19})), which is the only
// addition beyond the Python (Python tracks P(ancient) via Monte Carlo).

import {
  DPS_COEFF,
  DPS_EFFECTS,
  SUPPORT_COEFF,
  SUPPORT_EFFECTS,
} from './constants';
import type { AstroGem } from './models';
import { GemState, LastTurnGoal } from './models';
import { OptionPool } from './pool';
import { GoalProbabilityTable, SideValueTable } from './probability';
import type { DecisionContext } from './decision';
import { ActionKind, decidePostRoll } from './decision';

export { ActionKind };

// ---------------------------------------------------------------------------
// Constants: rarity → turns / base rerolls
// ---------------------------------------------------------------------------

const RARITY_TURNS: Record<string, number> = { common: 5, rare: 7, epic: 9 };
const RARITY_REROLLS: Record<string, number> = { common: 0, rare: 1, epic: 2 };

// ---------------------------------------------------------------------------
// Public config / input / output types
// ---------------------------------------------------------------------------

export interface AdvisorConfig {
  rarity: 'common' | 'rare' | 'epic';
  minWill?: number;
  minChaos?: number;
  minFirst?: number;
  minSecond?: number;
  minTotalWillChaos?: number;
  minTotal?: number;
  minSideCoeff?: number;
  relicCoeff?: number | null;
  ancientCoeff?: number | null;
  relicRerollThreshold?: number;
  forceRerollNoProgress?: number;
  endgameRisk?: number;
  ignoreSideNodeValues?: boolean;
  /** Tri-state: true = force-on, false = hard-off, null/undefined = off-but-armed */
  extraTicket?: boolean | null;
  /** Per-turn extra-ticket enablers (mirror the Python flags). */
  rerollMinCoeff?: number;
  rerollGoal?: number;
  rerollGoalThreshold?: number;
  optimize?: 'dps' | 'support';
}

/** Opaque context; exposes resolved build params for assertions. */
export interface EngineContext {
  readonly turnsTotal: number;
  readonly dpMaxRerolls: number;
  readonly baseRerolls: number;
  // Internal — accessed by advise(). Not part of the public interface contract.
  _decisionCtx: DecisionContext;
  _relicProbTable: GoalProbabilityTable;
  _ancientProbTable: GoalProbabilityTable;
  _sideValueTable: SideValueTable;
  _displayValueTable: SideValueTable;
  _freshState: GemState;
}

export interface AdvisorInput {
  state: GemState;
  offers: import('./models').Option[];
  turn: number;
  turnsLeft: number;
  rerolls: number;
  resetAvailable: boolean;
}

export type ActionMetrics = { pGoal: number; pRelic: number; pAncient: number; eValue: number };
export type ActionsMap = { process: ActionMetrics | null; reroll: ActionMetrics | null; reset: ActionMetrics | null };

/** A full metric snapshot at a fixed reroll budget (for the ticket comparison). */
export type ActionsSnapshot = {
  pGoal: number; pRelic: number; pAncient: number; eValue: number; actions: ActionsMap;
};

/**
 * With/without extra-ticket comparison, attached by computeAdvice when the
 * player owns the ticket. `withoutTicket` uses the free reroll count, `withTicket`
 * uses free+1; `lent` is whether the recommendation actually used the ticket;
 * `spent` is whether the ticket is known already used this cutting process
 * (suppresses lending — the With-extra column is shown greyed/informational).
 */
export type TicketComparison = {
  owned: boolean; lent: boolean; spent: boolean; free: number;
  withoutTicket: ActionsSnapshot; withTicket: ActionsSnapshot;
};

export interface AdvisorOutput {
  action: ActionKind;
  branch: string;
  reason: string;
  pGoal: number;
  pRelic: number;
  pAncient: number;
  eValue: number;
  perOffer: Array<{ key: string; pGoalAfter: number; eValueAfter: number }>;
  actions: ActionsMap;
  /** Set by computeAdvice when the extra ticket is owned; null otherwise. */
  ticket?: TicketComparison | null;
}

// ---------------------------------------------------------------------------
// Helper: side coefficients from gem + optimize
// ---------------------------------------------------------------------------

function sideCoeffs(gem: AstroGem, optimize: string): [number, number] {
  const coeffMap = optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
  const targetSet = optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
  const f = targetSet.has(gem.firstEffect) ? coeffMap[gem.firstEffect] ?? 0 : 0;
  const s = targetSet.has(gem.secondEffect) ? coeffMap[gem.secondEffect] ?? 0 : 0;
  return [f, s];
}

// ---------------------------------------------------------------------------
// buildEngineContext
// ---------------------------------------------------------------------------

export function buildEngineContext(gem: AstroGem, config: AdvisorConfig): EngineContext {
  const rarity = config.rarity;
  const turnsTotal = RARITY_TURNS[rarity]!;

  // Reroll budget formula (verbatim from task brief / simulator.py:86-100):
  //   base = RARITY_REROLLS[rarity] + (extraTicket !== false ? 1 : 0)
  //   dpMaxRerolls = base + ((relicRerollThreshold > 0 || goalRerollActive) ? 1 : 0)
  // goalRerollActive is always false in Plan 1 (no --reroll-goal flag).
  const extraTicket = config.extraTicket;
  // baseRerolls / dpMaxRerolls keep the original budget sizing (covers free
  // rerolls + the lent ticket + the look-ahead margin, so reroll-aware lookups
  // never clamp). The ticket is no longer folded into the *current* budget —
  // it is lent per frame in computeAdvice via ticketEnabled.
  const ownable = extraTicket !== false;
  const baseRerolls = RARITY_REROLLS[rarity]! + (ownable ? 1 : 0);
  const relicRerollThreshold = config.relicRerollThreshold ?? 0;
  const rerollMinCoeff = config.rerollMinCoeff ?? 0;
  const rerollGoal = config.rerollGoal;
  const rerollGoalThreshold = config.rerollGoalThreshold ?? 0;
  const goalRerollActive = rerollGoal !== undefined && rerollGoalThreshold > 0;
  const dpMaxRerolls = baseRerolls + ((relicRerollThreshold > 0 || goalRerollActive) ? 1 : 0);

  const optimize = config.optimize ?? gem.optimize ?? 'dps';
  const gemType = gem.gemType ?? '';

  // Goal
  const goal = new LastTurnGoal({
    minWill: config.minWill,
    minChaos: config.minChaos,
    minFirst: config.minFirst,
    minSecond: config.minSecond,
    minTotalWillChaos: config.minTotalWillChaos,
    minTotal: config.minTotal,
  });

  const minSideCoeff = config.minSideCoeff ?? 0;
  const ignoreSide = config.ignoreSideNodeValues ?? false;
  const relicCoeff = config.relicCoeff ?? null;
  const ancientCoeff = config.ancientCoeff ?? null;
  const forceReroll = config.forceRerollNoProgress ?? 0;
  const endgameRisk = config.endgameRisk; // undefined → auto-gate

  const pool = new OptionPool();

  // Side coefficients from the gem's effects (mirrors simulator.py:108-117)
  const [scf, scs] = sideCoeffs(gem, optimize);
  // If both are 0 (gem type unknown / cross-type w/o coeff), don't pass
  // min_side_coeff to the DP (it would think the goal is always infeasible).
  const dpMinSideCoeff = scf > 0 || scs > 0 ? minSideCoeff : 0;

  // 1. Reroll-aware goal table (effect-aware; for optimal reroll timing)
  const probTable = new GoalProbabilityTable(goal, turnsTotal, pool, {
    sideCoeffFirst: scf,
    sideCoeffSecond: scs,
    minSideCoeff: dpMinSideCoeff,
    earlyFinish: true,
    maxRerolls: dpMaxRerolls,
    effectAware: true,
    gemType,
    optimize,
  });

  // 2. Standard goal table (no reroll dimension; for reset decisions / pFresh)
  const resetProbTable = new GoalProbabilityTable(goal, turnsTotal, pool, {
    sideCoeffFirst: scf,
    sideCoeffSecond: scs,
    minSideCoeff: dpMinSideCoeff,
    earlyFinish: true,
    effectAware: true,
    gemType,
    optimize,
  });

  // 3. Relic+ table: P(total_points >= 16), reroll-aware.
  const relicProbTable = new GoalProbabilityTable(
    new LastTurnGoal({ minTotal: 16 }),
    turnsTotal,
    pool,
    { earlyFinish: false, maxRerolls: dpMaxRerolls }
  );

  // 4. Ancient table: P(total_points >= 19), reroll-aware.
  //    This is the only addition beyond the Python (Python tracks P(ancient)
  //    via Monte Carlo; the advisor needs a DP value).
  const ancientProbTable = new GoalProbabilityTable(
    new LastTurnGoal({ minTotal: 19 }),
    turnsTotal,
    pool,
    { earlyFinish: false, maxRerolls: dpMaxRerolls }
  );

  // 5. Reroll-aware value table (goal-conditioned). Phase B: used for BOTH the
  // finish/continue decision gate AND the displayed eValue matrix, threaded with
  // the live reroll budget. (When dpMaxRerolls === 0 a reroll-aware build is
  // byte-identical to a flat one.)
  const sideValueTable = new SideValueTable(goal, turnsTotal, pool, gemType, {
    optimize,
    minSideCoeff,
    relicCoeff,
    ancientCoeff,
    valueMode: ignoreSide ? 'will_chaos' : 'side',
    maxRerolls: dpMaxRerolls,
  });

  // 6. Grade-value table (goal-independent; dead-goal decisions), reroll-aware.
  const gradeValueTable = new SideValueTable(new LastTurnGoal(), turnsTotal, pool, gemType, {
    optimize,
    minSideCoeff: 0,
    relicCoeff,
    ancientCoeff,
    valueMode: ignoreSide ? 'grade_only' : 'side',
    maxRerolls: dpMaxRerolls,
  });

  // 7. Maxed-oracle (side-mode; only when ignoreSide is set, at will/chaos cap),
  // reroll-aware.
  const maxedValueTable = ignoreSide
    ? new SideValueTable(goal, turnsTotal, pool, gemType, {
        optimize,
        minSideCoeff,
        relicCoeff,
        ancientCoeff,
        valueMode: 'side',
        maxRerolls: dpMaxRerolls,
      })
    : null;

  // Display value table: the shown eValue is always an expected side
  // coefficient (never the will+chaos sum). Without ignoreSide, `sideValueTable`
  // (side mode, reroll-aware) already IS the value the decision follows, so it
  // doubles as the display. Under ignoreSide the decision optimizes will+chaos
  // and the side node only rides along, so the value-iteration table would
  // overstate the realistic coefficient (it assumes you chase the side node).
  // Instead the display is a POLICY EVALUATION of the will+chaos policy — a
  // coupled flat DP that follows the policy's finish-vs-continue choice and
  // accumulates side value — yielding the lower, realistic expected coefficient.
  // Flat (no reroll dimension): the variance-aware reroll model has no discrete
  // per-state argmax to follow, and under ignoreSide rerolls aren't spent on the
  // side node anyway, so the side value earns no reroll boost.
  const displayValueTable = ignoreSide
    ? new SideValueTable(goal, turnsTotal, pool, gemType, {
        optimize,
        minSideCoeff,
        relicCoeff,
        ancientCoeff,
        valueMode: 'side',
        policyValueMode: 'will_chaos',
      })
    : sideValueTable;

  // 8. Goal-conditioned expected side-coefficient table (grade coeffs 0 ->
  //    value == E[side_coeff]) for the per-turn --reroll-min-coeff ticket
  //    enabler. ~0 once the goal is unreachable.
  const expectedCoeffTable = rerollMinCoeff > 0
    ? new SideValueTable(goal, turnsTotal, pool, gemType, {
        optimize, minSideCoeff, relicCoeff: 0, ancientCoeff: 0, valueMode: 'side',
      })
    : null;

  // 9. Will/chaos-total table for the --reroll-goal ticket enabler.
  const rerollGoalProbTable = goalRerollActive
    ? new GoalProbabilityTable(
        new LastTurnGoal({ minTotalWillChaos: rerollGoal }), turnsTotal, pool,
        { earlyFinish: false, maxRerolls: dpMaxRerolls })
    : null;

  // Fresh state (used for reset projection in advise() and pFresh below)
  const freshState = new GemState({ firstEffect: gem.firstEffect, secondEffect: gem.secondEffect });

  // Fresh-start probability (mirrors build_ctx / simulator._decision_context)
  const pFresh = resetProbTable.lookup(freshState, turnsTotal);

  const decisionCtx: DecisionContext = {
    goal,
    pool,
    optimize,
    bisOnly: false,
    minSideCoeff,
    probResetThreshold: 0.0,
    relicRerollThreshold,
    forceRerollNoProgress: forceReroll,
    turnsTotal,
    baseRerolls,
    pFresh,
    probTable,
    resetProbTable,
    relicProbTable,
    gemType,
    forceRerollActive: false,
    confirmActive: false,
    confirmMinCoeff: 0,
    endgameRisk,
    sideValueTable,
    gradeValueTable,
    maxedValueTable,
    extraTicketForceOn: extraTicket === true,
    rerollGoalProbTable,
    rerollGoalThreshold,
    rerollMinCoeff,
    expectedCoeffTable,
  };

  return {
    turnsTotal,
    dpMaxRerolls,
    baseRerolls,
    _decisionCtx: decisionCtx,
    _relicProbTable: relicProbTable,
    _ancientProbTable: ancientProbTable,
    _sideValueTable: sideValueTable,
    // advise()'s eValue rows read this (threaded with the live reroll budget).
    // It is the 'side'-mode value table so the displayed eValue is always an
    // expected side coefficient. It equals `sideValueTable` except under
    // ignoreSideNodeValues, where the decision table is 'will_chaos' and this
    // diverges to the side-mode maxed oracle (see displayValueTable above).
    _displayValueTable: displayValueTable,
    _freshState: freshState,
  };
}

// ---------------------------------------------------------------------------
// advise
// ---------------------------------------------------------------------------

export function advise(ctx: EngineContext, input: AdvisorInput): AdvisorOutput {
  const dc = ctx._decisionCtx;
  const { state, offers, turn, turnsLeft, rerolls, resetAvailable } = input;

  const decision = decidePostRoll(dc, { state, offers, turn, turnsLeft, rerolls, resetAvailable });

  // Position value of the current state — the fallback headline for FINISH/FAIL,
  // where there is no projected action row (stopping locks in the current gem).
  const posPGoal = dc.probTable.lookup(state, turnsLeft, rerolls);
  const posRelic = ctx._relicProbTable.lookup(state, turnsLeft, rerolls);
  const posAncient = ctx._ancientProbTable.lookup(state, turnsLeft, rerolls);
  const posEValue = ctx._displayValueTable.lookup(state, turnsLeft, rerolls);

  // Per-offer breakdown
  const turnsLeftAfter = turnsLeft - 1;
  const perOffer = offers.map((o) => ({
    key: o.key,
    pGoalAfter: dc.probTable.expectedProbAfterClick(state, [o], turnsLeftAfter, rerolls),
    eValueAfter: ctx._displayValueTable.expectedValueAfterClick(state, [o], turnsLeftAfter, rerolls),
  }));

  // ---------------------------------------------------------------------------
  // Actions projection: process / reroll / reset × { pGoal, pRelic, pAncient, eValue }
  // ---------------------------------------------------------------------------
  const probT = dc.probTable, relicT = ctx._relicProbTable, ancientT = ctx._ancientProbTable, dispT = ctx._displayValueTable;
  const tlAfter = turnsLeft - 1;

  // process = expected outcome of clicking. The game applies a uniformly-random
  // one of the 4 offers (simulator.py: rng.choice(offers)), so this is the
  // AVERAGE over the offers — not the best single offer. The per-offer table
  // above shows each individual outcome (the spread). Matches the keep value
  // the reroll decision compares against.
  const processM: ActionMetrics | null = offers.length > 0 ? {
    pGoal: probT.expectedProbAfterClick(state, offers, tlAfter, rerolls),
    pRelic: relicT.expectedProbAfterClick(state, offers, tlAfter, rerolls),
    pAncient: ancientT.expectedProbAfterClick(state, offers, tlAfter, rerolls),
    eValue: dispT.expectedValueAfterClick(state, offers, tlAfter, rerolls),
  } : null;

  // reroll = same state, one reroll spent (state/turnsLeft unchanged → side value unchanged)
  const rerollM: ActionMetrics | null = rerolls > 0 ? {
    pGoal: probT.lookup(state, turnsLeft, rerolls - 1),
    pRelic: relicT.lookup(state, turnsLeft, rerolls - 1),
    pAncient: ancientT.lookup(state, turnsLeft, rerolls - 1),
    eValue: dispT.lookup(state, turnsLeft, rerolls - 1),
  } : null;

  // reset = fresh gem, full budget (reroll-aware tables for matrix consistency)
  const resetM: ActionMetrics | null = resetAvailable ? {
    pGoal: probT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
    pRelic: relicT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
    pAncient: ancientT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
    eValue: dispT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
  } : null;

  // Headline = the recommended action's projected row, so the big P(click) block
  // matches the advice (recommend Process → show the Process odds for THESE
  // offers). Only PROCESS/REROLL/RESET have a row; FINISH/FAIL fall back to the
  // position value.
  const recRow =
    decision.action === ActionKind.PROCESS ? processM :
    decision.action === ActionKind.REROLL ? rerollM :
    decision.action === ActionKind.RESET ? resetM : null;
  const pGoal = recRow ? recRow.pGoal : posPGoal;
  const pRelic = recRow ? recRow.pRelic : posRelic;
  const pAncient = recRow ? recRow.pAncient : posAncient;
  const eValue = recRow ? recRow.eValue : posEValue;

  return {
    action: decision.action,
    branch: decision.branch,
    reason: decision.reason,
    pGoal,
    pRelic,
    pAncient,
    eValue,
    perOffer,
    actions: { process: processM, reroll: rerollM, reset: resetM },
  };
}
