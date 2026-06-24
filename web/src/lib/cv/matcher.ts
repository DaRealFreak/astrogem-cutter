/**
 * Template matching wrappers — port of arkgrid/vision/matcher.py.
 *
 * Uses TM_CCOEFF_NORMED + minMaxLoc (same method as the Python source).
 * All intermediate Mats are deleted to avoid WASM memory leaks.
 * Environment-agnostic: no node:fs, only opencv.js via getCv().
 */

import { getCv } from './cvRuntime';
import type { Roi } from './constants';

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface MatchResult {
  key: string;
  score: number;
  loc: { x: number; y: number };
}

// ---------------------------------------------------------------------------
// findTemplate
// ---------------------------------------------------------------------------

/**
 * Find `template` in `frame`, optionally restricted to `roi` (x, y, w, h).
 *
 * Returns `{ score, x, y }` where x/y are in full-frame coordinates (the ROI
 * offset is added back, mirroring Python's `find_template`).
 *
 * Returns score 0 if the template is larger than the (possibly clipped) target,
 * or if the clamped ROI is empty.
 */
export function findTemplate(
  frame: any,
  template: any,
  roi?: Roi,
): { score: number; x: number; y: number } {
  const cv = getCv();

  let ox = 0;
  let oy = 0;
  let target: any = frame;
  let roiMat: any = null;

  if (roi !== undefined) {
    // Clamp to frame bounds (mirrors Python: max(0,rx), min(rw, cols-rx), etc.)
    let [rx, ry, rw, rh] = roi;
    rx = Math.max(0, rx);
    ry = Math.max(0, ry);
    rw = Math.min(rw, frame.cols - rx);
    rh = Math.min(rh, frame.rows - ry);

    if (rw <= 0 || rh <= 0) {
      return { score: 0, x: 0, y: 0 };
    }

    roiMat = frame.roi(new cv.Rect(rx, ry, rw, rh));
    target = roiMat;
    ox = rx;
    oy = ry;
  }

  try {
    // Template must fit inside target
    if (template.rows > target.rows || template.cols > target.cols) {
      return { score: 0, x: 0, y: 0 };
    }

    const result = new cv.Mat();
    try {
      cv.matchTemplate(target, template, result, cv.TM_CCOEFF_NORMED);
      const { maxVal, maxLoc } = cv.minMaxLoc(result);
      return {
        score: maxVal,
        x: maxLoc.x + ox,
        y: maxLoc.y + oy,
      };
    } finally {
      result.delete();
    }
  } finally {
    if (roiMat !== null) {
      roiMat.delete();
    }
  }
}

// ---------------------------------------------------------------------------
// findBestMatch
// ---------------------------------------------------------------------------

/**
 * Try all templates in `templates`, return the highest-scoring one ≥ threshold.
 * Returns null if no template clears the threshold.
 *
 * Mirrors Python's `find_best_match`.
 */
export function findBestMatch(
  frame: any,
  templates: Map<string, any>,
  roi?: Roi,
  threshold = 0.8,
): MatchResult | null {
  let best: MatchResult | null = null;

  for (const [key, tmpl] of templates) {
    const { score, x, y } = findTemplate(frame, tmpl, roi);
    if (score >= threshold && (best === null || score > best.score)) {
      best = { key, score, loc: { x, y } };
    }
  }

  return best;
}
