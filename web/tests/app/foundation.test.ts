import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import App from '../../src/App.svelte';

describe('App', () => {
  it('mounts: title, share button, idle waiting state', () => {
    render(App);
    expect(screen.getByText('Astrogem Advisor')).toBeTruthy();
    expect(screen.getByRole('button', { name: /share screen/i })).toBeTruthy();
    expect(screen.getByText(/waiting for cutting screen/i)).toBeTruthy();
    expect(screen.getByText(/goal/i)).toBeTruthy(); // ConfigPanel present
  });
});
