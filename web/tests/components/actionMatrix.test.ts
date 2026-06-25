import { render, screen, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach } from 'vitest';
import ActionMatrix from '../../src/components/ActionMatrix.svelte';

afterEach(cleanup);

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

  it('shows both with/without-ticket matrices when a ticket comparison is present', () => {
    // Unique E[coeff] sentinels per budget so each appears exactly once.
    const withoutTicket = { pGoal: 0.5, pRelic: 0.3, pAncient: 0.05, eValue: 1001,
      actions: { ...actions, reroll: { pGoal: 0.5, pRelic: 0.3, pAncient: 0.05, eValue: 1001 } } };
    const withTicket = { pGoal: 0.7, pRelic: 0.6, pAncient: 0.12, eValue: 1301,
      actions: { ...actions, reroll: { pGoal: 0.7, pRelic: 0.6, pAncient: 0.12, eValue: 1301 } } };
    render(ActionMatrix, { props: {
      actions: withTicket.actions, recommended: 'REROLL' as any,
      ticket: { owned: true, lent: true, free: 1, withoutTicket, withTicket } as any,
    } });
    expect(screen.getByText(/without extra reroll/i)).toBeTruthy();
    // "with extra reroll" caption (the without-caption doesn't contain it as a substring).
    expect(screen.getByText(/^with extra reroll/i)).toBeTruthy();
    // Each budget's reroll E[coeff] sentinel appears once.
    expect(screen.getByText('1001.0')).toBeTruthy();   // without-ticket reroll
    expect(screen.getByText('1301.0')).toBeTruthy();   // with-ticket reroll
  });

  it('flags a spent ticket and marks the recommended budget', () => {
    const withoutTicket = { pGoal: 0.5, pRelic: 0.3, pAncient: 0.05, eValue: 1001,
      actions: { ...actions, reroll: { pGoal: 0.5, pRelic: 0.3, pAncient: 0.05, eValue: 1001 } } };
    const withTicket = { pGoal: 0.7, pRelic: 0.6, pAncient: 0.12, eValue: 1301,
      actions: { ...actions, reroll: { pGoal: 0.7, pRelic: 0.6, pAncient: 0.12, eValue: 1301 } } };
    render(ActionMatrix, { props: {
      actions: withoutTicket.actions, recommended: 'PROCESS' as any,
      ticket: { owned: true, lent: false, spent: true, free: 0, withoutTicket, withTicket } as any,
    } });
    expect(screen.getByText(/already used this gem/i)).toBeTruthy();
    expect(screen.getByText(/without extra reroll.*recommended/i)).toBeTruthy();
  });
});
