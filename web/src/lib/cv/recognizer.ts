/**
 * Vision recognizer — detect() and its private opencv helpers.
 * Pure parse helpers and types have been moved to parse.ts / types.ts;
 * this file re-exports them so existing import sites keep working.
 */

// Re-export opencv-free types and helpers so existing consumers don't break.
export type { DetectionResult, OptionDetection } from './types';
export {
  parseRerolls,
  parseDelta,
  determineOptionKind,
  sideNodeLevel,
  type DeltaKind,
} from './parse';

import type { DetectionResult } from './types';
import { sideNodeLevel } from './parse';
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
  ROI_RESET_BUTTON,
  RESET_BRIGHT_LUMA,
  RESET_ENABLED_FRACTION,
  ROI_PROCESS_STEPS,
  ROI_STAT_FIRST,
  ROI_STAT_SECOND,
  RARITY_TOTAL_STEPS,
  OPTION_CARD_POSITIONS,
  OPTION_CARD_Y_OFFSET,
  OPTION_CARD_HEIGHT,
} from './constants';

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
    resetEnabled: null,
    resetScore: 0.0,
    currentStep: null,
    stepScore: 0.0,
    totalSteps: null,
    rarityScore: 0.0,
    options: [],
    anchor: null,
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
  result.anchor = { x: ax, y: ay };

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

  // --- Reset button (brightness, not template matching) ---
  // Mirrors Python `(crop > RESET_BRIGHT_LUMA).mean()`: THRESH_BINARY keeps
  // pixels strictly greater than the threshold, countNonZero / area = fraction.
  crop = _cropRoi(gray, ax, ay, ROI_RESET_BUTTON);
  if (crop !== null) {
    const dst = new cv.Mat();
    try {
      cv.threshold(crop, dst, RESET_BRIGHT_LUMA, 255, cv.THRESH_BINARY);
      const frac = cv.countNonZero(dst) / (crop.rows * crop.cols);
      result.resetScore = frac;
      result.resetEnabled = frac >= RESET_ENABLED_FRACTION;
    } finally {
      dst.delete();
      crop.delete();
    }
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
