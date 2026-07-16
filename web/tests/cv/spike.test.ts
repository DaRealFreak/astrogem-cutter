import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv, getCv } from '../../src/lib/cv/cvRuntime';
import { loadGrayMat } from '../helpers/loadImage';
// vite asset URLs (served from repo root via server.fs.allow):
import exampleUrl from '../../../examples/20260716010621_1.jpg?url';
import anchorUrl from '../../../arkgrid/vision/templates/anchor/processing.png?url';

describe('opencv.js browser spike', () => {
  beforeAll(async () => { await initOpenCv(); }, 60_000);

  it('initializes and exposes matchTemplate + minMaxLoc', () => {
    const cv = getCv();
    expect(typeof cv.matchTemplate).toBe('function');
    expect(typeof cv.minMaxLoc).toBe('function');
  });

  it('decodes an example to a 1920x1080 gray Mat', async () => {
    const m = await loadGrayMat(exampleUrl);
    expect(m.cols).toBe(1920);
    expect(m.rows).toBe(1080);
    m.delete();
  });

  it('matches the anchor template inside its example with a high score', async () => {
    const cv = getCv();
    const gray = await loadGrayMat(exampleUrl);
    const tmpl = await loadGrayMat(anchorUrl);
    const res = new cv.Mat();
    cv.matchTemplate(gray, tmpl, res, cv.TM_CCOEFF_NORMED);
    const mm = cv.minMaxLoc(res);
    expect(mm.maxVal).toBeGreaterThan(0.7);
    [gray, tmpl, res].forEach((m) => m.delete());
  });
});
