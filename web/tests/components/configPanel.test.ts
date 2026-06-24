import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import ConfigPanel from '../../src/components/ConfigPanel.svelte';

describe('ConfigPanel', () => {
  it('renders core goal controls and an advanced expander', () => {
    render(ConfigPanel);
    expect(screen.getAllByText(/goal/i).length).toBeGreaterThan(0);
    // combined mode is the default — min will+chaos input is shown
    expect(screen.getByLabelText(/min will\+chaos/i)).toBeTruthy();
    expect(screen.getByText(/advanced/i)).toBeTruthy();
  });

  it('renders the goal-mode segmented toggle', () => {
    render(ConfigPanel);
    expect(screen.getAllByRole('group', { name: /goal mode/i }).length).toBeGreaterThan(0);
  });

  it('shows Min will+chaos input in combined mode (default)', () => {
    render(ConfigPanel);
    expect(screen.getByLabelText(/min will\+chaos/i)).toBeTruthy();
  });
});
