import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { loadGrayMat } from '../helpers/loadImage';
import { loadTemplateStore } from '../helpers/loadTemplates';
import { TemplateStore } from '../../src/lib/cv/templates';
import { detect } from '../../src/lib/cv/recognizer';
import detection from '../fixtures/detection.json';

// map example basename -> served URL
const EXAMPLE_URLS = import.meta.glob('../../../examples/*.jpg',
  { eager: true, query: '?url', import: 'default' }) as Record<string, string>;
const urlByName: Record<string, string> = {};
for (const [p, u] of Object.entries(EXAMPLE_URLS)) urlByName[p.split('/').pop()!] = u;

describe('detect() golden parity', () => {
  let store: TemplateStore;
  beforeAll(async () => { await initOpenCv(); store = await loadTemplateStore(); }, 120_000);

  it('reproduces the Python detected values/keys for every example', async () => {
    const mismatches: string[] = [];
    for (const r of (detection as any).records) {
      const e = r.expected;
      const gray = await loadGrayMat(urlByName[r.file]!);
      const d = detect(gray, store);
      gray.delete();
      const got = {
        found: d.found, gem_type: d.gemType, willpower: d.willpower, chaos: d.chaos,
        first_effect: d.firstEffect, first_level: d.firstLevel,
        second_effect: d.secondEffect, second_level: d.secondLevel,
        rerolls: d.rerolls, current_step: d.currentStep, total_steps: d.totalSteps,
        options: d.options.map((o) => ({ name_key: o.nameKey, delta_key: o.deltaKey })),
      };
      const want = {
        found: e.found, gem_type: e.gem_type, willpower: e.willpower, chaos: e.chaos,
        first_effect: e.first_effect, first_level: e.first_level,
        second_effect: e.second_effect, second_level: e.second_level,
        rerolls: e.rerolls, current_step: e.current_step, total_steps: e.total_steps,
        options: e.options.map((o: any) => ({ name_key: o.name_key, delta_key: o.delta_key })),
      };
      if (JSON.stringify(got) !== JSON.stringify(want)) {
        mismatches.push(`${r.file}\n  got : ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
      }
    }
    if (mismatches.length) throw new Error(`${mismatches.length}/${(detection as any).records.length} mismatched:\n` + mismatches.join('\n'));
  });
});
