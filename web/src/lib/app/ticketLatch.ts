import type { DetectionResult } from '../cv/types';
import { classifyRunTransition, turnFromDetection, type RunIdentity } from './runTransition';

export interface TicketLatch {
  spent: boolean;
  prev: { turn: number; id: RunIdentity } | null;
}

export function initTicketLatch(): TicketLatch {
  return { spent: false, prev: null };
}

/**
 * Advance the once-per-cutting-process extra-ticket latch by one observed frame.
 *
 * Clears `spent` on a new gem OR a reset — both start a fresh cutting process,
 * which grants a fresh extra reroll ticket. Latches `spent` the first frame the
 * Charge button is greyed with no free rerolls left (spent this run, or never
 * owned). This is what the stateless `ticketAvailableFromDetection` heuristic
 * cannot remember once free rerolls replenish.
 *
 * The latch also self-heals: a *yellow* Charge button at 0 free rerolls proves
 * the ticket is unspent (a spent ticket cannot return within the same cutting
 * process), so it clears a `spent` that was latched off a bad frame (capture
 * blip, dialog overlay darkening the button).
 */
export function observeTicketLatch(
  s: TicketLatch, det: DetectionResult, freeRerolls: number,
): TicketLatch {
  const turn = turnFromDetection(det);
  const id: RunIdentity = {
    gemType: det.gemType, firstEffect: det.firstEffect, secondEffect: det.secondEffect,
  };
  const transition = classifyRunTransition(s.prev, { turn, id });
  let spent = transition === 'new-gem' || transition === 'reset' ? false : s.spent;
  if (freeRerolls <= 0 && det.chargeEnabled === false) spent = true;
  else if (freeRerolls <= 0 && det.chargeEnabled === true) spent = false;
  return { spent, prev: { turn, id } };
}
