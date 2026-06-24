import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import ScreenshotUpload from '../../src/components/ScreenshotUpload.svelte';
import DebugView from '../../src/components/DebugView.svelte';

describe('ScreenshotUpload', () => {
  it('renders a file input', () => {
    const { container } = render(ScreenshotUpload, { props: { onfile: () => {} } });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(input).toBeTruthy();
    expect(input?.type).toBe('file');
  });
});

describe('DebugView', () => {
  it('renders a canvas element', () => {
    const { container } = render(DebugView, { props: { image: null } });
    expect(container.querySelector('canvas')).toBeTruthy();
  });
});
