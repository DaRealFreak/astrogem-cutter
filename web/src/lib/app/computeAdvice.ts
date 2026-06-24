import type { DetectionResult } from '../cv/types';
import { detectionToEngineInputs } from '../cv/adapter';
import { buildEngineContext, advise, type EngineContext, type AdvisorOutput } from '../engine';
import { isCompleteDetection, inferResetAvailable } from './optimize';
import { effectiveConfig, type AdvisorStoredConfig } from '../state/config';

let cache: { key: string; ctx: EngineContext } | null = null;
export function resetAdviceCache(): void { cache = null; }

export function computeAdvice(
  det: DetectionResult, stored: AdvisorStoredConfig,
): { ready: boolean; output: AdvisorOutput | null } {
  if (!isCompleteDetection(det)) return { ready: false, output: null };

  const eff = effectiveConfig(stored, det);
  const turn = (det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1;
  const resetAvailable = inferResetAvailable(turn, eff.resetOverride);

  const inputs = detectionToEngineInputs(det, {
    optimize: eff.optimize,
    extraTicket: stored.extraTicket === true,
    resetAvailable,
  });

  const key = JSON.stringify([
    inputs.gem.gemType, inputs.gem.firstEffect, inputs.gem.secondEffect, eff.advisorConfig,
  ]);
  if (!cache || cache.key !== key) {
    cache = { key, ctx: buildEngineContext(inputs.gem, eff.advisorConfig) };
  }

  const output = advise(cache.ctx, {
    state: inputs.state, offers: inputs.offers, turn: inputs.turn,
    turnsLeft: inputs.turnsLeft, rerolls: inputs.rerolls, resetAvailable: inputs.resetAvailable,
  });
  return { ready: true, output };
}
