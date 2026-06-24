import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import ActionMatrix from '../../src/components/ActionMatrix.svelte';

const actions = {
  process: { pGoal: 0.62, pRelic: 0.4, pAncient: 0.1, eValue: 1180 },
  reroll: { pGoal: 0.55, pRelic: 0.38, pAncient: 0.09, eValue: 1180 },
  reset: null,
};

describe('ActionMatrix', () => {
  it('renders a row per action with the 4 metrics, dashes for unavailable', () => {
    render(ActionMatrix, { props: { actions, recommended: 'PROCESS' as any } });
    expect(screen.getByText(/process/i)).toBeTruthy();
    expect(screen.getByText(/62\.0%/)).toBeTruthy();   // process P(goal)
    expect(screen.getAllByText('—').length).toBeGreaterThan(0); // reset row dashes
  });
});
