import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import App from '../../src/App.svelte';

describe('App foundation', () => {
  it('mounts and shows the title + share prompt', () => {
    render(App);
    expect(screen.getByText('Astrogem Advisor')).toBeTruthy();
    expect(screen.getByText(/share your screen/i)).toBeTruthy();
  });
});
