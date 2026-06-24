import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import BrowserGuard from '../../src/components/BrowserGuard.svelte';

describe('BrowserGuard', () => {
  it('shows a Chromium message when unsupported', () => {
    render(BrowserGuard, { props: { supported: false } });
    expect(screen.getByText(/chromium-based browser/i)).toBeTruthy();
  });
  it('renders nothing when supported', () => {
    const { container } = render(BrowserGuard, { props: { supported: true } });
    expect(container.textContent?.trim()).toBe('');
  });
});
