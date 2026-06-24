/**
 * Start-capture error classification — opencv/worker-free module.
 * Extracted so node tests can import without pulling the captureWorker/OpenCV graph.
 */

export const START_CAPTURE_ERROR_TYPES = [
  'recording',
  'worker-init-failed',
  'screen-permission-denied',
  'unknown',
] as const;

export type StartCaptureErrorType = (typeof START_CAPTURE_ERROR_TYPES)[number];

/** Returns true when `err` is a known StartCaptureErrorType token. */
export function isStartCaptureError(err: unknown): err is StartCaptureErrorType {
  return (
    typeof err === 'string' &&
    START_CAPTURE_ERROR_TYPES.includes(err as StartCaptureErrorType)
  );
}

/** Maps an arbitrary caught value to a StartCaptureErrorType. */
export function classifyCaptureError(err: unknown): StartCaptureErrorType {
  if (err instanceof DOMException) {
    if (err.name === 'NotAllowedError') {
      return 'screen-permission-denied';
    }
  }

  if (isStartCaptureError(err)) {
    return err; // pass-through known tokens
  }

  return 'unknown';
}
