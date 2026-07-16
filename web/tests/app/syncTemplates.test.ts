import { describe, it, expect, afterAll } from 'vitest';
import { mkdtempSync, rmSync, readdirSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { syncTemplates } from '../../scripts/sync-templates.mjs';

const SRC = join(__dirname, '..', '..', '..', 'arkgrid', 'vision', 'templates');

describe('syncTemplates', () => {
  const dest = mkdtempSync(join(tmpdir(), 'tmpl-'));
  afterAll(() => rmSync(dest, { recursive: true, force: true }));

  it('copies every source PNG, preserving subdirs', () => {
    const n = syncTemplates(SRC, dest);
    expect(n).toBeGreaterThan(50);             // the template set is ~100+ PNGs
    // anchor + nested side_nodes subdir survive
    expect(readdirSync(join(dest, 'anchor')).some((f) => f.endsWith('.png'))).toBe(true);
    expect(readdirSync(join(dest, 'side_nodes', 'names')).length).toBeGreaterThan(0);
  });

  it('prunes dest PNGs whose source was removed', () => {
    // Simulate a template deleted upstream: a stray dest PNG with no source
    // counterpart (import.meta.glob would otherwise keep bundling it).
    const straySub = join(dest, 'options', 'names');
    mkdirSync(straySub, { recursive: true });
    const stray = join(straySub, 'deleted_upstream_99.png');
    writeFileSync(stray, 'not a real png');
    syncTemplates(SRC, dest);
    expect(existsSync(stray)).toBe(false);
    // real templates survive the prune
    expect(readdirSync(straySub).some((f) => f.endsWith('.png'))).toBe(true);
  });
});
