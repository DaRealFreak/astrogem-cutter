import type { AdvisorConfig } from '../engine';
import type { DetectionResult } from '../cv/types';
import { RARITY_FROM_TOTAL_STEPS } from '../cv/constants';
import { resolveOptimize, gemCoeffSum } from '../app/optimize';

const RARITY_RANK: Record<string, number> = { common: 0, rare: 1, epic: 2 };

export interface AdvisorStoredConfig {
  // goal (editable starting suggestion; not a Python default)
  minWill?: number;
  minChaos?: number;
  minFirst?: number;
  minSecond?: number;
  minSideCoeff?: number;
  // goal shape
  goalMode: 'separate' | 'combined';
  minWillChaosTotal?: number;
  // tier valuation (null → engine resolves the fusion default)
  relicCoeff: number | null;
  ancientCoeff: number | null;
  // advanced behavioral knobs (Python defaults)
  relicRerollThreshold: number;
  forceRerollNoProgress: number;
  endgameRisk: number | null;          // null → auto-gate (undefined to engine)
  ignoreSideNodeValues: boolean;
  extraTicket: boolean | null;         // tri-state: true on / false off / null armed
  // coefficient/rarity gates (port of --reroll-min-coeff / --reset-min-coeff / --reset-ticket)
  rerollMinCoeff: number;              // arm extra reroll ticket only if gem coeff ≥ N (0 = off)
  resetMinCoeff: number;               // allow reset only if gem coeff ≥ N (0 = off)
  resetTicketRarity: 'off' | 'common' | 'rare' | 'epic'; // allow reset only at this rarity or higher
  // overrides
  optimizeOverride: 'dps' | 'support' | 'auto';
  rarityOverride: 'common' | 'rare' | 'epic' | 'auto';
  resetOverride: 'auto' | 'always' | 'never';
}

export const DEFAULT_CONFIG: AdvisorStoredConfig = {
  minWill: 4, minChaos: 4,
  goalMode: 'combined',
  minWillChaosTotal: 8,
  relicCoeff: null, ancientCoeff: null,
  relicRerollThreshold: 0, forceRerollNoProgress: 0, endgameRisk: null,
  ignoreSideNodeValues: false, extraTicket: null,
  rerollMinCoeff: 0, resetMinCoeff: 0, resetTicketRarity: 'off',
  optimizeOverride: 'auto', rarityOverride: 'auto', resetOverride: 'auto',
};

export function effectiveConfig(
  stored: AdvisorStoredConfig, det: DetectionResult,
): {
  advisorConfig: AdvisorConfig;
  optimize: 'dps' | 'support';
  resetOverride: 'auto' | 'always' | 'never';
  /** Whether the gem clears the reset coeff + rarity bars (false → suppress reset). */
  resetPolicyAllowed: boolean;
  /** Resolved sum of the gem's target-effect coefficients (for display/debug). */
  coeffSum: number;
} {
  const rarity = stored.rarityOverride !== 'auto'
    ? stored.rarityOverride
    : (RARITY_FROM_TOTAL_STEPS[det.totalSteps ?? 7] ?? 'rare') as 'common' | 'rare' | 'epic';
  const optimize = resolveOptimize(det.firstEffect ?? '', det.secondEffect ?? '', stored.optimizeOverride);
  const coeffSum = gemCoeffSum(det.firstEffect ?? '', det.secondEffect ?? '', optimize);

  // --reroll-min-coeff is no longer a one-time on/off gate on the ticket: it is a
  // per-turn enabler in the engine (expected side-coefficient vs the bar). We
  // just forward the tri-state ownership and the bar to the engine.
  const extraTicket = stored.extraTicket;

  // --reset-min-coeff / --reset-ticket <rarity>: only allow reset on a gem that
  // clears both bars (0 / 'off' = no gate).
  const resetCoeffOk = (stored.resetMinCoeff ?? 0) <= 0 || coeffSum >= stored.resetMinCoeff;
  const gate = stored.resetTicketRarity ?? 'off';
  const resetRarityOk = gate === 'off' || (RARITY_RANK[rarity] ?? 0) >= (RARITY_RANK[gate] ?? 0);
  const resetPolicyAllowed = resetCoeffOk && resetRarityOk;

  const separate = stored.goalMode !== 'combined';
  const advisorConfig: AdvisorConfig = {
    rarity,
    minWill: separate ? stored.minWill : undefined,
    minChaos: separate ? stored.minChaos : undefined,
    minTotalWillChaos: separate ? undefined : stored.minWillChaosTotal,
    minFirst: stored.minFirst,
    minSecond: stored.minSecond,
    minSideCoeff: stored.minSideCoeff,
    relicCoeff: stored.relicCoeff,
    ancientCoeff: stored.ancientCoeff,
    relicRerollThreshold: stored.relicRerollThreshold,
    forceRerollNoProgress: stored.forceRerollNoProgress,
    endgameRisk: stored.endgameRisk ?? undefined,
    ignoreSideNodeValues: stored.ignoreSideNodeValues,
    extraTicket,
    rerollMinCoeff: stored.rerollMinCoeff,
    optimize,
  };
  return { advisorConfig, optimize, resetOverride: stored.resetOverride, resetPolicyAllowed, coeffSum };
}
