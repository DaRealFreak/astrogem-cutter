import type { DetectionResult } from '../cv/types';
import { DPS_EFFECTS, SUPPORT_EFFECTS } from '../engine/constants';
import { THRESHOLD_GEM_INFO, THRESHOLD_OPTION_NAME } from '../cv/constants';

export function resolveOptimize(
  firstEffect: string, secondEffect: string, override: 'dps' | 'support' | 'auto' = 'auto',
): 'dps' | 'support' {
  if (override === 'dps' || override === 'support') return override;
  const anyDps = DPS_EFFECTS.has(firstEffect) || DPS_EFFECTS.has(secondEffect);
  const anySup = SUPPORT_EFFECTS.has(firstEffect) || SUPPORT_EFFECTS.has(secondEffect);
  if (anySup && !anyDps) return 'support';
  if (anyDps) return 'dps';
  if (anySup) return 'support';
  return 'dps';
}

export function inferResetAvailable(turn: number, override: 'auto' | 'always' | 'never' = 'auto'): boolean {
  if (override === 'always') return true;
  if (override === 'never') return false;
  return turn === 1;
}

/** Gate: only confident, fully-detected cutting-screen frames feed the engine. */
export function isCompleteDetection(det: DetectionResult): boolean {
  if (!det.found) return false;
  if (!det.gemType || det.gemTypeScore < THRESHOLD_GEM_INFO) return false;
  if (det.willpower === null || det.chaos === null) return false;
  if (det.currentStep === null || det.totalSteps === null) return false;
  if (det.options.length !== 4) return false;
  for (const o of det.options) {
    if (!o.nameKey || o.nameScore < THRESHOLD_OPTION_NAME) return false;
  }
  return true;
}
