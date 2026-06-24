import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { stripVariant, TemplateStore } from '../../src/lib/cv/templates';
import { loadTemplateStore } from '../helpers/loadTemplates';

describe('TemplateStore', () => {
  let store: TemplateStore;
  beforeAll(async () => { await initOpenCv(); store = await loadTemplateStore(); }, 120_000);

  it('strips numeric variant suffixes', () => {
    expect(stripVariant('additional_damage_01')).toBe('additional_damage');
    expect(stripVariant('attack_power')).toBe('attack_power');
  });

  it('loads grayscale templates for the willpower set (keys 1..5)', () => {
    const wp = store.get('willpower');
    expect(wp.size).toBe(5);
    expect([...wp.keys()].sort()).toEqual(['1', '2', '3', '4', '5']);
    expect(wp.get('1')!.channels()).toBe(1);   // grayscale
  });

  it('exposes every set detect() needs, each non-empty', () => {
    for (const name of ['anchor', 'gem_type', 'willpower', 'chaos', 'rerolls', 'steps',
                        'rarity', 'side_nodes/names', 'side_nodes/deltas',
                        'options/names', 'options/deltas']) {
      expect(store.has(name)).toBe(true);
      expect(store.get(name).size).toBeGreaterThan(0);
    }
  });
});
