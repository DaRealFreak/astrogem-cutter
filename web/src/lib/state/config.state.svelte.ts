import { persistedState } from 'svelte-persisted-state';
import { DEFAULT_CONFIG, type AdvisorStoredConfig } from './config';

// Persisted to localStorage; structuredClone so the default object isn't shared/mutated.
export const config = persistedState<AdvisorStoredConfig>('astrogem-advisor-config', structuredClone(DEFAULT_CONFIG));

// Migration: fill any keys added since the user's config was last saved, so
// older persisted configs gain new fields (e.g. the coeff/rarity gates) at
// their defaults rather than reading back as undefined.
config.current = { ...structuredClone(DEFAULT_CONFIG), ...config.current };
