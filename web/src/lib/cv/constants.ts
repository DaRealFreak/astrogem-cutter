/**
 * Vision constants: ROI offsets, thresholds, and name mappings.
 * Ported from arkgrid/vision/constants.py
 */

// Type alias for ROI: (x, y, width, height) in pixels
export type Roi = readonly [number, number, number, number];

// ---------------------------------------------------------------------------
// Match thresholds (0-1, higher = stricter)
// ---------------------------------------------------------------------------
export const THRESHOLD_ANCHOR = 0.70;
export const THRESHOLD_GEM_INFO = 0.65;
export const THRESHOLD_OPTION_NAME = 0.65;
export const THRESHOLD_OPTION_DELTA = 0.65;
export const THRESHOLD_STAT_LEVEL = 0.65;
export const THRESHOLD_DIGIT = 0.65;

// ---------------------------------------------------------------------------
// Reference resolution. All ROI offsets below are measured at this size.
// When the capture is a different resolution the recognizer scales to FHD
// before matching.
// ---------------------------------------------------------------------------
export const REF_WIDTH = 1920;
export const REF_HEIGHT = 1080;

// ---------------------------------------------------------------------------
// Anchor region – "Processing" header text.
// We search the upper-center of the screen first.
// ---------------------------------------------------------------------------
export const ANCHOR_SEARCH_ROI: Roi = [650, 20, 700, 80]; // generous search area
export const ANCHOR_SIZE: readonly [number, number] = [170, 22]; // expected template size

// ---------------------------------------------------------------------------
// All ROI offsets below are relative to the **top-left** corner of the
// detected anchor bounding-box (approx 895, 43 at FHD).
// Format: (dx, dy, width, height)
// ---------------------------------------------------------------------------

// Gem type icon (chaos/order gem subtype)
export const ROI_GEM_TYPE: Roi = [55, 68, 19, 23];

// Current astrogem points text (e.g. "4 Astrogem Points")
export const ROI_POINTS: Roi = [-11, 168, 140, 20];

// Diamond stat display – individual stat positions
// Willpower level (single digit, top of diamond)
export const ROI_STAT_WILLPOWER: Roi = [56, 309, 16, 16];
// First side node (left of diamond – effect name + Lv)
export const ROI_STAT_FIRST: Roi = [-72, 332, 102, 57];
// Second side node (right of diamond – effect name + Lv)
export const ROI_STAT_SECOND: Roi = [96, 332, 102, 57];
// Chaos/order points level (single digit, bottom of diamond)
export const ROI_STAT_CHAOS: Roi = [56, 427, 16, 16];

// ---------------------------------------------------------------------------
// Option cards – 4 cards arranged horizontally, 117px each, adjacent
// Centers: (781,598), (898,598), (1015,598), (1132,598)
// ---------------------------------------------------------------------------
export const OPTION_CARD_Y_OFFSET = 520; // dy from anchor top (598 - 35 - 43)
export const OPTION_CARD_HEIGHT = 70;

// (dx, width) for each card
export const OPTION_CARD_POSITIONS: ReadonlyArray<readonly [number, number]> = [
  [-172, 117], // Card 1: abs 723..840
  [-55, 117],  // Card 2: abs 840..957
  [62, 117],   // Card 3: abs 957..1074
  [179, 117],  // Card 4: abs 1074..1191
];

// ---------------------------------------------------------------------------
// Bottom info area
// ---------------------------------------------------------------------------
// Reroll count indicator
export const ROI_REROLL: Roi = [340, 542, 56, 20];

// Process button – contains "Process (X/Y)" text; only the step digit
export const ROI_PROCESS_STEPS: Roi = [195, 714, 28, 18];

// ---------------------------------------------------------------------------
// Option name → internal key mapping
// Maps the display text (as recognized) to our domain option types.
// ---------------------------------------------------------------------------
export const OPTION_NAME_MAP: Readonly<Record<string, string>> = {
  'atk. power': 'attack_power',
  'atk power': 'attack_power',
  'attack power': 'attack_power',
  'additional damage': 'additional_damage',
  'boss damage': 'boss_damage',
  'brand power': 'brand_power',
  'ally damage enh.': 'ally_damage',
  'ally damage': 'ally_damage',
  'ally attack enh.': 'ally_attack',
  'ally atk. enh.': 'ally_attack',
  'ally attack': 'ally_attack',
  'chaos points': 'chaos',
  'willpower': 'will',
  'willpower efficiency': 'will',
  'processing cost': 'cost',
  'view other items': 'view',
  'view other options': 'view',
  'processing modifier': 'other',
  'maintain': 'other',
};

// Delta text → (option_type, delta_value) mapping
export const DELTA_TEXT_MAP: Readonly<Record<string, string | readonly [string, number]>> = {
  'lv': 'level_change', // followed by a number showing target level
  '+100%': ['cost', 100],
  '-100%': ['cost', -100],
  '+100': ['cost', 100],
  '-100': ['cost', -100],
  'effect changed': 'effect_change',
  '+1 time': ['view', 1],
  '+2 times': ['view', 2],
  '+1 reroll': ['view', 1],
  '+2 rerolls': ['view', 2],
};

// Gem type display names → internal keys
export const GEM_TYPE_MAP: Readonly<Record<string, string>> = {
  'stability': 'stability',
  'fortitude': 'fortitude',
  'immutability': 'immutability',
  'corrosion': 'erosion',
  'erosion': 'erosion',
  'distortion': 'distortion',
  'collapse': 'collapse',
};

// Gem attribute display names → internal keys
export const GEM_ATTR_MAP: Readonly<Record<string, string>> = {
  'chaos': 'chaos',
  'order': 'order',
};

// ---------------------------------------------------------------------------
// Template key → domain key mappings
// ---------------------------------------------------------------------------
// Gem type template filenames → domain gem type keys (from arkgrid.constants)
export const GEM_TYPE_TEMPLATE_TO_DOMAIN: Readonly<Record<string, string>> = {
  'chaos_corrosion': 'chaos_erosion',
  'chaos_destruction': 'chaos_collapse',
  'chaos_distortion': 'chaos_distortion',
  'order_immutability': 'order_immutability',
  'order_solidity': 'order_fortitude',
  'order_stability': 'order_stability',
};

// Rarity template key → total steps
export const RARITY_TOTAL_STEPS: Readonly<Record<string, number>> = {
  'common': 5,
  'rare': 7,
  'epic': 9,
};

// Total steps → rarity
export const RARITY_FROM_TOTAL_STEPS: Readonly<Record<number, string>> = {
  5: 'common',
  7: 'rare',
  9: 'epic',
};
