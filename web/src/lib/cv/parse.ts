/**
 * Pure opencv-free parse helpers for interpreting template-matched keys.
 * No opencv dependency — safe to import in the Node test project.
 */

import { stripVariant } from './templates';

// Re-export for a single opencv-free import source.
export { stripVariant } from './templates';
export type { DetectionResult, OptionDetection } from './types';

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
