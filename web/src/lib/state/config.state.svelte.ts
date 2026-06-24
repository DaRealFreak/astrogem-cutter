import { persistedState } from 'svelte-persisted-state';
import { DEFAULT_CONFIG, type AdvisorStoredConfig } from './config';

// Persisted to localStorage; structuredClone so the default object isn't shared/mutated.
export const config = persistedState<AdvisorStoredConfig>('astrogem-advisor-config', structuredClone(DEFAULT_CONFIG));
