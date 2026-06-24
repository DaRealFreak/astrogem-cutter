import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import AdvisorPanel from '../../src/components/AdvisorPanel.svelte';
import OfferTable from '../../src/components/OfferTable.svelte';
import type { AdvisorOutput } from '../../src/lib/engine';

const output: AdvisorOutput = {
  action: 'REROLL' as any, branch: 'dp_reroll', reason: 'reroll for value',
  pGoal: 0.62, pRelic: 0.41, pAncient: 0.12, eValue: 1180,
  perOffer: [
    { key: 'will+1', pGoalAfter: 0.5, eValueAfter: 1100 },
    { key: 'chaos+1', pGoalAfter: 0.7, eValueAfter: 1150 },
    { key: 'will+2', pGoalAfter: 0.6, eValueAfter: 1170 },
    { key: 'reroll+1', pGoalAfter: 0.55, eValueAfter: 1120 },
  ],
};

describe('advisor display', () => {
  it('AdvisorPanel shows action, reason, and metrics', () => {
    render(AdvisorPanel, { props: { output, waiting: false } });
    expect(screen.getByText('REROLL')).toBeTruthy();
    expect(screen.getByText(/62\.0%/)).toBeTruthy();
  });
  it('AdvisorPanel shows a waiting state when gated', () => {
    render(AdvisorPanel, { props: { output: null, waiting: true } });
    expect(screen.getByText(/waiting for cutting screen/i)).toBeTruthy();
  });
  it('OfferTable renders one row per offer', () => {
    render(OfferTable, { props: { perOffer: output.perOffer } });
    expect(screen.getAllByRole('row')).toHaveLength(5); // header + 4
  });
});
