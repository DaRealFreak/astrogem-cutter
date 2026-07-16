import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Recursively mirror every *.png from srcDir to destDir, preserving structure.
 * Dest PNGs with no source counterpart are deleted (templates removed upstream
 * must not linger in the web bundle — import.meta.glob would keep loading them).
 * Returns the copied count.
 */
export function syncTemplates(srcDir, destDir) {
  let count = 0;
  const walk = (rel) => {
    const abs = join(srcDir, rel);
    for (const entry of readdirSync(abs)) {
      const childRel = join(rel, entry);
      const childAbs = join(srcDir, childRel);
      if (statSync(childAbs).isDirectory()) { walk(childRel); }
      else if (entry.endsWith('.png')) {
        const out = join(destDir, childRel);
        mkdirSync(dirname(out), { recursive: true });
        cpSync(childAbs, out);
        count++;
      }
    }
  };
  const prune = (rel) => {
    const abs = join(destDir, rel);
    if (!existsSync(abs)) return;
    for (const entry of readdirSync(abs)) {
      const childRel = join(rel, entry);
      const childAbs = join(destDir, childRel);
      if (statSync(childAbs).isDirectory()) { prune(childRel); }
      else if (entry.endsWith('.png') && !existsSync(join(srcDir, childRel))) {
        rmSync(childAbs);
      }
    }
  };
  mkdirSync(destDir, { recursive: true });
  walk('.');
  prune('.');
  return count;
}

// CLI: copy arkgrid/vision/templates → web/src/lib/cv/_templates
const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const here = dirname(fileURLToPath(import.meta.url));        // web/scripts
  const src = join(here, '..', '..', 'arkgrid', 'vision', 'templates');
  const dest = join(here, '..', 'src', 'lib', 'cv', '_templates');
  const n = syncTemplates(src, dest);
  console.log(`synced ${n} templates → ${dest}`);
}
