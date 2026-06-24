/**
 * Vision recognizer result types and parse helpers.
 * Pure functions for interpreting template-matched keys into structured decisions.
 */

import { stripVariant, TemplateStore } from './templates';
import { getCv } from './cvRuntime';
import { findTemplate, findBestMatch } from './matcher';
import {
  type Roi,
  ANCHOR_SEARCH_ROI,
  THRESHOLD_ANCHOR,
  ROI_GEM_TYPE,
  ROI_STAT_WILLPOWER,
  ROI_STAT_CHAOS,
  ROI_REROLL,
  ROI_PROCESS_STEPS,
  ROI_STAT_FIRST,
  ROI_STAT_SECOND,
  RARITY_TOTAL_STEPS,
  OPTION_CARD_POSITIONS,
  OPTION_CARD_Y_OFFSET,
  OPTION_CARD_HEIGHT,
} from './constants';

/**
 * One of the 4 detected option cards.
 */
export interface OptionDetection {
  nameKey: string | null;
  nameScore: number;
  deltaKey: string | null;
  deltaScore: number;
}

/**
 * Full recognition output for one frame.
 */
export interface DetectionResult {
  found: boolean;
  gemType: string | null;
  gemTypeScore: number;
  willpower: number | null;
  willpowerScore: number;
  chaos: number | null;
  chaosScore: number;
  firstEffect: string | null;
  firstEffectScore: number;
  firstLevel: number | null;
  firstLevelScore: number;
  secondEffect: string | null;
  secondEffectScore: number;
  secondLevel: number | null;
  secondLevelScore: number;
  rerolls: string | null;
  rerollsScore: number;
  currentStep: number | null;
  stepScore: number;
  totalSteps: number | null;
  rarityScore: number;
  options: OptionDetection[];
}

/**
 * Convert reroll template key to integer count.
 *
 * If extraTicket is true, adds +1 unless the key indicates the ticket
 * is unavailable ('0_ticket_not_available').
 */
export function parseRerolls(rerollKey: string | null, extraTicket: boolean = false): number {
  if (rerollKey === null) {
    return 0;
  }
  if (rerollKey === '0_ticket_not_available') {
    return 0;
  }
  if (rerollKey === '0_ticket_available') {
    return extraTicket ? 1 : 0;
  }
  // Strip variant suffix for keys like "1_01" -> "1"
  const base = stripVariant(rerollKey);
  let count = 0;
  try {
    count = parseInt(base, 10);
  } catch {
    return 0;
  }
  if (isNaN(count)) {
    return 0;
  }
  if (extraTicket) {
    count += 1;
  }
  return count;
}

/**
 * Delta kind hint from parsing a delta key.
 */
export type DeltaKind = 'lvl' | 'points' | 'cost' | 'reroll' | 'effect_changed' | 'maintained' | null;

/**
 * Parse a delta template key into (kind_hint, delta_value).
 *
 * Returns:
 *   kind_hint: "lvl", "points", "cost", "reroll", "effect_changed",
 *              "maintained", or null
 *   delta_value: signed int (e.g. +3, -1) or null for non-stat deltas
 *
 * Examples:
 *   "1_line_lvl+3"       -> ("lvl", 3)
 *   "2_line_+2"          -> ("points", 2)
 *   "1_line_-1"          -> ("points", -1)
 *   "cost+100"           -> ("cost", null)
 *   "reroll+1"           -> ("reroll", null)
 *   "1_line_effect_changed" -> ("effect_changed", null)
 *   "maintained"         -> ("maintained", null)
 */
export function parseDelta(deltaKey: string | null): [DeltaKind, number | null] {
  if (!deltaKey) {
    return [null, null];
  }

  // Strip line prefix
  let d = deltaKey;
  for (const prefix of ['1_line_', '2_line_']) {
    if (d.startsWith(prefix)) {
      d = d.slice(prefix.length);
      break;
    }
  }

  if (d.startsWith('lvl')) {
    const m = d.match(/^lvl([+-]?\d+)/);
    if (m && m[1]) {
      return ['lvl', parseInt(m[1], 10)];
    }
    return ['lvl', null];
  } else if (d === 'effect_changed') {
    return ['effect_changed', null];
  } else if (d === 'maintained') {
    return ['maintained', null];
  } else if (d.startsWith('cost')) {
    return ['cost', null];
  } else if (d.startsWith('reroll')) {
    return ['reroll', null];
  } else {
    // "+3", "-1", etc.
    const m = d.match(/^([+-]?\d+)/);
    if (m && m[1]) {
      return ['points', parseInt(m[1], 10)];
    }
    return [null, null];
  }
}

/**
 * Map a detected option to (pool_kind, stat_delta).
 *
 * pool_kind is one of: "will", "chaos", "first", "second",
 * "cost", "view", "other".
 * stat_delta is the signed change to the relevant stat, or null
 * for options that don't change will/chaos/first/second.
 */
export function determineOptionKind(
  nameKey: string | null,
  deltaKey: string | null,
  firstEffect: string,
  secondEffect: string,
): ['will' | 'chaos' | 'first' | 'second' | 'cost' | 'view' | 'other', number | null] {
  const [kindHint, deltaVal] = parseDelta(deltaKey);

  if (nameKey === 'will') {
    return ['will', deltaVal];
  } else if (nameKey === 'chaos' || nameKey === 'order') {
    return ['chaos', deltaVal];
  } else if (nameKey === 'cost') {
    return ['cost', null];
  } else if (nameKey === 'view') {
    return ['view', null];
  } else if (nameKey === 'maintain') {
    return ['other', null];
  } else if (kindHint === 'effect_changed') {
    // Determine which effect is being changed
    if (nameKey === firstEffect) {
      return ['other', null]; // change_first_effect
    } else if (nameKey === secondEffect) {
      return ['other', null]; // change_second_effect
    }
    return ['other', null];
  } else if (kindHint === 'maintained') {
    return ['other', null];
  } else {
    // Side effect option (attack_power, additional_damage, etc.)
    if (nameKey === firstEffect) {
      return ['first', deltaVal];
    } else if (nameKey === secondEffect) {
      return ['second', deltaVal];
    }
    // Fallback: can't determine
    return ['other', deltaVal];
  }
}

/**
 * Extract level from a delta key like '2_line_lvl3' -> 3.
 */
export function sideNodeLevel(deltaKey: string | null): number | null {
  if (!deltaKey) {
    return null;
  }
  const m = deltaKey.match(/lvl(\d)/);
  return m && m[1] ? parseInt(m[1], 10) : null;
}

// ---------------------------------------------------------------------------
// Detection — port of arkgrid/vision/template_recognizer.detect
// ---------------------------------------------------------------------------

/**
 * Find the best matching template in `crop`. Returns `[key, score]`.
 *
 * Mirrors Python `_match`: iterates the set, skips templates larger than the
 * crop, keeps the highest `TM_CCOEFF_NORMED` score, optionally strips the
 * numeric variant suffix off the winning key.
 *
 * Reuses `findTemplate` (no ROI) for the per-template matchTemplate call.
 */
function _match(
  crop: any,
  templates: Map<string, any>,
  stripVariants = false,
): [string | null, number] {
  let bestKey: string | null = null;
  let bestScore = 0.0;

  for (const [key, tmpl] of templates) {
    // Skip templates that don't fit inside the crop (Python: tmpl.shape > crop.shape).
    if (tmpl.rows > crop.rows || tmpl.cols > crop.cols) {
      continue;
    }
    const { score } = findTemplate(crop, tmpl);
    if (score > bestScore) {
      bestScore = score;
      bestKey = key;
    }
  }

  if (stripVariants && bestKey) {
    bestKey = stripVariant(bestKey);
  }
  return [bestKey, bestScore];
}

/**
 * Crop an anchor-relative ROI. Returns a cv.Mat view (caller must delete it)
 * or null when the clamped region is empty.
 *
 * Mirrors Python `_crop_roi`: clamp the top-left to >=0, then clamp width/height
 * to the frame bounds (numpy slicing semantics).
 */
function _cropRoi(gray: any, ax: number, ay: number, roi: Roi): any | null {
  const cv = getCv();
  const [dx, dy, rw, rh] = roi;
  let x = ax + dx;
  let y = ay + dy;
  const fw = gray.cols;
  const fh = gray.rows;
  x = Math.max(0, x);
  y = Math.max(0, y);
  const w = Math.min(rw, fw - x);
  const h = Math.min(rh, fh - y);
  if (w <= 0 || h <= 0) {
    return null;
  }
  return gray.roi(new cv.Rect(x, y, w, h));
}

function blankResult(): DetectionResult {
  return {
    found: false,
    gemType: null,
    gemTypeScore: 0.0,
    willpower: null,
    willpowerScore: 0.0,
    chaos: null,
    chaosScore: 0.0,
    firstEffect: null,
    firstEffectScore: 0.0,
    firstLevel: null,
    firstLevelScore: 0.0,
    secondEffect: null,
    secondEffectScore: 0.0,
    secondLevel: null,
    secondLevelScore: 0.0,
    rerolls: null,
    rerollsScore: 0.0,
    currentStep: null,
    stepScore: 0.0,
    totalSteps: null,
    rarityScore: 0.0,
    options: [],
  };
}

const DIGIT_RE = /^\d+$/;

/**
 * Detect full game state from a FHD (1920x1080) grayscale cv.Mat.
 *
 * Port of `template_recognizer.detect`. The Python's resize + cvtColor are
 * intentionally skipped: the caller (`loadGrayMat`) already decoded and
 * grayscaled, and the examples are already FHD.
 *
 * Does not delete `gray` (the caller owns it). All intermediate crop Mats are
 * deleted before returning.
 */
export function detect(gray: any, store: TemplateStore): DetectionResult {
  const cv = getCv();
  const result = blankResult();

  // Find anchor.
  const match = findBestMatch(gray, store.get('anchor'), ANCHOR_SEARCH_ROI, THRESHOLD_ANCHOR);
  if (match === null) {
    return result;
  }

  result.found = true;
  const ax = match.loc.x;
  const ay = match.loc.y;

  // --- Gem type ---
  let crop = _cropRoi(gray, ax, ay, ROI_GEM_TYPE);
  if (crop !== null) {
    const [key, score] = _match(crop, store.get('gem_type'), true);
    result.gemType = key;
    result.gemTypeScore = score;
    crop.delete();
  }

  // --- Willpower ---
  crop = _cropRoi(gray, ax, ay, ROI_STAT_WILLPOWER);
  if (crop !== null) {
    const [key, score] = _match(crop, store.get('willpower'), true);
    if (key && DIGIT_RE.test(key)) {
      result.willpower = parseInt(key, 10);
    }
    result.willpowerScore = score;
    crop.delete();
  }

  // --- Chaos ---
  crop = _cropRoi(gray, ax, ay, ROI_STAT_CHAOS);
  if (crop !== null) {
    const [key, score] = _match(crop, store.get('chaos'), true);
    if (key && DIGIT_RE.test(key)) {
      result.chaos = parseInt(key, 10);
    }
    result.chaosScore = score;
    crop.delete();
  }

  // --- Rerolls ---
  crop = _cropRoi(gray, ax, ay, ROI_REROLL);
  if (crop !== null) {
    const [key, score] = _match(crop, store.get('rerolls'), true);
    result.rerolls = key;
    result.rerollsScore = score;
    crop.delete();
  }

  // --- Steps + Rarity (both from same crop) ---
  crop = _cropRoi(gray, ax, ay, ROI_PROCESS_STEPS);
  if (crop !== null) {
    // Current step
    const [stepKey, stepScore] = _match(crop, store.get('steps'), true);
    if (stepKey && DIGIT_RE.test(stepKey)) {
      result.currentStep = parseInt(stepKey, 10);
    }
    result.stepScore = stepScore;

    // Rarity (total steps from same crop)
    const [rarityKey, rarityScore] = _match(crop, store.get('rarity'), true);
    if (rarityKey && rarityKey in RARITY_TOTAL_STEPS) {
      result.totalSteps = RARITY_TOTAL_STEPS[rarityKey]!;
    }
    result.rarityScore = rarityScore;
    crop.delete();
  }

  // --- Side nodes ---
  const snNames = store.get('side_nodes/names');
  const snDeltas = store.get('side_nodes/deltas');

  const sideNodes: ReadonlyArray<readonly ['first' | 'second', Roi]> = [
    ['first', ROI_STAT_FIRST],
    ['second', ROI_STAT_SECOND],
  ];
  for (const [prefix, roi] of sideNodes) {
    crop = _cropRoi(gray, ax, ay, roi);
    if (crop === null) {
      continue;
    }
    const [nameKey, nameScore] = _match(crop, snNames, true);
    const [deltaKey, deltaScore] = _match(crop, snDeltas);
    const lvl = sideNodeLevel(deltaKey);
    crop.delete();

    if (prefix === 'first') {
      result.firstEffect = nameKey;
      result.firstEffectScore = nameScore;
      result.firstLevel = lvl;
      result.firstLevelScore = deltaScore;
    } else {
      result.secondEffect = nameKey;
      result.secondEffectScore = nameScore;
      result.secondLevel = lvl;
      result.secondLevelScore = deltaScore;
    }
  }

  // --- Option cards ---
  const optNames = store.get('options/names');
  const optDeltas = store.get('options/deltas');

  for (const [dx, cardW] of OPTION_CARD_POSITIONS) {
    const cardX = ax + dx;
    const cardY = ay + OPTION_CARD_Y_OFFSET;
    // Replicate Python numpy slicing gray[cardY:cardY+H, cardX:cardX+W] with
    // its silent clamping (so an out-of-bounds anchor doesn't throw).
    const x = Math.max(0, cardX);
    const y = Math.max(0, cardY);
    const w = Math.min(cardW, gray.cols - x);
    const h = Math.min(OPTION_CARD_HEIGHT, gray.rows - y);

    let nameKey: string | null = null;
    let nameScore = 0.0;
    let deltaKey: string | null = null;
    let deltaScore = 0.0;

    if (w > 0 && h > 0) {
      const cardCrop = gray.roi(new cv.Rect(x, y, w, h));
      [nameKey, nameScore] = _match(cardCrop, optNames, true);
      [deltaKey, deltaScore] = _match(cardCrop, optDeltas);
      cardCrop.delete();
    }

    result.options.push({
      nameKey,
      nameScore,
      deltaKey,
      deltaScore,
    });
  }

  return result;
}
