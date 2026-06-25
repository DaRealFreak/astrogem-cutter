import type { DetectionResult } from '../cv/types';
import type { AdvisorOutput } from '../engine';

export type CaptureStatus = 'idle' | 'loading' | 'recording';

class AdvisorState {
  status = $state<CaptureStatus>('idle');
  detection = $state<DetectionResult | null>(null);
  output = $state<AdvisorOutput | null>(null);
  waiting = $state(true);            // last detection failed the completeness gate
  recomputing = $state(false);       // re-scoring the last reading after a config change
  error = $state<string | null>(null);
}

export const advisor = new AdvisorState();
