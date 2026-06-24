import type { DetectionResult } from './types';

export type CaptureWorkerRequest =
  | { type: 'init' }
  | { type: 'frame'; frame: VideoFrame; drawOverlays: boolean }
  | { type: 'image'; bitmap: ImageBitmap; drawOverlays: boolean };

export type CaptureWorkerResponse =
  | { type: 'init:done' }
  | { type: 'init:error'; error?: string }
  | { type: 'frame:done'; result: DetectionResult | null }
  | { type: 'image:done'; result: DetectionResult | null }
  | { type: 'debug'; image?: ImageBitmap; result?: DetectionResult; message?: string };
