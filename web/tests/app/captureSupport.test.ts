import { describe, it, expect } from 'vitest';
import { isCaptureSupported } from '../../src/lib/app/captureSupport';

describe('isCaptureSupported', () => {
  it('true when getDisplayMedia + MediaStreamTrackProcessor exist', () => {
    const nav = { mediaDevices: { getDisplayMedia: () => {} } } as any;
    const win = { MediaStreamTrackProcessor: function () {} } as any;
    expect(isCaptureSupported(nav, win)).toBe(true);
  });
  it('false when MediaStreamTrackProcessor missing (Firefox/Safari)', () => {
    const nav = { mediaDevices: { getDisplayMedia: () => {} } } as any;
    expect(isCaptureSupported(nav, {} as any)).toBe(false);
  });
  it('false when getDisplayMedia missing', () => {
    expect(isCaptureSupported({ mediaDevices: {} } as any, { MediaStreamTrackProcessor: function () {} } as any)).toBe(false);
  });
});
