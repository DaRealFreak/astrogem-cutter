import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
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

  describe('error-path resource hygiene', () => {
    const origGetContext = OffscreenCanvas.prototype.getContext;
    const origCreateImageBitmap = globalThis.createImageBitmap;

    afterEach(() => {
      OffscreenCanvas.prototype.getContext = origGetContext;
      globalThis.createImageBitmap = origCreateImageBitmap;
    });

    it('closes the ImageBitmap when the 2D context is unavailable', async () => {
      const bytes = await (await fetch(anchorUrl)).arrayBuffer();

      // Capture the ImageBitmap decodeGray creates and spy on its .close().
      let closeSpy: ReturnType<typeof vi.fn> | undefined;
      globalThis.createImageBitmap = (async (...args: Parameters<typeof origCreateImageBitmap>) => {
        const bmp = await origCreateImageBitmap(...args);
        closeSpy = vi.fn(bmp.close.bind(bmp));
        bmp.close = closeSpy as typeof bmp.close;
        return bmp;
      }) as typeof globalThis.createImageBitmap;

      // Force the null-context branch.
      OffscreenCanvas.prototype.getContext = (() => null) as typeof origGetContext;

      await expect(decodeGray(bytes)).rejects.toThrow('OffscreenCanvas 2D context unavailable');
      expect(closeSpy).toHaveBeenCalledTimes(1);
    });
  });
});
