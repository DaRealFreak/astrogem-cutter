import type { DetectionResult } from '../cv/types';

/**
 * Number of consecutive identical readings required before a detection is
 * trusted. The game animates for ~0.2-0.4s after a turn flips; at ~20-30
 * processed frames/s, three agreeing readings (~100-150ms past settle) reliably
 * outlast the transient misreads without adding noticeable latency.
 */
export const STABILITY_FRAMES = 3;

/**
 * Build a signature from the advice-relevant detection fields. Two frames with
 * the same signature produce identical advice, so a signature that holds across
 * frames means the screen has finished animating and the reading can be
 * trusted. Cosmetic fields (match scores, anchor pixel position) are excluded
 * so score jitter on an otherwise-identical frame does not reset the counter.
 */
export function detectionSignature(det: DetectionResult): string {
  return JSON.stringify([
    det.gemType, det.firstEffect, det.secondEffect,
    det.willpower, det.chaos, det.firstLevel, det.secondLevel,
    det.currentStep, det.totalSteps, det.rerolls, det.resetEnabled ?? null,
    det.options.map((o) => [o.nameKey, o.deltaKey]),
  ]);
}

/**
 * Debounces detections across frames. During the post-turn-flip animation the
 * side-node digits and offers misread and oscillate, which otherwise flickers
 * the advice and spams the turn log.
 *
 * `push()` returns `true` exactly once — on the reading where a signature has
 * held for `frames` consecutive frames (i.e. once the screen has settled) — and
 * then stays `false` until the signature changes. So each settled state commits
 * exactly once; rerolls and processes (which change the signature) re-settle and
 * commit again. A `null` signature (incomplete / off-screen) resets the streak.
 */
export class DetectionStabilizer {
  #sig: string | null = null;
  #count = 0;
  readonly #frames: number;

  constructor(frames: number = STABILITY_FRAMES) {
    this.#frames = Math.max(1, frames);
  }

  /** @returns true once, on the reading that reaches the stability threshold. */
  push(signature: string | null): boolean {
    if (signature === null) {
      this.reset();
      return false;
    }
    if (signature === this.#sig) {
      this.#count += 1;
    } else {
      this.#sig = signature;
      this.#count = 1;
    }
    return this.#count === this.#frames;
  }

  reset(): void {
    this.#sig = null;
    this.#count = 0;
  }
}
