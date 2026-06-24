import { describe, it, expect } from 'vitest';
import { upsertPreset, renamePreset, removePreset, SEED_PRESETS, type PresetMap } from '../../src/lib/state/presetOps';
import { DEFAULT_CONFIG } from '../../src/lib/state/config';

const cfg = (over = {}) => ({ ...structuredClone(DEFAULT_CONFIG), ...over });
const base = (): PresetMap => ({ A: cfg({ minWillChaosTotal: 8 }), B: cfg({ minWillChaosTotal: 9 }) });

describe('upsertPreset', () => {
  it('adds a new preset without mutating the input', () => {
    const m = base();
    const out = upsertPreset(m, 'C', cfg());
    expect(Object.keys(out)).toEqual(['A', 'B', 'C']);
    expect(Object.keys(m)).toEqual(['A', 'B']); // original untouched
  });
  it('overwrites an existing preset in place', () => {
    const out = upsertPreset(base(), 'A', cfg({ minWillChaosTotal: 3 }));
    expect(out.A.minWillChaosTotal).toBe(3);
    expect(Object.keys(out)).toEqual(['A', 'B']);
  });
  it('trims the name and ignores blank names', () => {
    expect(Object.keys(upsertPreset(base(), '  C  ', cfg()))).toContain('C');
    expect(upsertPreset(base(), '   ', cfg())).toEqual(base());
  });
});

describe('renamePreset', () => {
  it('renames while preserving insertion order', () => {
    const out = renamePreset(base(), 'A', 'Z');
    expect(Object.keys(out)).toEqual(['Z', 'B']); // not ['B','Z']
    expect(out.Z.minWillChaosTotal).toBe(8);
  });
  it('is a no-op for blank / unchanged / taken / missing names', () => {
    const m = base();
    expect(renamePreset(m, 'A', '')).toBe(m);
    expect(renamePreset(m, 'A', 'A')).toBe(m);
    expect(renamePreset(m, 'A', 'B')).toBe(m);   // target already exists
    expect(renamePreset(m, 'X', 'Y')).toBe(m);   // source missing
  });
});

describe('removePreset', () => {
  it('removes a preset and returns a new map', () => {
    const m = base();
    const out = removePreset(m, 'A');
    expect(Object.keys(out)).toEqual(['B']);
    expect(Object.keys(m)).toEqual(['A', 'B']);
  });
  it('returns the same map when the name is absent', () => {
    const m = base();
    expect(removePreset(m, 'X')).toBe(m);
  });
});

describe('SEED_PRESETS', () => {
  it('maps the endgame command to the web-modeled fields', () => {
    const p = SEED_PRESETS['Endgame DPS'];
    expect(p.goalMode).toBe('combined');
    expect(p.minWillChaosTotal).toBe(8);          // --min-total-will-chaos 8
    expect(p.optimizeOverride).toBe('dps');        // --optimize dps
    expect(p.minSideCoeff).toBe(2000);             // --min-side-coeff 2000
    expect(p.relicRerollThreshold).toBeCloseTo(0.1); // --relic-reroll-threshold 0.1
    expect(p.resetTicketRarity).toBe('epic');      // --reset-ticket epic
    expect(p.resetMinCoeff).toBe(1000);            // --reset-min-coeff 1000
    expect(p.rerollMinCoeff).toBe(700);            // --reroll-min-coeff 700
  });
  it('maps the new-char command (ignore side-node values, lower reset bar)', () => {
    const p = SEED_PRESETS['New char DPS'];
    expect(p.minWillChaosTotal).toBe(8);
    expect(p.optimizeOverride).toBe('dps');
    expect(p.ignoreSideNodeValues).toBe(true);     // --ignore-side-node-values
    expect(p.relicRerollThreshold).toBeCloseTo(0.1);
    expect(p.resetMinCoeff).toBe(700);             // --reset-min-coeff 700
  });
});
