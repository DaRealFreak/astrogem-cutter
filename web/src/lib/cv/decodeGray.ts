import { getCv } from './cvRuntime';

/**
 * Decode PNG bytes (or a Blob) into a single-channel grayscale cv.Mat.
 * Worker-safe: uses OffscreenCanvas + createImageBitmap (no `document`).
 * Caller owns the returned Mat and must .delete() it.
 */
export async function decodeGray(src: ArrayBuffer | Blob): Promise<any> {
  const cv = getCv();
  const blob = src instanceof Blob ? src : new Blob([src]);
  const bmp = await createImageBitmap(blob);
  const off = new OffscreenCanvas(bmp.width, bmp.height);
  const ctx = off.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('OffscreenCanvas 2D context unavailable');
  ctx.drawImage(bmp, 0, 0);
  const data = ctx.getImageData(0, 0, bmp.width, bmp.height);
  bmp.close();
  const rgba = cv.matFromImageData(data);
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  rgba.delete();
  return gray;
}
