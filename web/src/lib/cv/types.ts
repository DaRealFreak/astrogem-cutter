/**
 * Pure detection result types — no opencv dependency.
 * Extracted from recognizer.ts so downstream modules can import types
 * without transitively loading the OpenCV WASM bundle.
 */

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
