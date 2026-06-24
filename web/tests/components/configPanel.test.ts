import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import ConfigPanel from '../../src/components/ConfigPanel.svelte';

describe('ConfigPanel', () => {
  it('renders core goal controls and an advanced expander', () => {
    render(ConfigPanel);
    expect(screen.getByText(/goal/i)).toBeTruthy();
    expect(screen.getByLabelText(/min will/i)).toBeTruthy();
    expect(screen.getByText(/advanced/i)).toBeTruthy();
  });
});
