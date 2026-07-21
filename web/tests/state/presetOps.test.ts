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
    expect(p.rerollGoal).toBe(9);                  // --reroll-goal 9
    expect(p.rerollGoalThreshold).toBeCloseTo(0.15); // --reroll-goal-threshold 0.15
  });
  it('maps the new-char command (ignore side-node values, lower reset bar)', () => {
    const p = SEED_PRESETS['New char DPS'];
    expect(p.minWillChaosTotal).toBe(8);
    expect(p.optimizeOverride).toBe('dps');
    expect(p.ignoreSideNodeValues).toBe(true);     // --ignore-side-node-values
    expect(p.relicRerollThreshold).toBeCloseTo(0.1);
    expect(p.resetMinCoeff).toBe(700);             // --reset-min-coeff 700
  });
  it('support presets mirror the DPS ones with coeff bars scaled ×1.5', () => {
    // Lowest side-node coeff at level 5: DPS attack_power 400×5=2000,
    // support ally_damage 600×5=3000 → every coefficient bar scales ×1.5.
    const eg = SEED_PRESETS['Endgame Support'];
    expect(eg.optimizeOverride).toBe('support');
    expect(eg.minWillChaosTotal).toBe(8);
    expect(eg.minSideCoeff).toBe(3000);            // 2000 × 1.5
    expect(eg.resetMinCoeff).toBe(1500);           // 1000 × 1.5
    expect(eg.rerollMinCoeff).toBe(1050);          // 700 × 1.5
    expect(eg.relicRerollThreshold).toBeCloseTo(0.1);
    expect(eg.rerollGoal).toBe(9);
    expect(eg.rerollGoalThreshold).toBeCloseTo(0.15);
    expect(eg.resetTicketRarity).toBe('epic');

    const nc = SEED_PRESETS['New char Support'];
    expect(nc.optimizeOverride).toBe('support');
    expect(nc.ignoreSideNodeValues).toBe(true);
    expect(nc.resetMinCoeff).toBe(1050);           // 700 × 1.5
    expect(nc.relicRerollThreshold).toBeCloseTo(0.1);
    expect(nc.resetTicketRarity).toBe('epic');
  });
});
