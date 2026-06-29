/**
 * Debounce window (ms) for re-scoring the last reading after a config change.
 *
 * Editing a knob fires an `input` event per step — dragging the slider or
 * holding a number-field arrow emits a burst of them, each its own event-loop
 * task. The recompute rebuilds the DP (tens of ms), so running it per step makes
 * the drag stutter. This window outlasts the ~16-50ms gap between steps, so a
 * burst collapses into a single recompute once the player stops changing the
 * value. Long enough to coalesce, short enough to feel immediate after release.
 */
export const RECOMPUTE_DEBOUNCE_MS = 200;

/**
 * Trailing debounce: coalesces a burst of rapid `schedule()` calls into one
 * deferred invocation that fires `delayMs` after the *last* call. Each new
 * `schedule()` cancels the previous pending call, so only the final value runs.
 */
export class Debouncer {
  #timer: ReturnType<typeof setTimeout> | null = null;
  readonly #delayMs: number;

  constructor(delayMs: number) {
    this.#delayMs = Math.max(0, delayMs);
  }

  /** Run `fn` after the debounce window, cancelling any earlier pending call. */
  schedule(fn: () => void): void {
    this.cancel();
    this.#timer = setTimeout(() => {
      this.#timer = null;
      fn();
    }, this.#delayMs);
  }

  /** Drop a pending call without running it. */
  cancel(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
  }

  /** True while a scheduled call is waiting to fire. */
  get pending(): boolean {
    return this.#timer !== null;
  }
}
