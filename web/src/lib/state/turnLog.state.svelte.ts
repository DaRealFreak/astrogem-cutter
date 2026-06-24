import type { DetectionResult } from '../cv/types';
import type { ActionKind } from '../engine';
import { classifyRunTransition, type RunIdentity } from '../app/runTransition';

export interface TurnLogEntry {
  turn: number; will: number; chaos: number; firstLevel: number; secondLevel: number;
  action: ActionKind; pGoal: number; eValue: number;
}

class TurnLog {
  entries = $state<TurnLogEntry[]>([]);
  resetObserved = $state(false);
  #prev: { turn: number; id: RunIdentity } | null = null;

  observe(det: DetectionResult, action: ActionKind, pGoal: number, eValue: number): void {
    const turn = (det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1;
    const id: RunIdentity = { gemType: det.gemType, firstEffect: det.firstEffect, secondEffect: det.secondEffect };
    const transition = classifyRunTransition(this.#prev, { turn, id });
    if (transition === 'new-gem') { this.entries = []; this.resetObserved = false; }
    else if (transition === 'reset') { this.resetObserved = true; }
    this.#prev = { turn, id };

    const last = this.entries[this.entries.length - 1];
    const distinct = !last || last.turn !== turn || last.will !== (det.willpower ?? 0) || last.chaos !== (det.chaos ?? 0)
      || last.firstLevel !== (det.firstLevel ?? 0) || last.secondLevel !== (det.secondLevel ?? 0);
    if (distinct) {
      this.entries = [...this.entries, {
        turn, will: det.willpower ?? 0, chaos: det.chaos ?? 0,
        firstLevel: det.firstLevel ?? 0, secondLevel: det.secondLevel ?? 0,
        action, pGoal, eValue,
      }];
    }
  }

  clear(): void { this.entries = []; this.resetObserved = false; this.#prev = null; }
}

export const turnLog = new TurnLog();
