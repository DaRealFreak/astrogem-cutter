import type { DetectionResult } from '../cv/types';
import { initTicketLatch, observeTicketLatch, type TicketLatch } from '../app/ticketLatch';

/**
 * Run-scoped latch for the once-per-cutting-process extra reroll ticket. Observed
 * once per committed frame BEFORE computeAdvice reads `spent`, so the advice never
 * lends a ticket we've seen spent. Clears on new-gem/reset (handled in the latch).
 */
class TicketRun {
  spent = $state(false);
  #latch: TicketLatch = initTicketLatch();

  observe(det: DetectionResult, freeRerolls: number): void {
    this.#latch = observeTicketLatch(this.#latch, det, freeRerolls);
    this.spent = this.#latch.spent;
  }
}

export const ticketRun = new TicketRun();
