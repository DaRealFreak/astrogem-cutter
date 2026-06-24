import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { loadGrayMat } from '../helpers/loadImage';
import { findBestMatch, findTemplate } from '../../src/lib/cv/matcher';
import exampleUrl from '../../../examples/20260401130608_1.jpg?url';
import anchorUrl from '../../../arkgrid/vision/templates/anchor/processing.png?url';

describe('matcher', () => {
  beforeAll(async () => { await initOpenCv(); }, 60_000);

  it('finds the anchor in its example via findTemplate', async () => {
    const frame = await loadGrayMat(exampleUrl);
    const anchor = await loadGrayMat(anchorUrl);
    const r = findTemplate(frame, anchor, [650, 20, 700, 80]);
    expect(r.score).toBeGreaterThan(0.7);
    [frame, anchor].forEach((m) => m.delete());
  });

  it('findBestMatch returns null where the template is absent', async () => {
    const frame = await loadGrayMat(exampleUrl);
    const anchor = await loadGrayMat(anchorUrl);
    // search a bottom-screen ROI where the "Processing" anchor text is not present
    const res = findBestMatch(frame, new Map([['anchor', anchor]]), [100, 900, 400, 120], 0.70);
    expect(res).toBeNull();
    [frame, anchor].forEach((m) => m.delete());
  });
});
