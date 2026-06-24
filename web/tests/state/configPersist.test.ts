/**
 * Browser test: verifies that `config` (persistedState) writes to localStorage.
 * Must run in the browser project so localStorage is a real object.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';

const LS_KEY = 'astrogem-advisor-config';

beforeEach(() => {
  localStorage.removeItem(LS_KEY);
});
afterEach(() => {
  localStorage.removeItem(LS_KEY);
});

describe('config persistence', () => {
  it('writes to localStorage when current is mutated', async () => {
    // Import fresh so the module initialises against a clean localStorage
    const { config } = await import('../../src/lib/state/config.state.svelte');

    config.current = { ...config.current, minWill: 3 };

    // Allow the reactive effect to flush
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

    const stored = localStorage.getItem(LS_KEY);
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored!).minWill).toBe(3);
  });
});
