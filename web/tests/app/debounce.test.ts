import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Debouncer, RECOMPUTE_DEBOUNCE_MS } from '../../src/lib/app/debounce';

describe('Debouncer', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('runs the callback once after the delay, not before', () => {
    const d = new Debouncer(200);
    const fn = vi.fn();
    d.schedule(fn);
    vi.advanceTimersByTime(199);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('coalesces a rapid burst into a single trailing call', () => {
    // Models dragging a slider: each step is its own event-loop task ~30ms apart.
    // The old setTimeout(0) fired one recompute per step; the debounce must fire
    // exactly once, after the player stops.
    const d = new Debouncer(200);
    const fn = vi.fn();
    for (let i = 0; i < 10; i++) {
      d.schedule(fn);
      vi.advanceTimersByTime(30); // well under the 200ms window
    }
    expect(fn).not.toHaveBeenCalled(); // nothing fired mid-drag
    vi.advanceTimersByTime(200); // player lets go
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('reschedules to the latest callback (last write wins)', () => {
    const d = new Debouncer(100);
    const stale = vi.fn();
    const latest = vi.fn();
    d.schedule(stale);
    vi.advanceTimersByTime(50); // not yet fired
    d.schedule(latest); // replaces the pending call and restarts the window
    vi.advanceTimersByTime(100);
    expect(stale).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledTimes(1);
  });

  it('cancel() drops a pending call', () => {
    const d = new Debouncer(100);
    const fn = vi.fn();
    d.schedule(fn);
    expect(d.pending).toBe(true);
    d.cancel();
    expect(d.pending).toBe(false);
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });

  it('pending clears once the call fires', () => {
    const d = new Debouncer(100);
    d.schedule(() => {});
    expect(d.pending).toBe(true);
    vi.advanceTimersByTime(100);
    expect(d.pending).toBe(false);
  });
});

describe('RECOMPUTE_DEBOUNCE_MS', () => {
  it('is long enough to coalesce a slider drag', () => {
    // Drag/keyboard steps land ~16-50ms apart; the window must comfortably
    // outlast that so a drag yields one recompute, not one per step. A 0ms
    // delay (the pre-fix value) would recompute on every step.
    expect(RECOMPUTE_DEBOUNCE_MS).toBeGreaterThanOrEqual(120);
  });
});
