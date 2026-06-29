import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, it, expect, beforeEach } from 'vitest';
import ConfigPanel from '../../src/components/ConfigPanel.svelte';
import { config } from '../../src/lib/state/config.state.svelte';

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

describe('ConfigPanel relic-reroll slider (commit on release)', () => {
  beforeEach(() => {
    config.current = { ...config.current, relicRerollThreshold: 0 };
  });

  it('does not write config while dragging (input) — only on release (change)', async () => {
    render(ConfigPanel);
    const slider = screen.getByLabelText(/relic reroll threshold/i) as HTMLInputElement;

    // Drag: input events update the thumb/label but must NOT touch config
    // (config drives the recompute, so a write per step re-scores mid-drag).
    await fireEvent.input(slider, { target: { value: '0.5' } });
    expect(config.current.relicRerollThreshold).toBe(0);
    await fireEvent.input(slider, { target: { value: '0.75' } });
    expect(config.current.relicRerollThreshold).toBe(0);

    // Release commits the final value exactly once.
    await fireEvent.change(slider, { target: { value: '0.75' } });
    expect(config.current.relicRerollThreshold).toBe(0.75);
  });

  it('reflects an external config change on the slider (preset load)', async () => {
    render(ConfigPanel);
    const slider = screen.getByLabelText(/relic reroll threshold/i) as HTMLInputElement;
    config.current = { ...config.current, relicRerollThreshold: 0.3 };
    await tick();
    expect(slider.value).toBe('0.3');
  });
});
