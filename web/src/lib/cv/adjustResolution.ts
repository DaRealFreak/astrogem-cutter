export interface ResolutionScale { scale: number; label: string; }

/** Scale factor to normalize a captured frame of the given pixel height to ~FHD (1080p). */
export function adjustResolution(height: number): ResolutionScale {
  if (height < 1080) return { scale: 1080 / (height - 27), label: 'sub-FHD (upscaled)' };
  if (height <= 1080 + 48) return { scale: 1, label: 'FHD' };
  if (height >= 1440 && height <= 1440 + 48) return { scale: 3 / 4, label: 'QHD' };
  if (height >= 2160 && height <= 2160 + 48) return { scale: 1 / 2, label: 'UHD' };
  return { scale: 1, label: 'unknown' };
}
