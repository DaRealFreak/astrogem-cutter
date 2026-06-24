import { describe, it, expect, vi } from 'vitest';
import { isStartCaptureError, classifyCaptureError } from '../../src/lib/cv/captureErrors';
import { CaptureController } from '../../src/lib/cv/captureController';
import type { CaptureWorkerResponse } from '../../src/lib/cv/workerTypes';
import type { DetectionResult } from '../../src/lib/cv/types';

describe('capture error classification', () => {
  it('recognizes its own error tokens', () => {
    expect(isStartCaptureError('recording')).toBe(true);
    expect(isStartCaptureError('nope')).toBe(false);
  });
  it('maps a NotAllowedError DOMException to permission-denied', () => {
    const e = new DOMException('denied', 'NotAllowedError');
    expect(classifyCaptureError(e)).toBe('screen-permission-denied');
  });
  it('falls back to unknown', () => { expect(classifyCaptureError(new Error('x'))).toBe('unknown'); });
});

// Seam test for the upload→advice routing (Fix #1): an 'image:done' response
// must reach onDetection even when the controller is idle (not 'recording').
// Exercises the message-handler contract directly — no Worker / no display media.
describe('image:done routing', () => {
  // handleWorkerMessage is private; reach it via the same seam the worker uses.
  function dispatch(c: CaptureController, msg: CaptureWorkerResponse) {
    const handler = (c as unknown as {
      handleWorkerMessage: (e: MessageEvent<CaptureWorkerResponse>) => void;
    }).handleWorkerMessage.bind(c);
    handler(new MessageEvent('message', { data: msg }));
  }

  it('routes image:done to onDetection while idle (not recording)', () => {
    const c = new CaptureController();
    const seen: Array<DetectionResult | null> = [];
    c.onDetection = (r) => seen.push(r);
    const result = { gemType: 'order' } as unknown as DetectionResult;

    dispatch(c, { type: 'image:done', result });

    expect(c.isRecording()).toBe(false); // confirms we are not in the recording state
    expect(seen).toEqual([result]);
  });

  it('forwards a null image:done result too', () => {
    const c = new CaptureController();
    const onDetection = vi.fn();
    c.onDetection = onDetection;

    dispatch(c, { type: 'image:done', result: null });

    expect(onDetection).toHaveBeenCalledTimes(1);
    expect(onDetection).toHaveBeenCalledWith(null, 'image');
  });
});
