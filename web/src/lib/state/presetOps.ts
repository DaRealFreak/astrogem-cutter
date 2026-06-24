import { DEFAULT_CONFIG, type AdvisorStoredConfig } from './config';

export type PresetMap = Record<string, AdvisorStoredConfig>;

/** Build a preset from the defaults plus overrides (keeps presets complete as fields grow). */
export function preset(over: Partial<AdvisorStoredConfig>): AdvisorStoredConfig {
  return { ...structuredClone(DEFAULT_CONFIG), ...over };
}

// Seeded starting presets — the two cutting profiles from the user's Python `auto`
// commands. Flags a read-only web advisor can't model are dropped: --confirm-min-coeff
// (no clicking → no prompt), --all (the web reads the real gem), and the exact
// --reroll-goal activation timing (the extra ticket is armed via the relic threshold).
export const SEED_PRESETS: PresetMap = {
  'Endgame DPS': preset({
    goalMode: 'combined', minWillChaosTotal: 8,
    optimizeOverride: 'dps',
    minSideCoeff: 2000,
    relicRerollThreshold: 0.1,
    resetTicketRarity: 'epic',
    resetMinCoeff: 1000,
    rerollMinCoeff: 700,
  }),
  'New char DPS': preset({
    goalMode: 'combined', minWillChaosTotal: 8,
    optimizeOverride: 'dps',
    ignoreSideNodeValues: true,
    relicRerollThreshold: 0.1,
    resetTicketRarity: 'epic',
    resetMinCoeff: 700,
  }),
};

/** Create or overwrite `name` (upsert). Returns a new map; empty names are ignored. */
export function upsertPreset(map: PresetMap, name: string, cfg: AdvisorStoredConfig): PresetMap {
  const trimmed = name.trim();
  if (!trimmed) return map;
  return { ...map, [trimmed]: cfg };
}

/**
 * Rename `oldName` → `newName`, preserving insertion order. No-op if the new
 * name is blank, unchanged, already taken, or the old name is missing.
 */
export function renamePreset(map: PresetMap, oldName: string, newName: string): PresetMap {
  const next = newName.trim();
  if (!next || next === oldName || !(oldName in map) || next in map) return map;
  const out: PresetMap = {};
  for (const [k, v] of Object.entries(map)) out[k === oldName ? next : k] = v;
  return out;
}

/** Remove `name`. Returns a new map (or the same map if `name` is absent). */
export function removePreset(map: PresetMap, name: string): PresetMap {
  if (!(name in map)) return map;
  const { [name]: _omit, ...rest } = map;
  return rest;
}
