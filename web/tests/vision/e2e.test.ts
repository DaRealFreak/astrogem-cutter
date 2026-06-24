import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { loadGrayMat } from '../helpers/loadImage';
import { loadTemplateStore } from '../helpers/loadTemplates';
import { TemplateStore } from '../../src/lib/cv/templates';
import { detect } from '../../src/lib/cv/recognizer';
import { detectionToEngineInputs } from '../../src/lib/cv/adapter';
import { buildEngineContext, advise } from '../../src/lib/engine';
import detection from '../fixtures/detection.json';

const EXAMPLE_URLS = import.meta.glob('../../../examples/*.jpg',
  { eager: true, query: '?url', import: 'default' }) as Record<string, string>;
const urlByName: Record<string, string> = {};
for (const [p, u] of Object.entries(EXAMPLE_URLS)) urlByName[p.split('/').pop()!] = u;

describe('e2e: screenshot -> detect -> adapt -> advise', () => {
  let store: TemplateStore;
  beforeAll(async () => { await initOpenCv(); store = await loadTemplateStore(); }, 120_000);

  it('produces a coherent recommendation for detected cutting frames', async () => {
    // pick a few records the Python detected as a full cutting screen
    const cutting = (detection as any).records.filter((r: any) => r.expected.found
      && r.expected.gem_type && r.expected.total_steps && r.expected.current_step
      && r.expected.first_effect && r.expected.second_effect).slice(0, 5);
    expect(cutting.length).toBeGreaterThan(0);

    for (const r of cutting) {
      const gray = await loadGrayMat(urlByName[r.file]!);
      const det = detect(gray, store); gray.delete();
      const inputs = detectionToEngineInputs(det, { optimize: 'dps' });
      const rarity = ({ 5: 'common', 7: 'rare', 9: 'epic' } as const)[inputs.turnsTotal as 5 | 7 | 9];
      const ctx = buildEngineContext(inputs.gem, { rarity: rarity!, minWill: 4, minChaos: 5 });
      const out = advise(ctx, { state: inputs.state, offers: inputs.offers,
        turn: inputs.turn, turnsLeft: inputs.turnsLeft, rerolls: inputs.rerolls,
        resetAvailable: inputs.resetAvailable });
      expect(['process', 'reroll', 'reset', 'finish', 'fail']).toContain(out.action);
      expect(out.pGoal).toBeGreaterThanOrEqual(0); expect(out.pGoal).toBeLessThanOrEqual(1);
      expect(out.pRelic).toBeGreaterThanOrEqual(out.pAncient);
      expect(out.perOffer).toHaveLength(4);
    }
  }, 60_000);
});
