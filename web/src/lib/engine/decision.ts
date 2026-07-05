// Port of arkgrid/decision.py — shared per-turn decision logic for both the
// simulator and the automation loop.
//
// Faithful transcription of the Branch 0-6 decision tree. The
// `_POST_ROLL_BRANCHES` order is load-bearing and preserved exactly.
//
// `decide_reroll_only` (the narrow reroll-loop tree) is also ported for
// fidelity, but the golden parity is on `decidePostRoll`.

import {
  DPS_COEFF,
  DPS_EFFECTS,
  SUPPORT_COEFF,
  SUPPORT_EFFECTS,
  changeDestMaxCoeff,
} from './constants';
import type { GemState, LastTurnGoal, Option } from './models';
import { OptionPool } from './pool';
import { GoalProbabilityTable, SideValueTable } from './probability';

// ---------------------------------------------------------------------------
// Action / decision types
// ---------------------------------------------------------------------------

export enum ActionKind {
  PROCESS = 'process', // apply one of the visible offers
  REROLL = 'reroll', // spend a reroll, redraw offers
  RESET = 'reset', // spend the reset ticket, restart from turn 1
  FINISH = 'finish', // stop early — goal+relic+ unreachable, or early-finish
  FAIL = 'fail', // simulator-only: no path to goal, no reset; auto maps to FINISH
}

export interface Decision {
  action: ActionKind;
  branch: string;
  reason: string;
  metrics: Record<string, unknown>;
  needsConfirmation: boolean;
  confirmChoices: string[];
}

function makeDecision(d: {
  action: ActionKind;
  branch: string;
  reason: string;
  metrics?: Record<string, unknown>;
  needsConfirmation?: boolean;
  confirmChoices?: string[];
}): Decision {
  return {
    action: d.action,
    branch: d.branch,
    reason: d.reason,
    metrics: d.metrics ?? {},
    needsConfirmation: d.needsConfirmation ?? false,
    confirmChoices: d.confirmChoices ?? [],
  };
}

// ---------------------------------------------------------------------------
// Context built once per run / per turn
// ---------------------------------------------------------------------------

export interface DecisionContext {
  goal: LastTurnGoal;
  pool: OptionPool;
  optimize: string; // "dps" | "support"
  bisOnly: boolean;
  minSideCoeff: number;
  probResetThreshold: number;
  relicRerollThreshold: number;
  forceRerollNoProgress: number;
  turnsTotal: number;
  baseRerolls: number;
  pFresh: number;
  probTable: GoalProbabilityTable; // reroll-aware goal table
  resetProbTable: GoalProbabilityTable; // standard goal table for reset
  relicProbTable: GoalProbabilityTable | null;
  gemType: string;
  forceRerollActive: boolean; // gated by starting coeff
  confirmActive: boolean;
  confirmMinCoeff: number;
  // undefined => auto-gate (grade-protect a below-benchmark relic/ancient gem);
  // a number is an explicit player-set finish margin.
  endgameRisk: number | undefined;
  sideValueTable: SideValueTable | null;
  // Goal-independent value table (`side_coeff + grade tier bonus`). Consulted
  // only on dead-goal turns. null unless relic/ancient grade has a coefficient.
  gradeValueTable: SideValueTable | null;
  // Side-mode value oracle consulted only at the will/chaos cap under
  // --ignore-side-node-values. null unless the flag is set.
  maxedValueTable: SideValueTable | null;
  // --- Extra-ticket per-turn enable gate (see `ticketEnabled`) ---
  // The gold-costing extra reroll ticket is re-evaluated every frame, OR-ing
  // these enablers. `extraTicketForceOn` is `--extra-ticket` (always on).
  extraTicketForceOn: boolean;
  rerollGoalProbTable: GoalProbabilityTable | null;
  rerollGoalThreshold: number;
  rerollMinCoeff: number;
  // Goal-conditioned expected side-coefficient table (relic/ancient coeff 0,
  // so value == E[side_coeff]); ~0 when the goal is unreachable.
  expectedCoeffTable: SideValueTable | null;
}

/**
 * Whether the gold-costing extra reroll ticket may be used this turn/frame.
 * Mirror of `arkgrid.decision.ticket_enabled`. Re-evaluated every frame (never
 * banked). Usable if ANY enabler clears its bar, each looking ahead as if the
 * ticket were in hand (`freeRerolls + 1`), except the reroll-independent coeff
 * enabler. Free rerolls are unaffected — this governs only the extra ticket.
 */
export function ticketEnabled(
  ctx: DecisionContext, state: GemState, turnsLeft: number, freeRerolls: number,
): boolean {
  if (ctx.extraTicketForceOn) return true;
  if (ctx.rerollMinCoeff > 0 && ctx.expectedCoeffTable !== null
      && ctx.expectedCoeffTable.lookup(state, turnsLeft) >= ctx.rerollMinCoeff) {
    return true;
  }
  const lookAhead = freeRerolls + 1; // P "as if the ticket were used"
  if (ctx.relicRerollThreshold > 0 && ctx.relicProbTable !== null
      && ctx.relicProbTable.lookup(state, turnsLeft, lookAhead)
         >= ctx.relicRerollThreshold) {
    return true;
  }
  if (ctx.rerollGoalThreshold > 0 && ctx.rerollGoalProbTable !== null
      && ctx.rerollGoalProbTable.lookup(state, turnsLeft, lookAhead)
         >= ctx.rerollGoalThreshold) {
    return true;
  }
  return false;
}

export interface TurnInput {
  state: GemState;
  offers: Option[];
  turn: number; // 1-indexed
  turnsLeft: number;
  rerolls: number; // caller-managed count
  resetAvailable: boolean;
}

// ---------------------------------------------------------------------------
// has_progress_offer (used by force-reroll-no-progress)
// ---------------------------------------------------------------------------

export function hasProgressOffer(
  offers: Option[],
  state: GemState,
  goal: LastTurnGoal,
  minSideCoeff: number,
  sideCoeffFirst: number,
  sideCoeffSecond: number
): boolean {
  const needTotal =
    goal.minTotal !== undefined &&
    state.will + state.chaos + state.first + state.second < goal.minTotal;
  const needWcTotal =
    goal.minTotalWillChaos !== undefined &&
    state.will + state.chaos < goal.minTotalWillChaos;
  const needWill = goal.minWill !== undefined && state.will < goal.minWill;
  const needChaos = goal.minChaos !== undefined && state.chaos < goal.minChaos;
  const needFirst = goal.minFirst !== undefined && state.first < goal.minFirst;
  const needSecond = goal.minSecond !== undefined && state.second < goal.minSecond;
  const needCoeffFirst = minSideCoeff > 0 && sideCoeffFirst > 0 && state.first < 5;
  const needCoeffSecond = minSideCoeff > 0 && sideCoeffSecond > 0 && state.second < 5;

  for (const o of offers) {
    // change_first/second_effect has delta == 0 and must be checked before
    // the delta guard below.
    if (o.key === 'change_first_effect' && minSideCoeff > 0 && sideCoeffFirst === 0) {
      return true;
    }
    if (o.key === 'change_second_effect' && minSideCoeff > 0 && sideCoeffSecond === 0) {
      return true;
    }
    if (o.delta <= 0) {
      continue;
    }
    if (o.kind === 'will' && (needWill || needWcTotal || needTotal)) {
      return true;
    }
    if (o.kind === 'chaos' && (needChaos || needWcTotal || needTotal)) {
      return true;
    }
    if (o.kind === 'first' && (needFirst || needCoeffFirst || needTotal)) {
      return true;
    }
    if (o.kind === 'second' && (needSecond || needCoeffSecond || needTotal)) {
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Metrics: computed once per turn, fed to all branch helpers
// ---------------------------------------------------------------------------

export interface TurnMetrics {
  pKeepGoal: number; // prob_table.expected_prob_after_click
  pKeepGoalReset: number; // reset_prob_table.expected_prob_after_click
  pKeepRelic: number; // relic_table.expected_prob_after_click (0 if None)
  pRerollRelic: number; // relic_table.lookup(state, tl, rerolls-1) (0 if None/no reroll)
  feasibleCount: number; // # offers where prob_table DP > 0 after pick
}

function goalFullySatisfied(ctx: DecisionContext, state: GemState): boolean {
  if (!ctx.goal.satisfied(state.will, state.chaos, state.first, state.second)) {
    return false;
  }
  if (ctx.bisOnly) {
    const target = ctx.optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
    if (!target.has(state.firstEffect) || !target.has(state.secondEffect)) {
      return false;
    }
  }
  if (ctx.minSideCoeff > 0) {
    const coeff = ctx.optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
    const target = ctx.optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
    let coeffTotal = 0;
    if (target.has(state.firstEffect)) {
      coeffTotal += state.first * (coeff[state.firstEffect] ?? 0);
    }
    if (target.has(state.secondEffect)) {
      coeffTotal += state.second * (coeff[state.secondEffect] ?? 0);
    }
    if (coeffTotal < ctx.minSideCoeff) {
      return false;
    }
  }
  return true;
}

function sideCoeff(ctx: DecisionContext, state: GemState): number {
  const coeffMap = ctx.optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
  const target = ctx.optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
  let total = 0;
  if (target.has(state.firstEffect)) {
    total += state.first * (coeffMap[state.firstEffect] ?? 0);
  }
  if (target.has(state.secondEffect)) {
    total += state.second * (coeffMap[state.secondEffect] ?? 0);
  }
  return total;
}

function handIsWcSafe(offers: Option[]): boolean {
  return !offers.some((o) => (o.kind === 'will' || o.kind === 'chaos') && o.delta < 0);
}

function legalActions(ti: TurnInput): string[] {
  const choices: string[] = [ActionKind.FINISH, ActionKind.PROCESS];
  if (ti.rerolls > 0 && ti.turn !== 1) {
    // Rerolling is disallowed on turn 1 — don't offer a dead button.
    choices.push(ActionKind.REROLL);
  }
  if (ti.resetAvailable) {
    choices.push(ActionKind.RESET);
  }
  return choices;
}

function maybeConfirm(
  ctx: DecisionContext,
  ti: TurnInput,
  decision: Decision
): Decision {
  if (!ctx.confirmActive) {
    return decision;
  }
  if (sideCoeff(ctx, ti.state) < ctx.confirmMinCoeff) {
    return decision;
  }
  return {
    ...decision,
    needsConfirmation: true,
    confirmChoices: legalActions(ti),
  };
}

export function computePostRollMetrics(ctx: DecisionContext, ti: TurnInput): TurnMetrics {
  if (ti.offers.length === 0) {
    return { pKeepGoal: 0.0, pKeepGoalReset: 0.0, pKeepRelic: 0.0, pRerollRelic: 0.0, feasibleCount: 0 };
  }

  const tla = ti.turnsLeft - 1; // turns_left after this click

  const pKeepGoal = ctx.probTable.expectedProbAfterClick(ti.state, ti.offers, tla, ti.rerolls);
  const pKeepGoalReset = ctx.resetProbTable.expectedProbAfterClick(ti.state, ti.offers, tla);

  let pKeepRelic = 0.0;
  let pRerollRelic = 0.0;
  if (ctx.relicProbTable !== null) {
    pKeepRelic = ctx.relicProbTable.expectedProbAfterClick(ti.state, ti.offers, tla, ti.rerolls);
    const canReroll = ti.rerolls > 0 && ti.turn !== 1;
    pRerollRelic = canReroll
      ? ctx.relicProbTable.lookup(ti.state, ti.turnsLeft, ti.rerolls - 1)
      : 0.0;
  }

  // Per-offer post-click feasibility under the goal DP. Destination-blind:
  // change offers count via their destination-average P (the card doesn't
  // reveal the destination in-game), consistent with pKeepGoal above.
  let feasibleCount = 0;
  for (const o of ti.offers) {
    if (ctx.probTable.probAfterOption(ti.state, o, tla, ti.rerolls) > 0) {
      feasibleCount += 1;
    }
  }

  return { pKeepGoal, pKeepGoalReset, pKeepRelic, pRerollRelic, feasibleCount };
}

// ---------------------------------------------------------------------------
// Branch 0: early-finish (goal already satisfied)
// ---------------------------------------------------------------------------

export function earlyFinishDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics
): Decision | null {
  if (!goalFullySatisfied(ctx, ti.state)) {
    return null;
  }
  if (ti.offers.length === 0) {
    return null;
  }
  return sideValueFinishDecision(ctx, ti, m);
}

function maxedHoldDecision(ctx: DecisionContext, ti: TurnInput): Decision {
  // ctx.maxedValueTable is non-null here (guarded by the caller).
  const oracle = ctx.maxedValueTable!;
  const finishVal = oracle.gemValue(ti.state);
  const processEv = oracle.expectedValueAfterClick(ti.state, ti.offers, ti.turnsLeft - 1, ti.rerolls);
  const handSafe = handIsWcSafe(ti.offers);
  const canReroll = ti.rerolls > 0 && ti.turn !== 1;
  const metrics: Record<string, unknown> = {
    finish_val: finishVal,
    process_ev: processEv,
    hand_safe: handSafe,
  };

  if (canReroll) {
    const rerollVal = oracle.lookup(ti.state, ti.turnsLeft, ti.rerolls - 1);
    metrics['reroll_val'] = rerollVal;
    const bestContinue = handSafe ? Math.max(rerollVal, processEv) : rerollVal;
    if (bestContinue <= finishVal + GRADE_VALUE_EPS) {
      return makeDecision({
        action: ActionKind.FINISH,
        branch: 'maxed_hold',
        reason: `will/chaos maxed, no side/grade upside left`,
        metrics,
      });
    }
    if (handSafe && processEv >= rerollVal) {
      return makeDecision({
        action: ActionKind.PROCESS,
        branch: 'maxed_hold',
        reason: `will/chaos maxed, processing safe hand for side/grade`,
        metrics,
      });
    }
    const reason = handSafe
      ? `will/chaos maxed, rerolling for side/grade`
      : 'will/chaos maxed, rerolling — hand can reduce will/chaos';
    return makeDecision({
      action: ActionKind.REROLL,
      branch: 'maxed_hold',
      reason,
      metrics,
    });
  }

  // No reroll (exhausted / turn 1): process a safe improving hand, else stop.
  if (handSafe && processEv > finishVal + GRADE_VALUE_EPS) {
    return makeDecision({
      action: ActionKind.PROCESS,
      branch: 'maxed_hold',
      reason: `will/chaos maxed, processing safe hand for side/grade`,
      metrics,
    });
  }
  return makeDecision({
    action: ActionKind.FINISH,
    branch: 'maxed_hold',
    reason: `will/chaos maxed, holding — no safe improvement`,
    metrics,
  });
}

function sideValueFinishDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  _m: TurnMetrics
): Decision | null {
  // At the will/chaos cap under --ignore-side-node-values the will_chaos
  // side-value table is degenerate. Delegate to the side-mode maxed oracle.
  if (ctx.maxedValueTable !== null && ti.state.will === 5 && ti.state.chaos === 5) {
    return maxedHoldDecision(ctx, ti);
  }

  const svt = ctx.sideValueTable;
  if (svt === null || !svt.enabled) {
    return null;
  }

  const finishVal = svt.gemValue(ti.state);
  const processEv = svt.expectedValueAfterClick(ti.state, ti.offers, ti.turnsLeft - 1, ti.rerolls);
  const canReroll = ti.rerolls > 0 && ti.turn !== 1;

  if (canReroll) {
    // Never finish with a free reroll in hand.
    const rerollVal = svt.lookup(ti.state, ti.turnsLeft, ti.rerolls - 1);
    const metrics = { finish_val: finishVal, process_ev: processEv, reroll_val: rerollVal };
    if (rerollVal >= processEv) {
      return makeDecision({
        action: ActionKind.REROLL,
        branch: 'side_value_finish',
        reason: `goal met, spending a free reroll`,
        metrics,
      });
    }
    return null; // PROCESS — the offers in hand beat a redraw
  }

  // No reroll available (exhausted, or turn 1): finish vs process.
  const autoGate = ctx.endgameRisk === undefined && !ctx.confirmActive;
  let gradeProtect = false;
  let benchmark = 0;
  if (autoGate) {
    const total = ti.state.totalPoints();
    if (total >= 19) {
      benchmark = svt.ancientCoeff;
    } else if (total >= 16) {
      benchmark = svt.relicCoeff;
    }
    // benchmark stays 0 for legendary grade -> no grade to protect.
    if (benchmark > 0 && sideCoeff(ctx, ti.state) < benchmark) {
      gradeProtect = true;
    }
  }

  // The confirm gate disables only the AUTO-gate above; an explicitly
  // passed endgameRisk is the player's finish bar and applies to gated
  // and ungated gems alike.
  const margin = ctx.endgameRisk === undefined ? 0.0 : ctx.endgameRisk;
  const metrics = {
    finish_val: finishVal,
    process_ev: processEv,
    margin,
    grade_protect: gradeProtect,
  };
  if (!gradeProtect && finishVal < processEv + margin) {
    return null; // PROCESS — continuing beats finishing
  }

  let reason: string;
  if (gradeProtect) {
    reason = `goal met, no rerolls left, side coeff ${sideCoeff(ctx, ti.state)} below grade benchmark ${benchmark} — finishing to protect the grade`;
  } else {
    reason = `goal met, no rerolls left, finish_val>=process_ev+margin`;
  }
  if (ctx.confirmActive && sideCoeff(ctx, ti.state) >= ctx.confirmMinCoeff) {
    return makeDecision({
      action: ActionKind.FINISH,
      branch: 'side_value_finish',
      reason: reason + ' — player confirmation required',
      metrics,
      needsConfirmation: true,
      confirmChoices: legalActions(ti),
    });
  }
  return makeDecision({
    action: ActionKind.FINISH,
    branch: 'side_value_finish',
    reason,
    metrics,
  });
}

// ---------------------------------------------------------------------------
// Branch 1 / 3 helpers: goal infeasibility + no feasible offer
// ---------------------------------------------------------------------------

interface FeasibilityArgs {
  minSideCoeff?: number;
  sideCoeffFirst?: number;
  sideCoeffSecond?: number;
  changeDestMaxCoeff?: number;
}

function feasibilityArgs(ctx: DecisionContext, state: GemState): FeasibilityArgs {
  if (ctx.minSideCoeff <= 0) {
    return {};
  }
  const coeffMap = ctx.optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
  return {
    minSideCoeff: ctx.minSideCoeff,
    sideCoeffFirst: coeffMap[state.firstEffect] ?? 0,
    sideCoeffSecond: coeffMap[state.secondEffect] ?? 0,
    changeDestMaxCoeff: changeDestMaxCoeff(
      ctx.gemType,
      state.firstEffect,
      state.secondEffect,
      ctx.optimize
    ),
  };
}

// Float slack for "the optimal continuation can't beat finishing".
const GRADE_VALUE_EPS = 1e-9;

function gradeValueDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  gvt: SideValueTable,
  branch: string,
  reason: string
): Decision {
  const finishVal = gvt.gemValue(ti.state);
  const processEv = gvt.expectedValueAfterClick(ti.state, ti.offers, ti.turnsLeft - 1, ti.rerolls);
  const canReroll = ti.rerolls > 0 && ti.turn !== 1;
  const metrics: Record<string, unknown> = { finish_val: finishVal, process_ev: processEv };

  if (canReroll) {
    const rerollVal = gvt.lookup(ti.state, ti.turnsLeft, ti.rerolls - 1);
    metrics['reroll_val'] = rerollVal;
    const bestContinue = Math.max(rerollVal, processEv);
    if (bestContinue <= finishVal + GRADE_VALUE_EPS) {
      return makeDecision({
        action: ActionKind.FINISH,
        branch,
        reason: `${reason}, no grade upside left`,
        metrics,
      });
    }
    if (rerollVal >= processEv) {
      return makeDecision({
        action: ActionKind.REROLL,
        branch,
        reason: `${reason}, chasing gem value`,
        metrics,
      });
    }
    return makeDecision({
      action: ActionKind.PROCESS,
      branch,
      reason: `${reason}, processing for gem value`,
      metrics,
    });
  }

  // No reroll (exhausted, or turn 1): finish vs process by value.
  // Explicit endgameRisk margin applies regardless of the confirm gate
  // (mirrors sideValueFinishDecision).
  const margin = ctx.endgameRisk === undefined ? 0.0 : ctx.endgameRisk;
  metrics['margin'] = margin;
  if (finishVal >= processEv + margin) {
    return makeDecision({
      action: ActionKind.FINISH,
      branch,
      reason: `${reason}, finishing for gem value`,
      metrics,
    });
  }
  return makeDecision({
    action: ActionKind.PROCESS,
    branch,
    reason: `${reason}, processing for gem value`,
    metrics,
  });
}

function resetOrChaseRelic(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics,
  branch: string,
  reason: string
): Decision {
  const baseMetrics: Record<string, unknown> = {
    p_keep_relic: m.pKeepRelic,
    p_reroll_relic: m.pRerollRelic,
  };

  if (ti.resetAvailable) {
    return makeDecision({
      action: ActionKind.RESET,
      branch,
      reason,
      metrics: baseMetrics,
    });
  }

  const canReroll = ti.rerolls > 0 && ti.turn !== 1;
  const pRerollGoal = canReroll
    ? ctx.probTable.lookup(ti.state, ti.turnsLeft, ti.rerolls - 1)
    : 0.0;

  // Note: `relicRerollThreshold` does NOT force-finish a dead gem here. Rerolls
  // are free, so while a free reroll (or the current offers) can still reach
  // relic+, the grade-value chase below keeps working them. The threshold's
  // sole job is gating the gold-costing extra ticket (handled at arming time:
  // the ticket only enters the reroll budget when P(relic+) clears the
  // threshold). User directive: use free rerolls to chase a reachable relic+.

  // Preferred path: value-aware grade chase via the goal-independent table.
  const gvt = ctx.gradeValueTable;
  if (gvt !== null && gvt.enabled) {
    // A reroll that can still reach the goal dominates grade chasing.
    if (pRerollGoal > 0) {
      return makeDecision({
        action: ActionKind.REROLL,
        branch,
        reason: `${reason}, rerolling for goal`,
        metrics: { ...baseMetrics, p_reroll_goal: pRerollGoal },
      });
    }
    return gradeValueDecision(ctx, ti, gvt, branch, reason);
  }

  // Binary relic+ fallback — no grade coefficient set, or gem type unknown.
  if (ctx.relicProbTable !== null) {
    const hasChance = m.pKeepRelic > 0 || (canReroll && m.pRerollRelic > 0);
    if (hasChance) {
      if (canReroll && m.pRerollRelic > m.pKeepRelic) {
        return makeDecision({
          action: ActionKind.REROLL,
          branch,
          reason: `${reason}, chasing relic+`,
          metrics: baseMetrics,
        });
      }
      return makeDecision({
        action: ActionKind.PROCESS,
        branch,
        reason: `${reason}, chasing relic+`,
        metrics: baseMetrics,
      });
    }
    // Relic+ unreachable. A reroll might still find a goal-reaching offer.
    if (pRerollGoal > 0) {
      return makeDecision({
        action: ActionKind.REROLL,
        branch,
        reason: `${reason}, rerolling for goal`,
        metrics: { ...baseMetrics, p_reroll_goal: pRerollGoal },
      });
    }
    // Goal AND relic+ both unreachable
    return makeDecision({
      action: ActionKind.FINISH,
      branch,
      reason: 'goal & relic+ both unreachable',
      metrics: baseMetrics,
    });
  }

  // No relic table — try the goal-reroll fallback before failing.
  if (pRerollGoal > 0) {
    return makeDecision({
      action: ActionKind.REROLL,
      branch,
      reason: `${reason}, rerolling for goal`,
      metrics: { ...baseMetrics, p_reroll_goal: pRerollGoal },
    });
  }
  return makeDecision({
    action: ActionKind.FAIL,
    branch,
    reason: `${reason}, no reset available`,
    metrics: baseMetrics,
  });
}

export function infeasibilityDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics
): Decision | null {
  const fa = feasibilityArgs(ctx, ti.state);
  if (
    ctx.goal.feasible(ti.state.will, ti.state.chaos, ti.turnsLeft, ti.state.first, ti.state.second, fa)
  ) {
    return null;
  }
  const decision = resetOrChaseRelic(ctx, ti, m, 'infeasible', 'goal infeasible');
  return maybeConfirm(ctx, ti, decision);
}

export function noFeasibleOfferDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics
): Decision | null {
  if (ti.offers.length === 0 || m.feasibleCount > 0) {
    return null;
  }
  // A gem that already satisfies the goal is a guaranteed success (early
  // finish locks it in) — never hand it to the reset/relic-chase tail.
  // Reachable goal-met only when Branch 0 deferred (gem type unknown, no
  // value tables): every offer would break the goal irrecoverably, so
  // spend a free reroll fishing for a safe hand, else finish.
  if (goalFullySatisfied(ctx, ti.state)) {
    if (ti.rerolls > 0 && ti.turn !== 1) {
      return makeDecision({
        action: ActionKind.REROLL,
        branch: 'no_feasible_offer',
        reason: 'goal met, every offer risks it — rerolling for a safe hand',
      });
    }
    return makeDecision({
      action: ActionKind.FINISH,
      branch: 'no_feasible_offer',
      reason: 'goal met, every offer risks it — finishing to lock success',
    });
  }
  const decision = resetOrChaseRelic(ctx, ti, m, 'no_feasible_offer', 'no offer reaches goal');
  return maybeConfirm(ctx, ti, decision);
}

// ---------------------------------------------------------------------------
// Branch 2: prob_reset_threshold (post-click posterior)
// ---------------------------------------------------------------------------

export function probResetDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics
): Decision | null {
  if (ctx.probResetThreshold <= 0 || !ti.resetAvailable) {
    return null;
  }
  if (goalFullySatisfied(ctx, ti.state)) {
    return null;
  }
  if (m.pKeepGoalReset >= ctx.probResetThreshold) {
    return null;
  }
  return maybeConfirm(
    ctx,
    ti,
    makeDecision({
      action: ActionKind.RESET,
      branch: 'prob_reset',
      reason: `post-click P(goal) < threshold`,
      metrics: { p_keep_goal_reset: m.pKeepGoalReset },
    })
  );
}

// ---------------------------------------------------------------------------
// Branch 4: last-turn fresh-start comparison
// ---------------------------------------------------------------------------

export function lastTurnResetDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics
): Decision | null {
  if (ti.turnsLeft !== 1 || !ti.resetAvailable || ctx.pFresh <= 0) {
    return null;
  }
  if (goalFullySatisfied(ctx, ti.state)) {
    return null;
  }
  if (m.pKeepGoalReset >= ctx.pFresh) {
    return null;
  }
  return maybeConfirm(
    ctx,
    ti,
    makeDecision({
      action: ActionKind.RESET,
      branch: 'last_turn_fresh',
      reason: `last turn post-click < fresh start`,
      metrics: { p_keep_goal_reset: m.pKeepGoalReset, p_fresh: ctx.pFresh },
    })
  );
}

// ---------------------------------------------------------------------------
// Branch 5: DP-optimal reroll (with force-no-progress override)
// ---------------------------------------------------------------------------

export function dpRerollDecision(
  ctx: DecisionContext,
  ti: TurnInput,
  m: TurnMetrics
): Decision | null {
  if (ti.rerolls <= 0 || ti.turn === 1) {
    return null;
  }

  const coeffMap = ctx.optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
  const targetSet = ctx.optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
  const sideCoeffFirst = targetSet.has(ti.state.firstEffect)
    ? coeffMap[ti.state.firstEffect] ?? 0
    : 0;
  const sideCoeffSecond = targetSet.has(ti.state.secondEffect)
    ? coeffMap[ti.state.secondEffect] ?? 0
    : 0;

  if (
    ctx.forceRerollActive &&
    !hasProgressOffer(
      ti.offers,
      ti.state,
      ctx.goal,
      ctx.minSideCoeff,
      sideCoeffFirst,
      sideCoeffSecond
    )
  ) {
    return makeDecision({
      action: ActionKind.REROLL,
      branch: 'dp_reroll',
      reason: `forced_no_progress`,
      metrics: { reasons: ['forced_no_progress'] },
    });
  }

  if (ctx.probTable.shouldRerollDp(ti.state, ti.offers, ti.turnsLeft, ti.rerolls)) {
    return makeDecision({
      action: ActionKind.REROLL,
      branch: 'dp_reroll',
      reason: `dp_reroll_optimal`,
      metrics: { reasons: ['dp_reroll_optimal'] },
    });
  }
  return null;
}

// ---------------------------------------------------------------------------
// Decision-tree assembly
// ---------------------------------------------------------------------------

type BranchFn = (ctx: DecisionContext, ti: TurnInput, m: TurnMetrics) => Decision | null;

const POST_ROLL_BRANCHES: BranchFn[] = [
  earlyFinishDecision,
  infeasibilityDecision,
  probResetDecision,
  noFeasibleOfferDecision,
  lastTurnResetDecision,
  dpRerollDecision,
];

export function decidePostRoll(ctx: DecisionContext, ti: TurnInput): Decision {
  const m = computePostRollMetrics(ctx, ti);
  for (const fn of POST_ROLL_BRANCHES) {
    const d = fn(ctx, ti, m);
    if (d !== null) {
      return d;
    }
  }
  return makeDecision({
    action: ActionKind.PROCESS,
    branch: 'default_process',
    reason: `P(click)`,
    metrics: { p_keep_goal: m.pKeepGoal },
  });
}

export function decideRerollOnly(ctx: DecisionContext, ti: TurnInput): Decision {
  const m = computePostRollMetrics(ctx, ti);
  let d = earlyFinishDecision(ctx, ti, m);
  if (d !== null && d.action === ActionKind.REROLL) {
    return d;
  }
  d = dpRerollDecision(ctx, ti, m);
  if (d !== null) {
    return d;
  }
  return makeDecision({
    action: ActionKind.PROCESS,
    branch: 'default_process',
    reason: `P(click)`,
    metrics: { p_keep_goal: m.pKeepGoal },
  });
}
