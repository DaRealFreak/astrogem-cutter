// env-agnostic: no node:fs, no import.meta.glob
// The browser glob loader lives in tests/helpers/loadTemplates.ts.

/**
 * Strip a trailing numeric variant suffix from a template stem.
 * e.g. 'additional_damage_01' -> 'additional_damage'
 *      'attack_power'         -> 'attack_power'
 */
export function stripVariant(key: string): string {
  return key.replace(/_\d+$/, '');
}

/**
 * Group flat [relPath-without-ext, mat] entries into nested Maps keyed by set name.
 *
 * Each relPath is split at the LAST '/' so that nested subdirs are preserved as the
 * set name:
 *   "willpower/1"            -> set "willpower",        stem "1"
 *   "side_nodes/names/foo"   -> set "side_nodes/names", stem "foo"
 *   "anchor/processing"      -> set "anchor",            stem "processing"
 */
export function groupBySet(entries: Array<[string, any]>): Map<string, Map<string, any>> {
  const result = new Map<string, Map<string, any>>();
  for (const [rel, mat] of entries) {
    const lastSlash = rel.lastIndexOf('/');
    if (lastSlash === -1) {
      // No slash: treat entire path as stem in a root "" set (shouldn't happen with template layout)
      const setMap = result.get('') ?? new Map<string, any>();
      setMap.set(rel, mat);
      result.set('', setMap);
    } else {
      const setName = rel.slice(0, lastSlash);
      const stem = rel.slice(lastSlash + 1);
      const setMap = result.get(setName) ?? new Map<string, any>();
      setMap.set(stem, mat);
      result.set(setName, setMap);
    }
  }
  return result;
}

/**
 * Holds pre-decoded grayscale template Mats grouped by set name.
 * Env-agnostic: construction takes a pre-built Map (decoded by the caller).
 */
export class TemplateStore {
  private readonly sets: Map<string, Map<string, any>>;

  constructor(sets: Map<string, Map<string, any>>) {
    this.sets = sets;
  }

  /**
   * Return the named set. Throws if the set was not loaded.
   */
  get(setName: string): Map<string, any> {
    const s = this.sets.get(setName);
    if (s === undefined) {
      throw new Error(`TemplateStore: set "${setName}" not found. Available: ${[...this.sets.keys()].join(', ')}`);
    }
    return s;
  }

  has(setName: string): boolean {
    return this.sets.has(setName);
  }

  setNames(): string[] {
    return [...this.sets.keys()];
  }
}
