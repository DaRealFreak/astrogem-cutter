import type { DetectionResult } from '../cv/types';
import { classifyRunTransition, turnFromDetection, type RunIdentity } from './runTransition';

interface TurnStats {
  will: number;
  chaos: number;
  first: number;
  second: number;
}

function statsOf(det: DetectionResult): TurnStats {
  return {
    will: det.willpower ?? 0,
    chaos: det.chaos ?? 0,
    first: det.firstLevel ?? 0,
    second: det.secondLevel ?? 0,
  };
}

function sameStats(a: TurnStats, b: TurnStats): boolean {
  return a.will === b.will && a.chaos === b.chaos && a.first === b.first && a.second === b.second;
}

function offersOf(det: DetectionResult): string {
  return JSON.stringify(det.options.map((o) => [o.nameKey, o.deltaKey]));
}

/**
 * Rejects in-game-cursor artifacts on live frames.
 *
 * Within one turn of one run the screen's advice-relevant state can only
 * change in two ways: nothing at all, or a reroll (new offers AND a lower
 * reroll count). The gem's stats (willpower/chaos/side-node levels) are
 * immutable until a processing is applied, which also moves the step counter.
 *
 * The captured in-game cursor breaks both invariants: parking it on an offer
 * card previews the result on the gem (hovering "Additional Damage Lv. +3" at
 * Lv. 2 renders the side node as Lv. 5) and the cursor sprite itself overlaps
 * a card and corrupts its name/delta read. Both artifacts hold still long
 * enough to pass the anti-flicker gate, which spammed the turn log with
 * phantom entries and fed previewed/corrupted state into the advice.
 *
 * The latch pins the first settled reading per (run identity, turn) and
 * rejects later same-turn readings that violate the invariants:
 *   - stats differ                      -> hover preview, reject
 *   - offers differ, reroll count same  -> cursor over a card, reject
 *   - offers differ, reroll count moved -> real reroll, accept + re-pin
 * A new gem, a reset, or a step change always re-pins.
 *
 * Known limitation: if the cursor already sits on a card when the turn's first
 * reading settles, the corrupted state gets pinned and the true state is
 * rejected until the next turn — same failure window as before, but it no
 * longer flip-flops.
 */
export class TurnStateLatch {
  #pinned: { turn: number; id: RunIdentity; stats: TurnStats; offers: string; rerolls: string | null } | null = null;

  /** @returns true when the reading is trustworthy (and pins it); false for a
   *  same-turn invariant violation (cursor artifact — discard the frame). */
  accept(det: DetectionResult): boolean {
    const turn = turnFromDetection(det);
    const id: RunIdentity = {
      gemType: det.gemType,
      firstEffect: det.firstEffect,
      secondEffect: det.secondEffect,
    };
    const stats = statsOf(det);
    const offers = offersOf(det);
    const transition = classifyRunTransition(
      this.#pinned && { turn: this.#pinned.turn, id: this.#pinned.id },
      { turn, id },
    );
    if (transition === 'continue' && this.#pinned !== null && turn === this.#pinned.turn) {
      if (!sameStats(stats, this.#pinned.stats)) {
        return false; // hover preview altered the gem display
      }
      if (offers !== this.#pinned.offers && det.rerolls === this.#pinned.rerolls) {
        return false; // offers can't change without spending a reroll
      }
    }
    this.#pinned = { turn, id, stats, offers, rerolls: det.rerolls ?? null };
    return true;
  }

  reset(): void {
    this.#pinned = null;
  }
}
