/**
 * Debug overlay drawing — opencv-free, node-testable.
 * Draws ROI boxes and value/confidence labels onto a canvas context,
 * positioned relative to the detected anchor.
 */

import type { DetectionResult } from '../cv/types';
import {
  ROI_GEM_TYPE,
  ROI_POINTS,
  ROI_STAT_WILLPOWER,
  ROI_STAT_FIRST,
  ROI_STAT_SECOND,
  ROI_STAT_CHAOS,
  OPTION_CARD_POSITIONS,
  OPTION_CARD_Y_OFFSET,
  OPTION_CARD_HEIGHT,
} from '../cv/constants';

type Ctx2D = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

/** Draw a single ROI rectangle + label near it. */
function drawRoi(
  ctx: Ctx2D,
  ax: number,
  ay: number,
  dx: number,
  dy: number,
  w: number,
  h: number,
  scale: number,
  label: string,
): void {
  const x = (ax + dx) * scale;
  const y = (ay + dy) * scale;
  ctx.strokeRect(x, y, w * scale, h * scale);
  ctx.fillText(label, x + 2, y - 3);
}

/**
 * Draw detection ROI boxes and value/confidence labels onto a 2D canvas context.
 *
 * No-ops when `det.anchor` is null or undefined.
 * Pure function — no opencv dependency; safe to use in Node tests.
 *
 * @param ctx   The 2D rendering context to draw on.
 * @param det   The DetectionResult from detect().
 * @param scale Multiplier applied to all coordinates (use 1 for FHD canvases).
 */
export function drawDetectionOverlay(ctx: Ctx2D, det: DetectionResult, scale: number): void {
  if (!det.anchor) return;

  const { x: ax, y: ay } = det.anchor;

  // Style setup
  ctx.strokeStyle = '#00ff00';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#00ff00';
  ctx.font = '10px monospace';

  // Gem type
  {
    const [dx, dy, w, h] = ROI_GEM_TYPE;
    drawRoi(ctx, ax, ay, dx, dy, w, h, scale,
      `type:${det.gemType ?? '?'} (${det.gemTypeScore.toFixed(2)})`);
  }

  // Points
  {
    const [dx, dy, w, h] = ROI_POINTS;
    drawRoi(ctx, ax, ay, dx, dy, w, h, scale, 'points');
  }

  // Willpower
  {
    const [dx, dy, w, h] = ROI_STAT_WILLPOWER;
    drawRoi(ctx, ax, ay, dx, dy, w, h, scale,
      `will:${det.willpower ?? '?'} (${det.willpowerScore.toFixed(2)})`);
  }

  // Chaos
  {
    const [dx, dy, w, h] = ROI_STAT_CHAOS;
    drawRoi(ctx, ax, ay, dx, dy, w, h, scale,
      `chaos:${det.chaos ?? '?'} (${det.chaosScore.toFixed(2)})`);
  }

  // First side node
  {
    const [dx, dy, w, h] = ROI_STAT_FIRST;
    drawRoi(ctx, ax, ay, dx, dy, w, h, scale,
      `1st:${det.firstEffect ?? '?'} Lv${det.firstLevel ?? '?'} (${det.firstEffectScore.toFixed(2)})`);
  }

  // Second side node
  {
    const [dx, dy, w, h] = ROI_STAT_SECOND;
    drawRoi(ctx, ax, ay, dx, dy, w, h, scale,
      `2nd:${det.secondEffect ?? '?'} Lv${det.secondLevel ?? '?'} (${det.secondEffectScore.toFixed(2)})`);
  }

  // Option cards
  for (let i = 0; i < OPTION_CARD_POSITIONS.length; i++) {
    const [dx, cardW] = OPTION_CARD_POSITIONS[i]!;
    const opt = det.options[i];
    const label = opt
      ? `opt${i + 1}:${opt.nameKey ?? '?'} (${opt.nameScore.toFixed(2)})`
      : `opt${i + 1}`;
    drawRoi(ctx, ax, ay, dx, OPTION_CARD_Y_OFFSET, cardW, OPTION_CARD_HEIGHT, scale, label);
  }
}
