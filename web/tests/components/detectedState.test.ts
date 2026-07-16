import { render, screen, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach } from 'vitest';
import DetectedState from '../../src/components/DetectedState.svelte';
import AdvisorPanel from '../../src/components/AdvisorPanel.svelte';
import type { DetectionResult } from '../../src/lib/cv/types';
import type { AdvisorOutput, TicketComparison } from '../../src/lib/engine';

afterEach(cleanup);

function det(overrides: Partial<DetectionResult> = {}): DetectionResult {
  return {
    found: true,
    gemType: 'chaos_destruction', gemTypeScore: 0.99,
    willpower: 1, willpowerScore: 1,
    chaos: 1, chaosScore: 1,
    firstEffect: 'additional_damage', firstEffectScore: 1, firstLevel: 1, firstLevelScore: 1,
    secondEffect: 'boss_damage', secondEffectScore: 1, secondLevel: 1, secondLevelScore: 1,
    rerolls: '4', rerollsScore: 1,
    resetEnabled: true, resetScore: 0.08,
    chargeEnabled: true, chargeScore: 0.07,
    currentStep: 8, stepScore: 1,
    totalSteps: 9, rarityScore: 1,
    options: [],
    ...overrides,
  };
}

function ticket(overrides: Partial<TicketComparison> = {}): TicketComparison {
  const snap = { pGoal: 0, pRelic: 0, pAncient: 0, eValue: 0, actions: { process: null, reroll: null, reset: null } };
  return { owned: true, lent: true, spent: false, free: 4, withoutTicket: snap, withTicket: snap, ...overrides };
}

describe('DetectedState reroll split display', () => {
  it('shows free(+1)/base when the ticket is lent (epic, 4 free)', () => {
    render(DetectedState, { props: { detection: det(), ticket: ticket() } });
    expect(screen.getByText('4(+1)/2')).toBeTruthy();
  });

  it('shows free/base without the lend', () => {
    render(DetectedState, { props: { detection: det({ rerolls: '3', totalSteps: 7 }), ticket: ticket({ lent: false, free: 3 }) } });
    expect(screen.getByText('3/1')).toBeTruthy();
  });

  it('shows 0 free rerolls while the Charge button is yellow (bug repro frame)', () => {
    // Regression (2026-07-16): a yellow Charge button means 0 FREE rerolls —
    // the display must never count the ticket as a free reroll.
    render(DetectedState, {
      props: {
        detection: det({ rerolls: '0_ticket_available', totalSteps: 9, currentStep: 3 }),
        ticket: ticket({ lent: true, free: 0 }),
      },
    });
    expect(screen.getByText('0(+1)/2')).toBeTruthy();
  });

  it('falls back to a dash when the counter was not detected', () => {
    render(DetectedState, { props: { detection: det({ rerolls: null }), ticket: null } });
    expect(screen.getByText('—')).toBeTruthy();
  });
});

describe('AdvisorPanel ticket-reroll note', () => {
  const output = (t: TicketComparison | null): AdvisorOutput => ({
    action: 'reroll' as any, branch: 'side_value_finish',
    reason: 'goal met, spending the reroll ticket (Charge)',
    pGoal: 0.5, pRelic: 0.5, pAncient: 0.1, eValue: 1000,
    perOffer: [], actions: { process: null, reroll: null, reset: null },
    ticket: t,
  } as any);

  it('warns when the recommended reroll spends the ticket (0 free)', () => {
    render(AdvisorPanel, { props: { output: output(ticket({ lent: true, free: 0 })), waiting: false } });
    expect(screen.getByText(/spends the reroll ticket/i)).toBeTruthy();
  });

  it('stays silent while free rerolls remain', () => {
    render(AdvisorPanel, { props: { output: output(ticket({ lent: true, free: 2 })), waiting: false } });
    expect(screen.queryByText(/spends the reroll ticket/i)).toBeNull();
  });
});
