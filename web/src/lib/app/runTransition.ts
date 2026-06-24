export interface RunIdentity { gemType: string | null; firstEffect: string | null; secondEffect: string | null; }

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
