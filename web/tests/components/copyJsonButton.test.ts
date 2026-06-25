import { render, screen, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach } from 'vitest';
import CopyJsonButton from '../../src/components/CopyJsonButton.svelte';
import { advisor } from '../../src/lib/state/advisor.state.svelte';

afterEach(() => { cleanup(); advisor.output = null; });

describe('CopyJsonButton', () => {
  it('is disabled while there is no advice', () => {
    advisor.output = null;
    render(CopyJsonButton);
    const btn = screen.getByRole('button', { name: /copy json/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
