import { initOpenCv, getCv } from './cvRuntime';
import { decodeGray } from './decodeGray';
import { TemplateStore, groupBySet } from './templates';
import { detect } from './recognizer';
import { adjustResolution } from './adjustResolution';
import { drawDetectionOverlay } from '../app/overlay';
import type { CaptureWorkerRequest, CaptureWorkerResponse } from './workerTypes';

// vite enumerates the synced PNGs at build time (predev/prebuild runs sync-templates).
const TEMPLATE_URLS = import.meta.glob('./_templates/**/*.png', {
  eager: true, query: '?url', import: 'default',
}) as Record<string, string>;

let store: TemplateStore | null = null;
const canvas = new OffscreenCanvas(0, 0);
// Acquired during `init` (see acquireCtx). A null 2D context surfaces as a clean
// init:error rather than a silent stream of frame:done {result: null}.
let ctx: OffscreenCanvasRenderingContext2D | null = null;

function acquireCtx(): void {
  ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('OffscreenCanvas 2D context unavailable');
}

async function loadStore(): Promise<TemplateStore> {
  const entries: Array<[string, any]> = [];
  for (const [path, url] of Object.entries(TEMPLATE_URLS)) {
    const rel = path.split('/_templates/')[1]!.replace(/\.png$/, '');
    entries.push([rel, await decodeGray(await (await fetch(url)).arrayBuffer())]);
  }
  return new TemplateStore(groupBySet(entries));
}

function post(msg: CaptureWorkerResponse, transfer?: Transferable[]) {
  (self as unknown as Worker).postMessage(msg, transfer ?? []);
}

function processFrame(frame: VideoFrame): DetectionResultLike {
  if (!ctx) throw new Error('canvas not initialized');
  const cv = getCv();
  const { scale } = adjustResolution(frame.displayHeight);
  canvas.width = Math.round(frame.displayWidth * scale);
  canvas.height = Math.round(frame.displayHeight * scale);
  ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const rgba = cv.matFromImageData(data);
  const gray = new cv.Mat();
  try {
    cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
    return detect(gray, store!);
  } finally {
    rgba.delete();
    gray.delete();
  }
}
type DetectionResultLike = ReturnType<typeof detect>;

self.onmessage = async (e: MessageEvent<CaptureWorkerRequest>) => {
  const data = e.data;
  if (data.type === 'init') {
    try {
      await initOpenCv();
      acquireCtx();
      store = await loadStore();
      if (!store.has('anchor')) throw new Error('no templates loaded');
      post({ type: 'init:done' });
    } catch (err) {
      post({ type: 'init:error', error: err instanceof Error ? err.message : String(err) });
    }
    return;
  }
  if (data.type === 'frame') {
    let result: DetectionResultLike | null = null;
    try {
      if (store) result = processFrame(data.frame);
    } catch {
      result = null;
    } finally {
      data.frame.close();
    }
    // Always mirror the captured frame to the UI; the overlay annotations are
    // optional. processFrame left the frame drawn on the OffscreenCanvas at
    // FHD-normalised size (adjustResolution scales to REF_WIDTH x REF_HEIGHT),
    // so canvas pixels are 1:1 with the ROI coordinate space → scale = 1.
    if (result !== null && ctx !== null) {
      if (data.drawOverlays) drawDetectionOverlay(ctx, result, 1);
      const bmp = canvas.transferToImageBitmap();
      // Send the screen bitmap first, then release the backpressure lock.
      post({ type: 'debug', image: bmp, result }, [bmp]);
    }
    post({ type: 'frame:done', result });
  }
  if (data.type === 'image') {
    let result: DetectionResultLike | null = null;
    try {
      if (!ctx) throw new Error('canvas not initialized');
      const cv = getCv();
      const { scale } = adjustResolution(data.bitmap.height);
      canvas.width = Math.round(data.bitmap.width * scale);
      canvas.height = Math.round(data.bitmap.height * scale);
      ctx.drawImage(data.bitmap, 0, 0, canvas.width, canvas.height);
      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const rgba = cv.matFromImageData(imgData);
      const gray = new cv.Mat();
      try {
        cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
        if (store) result = detect(gray, store);
      } finally {
        rgba.delete();
        gray.delete();
      }
    } catch {
      result = null;
    } finally {
      data.bitmap.close();
    }
    // Mirror the uploaded image too (overlays optional), so it shows in the
    // screen view just like a live frame.
    if (result !== null && ctx !== null) {
      if (data.drawOverlays) drawDetectionOverlay(ctx, result, 1);
      const bmp = canvas.transferToImageBitmap();
      // Send the screen bitmap first, then the detection result.
      post({ type: 'debug', image: bmp, result }, [bmp]);
    }
    // Distinct from frame:done — image requests are one-shot (outside the frame
    // loop), so the controller routes this to onDetection unconditionally and
    // does not touch frame backpressure.
    post({ type: 'image:done', result });
  }
};
