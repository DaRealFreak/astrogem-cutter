import { initOpenCv, getCv } from './cvRuntime';
import { decodeGray } from './decodeGray';
import { TemplateStore, groupBySet } from './templates';
import { detect } from './recognizer';
import { adjustResolution } from './adjustResolution';
import type { CaptureWorkerRequest, CaptureWorkerResponse } from './workerTypes';

// vite enumerates the synced PNGs at build time (predev/prebuild runs sync-templates).
const TEMPLATE_URLS = import.meta.glob('./_templates/**/*.png', {
  eager: true, query: '?url', import: 'default',
}) as Record<string, string>;

let store: TemplateStore | null = null;
const canvas = new OffscreenCanvas(0, 0);
const ctx = canvas.getContext('2d', { willReadFrequently: true })!;

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
  const cv = getCv();
  const { scale } = adjustResolution(frame.displayHeight);
  canvas.width = Math.round(frame.displayWidth * scale);
  canvas.height = Math.round(frame.displayHeight * scale);
  ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const rgba = cv.matFromImageData(data);
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  rgba.delete();
  try {
    return detect(gray, store!);
  } finally {
    gray.delete();
  }
}
type DetectionResultLike = ReturnType<typeof detect>;

self.onmessage = async (e: MessageEvent<CaptureWorkerRequest>) => {
  const data = e.data;
  if (data.type === 'init') {
    try {
      await initOpenCv();
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
    post({ type: 'frame:done', result });
  }
};
