import { describe, it, expect } from 'vitest';
import { isStartCaptureError, classifyCaptureError } from '../../src/lib/cv/captureErrors';

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
