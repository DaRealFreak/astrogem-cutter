import type { DetectionResult } from '../cv/types';
import type { AdvisorOutput } from '../engine';
import type { AdvisorStoredConfig } from '../state/config';
import { computeAdvice } from './computeAdvice';

/**
 * Sink for advisory results. Decouples the recompute orchestration from the
 * reactive Svelte stores so the logic is unit-testable without a DOM.
 */
export interface AdviceSink {
  /** Push a fresh advisory output (recommendation + odds) to the UI. */
  applyAdvice(det: DetectionResult, output: AdvisorOutput): void;
  /** Append the reading to the turn log. Skipped on config-only recomputes. */
  observeTurn(det: DetectionResult, output: AdvisorOutput): void;
}

/**
 * Recompute advice for a detection and push it to the sink.
 *
 * `logTurn` decides whether this also records a turn-log entry: `true` for a
 * fresh detection frame (a real turn), `false` for a config-change recompute
 * (the same reading re-scored against a new goal — no new turn happened, so
 * logging one would be a phantom entry).
 *
 * @returns true if advice was produced and applied, false if the detection was
 *   incomplete (in which case the sink is left untouched).
 */
export function syncAdvice(
  det: DetectionResult,
  config: AdvisorStoredConfig,
  resetObserved: boolean,
  ticketSpent: boolean,
  logTurn: boolean,
  sink: AdviceSink,
): boolean {
  const { ready, output } = computeAdvice(det, config, resetObserved, ticketSpent);
  if (!ready || !output) return false;
  sink.applyAdvice(det, output);
  if (logTurn) sink.observeTurn(det, output);
  return true;
}
