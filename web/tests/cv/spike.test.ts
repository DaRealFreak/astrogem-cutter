import { describe, it, expect, beforeAll } from 'vitest';
import { resolve } from 'node:path';
import { initOpenCv, getCv } from '../../src/lib/cv/cvRuntime';
import { decodeToBgrMat } from '../helpers/decodeImage';

const REPO = resolve(__dirname, '../../..');           // web/tests/cv -> repo root
const EXAMPLE = resolve(REPO, 'examples');
const TEMPLATES = resolve(REPO, 'arkgrid/vision/templates');

describe('opencv.js spike', () => {
  beforeAll(async () => { await initOpenCv(); }, 60_000);

  it('initializes and exposes matchTemplate + minMaxLoc', () => {
    const cv = getCv();
    expect(typeof cv.matchTemplate).toBe('function');
    expect(typeof cv.minMaxLoc).toBe('function');
  });

  it('decodes an example to a 1920x1080 BGR Mat', () => {
    const m = decodeToBgrMat(resolve(EXAMPLE, '20260401130608_1.jpg'));
    expect(m.cols).toBe(1920);
    expect(m.rows).toBe(1080);
    m.delete();
  });

  it('matches the anchor template inside its example with a high score', () => {
    const cv = getCv();
    const frame = decodeToBgrMat(resolve(EXAMPLE, '20260401130608_1.jpg'));
    const gray = new cv.Mat();
    cv.cvtColor(frame, gray, cv.COLOR_BGR2GRAY);
    const tmplBgr = decodeToBgrMat(resolve(TEMPLATES, 'anchor/processing.png'));
    const tmpl = new cv.Mat();
    cv.cvtColor(tmplBgr, tmpl, cv.COLOR_BGR2GRAY);
    const res = new cv.Mat();
    cv.matchTemplate(gray, tmpl, res, cv.TM_CCOEFF_NORMED);
    const mm = cv.minMaxLoc(res);
    expect(mm.maxVal).toBeGreaterThan(0.7);
    [frame, gray, tmplBgr, tmpl, res].forEach((m) => m.delete());
  });
});
