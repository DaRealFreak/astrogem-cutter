import { persistedState } from 'svelte-persisted-state';
import { type AdvisorStoredConfig } from './config';
import { upsertPreset, renamePreset, removePreset, SEED_PRESETS, type PresetMap } from './presetOps';

export type { PresetMap };

const store = persistedState<PresetMap>('astrogem-advisor-presets', structuredClone(SEED_PRESETS));

/** Deep, plain-object copy (config is JSON-serialisable) — severs reactive references. */
function clone(c: AdvisorStoredConfig): AdvisorStoredConfig {
  return JSON.parse(JSON.stringify(c));
}

class Presets {
  /** Reactive map of name → config. */
  get map(): PresetMap { return store.current; }
  names(): string[] { return Object.keys(store.current); }
  get(name: string): AdvisorStoredConfig | undefined { return store.current[name]; }

  /** Create or overwrite a preset (upsert). */
  save(name: string, cfg: AdvisorStoredConfig): void {
    store.current = upsertPreset(store.current, name, clone(cfg));
  }

  rename(oldName: string, newName: string): void {
    store.current = renamePreset(store.current, oldName, newName);
  }

  remove(name: string): void {
    store.current = removePreset(store.current, name);
  }
}

export const presets = new Presets();
