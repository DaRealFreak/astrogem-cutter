import type { DetectionResult } from '../cv/types';
import type { AdvisorOutput } from '../engine';
import { effectiveConfig, type AdvisorStoredConfig } from '../state/config';
import { parseRerolls } from '../cv/parse';
import type { TurnLogEntry } from '../state/turnLog.state.svelte';

/** Curated, human-readable snapshot of the current advice for copy-to-clipboard. */
export function buildAdvisorSnapshot(
  det: DetectionResult,
  stored: AdvisorStoredConfig,
  output: AdvisorOutput,
  turnLogEntries: TurnLogEntry[],
): object {
  const eff = effectiveConfig(stored, det);
  return {
    gem: {
      gemType: det.gemType,
      optimize: eff.optimize,
      willpower: det.willpower,
      chaos: det.chaos,
      first: { effect: det.firstEffect, level: det.firstLevel },
      second: { effect: det.secondEffect, level: det.secondLevel },
      freeRerolls: parseRerolls(det.rerolls, false),
      resetAvailable: output.actions.reset !== null,
      chargeEnabled: det.chargeEnabled ?? null,
      step: { current: det.currentStep, total: det.totalSteps },
    },
    goal: eff.advisorConfig,
    advice: {
      action: output.action,
      branch: output.branch,
      reason: output.reason,
      headline: {
        pGoal: output.pGoal, pRelic: output.pRelic, pAncient: output.pAncient, eValue: output.eValue,
      },
      actions: output.actions,
      perOffer: output.perOffer,
    },
    ticket: output.ticket ?? null,
    turnLog: turnLogEntries,
  };
}
