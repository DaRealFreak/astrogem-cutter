# Astrogem Cutter Web Advisor — App Shell (Plan 3 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built, parity-tested decision engine (Plan 1, `web/src/lib/engine/`) and vision recognizer (Plan 2, `web/src/lib/cv/`) into a runnable, read-only Svelte web advisor deployed to GitHub Pages — the browser equivalent of `python -m arkgrid auto --dry-run`.

**Architecture:** A Vite + Svelte 5 app. A Web Worker captures the shared screen (`getDisplayMedia` → `MediaStreamTrackProcessor` → OpenCV `detect()`), posting a `DetectionResult` per frame to the main thread. The main thread gates the detection for completeness, adapts it to engine inputs, runs `advise()` against a per-gem-type/config-cached `EngineContext`, and renders the recommended action + P(goal)/P(relic+)/P(ancient)/E[coeff] in a two-column UI (config left, advisor right). A GitHub Actions workflow builds `web/` and publishes to Pages on push to `master`.

**Tech Stack:** Svelte 5 (runes), Vite 7, `@sveltejs/vite-plugin-svelte`, `svelte-check`, `svelte-persisted-state`, `@techstark/opencv-js` (already present), `@types/dom-mediacapture-transform`, Vitest (node + headless-Chromium browser projects, already configured), `@testing-library/svelte`, GitHub Actions Pages deploy.

**Design spec:** `docs/superpowers/specs/2026-06-24-astrogem-web-app-shell-design.md`
**Parent spec:** `docs/superpowers/specs/2026-06-23-astrogem-cutter-web-design.md`

## Global Constraints

- **Branch:** all work on `feat/web-engine-port` (continues Plans 1 & 2). Do not merge.
- **Pages base path:** vite `base: '/AstrogemCutter/'` (project page `https://darealfreak.github.io/AstrogemCutter/`).
- **Deploy trigger:** GitHub Actions on push to `master`, **path-filtered** to `web/**`, `arkgrid/vision/templates/**`, and the workflow file; plus `workflow_dispatch`. The site goes live only when the branch merges.
- **Layout:** two-column — config panel left, capture + advisor right.
- **Template delivery:** reuse the existing `TemplateStore` (Plan 2). **No** sprite atlas, **no** `spritesmith`/`generate-sprite`.
- **Defaults:** every config knob defaults to its Python default so the advisor is correct untouched.
- **Read-only:** the app never clicks or controls the game. No confirm gate, no F1–F4, no manual-entry form, no gold modeling (all out of scope per design §9).
- **Engine/vision libraries are consumed unchanged** except Task 2's pure-helper file split (no behavior change).
- **Browser purity:** `src/` must stay free of Node globals; `svelte-check` runs against a src-only svelte tsconfig.
- **Test gate:** the existing 38 Plan-1/Plan-2 tests must stay green at every task boundary. New opencv-importing tests go in the Vitest **browser** project (`web/vitest.config.ts` `BROWSER_TESTS` allowlist); opencv-free tests go in the **node** project.
- **Existing tsconfig set** (from Plan 1): `web/tsconfig.json` (src-only, no node), `web/tsconfig.check.json` (adds node, used by `npm run check` today), `web/tests/tsconfig.json`. Reconcile — do not duplicate — when adding the svelte-aware app tsconfig.
- **Worker constraint:** Web Workers have no `document`. Decode images with `OffscreenCanvas` + `createImageBitmap`, never `document.createElement('canvas')`.

## Port-reference convention

Like Plans 1 & 2 (which ported Python module-for-module), the two **port tasks** (capture worker, capture controller) adapt a concrete sibling source file — `lostark-arkgrid-gem-locator-v2/src/lib/cv/{captureWorker,captureController,types,matStore}.ts` — rather than transcribing it. Each such task names the exact source file, the precise adaptations (swap locator-v2's gem-grid recognition for our `detect()`; swap the message payload types), and inlines the genuinely-new glue. All **new-logic tasks** inline complete code.

## File structure

```
web/
  index.html                         # NEW (T1)
  package.json                       # MODIFY (T1): deps + scripts
  vite.config.ts                     # NEW (T1): base, svelte plugin, worker es
  svelte.config.js                   # NEW (T1)
  tsconfig.app.json                  # NEW (T1): svelte-aware, src-only, browser-pure
  tsconfig.node.json                 # NEW (T1): config/worker/script files (node)
  .gitignore                         # NEW (T3): ignore generated _templates/
  src/
    main.ts                          # NEW (T1)
    App.svelte                       # NEW (T1 stub → T11 full)
    app.css                          # NEW (T1)
    vite-env.d.ts                    # EXISTS (Plan 2)
    lib/
      cv/
        types.ts                     # NEW (T2): DetectionResult, OptionDetection
        parse.ts                     # NEW (T2): parse helpers (opencv-free)
        recognizer.ts                # MODIFY (T2): import from parse.ts/types.ts; keep detect()
        adapter.ts                   # MODIFY (T2): import from parse.ts/types.ts
        decodeGray.ts                # NEW (T3): OffscreenCanvas PNG→gray Mat (worker-safe)
        workerTypes.ts               # NEW (T4): capture worker message types
        adjustResolution.ts          # NEW (T4): FHD-normalize scale (pure)
        captureWorker.ts             # NEW (T4): worker — init + frame → detect()
        captureController.ts         # NEW (T5): getDisplayMedia → worker loop
        _templates/                  # GENERATED (T3, gitignored): synced template PNGs
      app/
        optimize.ts                  # NEW (T6): resolveOptimize, inferResetAvailable, isCompleteDetection
        computeAdvice.ts             # NEW (T8): detection → gate → adapter → ctx-cache → advise
      state/
        config.state.svelte.ts       # NEW (T7): persisted config + DEFAULT_CONFIG + effectiveConfig
        advisor.state.svelte.ts      # NEW (T8): runtime runes (status, detection, output)
    components/
      ConfigPanel.svelte             # NEW (T9)
      AdvisorPanel.svelte            # NEW (T10)
      OfferTable.svelte              # NEW (T10)
      DetectedState.svelte           # NEW (T10)
      CaptureControls.svelte         # NEW (T11)
  scripts/
    sync-templates.mjs               # NEW (T3): copy arkgrid/vision/templates → src/lib/cv/_templates
  tests/                             # NEW tests per task (node or browser project)
.github/workflows/deploy-web.yml     # NEW (T12)
```

---

### Task 1: Build foundation (Vite + Svelte 5 + tsconfig + entry)

Stand up a runnable Svelte app skeleton so `npm run dev`, `npm run build`, and `npm run check` work, without touching the engine/vision libraries. Pure scaffolding + one render smoke test.

**Files:**
- Modify: `web/package.json` (add deps + scripts)
- Create: `web/vite.config.ts`, `web/svelte.config.js`, `web/tsconfig.app.json`, `web/tsconfig.node.json`
- Create: `web/index.html`, `web/src/main.ts`, `web/src/App.svelte`, `web/src/app.css`
- Test: `web/tests/app/foundation.test.ts` (browser project)

**Interfaces:**
- Consumes: nothing (scaffolding).
- Produces: a mountable `App` Svelte component; `npm run dev/build/check` scripts; vite `base: '/AstrogemCutter/'`; `worker: { format: 'es' }`.

- [ ] **Step 1: Add dependencies**

In `web/package.json`, add to `devDependencies`: `"@sveltejs/vite-plugin-svelte": "^6.2.1"`, `"svelte": "^5.39.6"`, `"svelte-check": "^4.3.2"`, `"@tsconfig/svelte": "^5.0.5"`, `"@testing-library/svelte": "^5.2.8"`. Add to `dependencies`: `"svelte-persisted-state": "^1.2.0"`, `"@types/dom-mediacapture-transform": "^0.1.11"`. Then replace `scripts` with:

```json
"scripts": {
  "dev": "vite",
  "build": "vite build",
  "preview": "vite preview",
  "test": "vitest run",
  "test:watch": "vitest",
  "check": "svelte-check --tsconfig ./tsconfig.app.json"
}
```

Run: `cd web && npm install`. Expected: installs cleanly, `package-lock.json` updated (keep it tracked — global rule).

- [ ] **Step 2: Vite + Svelte config**

`web/vite.config.ts`:

```ts
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Pages project base path. Worker is an ES-module worker (import/export inside it).
export default defineConfig({
  base: '/AstrogemCutter/',
  plugins: [svelte()],
  worker: { format: 'es' },
});
```

`web/svelte.config.js`:

```js
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
export default { preprocess: vitePreprocess() };
```

> NOTE: `web/vitest.config.ts` already exists and is independent (it does not import `vite.config.ts`). Leave it as-is; the two coexist.

- [ ] **Step 3: tsconfigs (reconcile with Plan 1's set)**

`web/tsconfig.app.json` — svelte-aware, src-only, browser-pure (no node types):

```json
{
  "extends": "@tsconfig/svelte/tsconfig.json",
  "compilerOptions": {
    "target": "ESNext",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "types": ["svelte", "vite/client", "dom-mediacapture-transform"],
    "lib": ["ESNext", "DOM", "DOM.Iterable", "WebWorker"],
    "strict": true,
    "noEmit": true,
    "isolatedModules": true
  },
  "include": ["src/**/*.ts", "src/**/*.svelte", "src/vite-env.d.ts"]
}
```

`web/tsconfig.node.json` — config/worker-build/script files (node allowed):

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "types": ["node"],
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts", "svelte.config.js", "scripts/**/*.mjs"]
}
```

Leave `web/tsconfig.json`, `web/tsconfig.check.json`, `web/tests/tsconfig.json` unchanged (they still gate the engine/vision libs + tests). `npm run check` now points at `tsconfig.app.json` (svelte-aware) — this is the browser-purity gate the design calls for.

- [ ] **Step 4: App entry**

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Astrogem Cutter Advisor</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

`web/src/main.ts`:

```ts
import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

const app = mount(App, { target: document.getElementById('app')! });
export default app;
```

`web/src/app.css`: minimal reset + the two-column grid scaffold used later.

```css
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; }
.app-shell { display: grid; grid-template-columns: 320px 1fr; min-height: 100vh; }
.app-config { padding: 1rem; border-right: 1px solid color-mix(in srgb, currentColor 18%, transparent); overflow-y: auto; }
.app-main { padding: 1rem; display: flex; flex-direction: column; gap: 1rem; }
@media (max-width: 720px) { .app-shell { grid-template-columns: 1fr; } }
```

`web/src/App.svelte` (stub — replaced in T11):

```svelte
<script lang="ts">
</script>

<main class="app-shell">
  <aside class="app-config"><h1>Astrogem Advisor</h1></aside>
  <section class="app-main"><p>Share your screen to begin.</p></section>
</main>
```

- [ ] **Step 5: Write the smoke test** (`web/tests/app/foundation.test.ts`, browser project)

```ts
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
```

Add the **specific file** `'tests/app/foundation.test.ts'` to the `BROWSER_TESTS` array in `web/vitest.config.ts` (Svelte component render needs a real DOM; runs in headless Chromium). Do **not** add a broad `tests/app/**` glob — later `tests/app/` files (syncTemplates, optimize, computeAdvice) are opencv-free node tests and must stay in the node project.

- [ ] **Step 6: Run check + build + tests**

Run: `cd web && npm run check`
Expected: 0 errors.

Run: `cd web && npm run build`
Expected: builds to `web/dist/`; `dist/index.html` references assets under `/AstrogemCutter/`.

Run: `cd web && npm test`
Expected: previous 38 + 1 new = **39 passing** (node + browser projects), 0 leaked processes.

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/package-lock.json web/vite.config.ts web/svelte.config.js \
  web/tsconfig.app.json web/tsconfig.node.json web/index.html web/src/main.ts \
  web/src/App.svelte web/src/app.css web/tests/app/foundation.test.ts web/vitest.config.ts
git commit -m "feat(web): Svelte+Vite app foundation (base /AstrogemCutter/)"
```

---

### Task 2: Split opencv-free parse helpers into `parse.ts` + `types.ts`

Realizes the cleanup the Plan-2 ledger flagged as the recommended first Plan-3 task. Move the pure detection types and parse helpers out of `recognizer.ts` (which statically imports opencv) so `adapter.ts` and the new Plan-3 wiring no longer transitively pull opencv into the Node test project. **No behavior change** — pure code movement + re-export.

**Files:**
- Create: `web/src/lib/cv/types.ts`, `web/src/lib/cv/parse.ts`
- Modify: `web/src/lib/cv/recognizer.ts` (re-export from the new files; keep `detect()` + its private `_match`/`_cropRoi`/`blankResult`)
- Modify: `web/src/lib/cv/adapter.ts` (import `DetectionResult` + parse helpers from `parse.ts`/`types.ts`, not `recognizer.ts`)
- Modify: `web/vitest.config.ts` (move `tests/vision/parse.test.ts` + `tests/vision/adapter.test.ts` out of `BROWSER_TESTS` → node project)

**Interfaces:**
- Consumes: existing `recognizer.ts` exports.
- Produces: `types.ts` exports `DetectionResult`, `OptionDetection`; `parse.ts` exports `parseRerolls`, `parseDelta`, `determineOptionKind`, `sideNodeLevel`, `DeltaKind`, and re-exports `stripVariant` (from `templates.ts`, which is already opencv-free). `recognizer.ts` continues to export all of these names (re-export) plus `detect`.

- [ ] **Step 1: Create `types.ts`**

Move the `OptionDetection` and `DetectionResult` interface declarations verbatim from `recognizer.ts` into `web/src/lib/cv/types.ts` (with their doc comments). No imports needed.

- [ ] **Step 2: Create `parse.ts`**

Move `parseRerolls`, `DeltaKind`, `parseDelta`, `determineOptionKind`, `sideNodeLevel` verbatim from `recognizer.ts` into `web/src/lib/cv/parse.ts`. Its only import is `import { stripVariant } from './templates';` (already opencv-free). Re-export for convenience so downstream files have a single opencv-free import source:

```ts
export { stripVariant } from './templates';
export type { DetectionResult, OptionDetection } from './types';
```

- [ ] **Step 3: Trim `recognizer.ts` to opencv-only + re-export**

`recognizer.ts` keeps `detect`, `_match`, `_cropRoi`, `blankResult`, `DIGIT_RE`, and its opencv imports. Replace the moved declarations with re-exports so existing import sites keep working:

```ts
export type { DetectionResult, OptionDetection } from './types';
export {
  parseRerolls, parseDelta, determineOptionKind, sideNodeLevel, type DeltaKind,
} from './parse';
import type { DetectionResult } from './types';
import { sideNodeLevel } from './parse';   // detect() uses sideNodeLevel internally
```

`detect()` uses `sideNodeLevel` and the `blankResult`/`DetectionResult` type — import them from the new files. Verify no other moved symbol is referenced inside `detect()` except `sideNodeLevel`.

- [ ] **Step 4: Point `adapter.ts` at the opencv-free modules**

Change `adapter.ts`'s import from `'./recognizer'` to a single opencv-free source (`parse.ts` re-exports the type from `types.ts`, per Step 2):

```ts
import { parseRerolls, parseDelta, determineOptionKind, type DetectionResult } from './parse';
```

`adapter.ts` no longer imports `recognizer.ts`, so it no longer transitively imports opencv.

- [ ] **Step 5: Re-route the now-opencv-free tests to the node project**

In `web/vitest.config.ts`, remove `'tests/vision/parse.test.ts'` and `'tests/vision/adapter.test.ts'` from `BROWSER_TESTS`. They now run in the node project (faster, no browser). Verify `tests/vision/parse.test.ts` imports only from `parse.ts`/`recognizer.ts` re-exports (still resolves) and `tests/vision/adapter.test.ts` imports `adapter.ts` (now opencv-free). If either test imports `detect`/`recognizer.ts` opencv symbols, leave that specific test in the browser list; otherwise move it.

- [ ] **Step 6: Run the full suite**

Run: `cd web && npm test`
Expected: **39 passing**, identical assertions, but `parse`/`adapter` now execute in the node project. 0 leaked processes.

Run: `cd web && npm run check && npx tsc -p tsconfig.check.json --noEmit`
Expected: both clean (no broken imports).

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/cv/types.ts web/src/lib/cv/parse.ts web/src/lib/cv/recognizer.ts \
  web/src/lib/cv/adapter.ts web/vitest.config.ts
git commit -m "refactor(web): split opencv-free parse helpers into parse.ts/types.ts"
```

---

### Task 3: Template sync script + worker-safe `decodeGray`

Make the recognition templates available to the production build from their single source (`arkgrid/vision/templates/`), and provide a worker-safe PNG→grayscale decoder.

**Files:**
- Create: `web/scripts/sync-templates.mjs`
- Create: `web/src/lib/cv/decodeGray.ts`
- Create: `web/.gitignore`
- Modify: `web/package.json` (add `predev`/`prebuild`/`sync:templates` scripts)
- Test: `web/tests/app/syncTemplates.test.ts` (node), `web/tests/cv/decodeGray.test.ts` (browser)

**Interfaces:**
- Consumes: `arkgrid/vision/templates/**/*.png`; `getCv()` (`cvRuntime.ts`).
- Produces: `syncTemplates(srcDir: string, destDir: string): number` (returns count copied); `decodeGray(bytes: ArrayBuffer | Blob): Promise<any>` (a 1-channel `cv.Mat`, caller deletes). Generated `web/src/lib/cv/_templates/**/*.png` mirroring the source tree.

- [ ] **Step 1: Write `syncTemplates` test** (`web/tests/app/syncTemplates.test.ts`, node)

```ts
import { describe, it, expect, afterAll } from 'vitest';
import { mkdtempSync, rmSync, readdirSync } from 'node:fs';
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
});
```

Run: `cd web && npx vitest run tests/app/syncTemplates.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 2: Implement `web/scripts/sync-templates.mjs`**

```js
import { cpSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Recursively copy every *.png from srcDir to destDir, preserving structure. Returns count. */
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
  mkdirSync(destDir, { recursive: true });
  walk('.');
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
```

Run the test again — Expected: PASS.

- [ ] **Step 3: Wire npm lifecycle + gitignore**

Add to `web/package.json` scripts: `"sync:templates": "node scripts/sync-templates.mjs"`, `"predev": "npm run sync:templates"`, `"prebuild": "npm run sync:templates"`. Create `web/.gitignore`:

```
node_modules/
dist/
src/lib/cv/_templates/
```

Run: `cd web && npm run sync:templates` — Expected: prints "synced N templates …"; `web/src/lib/cv/_templates/anchor/processing.png` exists and is git-ignored (`git status` does not list it).

- [ ] **Step 4: Write `decodeGray` test** (`web/tests/cv/decodeGray.test.ts`, browser project)

```ts
import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { decodeGray } from '../../src/lib/cv/decodeGray';

const URL = (await import('../../../arkgrid/vision/templates/anchor/processing.png?url')).default;

describe('decodeGray', () => {
  beforeAll(async () => { await initOpenCv(); });
  it('decodes a PNG to a non-empty single-channel Mat', async () => {
    const bytes = await (await fetch(URL)).arrayBuffer();
    const mat = await decodeGray(bytes);
    expect(mat.rows).toBeGreaterThan(0);
    expect(mat.cols).toBeGreaterThan(0);
    expect(mat.channels()).toBe(1);
    mat.delete();
  });
});
```

Run: `cd web && npx vitest run tests/cv/decodeGray.test.ts` — Expected: FAIL (module not found). (`tests/cv/**` is already in `BROWSER_TESTS`.)

- [ ] **Step 5: Implement `web/src/lib/cv/decodeGray.ts`** (mirrors `matStore.ts`'s `fetchSpriteMat`, worker-safe)

```ts
import { getCv } from './cvRuntime';

/**
 * Decode PNG bytes (or a Blob) into a single-channel grayscale cv.Mat.
 * Worker-safe: uses OffscreenCanvas + createImageBitmap (no `document`).
 * Caller owns the returned Mat and must .delete() it.
 */
export async function decodeGray(src: ArrayBuffer | Blob): Promise<any> {
  const cv = getCv();
  const blob = src instanceof Blob ? src : new Blob([src]);
  const bmp = await createImageBitmap(blob);
  const off = new OffscreenCanvas(bmp.width, bmp.height);
  const ctx = off.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('OffscreenCanvas 2D context unavailable');
  ctx.drawImage(bmp, 0, 0);
  const data = ctx.getImageData(0, 0, bmp.width, bmp.height);
  bmp.close();
  const rgba = cv.matFromImageData(data);
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  rgba.delete();
  return gray;
}
```

Run the test again — Expected: PASS.

- [ ] **Step 6: Run gates + commit**

Run: `cd web && npm test` — Expected: **41 passing** (39 + syncTemplates + decodeGray).
Run: `cd web && npm run check` — Expected: 0 errors.

```bash
git add web/scripts/sync-templates.mjs web/src/lib/cv/decodeGray.ts web/.gitignore \
  web/package.json web/tests/app/syncTemplates.test.ts web/tests/cv/decodeGray.test.ts
git commit -m "feat(web): template sync script + worker-safe decodeGray"
```

---

### Task 4: Capture worker (init + frame → `detect()`)

The Web Worker that owns OpenCV: loads templates once, then per frame normalizes to FHD, grayscales, runs our `detect()`, and posts a `DetectionResult`. **Port** the worker-loop shape of `lostark-arkgrid-gem-locator-v2/src/lib/cv/captureWorker.ts`, but replace its FrameProcessor gem-grid recognition with our `detect()` and our message types.

**Files:**
- Create: `web/src/lib/cv/workerTypes.ts`, `web/src/lib/cv/adjustResolution.ts`, `web/src/lib/cv/captureWorker.ts`
- Test: `web/tests/cv/adjustResolution.test.ts` (node)

**Interfaces:**
- Consumes: `initOpenCv`/`getCv` (`cvRuntime.ts`), `decodeGray` (T3), `TemplateStore`/`groupBySet` (`templates.ts`), `detect` + `DetectionResult` (`recognizer.ts`/`types.ts`), generated `_templates/` (T3).
- Produces: `CaptureWorkerRequest`/`CaptureWorkerResponse` message types; `adjustResolution(height: number): { scale: number; label: string }`; an ES-module worker whose `init` loads templates and `frame` posts `{ type: 'frame:done', result: DetectionResult | null }`.

- [ ] **Step 1: Message types** — `web/src/lib/cv/workerTypes.ts`

```ts
import type { DetectionResult } from './types';

export type CaptureWorkerRequest =
  | { type: 'init' }
  | { type: 'frame'; frame: VideoFrame; drawDebug: boolean };

export type CaptureWorkerResponse =
  | { type: 'init:done' }
  | { type: 'init:error'; error?: string }
  | { type: 'frame:done'; result: DetectionResult | null }
  | { type: 'debug'; image?: ImageBitmap; message?: string };
```

- [ ] **Step 2: Write `adjustResolution` test** — `web/tests/cv/adjustResolution.test.ts` (node)

```ts
import { describe, it, expect } from 'vitest';
import { adjustResolution } from '../../src/lib/cv/adjustResolution';

describe('adjustResolution', () => {
  it('passes FHD through unscaled', () => { expect(adjustResolution(1080).scale).toBe(1); });
  it('downscales QHD by 3/4', () => { expect(adjustResolution(1440).scale).toBeCloseTo(0.75); });
  it('downscales UHD by 1/2', () => { expect(adjustResolution(2160).scale).toBe(0.5); });
  it('upscales sub-FHD above 1', () => { expect(adjustResolution(720).scale).toBeGreaterThan(1); });
});
```

Run: `cd web && npx vitest run tests/cv/adjustResolution.test.ts` — Expected: FAIL.

- [ ] **Step 3: Implement `adjustResolution`** — `web/src/lib/cv/adjustResolution.ts` (port of locator-v2 `FrameProcessor.adjustResolution`, FHD-target)

```ts
export interface ResolutionScale { scale: number; label: string; }

/** Scale factor to normalize a captured frame of the given pixel height to ~FHD (1080p). */
export function adjustResolution(height: number): ResolutionScale {
  if (height < 1080) return { scale: 1080 / (height - 27), label: 'sub-FHD (upscaled)' };
  if (height <= 1080 + 48) return { scale: 1, label: 'FHD' };
  if (height >= 1440 && height <= 1440 + 48) return { scale: 3 / 4, label: 'QHD' };
  if (height >= 2160 && height <= 2160 + 48) return { scale: 1 / 2, label: 'UHD' };
  return { scale: 1, label: 'unknown' };
}
```

Run the test again — Expected: PASS.

- [ ] **Step 4: Implement the worker** — `web/src/lib/cv/captureWorker.ts`

Template loading mirrors `tests/helpers/loadTemplates.ts` but globs the generated `_templates/` and decodes with `decodeGray` (worker-safe). Per-frame mirrors locator-v2's `processFrame` minus the gem-grid logic — it ends in `detect()`.

```ts
import { initOpenCv, getCv } from './cvRuntime';
import { decodeGray } from './decodeGray';
import { TemplateStore, groupBySet } from './templates';
import { detect } from './recognizer';
import { adjustResolution } from './adjustResolution';
import type { CaptureWorkerRequest, CaptureWorkerResponse } from './workerTypes';

// vite enumerates the synced PNGs at build time (predev/prebuild runs sync-templates).
const TEMPLATE_URLS = import.meta.glob('./_templates/**/*.png', {
  eager: true, query: '?url', import: 'default',
}) as Record<string, string>;

let store: TemplateStore | null = null;
const canvas = new OffscreenCanvas(0, 0);
const ctx = canvas.getContext('2d', { willReadFrequently: true })!;

async function loadStore(): Promise<TemplateStore> {
  const entries: Array<[string, any]> = [];
  for (const [path, url] of Object.entries(TEMPLATE_URLS)) {
    const rel = path.split('/_templates/')[1]!.replace(/\.png$/, '');
    entries.push([rel, await decodeGray(await (await fetch(url)).arrayBuffer())]);
  }
  return new TemplateStore(groupBySet(entries));
}

function post(msg: CaptureWorkerResponse, transfer?: Transferable[]) {
  (self as unknown as Worker).postMessage(msg, transfer ?? []);
}

function processFrame(frame: VideoFrame): DetectionResultLike {
  const cv = getCv();
  const { scale } = adjustResolution(frame.displayHeight);
  canvas.width = Math.round(frame.displayWidth * scale);
  canvas.height = Math.round(frame.displayHeight * scale);
  ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const rgba = cv.matFromImageData(data);
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
  rgba.delete();
  try {
    return detect(gray, store!);
  } finally {
    gray.delete();
  }
}
type DetectionResultLike = ReturnType<typeof detect>;

self.onmessage = async (e: MessageEvent<CaptureWorkerRequest>) => {
  const data = e.data;
  if (data.type === 'init') {
    try {
      await initOpenCv();
      store = await loadStore();
      if (!store.has('anchor')) throw new Error('no templates loaded');
      post({ type: 'init:done' });
    } catch (err) {
      post({ type: 'init:error', error: err instanceof Error ? err.message : String(err) });
    }
    return;
  }
  if (data.type === 'frame') {
    let result: DetectionResultLike | null = null;
    try {
      if (store) result = processFrame(data.frame);
    } catch {
      result = null;
    } finally {
      data.frame.close();
    }
    post({ type: 'frame:done', result });
  }
};
```

> The worker is never imported by tests; `import.meta.glob` returns `{}` when `_templates/` is absent (it is present for `dev`/`build` via predev/prebuild), and the `store.has('anchor')` guard turns a misconfigured build into a clean `init:error`.

- [ ] **Step 5: Type-check + commit**

Run: `cd web && npm run check` — Expected: 0 errors.
Run: `cd web && npm test` — Expected: **42 passing** (41 + adjustResolution).

```bash
git add web/src/lib/cv/workerTypes.ts web/src/lib/cv/adjustResolution.ts \
  web/src/lib/cv/captureWorker.ts web/tests/cv/adjustResolution.test.ts
git commit -m "feat(web): capture worker (FHD-normalize → detect)"
```

---

### Task 5: Capture controller (`getDisplayMedia` → worker loop)

The main-thread controller that requests the shared screen, drives the worker frame loop with backpressure, and surfaces detections + status via callbacks. **Port** `lostark-arkgrid-gem-locator-v2/src/lib/cv/captureController.ts` with these exact changes; keep its proven loop/backpressure/`closing` logic.

**Files:**
- Create: `web/src/lib/cv/captureController.ts`
- Test: `web/tests/cv/captureController.test.ts` (node — pure error-classification only)

**Interfaces:**
- Consumes: `CaptureWorkerRequest`/`CaptureWorkerResponse` (T4), `DetectionResult` (`types.ts`).
- Produces: `class CaptureController` with `startCapture()`, `stopCapture()`, `isRecording()`, `toggleDrawDebug()`, a `debugCanvas` setter, and callbacks `onDetection: (r: DetectionResult | null) => void`, `onStatus: (s: 'idle'|'loading'|'recording') => void`, `onError: (e: StartCaptureErrorType) => void`. Exports `StartCaptureErrorType` + `isStartCaptureError`.

**Port adaptations (apply to the locator-v2 source):**
1. Replace the worker URL/type imports with `./captureWorker.ts` + `./workerTypes`.
2. Replace `onFrameDone(gemAttr, gems)` with **`onDetection(result: DetectionResult | null)`**; in the `frame:done` handler call `onDetection(data.result)`.
3. Add `onStatus(state)` calls wherever `this.state` transitions (idle/loading/recording), so the UI can react. Keep `onStop`/`onReady` semantics folded into `onStatus`.
4. Drop `detectionMargin` and `locale` entirely. The `frame` message is `{ type:'frame', frame, drawDebug }`.
5. Keep `requestDisplayMedia`, the `MediaStreamTrackProcessor` reader, the `loop()` with `awaitFrameCompletion` backpressure, `classifyCaptureError`, and the `closing`→`idle` shutdown verbatim.

- [ ] **Step 1: Write the error-classification test** — `web/tests/cv/captureController.test.ts` (node)

Only the pure helpers are unit-testable (the capture loop needs a real browser + user gesture; it is covered by manual QA). Export `isStartCaptureError` and a static `classifyCaptureError` (make it a module-level pure function or a static method) so this test can run in node:

```ts
import { describe, it, expect } from 'vitest';
import { isStartCaptureError, classifyCaptureError } from '../../src/lib/cv/captureController';

describe('capture error classification', () => {
  it('recognizes its own error tokens', () => {
    expect(isStartCaptureError('recording')).toBe(true);
    expect(isStartCaptureError('nope')).toBe(false);
  });
  it('maps a NotAllowedError DOMException to permission-denied', () => {
    const e = new DOMException('denied', 'NotAllowedError');
    expect(classifyCaptureError(e)).toBe('screen-permission-denied');
  });
  it('falls back to unknown', () => { expect(classifyCaptureError(new Error('x'))).toBe('unknown'); });
});
```

> `DOMException` exists in Node ≥17, so this runs in the node project. Run: `cd web && npx vitest run tests/cv/captureController.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 2: Implement `captureController.ts`** by porting the locator-v2 source with the 5 adaptations above. Factor `classifyCaptureError(err): StartCaptureErrorType` and `isStartCaptureError(err)` as **exported module-level functions** (not instance methods) so the test imports them without constructing a controller. The class calls them internally.

Run the test again — Expected: PASS.

- [ ] **Step 3: Type-check + commit**

Run: `cd web && npm run check` — Expected: 0 errors.
Run: `cd web && npm test` — Expected: **43 passing**.

```bash
git add web/src/lib/cv/captureController.ts web/tests/cv/captureController.test.ts
git commit -m "feat(web): capture controller (getDisplayMedia → worker loop)"
```

---

### Task 6: `optimize.ts` — optimize resolver, reset inference, detection gate

Pure helpers the main thread uses to turn a raw `DetectionResult` into safe engine inputs. No opencv, no DOM — fully node-testable.

**Files:**
- Create: `web/src/lib/app/optimize.ts`
- Test: `web/tests/app/optimize.test.ts` (node)

**Interfaces:**
- Consumes: `DetectionResult` (`../cv/types`), `DPS_EFFECTS`/`SUPPORT_EFFECTS` (`../engine/constants`), `THRESHOLD_GEM_INFO`/`THRESHOLD_OPTION_NAME` (`../cv/constants`).
- Produces:
  - `resolveOptimize(firstEffect: string, secondEffect: string, override?: 'dps'|'support'|'auto'): 'dps'|'support'`
  - `inferResetAvailable(turn: number, override?: 'auto'|'always'|'never'): boolean`
  - `isCompleteDetection(det: DetectionResult): boolean`

- [ ] **Step 1: Write the tests** — `web/tests/app/optimize.test.ts` (node)

```ts
import { describe, it, expect } from 'vitest';
import { resolveOptimize, inferResetAvailable, isCompleteDetection } from '../../src/lib/app/optimize';
import type { DetectionResult } from '../../src/lib/cv/types';

const complete = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9,
  willpower: 3, willpowerScore: 0.9, chaos: 2, chaosScore: 0.9,
  firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1, firstLevelScore: 0.9,
  secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1, secondLevelScore: 0.9,
  rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9, totalSteps: 7, rarityScore: 0.9,
  options: Array.from({ length: 4 }, () => ({ nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 })),
  ...over,
});

describe('resolveOptimize', () => {
  it('honors an explicit override', () => { expect(resolveOptimize('attack_power', 'boss_damage', 'support')).toBe('support'); });
  it('returns dps for DPS effects', () => { expect(resolveOptimize('attack_power', 'boss_damage', 'auto')).toBe('dps'); });
  it('returns support for support effects', () => { expect(resolveOptimize('ally_damage', 'brand_power', 'auto')).toBe('support'); });
});

describe('inferResetAvailable', () => {
  it('auto → available only on turn 1', () => {
    expect(inferResetAvailable(1)).toBe(true);
    expect(inferResetAvailable(2)).toBe(false);
  });
  it('honors always/never', () => {
    expect(inferResetAvailable(5, 'always')).toBe(true);
    expect(inferResetAvailable(1, 'never')).toBe(false);
  });
});

describe('isCompleteDetection', () => {
  it('passes a full confident detection', () => { expect(isCompleteDetection(complete())).toBe(true); });
  it('rejects unfound / missing fields / low score / wrong option count', () => {
    expect(isCompleteDetection(complete({ found: false }))).toBe(false);
    expect(isCompleteDetection(complete({ gemType: null }))).toBe(false);
    expect(isCompleteDetection(complete({ willpower: null }))).toBe(false);
    expect(isCompleteDetection(complete({ totalSteps: null }))).toBe(false);
    expect(isCompleteDetection(complete({ gemTypeScore: 0.1 }))).toBe(false);
    expect(isCompleteDetection(complete({ options: [] }))).toBe(false);
  });
});
```

Run: `cd web && npx vitest run tests/app/optimize.test.ts` — Expected: FAIL. (No `vitest.config.ts` change needed: only `tests/app/foundation.test.ts` is in `BROWSER_TESTS`, so this opencv-free file is picked up by the node project's `include: ['tests/**/*.test.ts']` automatically.)

- [ ] **Step 2: Implement `web/src/lib/app/optimize.ts`**

```ts
import type { DetectionResult } from '../cv/types';
import { DPS_EFFECTS, SUPPORT_EFFECTS } from '../engine/constants';
import { THRESHOLD_GEM_INFO, THRESHOLD_OPTION_NAME } from '../cv/constants';

export function resolveOptimize(
  firstEffect: string, secondEffect: string, override: 'dps' | 'support' | 'auto' = 'auto',
): 'dps' | 'support' {
  if (override === 'dps' || override === 'support') return override;
  const anyDps = DPS_EFFECTS.has(firstEffect) || DPS_EFFECTS.has(secondEffect);
  const anySup = SUPPORT_EFFECTS.has(firstEffect) || SUPPORT_EFFECTS.has(secondEffect);
  if (anySup && !anyDps) return 'support';
  if (anyDps) return 'dps';
  if (anySup) return 'support';
  return 'dps';
}

export function inferResetAvailable(turn: number, override: 'auto' | 'always' | 'never' = 'auto'): boolean {
  if (override === 'always') return true;
  if (override === 'never') return false;
  return turn === 1;
}

/** Gate: only confident, fully-detected cutting-screen frames feed the engine. */
export function isCompleteDetection(det: DetectionResult): boolean {
  if (!det.found) return false;
  if (!det.gemType || det.gemTypeScore < THRESHOLD_GEM_INFO) return false;
  if (det.willpower === null || det.chaos === null) return false;
  if (det.currentStep === null || det.totalSteps === null) return false;
  if (det.options.length !== 4) return false;
  for (const o of det.options) {
    if (!o.nameKey || o.nameScore < THRESHOLD_OPTION_NAME) return false;
  }
  return true;
}
```

> Verify `DPS_EFFECTS`/`SUPPORT_EFFECTS` are exported from `web/src/lib/engine/constants.ts` as `Set<string>` (they are — `index.ts` imports them). If they are arrays, wrap with `.includes` instead of `.has`.

Run the test again — Expected: PASS.

- [ ] **Step 3: Commit**

Run: `cd web && npm test` — Expected: **44 passing**.

```bash
git add web/src/lib/app/optimize.ts web/tests/app/optimize.test.ts
git commit -m "feat(web): optimize resolver, reset inference, detection gate"
```

---

### Task 7: Config store (`config.ts` pure defaults + `config.state.svelte.ts` persisted)

The persisted user configuration, plus the pure `effectiveConfig` mapping that turns stored config + a detection into an `AdvisorConfig` for `buildEngineContext`. Split so the pure parts are node-testable (the `.svelte.ts` rune store needs a browser).

**Files:**
- Create: `web/src/lib/state/config.ts` (pure: `AdvisorStoredConfig`, `DEFAULT_CONFIG`, `effectiveConfig`)
- Create: `web/src/lib/state/config.state.svelte.ts` (persisted store only)
- Test: `web/tests/state/config.test.ts` (node)

**Interfaces:**
- Consumes: `AdvisorConfig` (`../engine`), `DetectionResult` (`../cv/types`), `RARITY_FROM_TOTAL_STEPS` (`../cv/constants`), `resolveOptimize` (`../app/optimize`).
- Produces:
  - `interface AdvisorStoredConfig` — all persisted knobs.
  - `const DEFAULT_CONFIG: AdvisorStoredConfig` — Python defaults for behavioral knobs; a non-trivial editable starting goal (min will 4 / min chaos 4).
  - `function effectiveConfig(stored, det): { advisorConfig: AdvisorConfig; optimize: 'dps'|'support'; resetOverride: 'auto'|'always'|'never' }`.
  - `const config` (in the `.svelte.ts`) — `persistedState('astrogem-advisor-config', DEFAULT_CONFIG)`.

- [ ] **Step 1: Write the tests** — `web/tests/state/config.test.ts` (node)

```ts
import { describe, it, expect } from 'vitest';
import { DEFAULT_CONFIG, effectiveConfig } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';

const det = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9,
  totalSteps: 7, rarityScore: 0.9, options: [], ...over,
});

describe('DEFAULT_CONFIG', () => {
  it('uses Python defaults for behavioral knobs', () => {
    expect(DEFAULT_CONFIG.relicCoeff).toBeNull();         // fusion-default resolved in engine
    expect(DEFAULT_CONFIG.ancientCoeff).toBeNull();
    expect(DEFAULT_CONFIG.relicRerollThreshold).toBe(0);
    expect(DEFAULT_CONFIG.forceRerollNoProgress).toBe(0);
    expect(DEFAULT_CONFIG.endgameRisk).toBeNull();        // null → engine auto-gate
    expect(DEFAULT_CONFIG.ignoreSideNodeValues).toBe(false);
    expect(DEFAULT_CONFIG.extraTicket).toBeNull();        // off-but-armed
    expect(DEFAULT_CONFIG.optimizeOverride).toBe('auto');
    expect(DEFAULT_CONFIG.rarityOverride).toBe('auto');
    expect(DEFAULT_CONFIG.resetOverride).toBe('auto');
  });
});

describe('effectiveConfig', () => {
  it('derives rarity from detected totalSteps when rarity is auto', () => {
    expect(effectiveConfig(DEFAULT_CONFIG, det({ totalSteps: 7 })).advisorConfig.rarity).toBe('rare');
    expect(effectiveConfig(DEFAULT_CONFIG, det({ totalSteps: 9 })).advisorConfig.rarity).toBe('epic');
  });
  it('honors a manual rarity override', () => {
    expect(effectiveConfig({ ...DEFAULT_CONFIG, rarityOverride: 'common' }, det()).advisorConfig.rarity).toBe('common');
  });
  it('auto-resolves optimize from detected effects', () => {
    expect(effectiveConfig(DEFAULT_CONFIG, det()).optimize).toBe('dps');
  });
  it('maps null endgameRisk to undefined (engine auto-gate)', () => {
    expect(effectiveConfig(DEFAULT_CONFIG, det()).advisorConfig.endgameRisk).toBeUndefined();
  });
});
```

Run: `cd web && npx vitest run tests/state/config.test.ts` — Expected: FAIL.

- [ ] **Step 2: Implement `web/src/lib/state/config.ts`**

```ts
import type { AdvisorConfig } from '../engine';
import type { DetectionResult } from '../cv/types';
import { RARITY_FROM_TOTAL_STEPS } from '../cv/constants';
import { resolveOptimize } from '../app/optimize';

export interface AdvisorStoredConfig {
  // goal (editable starting suggestion; not a Python default)
  minWill?: number;
  minChaos?: number;
  minFirst?: number;
  minSecond?: number;
  minSideCoeff?: number;
  // tier valuation (null → engine resolves the fusion default)
  relicCoeff: number | null;
  ancientCoeff: number | null;
  // advanced behavioral knobs (Python defaults)
  relicRerollThreshold: number;
  forceRerollNoProgress: number;
  endgameRisk: number | null;          // null → auto-gate (undefined to engine)
  ignoreSideNodeValues: boolean;
  extraTicket: boolean | null;         // tri-state: true on / false off / null armed
  // overrides
  optimizeOverride: 'dps' | 'support' | 'auto';
  rarityOverride: 'common' | 'rare' | 'epic' | 'auto';
  resetOverride: 'auto' | 'always' | 'never';
}

export const DEFAULT_CONFIG: AdvisorStoredConfig = {
  minWill: 4, minChaos: 4,
  relicCoeff: null, ancientCoeff: null,
  relicRerollThreshold: 0, forceRerollNoProgress: 0, endgameRisk: null,
  ignoreSideNodeValues: false, extraTicket: null,
  optimizeOverride: 'auto', rarityOverride: 'auto', resetOverride: 'auto',
};

export function effectiveConfig(
  stored: AdvisorStoredConfig, det: DetectionResult,
): { advisorConfig: AdvisorConfig; optimize: 'dps' | 'support'; resetOverride: 'auto' | 'always' | 'never' } {
  const rarity = stored.rarityOverride !== 'auto'
    ? stored.rarityOverride
    : (RARITY_FROM_TOTAL_STEPS[det.totalSteps ?? 7] ?? 'rare') as 'common' | 'rare' | 'epic';
  const optimize = resolveOptimize(det.firstEffect ?? '', det.secondEffect ?? '', stored.optimizeOverride);
  const advisorConfig: AdvisorConfig = {
    rarity,
    minWill: stored.minWill,
    minChaos: stored.minChaos,
    minFirst: stored.minFirst,
    minSecond: stored.minSecond,
    minSideCoeff: stored.minSideCoeff,
    relicCoeff: stored.relicCoeff,
    ancientCoeff: stored.ancientCoeff,
    relicRerollThreshold: stored.relicRerollThreshold,
    forceRerollNoProgress: stored.forceRerollNoProgress,
    endgameRisk: stored.endgameRisk ?? undefined,
    ignoreSideNodeValues: stored.ignoreSideNodeValues,
    extraTicket: stored.extraTicket,
    optimize,
  };
  return { advisorConfig, optimize, resetOverride: stored.resetOverride };
}
```

Run the test again — Expected: PASS.

- [ ] **Step 3: Implement the persisted store** — `web/src/lib/state/config.state.svelte.ts`

```ts
import { persistedState } from 'svelte-persisted-state';
import { DEFAULT_CONFIG, type AdvisorStoredConfig } from './config';

// Persisted to localStorage; structuredClone so the default object isn't shared/mutated.
export const config = persistedState<AdvisorStoredConfig>('astrogem-advisor-config', structuredClone(DEFAULT_CONFIG));
```

- [ ] **Step 4: Commit**

Run: `cd web && npm test` — Expected: **45 passing**. Run: `cd web && npm run check` — 0 errors.

```bash
git add web/src/lib/state/config.ts web/src/lib/state/config.state.svelte.ts web/tests/state/config.test.ts
git commit -m "feat(web): persisted config store + effectiveConfig mapping"
```

---

### Task 8: `computeAdvice` orchestrator + `advisor.state`

The glue that turns a `DetectionResult` + stored config into an `AdvisorOutput`, with the per-gem-type/config `EngineContext` cache, plus the runtime rune state the UI binds to.

**Files:**
- Create: `web/src/lib/app/computeAdvice.ts`
- Create: `web/src/lib/state/advisor.state.svelte.ts`
- Test: `web/tests/app/computeAdvice.test.ts` (node)

**Interfaces:**
- Consumes: `isCompleteDetection`/`inferResetAvailable` (`./optimize`), `effectiveConfig`/`AdvisorStoredConfig` (`../state/config`), `detectionToEngineInputs` (`../cv/adapter`), `buildEngineContext`/`advise`/`EngineContext`/`AdvisorOutput` (`../engine`), `DetectionResult` (`../cv/types`).
- Produces:
  - `function computeAdvice(det, stored): { ready: boolean; output: AdvisorOutput | null }` (gated; caches the context).
  - `function resetAdviceCache(): void` (test/teardown hook).
  - `class AdvisorState` rune store + `const advisor` (status, detection, output, waiting, error).

- [ ] **Step 1: Write the test** — `web/tests/app/computeAdvice.test.ts` (node)

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { computeAdvice, resetAdviceCache } from '../../src/lib/app/computeAdvice';
import { DEFAULT_CONFIG } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';
import { ActionKind } from '../../src/lib/engine';

const complete: DetectionResult = {
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9,
  totalSteps: 7, rarityScore: 0.9,
  options: [
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'chaos', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+2', deltaScore: 0.9 },
    { nameKey: 'view', nameScore: 0.9, deltaKey: 'reroll+1', deltaScore: 0.9 },
  ],
};

describe('computeAdvice', () => {
  beforeEach(() => resetAdviceCache());

  it('gates incomplete detections', () => {
    expect(computeAdvice({ ...complete, found: false }, DEFAULT_CONFIG).ready).toBe(false);
  });

  it('produces a coherent recommendation for a complete detection', () => {
    const { ready, output } = computeAdvice(complete, DEFAULT_CONFIG);
    expect(ready).toBe(true);
    expect(output).not.toBeNull();
    expect(Object.values(ActionKind)).toContain(output!.action);
    for (const p of [output!.pGoal, output!.pRelic, output!.pAncient]) {
      expect(p).toBeGreaterThanOrEqual(0); expect(p).toBeLessThanOrEqual(1);
    }
    expect(output!.perOffer).toHaveLength(4);
  });

  it('is deterministic across repeated calls (cache reuse)', () => {
    const a = computeAdvice(complete, DEFAULT_CONFIG).output!;
    const b = computeAdvice(complete, DEFAULT_CONFIG).output!;
    expect(b.action).toBe(a.action);
    expect(b.pGoal).toBeCloseTo(a.pGoal, 12);
  });
});
```

> This test runs in **node** — `computeAdvice` imports `adapter.ts` which (after Task 2) is opencv-free. If it still resolves opencv, Task 2 was incomplete: fix the split, don't move this test to the browser. Run: `cd web && npx vitest run tests/app/computeAdvice.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 2: Implement `web/src/lib/app/computeAdvice.ts`**

```ts
import type { DetectionResult } from '../cv/types';
import { detectionToEngineInputs } from '../cv/adapter';
import { buildEngineContext, advise, type EngineContext, type AdvisorOutput } from '../engine';
import { isCompleteDetection, inferResetAvailable } from './optimize';
import { effectiveConfig, type AdvisorStoredConfig } from '../state/config';

let cache: { key: string; ctx: EngineContext } | null = null;
export function resetAdviceCache(): void { cache = null; }

export function computeAdvice(
  det: DetectionResult, stored: AdvisorStoredConfig,
): { ready: boolean; output: AdvisorOutput | null } {
  if (!isCompleteDetection(det)) return { ready: false, output: null };

  const eff = effectiveConfig(stored, det);
  const turn = (det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1;
  const resetAvailable = inferResetAvailable(turn, eff.resetOverride);

  const inputs = detectionToEngineInputs(det, {
    optimize: eff.optimize,
    extraTicket: stored.extraTicket === true,
    resetAvailable,
  });

  const key = JSON.stringify([
    inputs.gem.gemType, inputs.gem.firstEffect, inputs.gem.secondEffect, eff.advisorConfig,
  ]);
  if (!cache || cache.key !== key) {
    cache = { key, ctx: buildEngineContext(inputs.gem, eff.advisorConfig) };
  }

  const output = advise(cache.ctx, {
    state: inputs.state, offers: inputs.offers, turn: inputs.turn,
    turnsLeft: inputs.turnsLeft, rerolls: inputs.rerolls, resetAvailable: inputs.resetAvailable,
  });
  return { ready: true, output };
}
```

Run the test again — Expected: PASS.

- [ ] **Step 3: Implement `web/src/lib/state/advisor.state.svelte.ts`**

```ts
import type { DetectionResult } from '../cv/types';
import type { AdvisorOutput } from '../engine';

export type CaptureStatus = 'idle' | 'loading' | 'recording';

class AdvisorState {
  status = $state<CaptureStatus>('idle');
  detection = $state<DetectionResult | null>(null);
  output = $state<AdvisorOutput | null>(null);
  waiting = $state(true);            // last detection failed the completeness gate
  error = $state<string | null>(null);
}

export const advisor = new AdvisorState();
```

- [ ] **Step 4: Commit**

Run: `cd web && npm test` — Expected: **46 passing**. Run: `cd web && npm run check` — 0 errors.

```bash
git add web/src/lib/app/computeAdvice.ts web/src/lib/state/advisor.state.svelte.ts \
  web/tests/app/computeAdvice.test.ts
git commit -m "feat(web): computeAdvice orchestrator + advisor runtime state"
```

---

### Task 9: `ConfigPanel.svelte` (core + advanced)

The left column: core knobs always visible, advanced behind an expander, two-way bound to the persisted store.

**Files:**
- Create: `web/src/components/ConfigPanel.svelte`
- Test: `web/tests/components/configPanel.test.ts` (browser project)

**Interfaces:**
- Consumes: `config` (`../lib/state/config.state.svelte`).
- Produces: a self-contained panel; no props.

- [ ] **Step 1: Add the components test glob to the browser project**

In `web/vitest.config.ts`, add `'tests/components/**/*.test.ts'` to `BROWSER_TESTS` (Svelte render needs a DOM).

- [ ] **Step 2: Write the render smoke** — `web/tests/components/configPanel.test.ts`

```ts
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
```

Run: `cd web && npx vitest run tests/components/configPanel.test.ts` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement `ConfigPanel.svelte`**

Bind every control to `config.current.<field>`. Core: goal mins, rarity select (incl. `auto`), relic/ancient coeff (empty = fusion default → `null`). Advanced (`<details>`): endgame risk, relic-reroll threshold, force-reroll-no-progress, extra-ticket tri-state, optimize override, ignore-side-node-values, reset override.

```svelte
<script lang="ts">
  import { config } from '../lib/state/config.state.svelte';
  const c = config;   // c.current is the reactive, bindable store value
</script>

<section class="config">
  <h2>Goal</h2>
  <label>Min will <input type="number" min="0" max="5" bind:value={c.current.minWill} /></label>
  <label>Min chaos <input type="number" min="0" max="5" bind:value={c.current.minChaos} /></label>
  <label>Min 1st node <input type="number" min="0" max="5" bind:value={c.current.minFirst} /></label>
  <label>Min 2nd node <input type="number" min="0" max="5" bind:value={c.current.minSecond} /></label>
  <label>Min side coeff <input type="number" min="0" step="any" bind:value={c.current.minSideCoeff} /></label>

  <h2>Grade</h2>
  <label>Rarity
    <select bind:value={c.current.rarityOverride}>
      <option value="auto">Auto (detected)</option>
      <option value="common">Common (5)</option>
      <option value="rare">Rare (7)</option>
      <option value="epic">Epic (9)</option>
    </select>
  </label>
  <label>Relic coeff <input type="number" step="any" placeholder="fusion default"
    value={c.current.relicCoeff ?? ''} oninput={(e) => c.current.relicCoeff = e.currentTarget.value === '' ? null : +e.currentTarget.value} /></label>
  <label>Ancient coeff <input type="number" step="any" placeholder="fusion default"
    value={c.current.ancientCoeff ?? ''} oninput={(e) => c.current.ancientCoeff = e.currentTarget.value === '' ? null : +e.currentTarget.value} /></label>

  <details class="advanced">
    <summary>Advanced</summary>
    <label>Endgame risk <input type="number" step="any" placeholder="auto-gate"
      value={c.current.endgameRisk ?? ''} oninput={(e) => c.current.endgameRisk = e.currentTarget.value === '' ? null : +e.currentTarget.value} /></label>
    <label>Relic reroll threshold <input type="number" min="0" max="1" step="any" bind:value={c.current.relicRerollThreshold} /></label>
    <label>Force reroll no-progress <input type="number" min="0" step="any" bind:value={c.current.forceRerollNoProgress} /></label>
    <label>Extra ticket
      <select value={String(c.current.extraTicket)} onchange={(e) => {
        const v = e.currentTarget.value; c.current.extraTicket = v === 'true' ? true : v === 'false' ? false : null;
      }}>
        <option value="null">Armed (off, enable on signal)</option>
        <option value="true">On</option>
        <option value="false">Off (hard)</option>
      </select>
    </label>
    <label>Optimize
      <select bind:value={c.current.optimizeOverride}>
        <option value="auto">Auto (from effects)</option>
        <option value="dps">DPS</option>
        <option value="support">Support</option>
      </select>
    </label>
    <label><input type="checkbox" bind:checked={c.current.ignoreSideNodeValues} /> Ignore side-node values</label>
    <label>Reset available
      <select bind:value={c.current.resetOverride}>
        <option value="auto">Auto (turn 1)</option>
        <option value="always">Always</option>
        <option value="never">Never</option>
      </select>
    </label>
  </details>
</section>
```

> The smoke asserts `getByLabelText(/min will/i)`; the `<label>Min will <input/></label>` association satisfies testing-library's label query. If it does not in your Svelte version, switch to explicit `for`/`id`.

Run the test again — Expected: PASS.

- [ ] **Step 4: Commit**

Run: `cd web && npm test` — Expected: **47 passing**. Run: `cd web && npm run check` — 0 errors.

```bash
git add web/src/components/ConfigPanel.svelte web/tests/components/configPanel.test.ts web/vitest.config.ts
git commit -m "feat(web): ConfigPanel (core + advanced)"
```

---

### Task 10: Advisor display components

The read-only display: recommended action + metrics (`AdvisorPanel`), the 4 offers (`OfferTable`), the detected-state readout (`DetectedState`). All take props (no store coupling) so they render in isolation under test.

**Files:**
- Create: `web/src/components/AdvisorPanel.svelte`, `web/src/components/OfferTable.svelte`, `web/src/components/DetectedState.svelte`
- Test: `web/tests/components/advisorDisplay.test.ts` (browser project)

**Interfaces:**
- `AdvisorPanel` props: `{ output: AdvisorOutput | null; waiting: boolean }`.
- `OfferTable` props: `{ perOffer: AdvisorOutput['perOffer'] }`.
- `DetectedState` props: `{ detection: DetectionResult | null }`.

- [ ] **Step 1: Write the render smoke** — `web/tests/components/advisorDisplay.test.ts`

```ts
import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import AdvisorPanel from '../../src/components/AdvisorPanel.svelte';
import OfferTable from '../../src/components/OfferTable.svelte';
import type { AdvisorOutput } from '../../src/lib/engine';

const output: AdvisorOutput = {
  action: 'REROLL' as any, branch: 'dp_reroll', reason: 'reroll for value',
  pGoal: 0.62, pRelic: 0.41, pAncient: 0.12, eValue: 1180,
  perOffer: [
    { key: 'will+1', pGoalAfter: 0.5, eValueAfter: 1100 },
    { key: 'chaos+1', pGoalAfter: 0.7, eValueAfter: 1150 },
    { key: 'will+2', pGoalAfter: 0.6, eValueAfter: 1170 },
    { key: 'reroll+1', pGoalAfter: 0.55, eValueAfter: 1120 },
  ],
};

describe('advisor display', () => {
  it('AdvisorPanel shows action, reason, and metrics', () => {
    render(AdvisorPanel, { props: { output, waiting: false } });
    expect(screen.getByText('REROLL')).toBeTruthy();
    expect(screen.getByText(/62\.0%/)).toBeTruthy();
  });
  it('AdvisorPanel shows a waiting state when gated', () => {
    render(AdvisorPanel, { props: { output: null, waiting: true } });
    expect(screen.getByText(/waiting for cutting screen/i)).toBeTruthy();
  });
  it('OfferTable renders one row per offer', () => {
    render(OfferTable, { props: { perOffer: output.perOffer } });
    expect(screen.getAllByRole('row')).toHaveLength(5); // header + 4
  });
});
```

Run: `cd web && npx vitest run tests/components/advisorDisplay.test.ts` — Expected: FAIL.

- [ ] **Step 2: Implement `AdvisorPanel.svelte`**

```svelte
<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { output, waiting }: { output: AdvisorOutput | null; waiting: boolean } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
</script>

{#if waiting || !output}
  <div class="advisor waiting"><p>Waiting for cutting screen…</p></div>
{:else}
  <div class="advisor">
    <div class="action action-{output.action}">{output.action}</div>
    <p class="reason">{output.reason}</p>
    <dl class="metrics">
      <div><dt>P(goal)</dt><dd>{pct(output.pGoal)}</dd></div>
      <div><dt>P(relic+)</dt><dd>{pct(output.pRelic)}</dd></div>
      <div><dt>P(ancient)</dt><dd>{pct(output.pAncient)}</dd></div>
      <div><dt>E[coeff]</dt><dd>{output.eValue.toFixed(1)}</dd></div>
    </dl>
  </div>
{/if}
```

- [ ] **Step 3: Implement `OfferTable.svelte`** (highlight the highest-P(goal)-after offer)

```svelte
<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { perOffer }: { perOffer: AdvisorOutput['perOffer'] } = $props();
  const favored = $derived(
    perOffer.length === 0 ? -1
      : perOffer.reduce((best, o, i, a) => (o.pGoalAfter > a[best].pGoalAfter ? i : best), 0),
  );
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
</script>

<table class="offers">
  <thead><tr><th>Offer</th><th>P(goal) after</th><th>E[coeff] after</th></tr></thead>
  <tbody>
    {#each perOffer as o, i}
      <tr class:favored={i === favored}>
        <td>{o.key}</td><td>{pct(o.pGoalAfter)}</td><td>{o.eValueAfter.toFixed(1)}</td>
      </tr>
    {/each}
  </tbody>
</table>
```

- [ ] **Step 4: Implement `DetectedState.svelte`**

```svelte
<script lang="ts">
  import type { DetectionResult } from '../lib/cv/types';
  let { detection }: { detection: DetectionResult | null } = $props();
</script>

{#if detection}
  <dl class="detected">
    <div><dt>Gem</dt><dd>{detection.gemType ?? '—'} <span class="score">{detection.gemTypeScore.toFixed(2)}</span></dd></div>
    <div><dt>Will</dt><dd>{detection.willpower ?? '—'}</dd></div>
    <div><dt>Chaos</dt><dd>{detection.chaos ?? '—'}</dd></div>
    <div><dt>1st</dt><dd>{detection.firstEffect ?? '—'} Lv{detection.firstLevel ?? '—'}</dd></div>
    <div><dt>2nd</dt><dd>{detection.secondEffect ?? '—'} Lv{detection.secondLevel ?? '—'}</dd></div>
    <div><dt>Rerolls</dt><dd>{detection.rerolls ?? '—'}</dd></div>
    <div><dt>Step</dt><dd>{detection.currentStep ?? '—'}/{detection.totalSteps ?? '—'}</dd></div>
  </dl>
{/if}
```

Run the test again — Expected: PASS.

- [ ] **Step 5: Commit**

Run: `cd web && npm test` — Expected: **49 passing** (47 + 2 new in the file → count is by `it`s; expect +3 ⇒ 50; the gate is "all green", exact count is informational). Run: `cd web && npm run check` — 0 errors.

```bash
git add web/src/components/AdvisorPanel.svelte web/src/components/OfferTable.svelte \
  web/src/components/DetectedState.svelte web/tests/components/advisorDisplay.test.ts
git commit -m "feat(web): advisor display components (action, metrics, offers, detected)"
```

---

### Task 11: App assembly + capture wiring (`CaptureControls` + `App`)

Wire the capture controller to `computeAdvice` and the advisor store, and assemble the two-column shell.

**Files:**
- Create: `web/src/components/CaptureControls.svelte`
- Modify: `web/src/App.svelte` (replace the T1 stub with the full two-column layout)
- Modify: `web/tests/app/foundation.test.ts` (update to the assembled App)
- Append styles to `web/src/app.css` (action/metrics/offers/detected presentation)

**Interfaces:**
- Consumes: `CaptureController` (`../lib/cv/captureController`), `computeAdvice` (`../lib/app/computeAdvice`), `config` + `advisor` stores, all T9/T10 components.
- Produces: the running app.

- [ ] **Step 1: Implement `CaptureControls.svelte`** (the controller↔engine↔store wiring lives here)

```svelte
<script lang="ts">
  import { CaptureController } from '../lib/cv/captureController';
  import { computeAdvice } from '../lib/app/computeAdvice';
  import { config } from '../lib/state/config.state.svelte';
  import { advisor } from '../lib/state/advisor.state.svelte';

  let controller: CaptureController | null = null;
  let debugCanvas = $state<HTMLCanvasElement | null>(null);
  let drawDebug = $state(false);

  function ensure(): CaptureController {
    if (controller) return controller;
    const c = new CaptureController(debugCanvas);
    c.onStatus = (s) => { advisor.status = s; };
    c.onError = (e) => { advisor.error = e; advisor.status = 'idle'; };
    c.onDetection = (det) => {
      advisor.detection = det;
      advisor.error = null;
      if (!det) { advisor.waiting = true; return; }
      const { ready, output } = computeAdvice(det, config.current);
      advisor.waiting = !ready;
      if (ready) advisor.output = output;
    };
    controller = c;
    return c;
  }
  async function start() { advisor.error = null; await ensure().startCapture(); }
  function stop() { controller?.stopCapture(); }
  function toggleDebug() { drawDebug = ensure().toggleDrawDebug(); }
</script>

<div class="capture-controls">
  {#if advisor.status === 'recording'}
    <button onclick={stop}>Stop</button>
  {:else}
    <button onclick={start} disabled={advisor.status === 'loading'}>Share screen</button>
  {/if}
  <span class="status">Status: {advisor.status}</span>
  <label><input type="checkbox" checked={drawDebug} onchange={toggleDebug} /> debug</label>
  {#if advisor.error}<span class="error">{advisor.error}</span>{/if}
  <canvas class="debug" bind:this={debugCanvas} hidden={!drawDebug}></canvas>
</div>
```

> `CaptureController`'s constructor takes `(debugCanvas?: HTMLCanvasElement | null)` (per the T5 port). `debugCanvas` is bound after mount and read on first `ensure()` (lazy, on first user action), so it is non-null by then.

- [ ] **Step 2: Replace `App.svelte`** with the two-column assembly

```svelte
<script lang="ts">
  import ConfigPanel from './components/ConfigPanel.svelte';
  import CaptureControls from './components/CaptureControls.svelte';
  import AdvisorPanel from './components/AdvisorPanel.svelte';
  import OfferTable from './components/OfferTable.svelte';
  import DetectedState from './components/DetectedState.svelte';
  import { advisor } from './lib/state/advisor.state.svelte';
</script>

<main class="app-shell">
  <aside class="app-config">
    <h1>Astrogem Advisor</h1>
    <ConfigPanel />
  </aside>
  <section class="app-main">
    <CaptureControls />
    <AdvisorPanel output={advisor.output} waiting={advisor.waiting} />
    {#if advisor.output}<OfferTable perOffer={advisor.output.perOffer} />{/if}
    <DetectedState detection={advisor.detection} />
  </section>
</main>
```

- [ ] **Step 3: Update the foundation smoke** — `web/tests/app/foundation.test.ts`

```ts
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
```

- [ ] **Step 4: Append presentation styles to `web/src/app.css`** — classes used above (`.capture-controls`, `.action`, `.metrics`, `.offers`, `.offers .favored`, `.detected`, `.advisor.waiting`, `canvas.debug { max-width: 100%; }`). Keep it lean; correctness, not polish.

- [ ] **Step 5: Run gates**

Run: `cd web && npm run check` — Expected: 0 errors (browser-purity gate via `tsconfig.app.json`).
Run: `cd web && npm test` — Expected: all green (the updated foundation smoke + everything prior).
Run: `cd web && npm run build` — Expected: builds; the worker chunk emits; `dist/` produced.

Optional manual QA (not a gate): `cd web && npm run dev`, open the app, "Share screen", select the Lost Ark window on the cutting screen, confirm the advice updates live.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/CaptureControls.svelte web/src/App.svelte \
  web/tests/app/foundation.test.ts web/src/app.css
git commit -m "feat(web): assemble two-column app + wire capture → advise"
```

---

### Task 12: GitHub Actions Pages deploy + docs

Publish `web/dist` to GitHub Pages on push to `master`, path-filtered to the app + templates + workflow.

**Files:**
- Create: `.github/workflows/deploy-web.yml`
- Modify: `web/README.md` (run/build/deploy instructions)

**Interfaces:** none (CI + docs).

- [ ] **Step 1: Write the workflow** — `.github/workflows/deploy-web.yml`

```yaml
name: Deploy web advisor

on:
  push:
    branches: [master]
    paths:
      - 'web/**'
      - 'arkgrid/vision/templates/**'
      - '.github/workflows/deploy-web.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npm run check
      - run: npm run build
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: web/dist        # repo-root-relative (working-directory affects only `run` steps)

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

> `npm run build` fires `prebuild` → `sync:templates`, so the CI runner gets `_templates/` before vite bundles. The base path `/AstrogemCutter/` is hard-set in `vite.config.ts` (no `configure-pages` base injection needed). Pages must be set to "GitHub Actions" as the source in the repo settings (one-time, manual — note it in the README).

- [ ] **Step 2: Verify the build output base path** (manual gate, not a vitest test)

Run: `cd web && npm run build` then confirm `dist/index.html` references hashed assets under `/AstrogemCutter/`:

Run: `grep -o '/AstrogemCutter/[^"]*' web/dist/index.html | head`
Expected: at least one `/AstrogemCutter/assets/...` path. If paths are root-relative (`/assets/...`), the vite `base` is wrong — fix `vite.config.ts`.

- [ ] **Step 3: Update `web/README.md`**

Document: `npm install`; `npm run dev` (local advisor); `npm test`; `npm run build`; deployment (push to `master` under the path filter, or `workflow_dispatch`; Pages source = GitHub Actions; live at `https://darealfreak.github.io/AstrogemCutter/`). Note the read-only nature (it advises; the player clicks).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy-web.yml web/README.md
git commit -m "ci(web): GitHub Pages deploy workflow (path-filtered to web/ + templates)"
```

---

## Done criteria

- `cd web && npm test` green (node + headless-Chromium browser projects), 0 leaked processes.
- `cd web && npm run check` clean (svelte-check on `tsconfig.app.json` — `src/` browser-pure).
- `cd web && npm run build` produces `web/dist/` with assets under `/AstrogemCutter/`.
- `npm run dev` runs the advisor; sharing a Lost Ark cutting screen shows live action + P(goal)/P(relic+)/P(ancient)/E[coeff] + the 4 offers (manual QA).
- The deploy workflow exists and is path-filtered; the site publishes on merge to `master`.
- Branch `feat/web-engine-port` holds Plans 1+2+3 and is now in a workable state, ready to merge when you choose.

## Notes for the final whole-branch review

- Confirm Task 2's split left `recognizer.ts` behavior identical (re-exports cover every prior import site) and that no `src/lib/cv/*` except `recognizer.ts`/`captureWorker.ts`/`decodeGray.ts`/`matcher.ts`/`cvRuntime.ts` imports opencv.
- Confirm `src/` is free of Node globals (the Plan-1 browser-purity item, now enforced by `tsconfig.app.json`).
- The capture loop (`getDisplayMedia` + worker) is verified by manual QA, not automated tests — the recognizer pipeline it drives is covered by Plan 2's `detect → adapt → advise` e2e. Flag if deeper automated capture coverage is wanted.
- Triage the Plan-2 deferred minors that remain relevant (e2e rarity `?? 'rare'` now lives in `effectiveConfig`; adapter `?? 0`/`?? ''` fallbacks are now gated by `isCompleteDetection`).
