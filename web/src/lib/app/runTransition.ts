import type { DetectionResult } from '../cv/types';

export interface RunIdentity { gemType: string | null; firstEffect: string | null; secondEffect: string | null; }

/** Turn number from the on-screen step counter (mirrors turnLog's formula). */
export function turnFromDetection(det: DetectionResult): number {
  return (det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1;
}

function sameId(a: RunIdentity, b: RunIdentity): boolean {
  return a.gemType === b.gemType && a.firstEffect === b.firstEffect && a.secondEffect === b.secondEffect;
}

/** Classify the transition between two observed frames (a reset restarts the turn counter,
 *  so the only signal distinguishing reset from a new gem is unchanged identity). */
export function classifyRunTransition(
  prev: { turn: number; id: RunIdentity } | null,
  next: { turn: number; id: RunIdentity },
): 'continue' | 'new-gem' | 'reset' {
  if (!prev) return 'continue';
  if (!sameId(prev.id, next.id)) return 'new-gem';
  if (next.turn < prev.turn && next.turn === 1) return 'reset';
  return 'continue';
}

/** Reset is a one-time restart available until observed; overridable. */
export function inferResetFromLog(resetObserved: boolean, override: 'auto' | 'always' | 'never'): boolean {
  if (override === 'always') return true;
  if (override === 'never') return false;
  return !resetObserved;
}

/**
 * Resolve whether the reset ticket is available for this frame.
 *
 * A manual override always wins. Otherwise the reset button's detected
 * brightness (`detectedResetEnabled`) is authoritative — the in-game button is
 * greyed once the ticket is spent (and on turn 1, where reset is a no-op), so
 * the screen tells us directly. The stateless log inference (`!resetObserved`)
 * is only a fallback for detections that predate brightness detection (e.g. a
 * fixture without the field).
 */
export function resolveResetAvailable(
  detectedResetEnabled: boolean | null | undefined,
  resetObserved: boolean,
  override: 'auto' | 'always' | 'never',
): boolean {
  if (override === 'always') return true;
  if (override === 'never') return false;
  if (typeof detectedResetEnabled === 'boolean') return detectedResetEnabled;
  return !resetObserved;
}
