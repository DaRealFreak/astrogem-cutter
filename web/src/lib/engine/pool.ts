// Port of arkgrid/pool.py (_build_pool + eligible + _can_increase/_can_decrease)
// Skips: generate_offers, _weighted_* (RNG, out of scope)

import type { Option, GemState } from './models';
import { makeOption } from './models';

export class OptionPool {
  readonly pool: Option[];

  constructor() {
    this.pool = this._buildPool();
  }

  private _buildPool(): Option[] {
    const pool: Option[] = [];

    const add = (key: string, weight: number, kind: string, delta = 0): void => {
      pool.push(makeOption(key, weight, kind, delta));
    };

    // Willpower
    add("will+1", 11.6500, "will", 1);
    add("will+2", 4.4000, "will", 2);
    add("will+3", 1.7500, "will", 3);
    add("will+4", 0.4500, "will", 4);
    add("will-1", 3.0000, "will", -1);

    // Chaos
    add("chaos+1", 11.6500, "chaos", 1);
    add("chaos+2", 4.4000, "chaos", 2);
    add("chaos+3", 1.7500, "chaos", 3);
    add("chaos+4", 0.4500, "chaos", 4);
    add("chaos-1", 3.0000, "chaos", -1);

    // First
    add("first+1", 11.6500, "first", 1);
    add("first+2", 4.4000, "first", 2);
    add("first+3", 1.7500, "first", 3);
    add("first+4", 0.4500, "first", 4);
    add("first-1", 3.0000, "first", -1);

    // Second
    add("second+1", 11.6500, "second", 1);
    add("second+2", 4.4000, "second", 2);
    add("second+3", 1.7500, "second", 3);
    add("second+4", 0.4500, "second", 4);
    add("second-1", 3.0000, "second", -1);

    // Other
    add("change_first_effect", 3.2500, "other", 0);
    add("change_second_effect", 3.2500, "other", 0);
    add("maintain", 1.7500, "other", 0);

    // Cost modifiers
    add("cost+100", 1.7500, "cost", 0);
    add("cost-100", 1.7500, "cost", 0);

    // View => modeled as gaining rerolls
    add("view+1", 2.5000, "view", 1);
    add("view+2", 0.7500, "view", 2);

    return pool;
  }

  private static _canIncrease(cur: number, k: number): boolean {
    return cur <= 5 - k;
  }

  private static _canDecrease(cur: number): boolean {
    return cur >= 2;
  }

  eligible(opt: Option, state: GemState, turn: number, turnsLeft: number): boolean {
    if (opt.kind === "will") {
      return opt.delta > 0
        ? OptionPool._canIncrease(state.will, opt.delta)
        : OptionPool._canDecrease(state.will);
    }
    if (opt.kind === "chaos") {
      return opt.delta > 0
        ? OptionPool._canIncrease(state.chaos, opt.delta)
        : OptionPool._canDecrease(state.chaos);
    }
    if (opt.kind === "first") {
      return opt.delta > 0
        ? OptionPool._canIncrease(state.first, opt.delta)
        : OptionPool._canDecrease(state.first);
    }
    if (opt.kind === "second") {
      return opt.delta > 0
        ? OptionPool._canIncrease(state.second, opt.delta)
        : OptionPool._canDecrease(state.second);
    }

    // cost options excluded on last turn
    if (opt.kind === "cost") {
      if (turnsLeft === 1) {
        return false;
      }
      if (opt.key === "cost+100") {
        return state.costRatio < 100;
      }
      if (opt.key === "cost-100") {
        return state.costRatio > -100;
      }
      return true;
    }

    // view options excluded on the last turn only (per the official
    // disclosure and verified in-game: they CAN appear among the turn-1
    // picks — the reroll BUTTON is what's locked on turn 1, and rerolls
    // banked from a turn-1 view pick are usable from turn 2).
    if (opt.kind === "view") {
      if (turnsLeft === 1) {
        return false;
      }
      return true;
    }

    return true;
  }
}
