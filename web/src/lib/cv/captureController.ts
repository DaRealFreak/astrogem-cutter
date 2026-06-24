import type { CaptureWorkerRequest, CaptureWorkerResponse } from './workerTypes';
import type { DetectionResult } from './types';
export type { StartCaptureErrorType } from './captureErrors';
export { isStartCaptureError, classifyCaptureError } from './captureErrors';

import { isStartCaptureError, classifyCaptureError } from './captureErrors';
import type { StartCaptureErrorType } from './captureErrors';

export class CaptureController {
  private state: 'idle' | 'loading' | 'recording' | 'closing' = 'idle';

  // screen capture
  private reader: ReadableStreamDefaultReader<VideoFrame> | null = null;
  private track: MediaStreamVideoTrack | null = null;

  // web worker
  private worker: Worker | null = null;
  // Stored init promise so analyzeImage can await it if init is already in flight
  private _workerInitPromise: Promise<void> | null = null;

  // debug
  private drawDebug: boolean = false;
  private _debugCanvas: HTMLCanvasElement | null = null;

  // pending promise resolvers
  private awaitWorkerInitialization: {
    resolve: () => void;
    reject: (reason: StartCaptureErrorType) => void;
  } | null = null;
  private awaitFrameCompletion: (() => void) | null = null;

  // external callbacks
  // `source` lets the consumer treat live frames (debounced) and one-shot
  // uploaded stills (committed immediately) differently.
  onDetection: ((result: DetectionResult | null, source: 'frame' | 'image') => void) | null = null;
  onStatus: ((s: 'idle' | 'loading' | 'recording') => void) | null = null;
  onError: ((e: StartCaptureErrorType) => void) | null = null;
  onDebug: ((image: ImageBitmap | null, result: DetectionResult | null) => void) | null = null;

  constructor(debugCanvas?: HTMLCanvasElement | null) {
    if (debugCanvas) this._debugCanvas = debugCanvas;
  }

  /** Allow the debug canvas to be bound after construction (Task 11). */
  set debugCanvas(canvas: HTMLCanvasElement | null) {
    this._debugCanvas = canvas;
  }

  // type-safe wrapper
  private postMessage(msg: CaptureWorkerRequest) {
    if (!this.worker) throw Error('worker is not set');
    this.worker.postMessage(msg);
  }

  private setState(next: 'idle' | 'loading' | 'recording' | 'closing') {
    this.state = next;
    // notify on the public subset
    if (next !== 'closing') {
      const onStatus = this.onStatus;
      if (onStatus) {
        queueMicrotask(() => onStatus(next));
      }
    }
  }

  private handleWorkerMessage(e: MessageEvent<CaptureWorkerResponse>) {
    const data = e.data;

    switch (data.type) {
      case 'init:done':
        this.awaitWorkerInitialization?.resolve();
        this.awaitWorkerInitialization = null;
        break;

      case 'frame:done':
        // release backpressure lock
        this.awaitFrameCompletion?.();
        this.awaitFrameCompletion = null;

        // Forward result only while recording.
        // Local-capture + queueMicrotask: avoids closure hazards when state
        // changes before the microtask runs.
        if (this.state === 'recording') {
          const result = data.result;
          const onDetection = this.onDetection;
          if (onDetection) {
            queueMicrotask(() => {
              onDetection(result, 'frame'); // forward null too (UI uses null → "waiting")
            });
          }
        }
        break;

      case 'image:done':
        // One-shot still-image detect (upload path). Runs outside the frame
        // loop, so there is no awaitFrameCompletion to release and no
        // 'recording' gate — route unconditionally to onDetection so uploads
        // drive computeAdvice + turnLog.observe just like live frames.
        this.onDetection?.(data.result ?? null, 'image');
        break;

      case 'init:error':
        if (this.awaitWorkerInitialization) {
          this.awaitWorkerInitialization.reject('worker-init-failed');
          this.awaitWorkerInitialization = null;
        }
        break;

      case 'debug': {
        if (data.message) console.log(data.message);
        // Legacy synchronous debug canvas draw (drawn before any handoff close).
        if (data.image && this._debugCanvas && this.state === 'recording') {
          try {
            this._debugCanvas.width = data.image.width;
            this._debugCanvas.height = data.image.height;
            this._debugCanvas.getContext('2d')?.drawImage(data.image, 0, 0);
          } catch {
            // A draw failure must not strand the bitmap or break the handler.
          }
        }
        // Ownership of the bitmap transfers to the onDebug consumer (DebugView),
        // which draws it asynchronously and closes it. Only close here when no
        // consumer exists, to avoid a leak. DebugView is the sole closer of
        // handed-off bitmaps — never double-close.
        if (this.onDebug) {
          this.onDebug(data.image ?? null, data.result ?? null);
        } else if (data.image) {
          data.image.close();
        }
        break;
      }
    }
  }

  private async requestDisplayMedia() {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 30, cursor: 'never' } as MediaTrackConstraints,
      audio: false,
    });
    if (!stream) {
      throw Error('No stream');
    }
    this.track = stream.getVideoTracks()[0];
    if (!this.track) {
      throw Error('No video track');
    }
    const processor = new MediaStreamTrackProcessor({ track: this.track });
    this.reader = processor.readable.getReader();
  }

  async startCapture(deferDisplayRequest: boolean = false) {
    try {
      if (this.state !== 'idle') {
        throw 'recording' satisfies StartCaptureErrorType;
      }

      // → loading (lock)
      this.setState('loading');

      // Create worker and register message handler
      if (!this.worker) {
        this.worker = new Worker(new URL('./captureWorker.ts', import.meta.url), {
          type: 'module',
        });
        this.worker.onmessage = this.handleWorkerMessage.bind(this);
      }

      // Create a promise that resolves/rejects when the worker finishes init
      const waitForInit = new Promise<void>((resolve, reject) => {
        this.awaitWorkerInitialization = { resolve, reject };
      });
      this._workerInitPromise = waitForInit;
      this.postMessage({ type: 'init' });

      if (deferDisplayRequest) {
        await waitForInit;
        await this.requestDisplayMedia();
      } else {
        // Request screen share while worker initialises — run both in parallel
        await Promise.all([this.requestDisplayMedia(), waitForInit]);
      }

      if (!this.reader) {
        throw Error('reader is not ready');
      }

      // Wait until we can read at least one frame (confirms the stream is live)
      const { value, done } = await this.reader.read();
      if (done) {
        throw Error('Failed to read even a frame');
      }
      value?.close();

      // → recording; then start the frame loop.
      // loop() is fire-and-forget; guard its (unreachable-in-practice) defensive
      // throws so they surface via onError instead of becoming unhandled rejections.
      this.setState('recording');
      this.loop().catch((e) => {
        this.onError?.(classifyCaptureError(e));
      });
    } catch (err) {
      const classified = classifyCaptureError(err);
      // Init-error teardown: requestDisplayMedia may have already acquired the
      // track before waitForInit rejected. Stop it so the browser drops the
      // "sharing your screen" indicator (stopCapture() can't — state is loading,
      // not recording). On the success path the catch never runs and loop() owns
      // the track, so this can't double-stop.
      this.track?.stop();
      this.track = null;
      this.reader = null;
      this.onError?.(classified);
    } finally {
      // If something went wrong during loading, revert to idle
      if (this.state === 'loading') {
        this.setState('idle');
      }
    }
  }

  private async loop() {
    while (this.state === 'recording') {
      if (!this.reader) {
        throw Error('reader not exists');
      }
      let value: VideoFrame | undefined;
      try {
        if (!this.worker) throw Error('worker not exists');
        const result = await this.reader.read();
        value = result.value;
        const done = result.done;
        if (done) break; // user ended screen share
        if (!value) break;

        // Create a promise that resolves when the worker signals frame:done
        const waitForAnalysis = new Promise<void>((resolve) => {
          this.awaitFrameCompletion = resolve;
        });

        // Transfer the frame to the worker (ownership passes, no detectionMargin)
        this.worker.postMessage(
          { type: 'frame', frame: value, drawDebug: this.drawDebug } satisfies CaptureWorkerRequest,
          [value]
        );
        value = undefined; // ownership transferred — do not touch

        await waitForAnalysis;
      } finally {
        // If ownership was never transferred (error path), close to avoid leak
        value?.close();
      }
    }

    // Loop exited — clean up and signal idle
    this.track?.stop();
    this.track = null;
    this.setState('idle');
  }

  stopCapture() {
    // We cannot cancel the in-flight reader.read() or waitForAnalysis promises,
    // so we signal the loop to exit on its next iteration via the 'closing' state.
    if (this.state === 'recording') {
      this.state = 'closing'; // loop checks state === 'recording'; next iteration exits
    }
  }

  isRecording() {
    return this.state === 'recording';
  }

  toggleDrawDebug() {
    this.drawDebug = !this.drawDebug;
    return this.drawDebug;
  }

  /** Set the debug-overlay flag explicitly (lets the UI default it on). */
  setDrawDebug(on: boolean) {
    this.drawDebug = on;
    return this.drawDebug;
  }

  /** Ensure the worker is created and initialized (idempotent). */
  private async ensureWorkerReady(): Promise<void> {
    if (!this.worker) {
      this.worker = new Worker(new URL('./captureWorker.ts', import.meta.url), {
        type: 'module',
      });
      this.worker.onmessage = this.handleWorkerMessage.bind(this);
      const waitForInit = new Promise<void>((resolve, reject) => {
        this.awaitWorkerInitialization = { resolve, reject };
      });
      this._workerInitPromise = waitForInit;
      this.postMessage({ type: 'init' });
    }
    if (this._workerInitPromise) {
      await this._workerInitPromise;
    }
  }

  /** Analyze a still image (upload path). Initializes the worker on demand. */
  async analyzeImage(bitmap: ImageBitmap): Promise<void> {
    await this.ensureWorkerReady();
    if (!this.worker) throw new Error('worker is not set');
    this.worker.postMessage(
      { type: 'image', bitmap, drawDebug: this.drawDebug } satisfies CaptureWorkerRequest,
      [bitmap],
    );
  }
}
