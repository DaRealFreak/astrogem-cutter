import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import App from '../../src/App.svelte';

describe('App', () => {
  it('mounts: title, share button, idle waiting state', () => {
    render(App);
    expect(screen.getByText('Astrogem Cutter')).toBeTruthy();
    expect(screen.getByRole('button', { name: /share screen/i })).toBeTruthy();
    expect(screen.getByText(/waiting for cutting screen/i)).toBeTruthy();
    expect(screen.getAllByText(/goal/i).length).toBeGreaterThan(0); // ConfigPanel Goal section present
    // combined mode is default — combined goal input is visible
    expect(screen.getByLabelText(/min will\+chaos/i)).toBeTruthy();
  });
});
