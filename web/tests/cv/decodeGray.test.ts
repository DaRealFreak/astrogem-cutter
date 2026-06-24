import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { decodeGray } from '../../src/lib/cv/decodeGray';
import anchorUrl from '../../../arkgrid/vision/templates/anchor/processing.png?url';

describe('decodeGray', () => {
  beforeAll(async () => { await initOpenCv(); });
  it('decodes a PNG to a non-empty single-channel Mat', async () => {
    const bytes = await (await fetch(anchorUrl)).arrayBuffer();
    const mat = await decodeGray(bytes);
    expect(mat.rows).toBeGreaterThan(0);
    expect(mat.cols).toBeGreaterThan(0);
    expect(mat.channels()).toBe(1);
    mat.delete();
  });
});
