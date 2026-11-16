import { render, screen, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach } from 'vitest';
import TurnLog from '../../src/components/TurnLog.svelte';

afterEach(cleanup);

describe('TurnLog', () => {
  it('lists P(bot) next to P(goal) for every recorded turn', () => {
    render(TurnLog, { props: { entries: [{
      turn: 3, will: 2, chaos: 3, firstLevel: 1, secondLevel: 2, action: 'process' as any,
      pGoal: 0.18, pBot: 0.29, pRelic: 0.2, pAncient: 0.01, eValue: 950,
    }] } });
    expect(screen.getByText('P(bot)')).toBeTruthy();
    expect(screen.getByText('18%')).toBeTruthy();
    expect(screen.getByText('29%')).toBeTruthy();
  });

  it('says so when nothing was recorded yet', () => {
    render(TurnLog, { props: { entries: [] } });
    expect(screen.getByText(/no turns recorded/i)).toBeTruthy();
  });
});
