/** True only on browsers with the capture APIs the advisor needs (Chromium family). */
export function isCaptureSupported(
  nav: Navigator = typeof navigator !== 'undefined' ? navigator : ({} as Navigator),
  win: typeof globalThis = globalThis,
): boolean {
  return (
    typeof nav?.mediaDevices?.getDisplayMedia === 'function' &&
    'MediaStreamTrackProcessor' in win
  );
}
