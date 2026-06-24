/**
 * DetectionResult → engine inputs adapter.
 *
 * Ports three functions from arkgrid/automation.py:
 *   - _parse_view_delta  (lines 412-417)
 *   - _analyze_frame state/turn build (lines 430-450)
 *   - _detected_to_options (lines 522-550)
 */

import {
  parseRerolls,
  parseDelta,
  determineOptionKind,
  type DetectionResult,
} from './parse';
import { GEM_TYPE_TEMPLATE_TO_DOMAIN } from './constants';
import { GemState, makeOption, type AstroGem, type Option } from '../engine/models';

// ---------------------------------------------------------------------------
// parseViewDelta — port of _parse_view_delta
// Extract signed integer from a view/reroll delta key (e.g. 'reroll+1' -> 1).
// ---------------------------------------------------------------------------

export function parseViewDelta(deltaKey: string | null): number {
  if (!deltaKey) {
    return 0;
  }
  const m = deltaKey.match(/[+-]?\d+/);
  return m ? parseInt(m[0], 10) : 0;
}

// ---------------------------------------------------------------------------
// EngineInputs — the full set of inputs Plan 1's advise() consumes.
// ---------------------------------------------------------------------------

export interface EngineInputs {
  gem: AstroGem;
  state: GemState;
  offers: Option[];
  turn: number;
  turnsLeft: number;
  turnsTotal: number;
  rerolls: number;
  resetAvailable: boolean;
}

// ---------------------------------------------------------------------------
// detectionToEngineInputs — port of _analyze_frame + _detected_to_options
// ---------------------------------------------------------------------------

export function detectionToEngineInputs(
  det: DetectionResult,
  opts: { optimize: 'dps' | 'support'; extraTicket?: boolean; resetAvailable?: boolean },
): EngineInputs {
  // --- Gem type domain mapping (from _analyze_frame:430) ---
  const gemType = det.gemType
    ? (GEM_TYPE_TEMPLATE_TO_DOMAIN[det.gemType] ?? det.gemType)
    : '';

  // --- Turn fields (from _analyze_frame:432-434) ---
  const turnsTotal = det.totalSteps ?? 0;
  const turnsLeft = det.currentStep ?? 0;
  const turn = turnsTotal - turnsLeft + 1;

  // --- Rerolls (from _analyze_frame:436-439) ---
  const rerolls = parseRerolls(det.rerolls, opts.extraTicket ?? false);

  // --- AstroGem ---
  const gem: AstroGem = {
    gemType,
    firstEffect: det.firstEffect ?? '',
    secondEffect: det.secondEffect ?? '',
    optimize: opts.optimize,
  };

  // --- GemState (from _analyze_frame:441-450) ---
  const state = new GemState({
    will: det.willpower ?? 1,
    chaos: det.chaos ?? 1,
    first: det.firstLevel ?? 1,
    second: det.secondLevel ?? 1,
    costRatio: 0,
    rerolls,
    firstEffect: det.firstEffect ?? '',
    secondEffect: det.secondEffect ?? '',
  });

  // --- Offers (_detected_to_options, lines 522-550) ---
  const firstEffect = state.firstEffect;
  const secondEffect = state.secondEffect;

  const offers: Option[] = det.options.map((opt) => {
    const [kind, deltaVal] = determineOptionKind(
      opt.nameKey,
      opt.deltaKey,
      firstEffect,
      secondEffect,
    );
    const [kindHint] = parseDelta(opt.deltaKey);

    // Build the option key (mirrors _detected_to_options key construction)
    let key: string;
    if (
      (kind === 'will' || kind === 'chaos' || kind === 'first' || kind === 'second') &&
      deltaVal !== null
    ) {
      // e.g. "will+2", "first+3"
      key = `${kind}${deltaVal >= 0 ? '+' : ''}${deltaVal}`;
    } else if (kindHint === 'cost') {
      key = opt.deltaKey ?? 'cost+100';
    } else if (kindHint === 'reroll') {
      key = opt.deltaKey ?? 'reroll+1';
    } else if (kindHint === 'effect_changed') {
      const slot = opt.nameKey === firstEffect ? 'first' : 'second';
      key = `change_${slot}_effect`;
    } else if (kindHint === 'maintained') {
      key = 'maintain';
    } else {
      key = opt.nameKey ?? 'other';
    }

    // Build the delta value
    let delta: number;
    if (kind === 'view') {
      delta = parseViewDelta(opt.deltaKey);
    } else {
      delta = deltaVal ?? 0;
    }

    return makeOption(key, 1.0, kind, delta);
  });

  return {
    gem,
    state,
    offers,
    turn,
    turnsLeft,
    turnsTotal,
    rerolls,
    resetAvailable: opts.resetAvailable ?? false,
  };
}
