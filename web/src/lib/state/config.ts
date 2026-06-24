import type { AdvisorConfig } from '../engine';
import type { DetectionResult } from '../cv/types';
import { RARITY_FROM_TOTAL_STEPS } from '../cv/constants';
import { resolveOptimize } from '../app/optimize';

export interface AdvisorStoredConfig {
  // goal (editable starting suggestion; not a Python default)
  minWill?: number;
  minChaos?: number;
  minFirst?: number;
  minSecond?: number;
  minSideCoeff?: number;
  // tier valuation (null → engine resolves the fusion default)
  relicCoeff: number | null;
  ancientCoeff: number | null;
  // advanced behavioral knobs (Python defaults)
  relicRerollThreshold: number;
  forceRerollNoProgress: number;
  endgameRisk: number | null;          // null → auto-gate (undefined to engine)
  ignoreSideNodeValues: boolean;
  extraTicket: boolean | null;         // tri-state: true on / false off / null armed
  // overrides
  optimizeOverride: 'dps' | 'support' | 'auto';
  rarityOverride: 'common' | 'rare' | 'epic' | 'auto';
  resetOverride: 'auto' | 'always' | 'never';
}

export const DEFAULT_CONFIG: AdvisorStoredConfig = {
  minWill: 4, minChaos: 4,
  relicCoeff: null, ancientCoeff: null,
  relicRerollThreshold: 0, forceRerollNoProgress: 0, endgameRisk: null,
  ignoreSideNodeValues: false, extraTicket: null,
  optimizeOverride: 'auto', rarityOverride: 'auto', resetOverride: 'auto',
};

export function effectiveConfig(
  stored: AdvisorStoredConfig, det: DetectionResult,
): { advisorConfig: AdvisorConfig; optimize: 'dps' | 'support'; resetOverride: 'auto' | 'always' | 'never' } {
  const rarity = stored.rarityOverride !== 'auto'
    ? stored.rarityOverride
    : (RARITY_FROM_TOTAL_STEPS[det.totalSteps ?? 7] ?? 'rare') as 'common' | 'rare' | 'epic';
  const optimize = resolveOptimize(det.firstEffect ?? '', det.secondEffect ?? '', stored.optimizeOverride);
  const advisorConfig: AdvisorConfig = {
    rarity,
    minWill: stored.minWill,
    minChaos: stored.minChaos,
    minFirst: stored.minFirst,
    minSecond: stored.minSecond,
    minSideCoeff: stored.minSideCoeff,
    relicCoeff: stored.relicCoeff,
    ancientCoeff: stored.ancientCoeff,
    relicRerollThreshold: stored.relicRerollThreshold,
    forceRerollNoProgress: stored.forceRerollNoProgress,
    endgameRisk: stored.endgameRisk ?? undefined,
    ignoreSideNodeValues: stored.ignoreSideNodeValues,
    extraTicket: stored.extraTicket,
    optimize,
  };
  return { advisorConfig, optimize, resetOverride: stored.resetOverride };
}
