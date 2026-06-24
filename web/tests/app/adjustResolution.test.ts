import { describe, it, expect } from 'vitest';
import { adjustResolution } from '../../src/lib/cv/adjustResolution';

describe('adjustResolution', () => {
  it('passes FHD through unscaled', () => { expect(adjustResolution(1080).scale).toBe(1); });
  it('downscales QHD by 3/4', () => { expect(adjustResolution(1440).scale).toBeCloseTo(0.75); });
  it('downscales UHD by 1/2', () => { expect(adjustResolution(2160).scale).toBe(0.5); });
  it('upscales sub-FHD above 1', () => { expect(adjustResolution(720).scale).toBeGreaterThan(1); });
  it('returns unknown (scale 1) for the gap between FHD and QHD', () => {
    expect(adjustResolution(1200).scale).toBe(1);
    expect(adjustResolution(1200).label).toBe('unknown');
  });
});
