import type { DetectionResult } from '../cv/types';
import type { AdvisorOutput } from '../engine';

export type CaptureStatus = 'idle' | 'loading' | 'recording';

class AdvisorState {
  status = $state<CaptureStatus>('idle');
  detection = $state<DetectionResult | null>(null);
  output = $state<AdvisorOutput | null>(null);
  waiting = $state(true);            // last detection failed the completeness gate
  error = $state<string | null>(null);
}

export const advisor = new AdvisorState();
