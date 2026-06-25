import type { DetectionResult } from '../cv/types';

/**
 * Whether the owned extra reroll ticket should be assumed available this frame.
 *
 * The web advisor is stateless across turns, so it cannot track whether the
 * ticket was already spent. Heuristic (per the user): assume it is available
 * while free rerolls remain — the in-game "Charge" button isn't shown yet, so we
 * can't tell — and once free rerolls hit 0, trust the detected Charge-button
 * state (yellow = available, greyed = spent/none).
 *
 * `det.chargeEnabled` is the brightness-read Charge-button signal; until
 * detection supplies it (null/undefined) the free==0 case also assumes
 * available (the documented stateless fallback).
 */
export function ticketAvailableFromDetection(
  det: DetectionResult, freeRerolls: number,
): boolean {
  if (freeRerolls <= 0 && det.chargeEnabled != null) return det.chargeEnabled;
  return true;
}
