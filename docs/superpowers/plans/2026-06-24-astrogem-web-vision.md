# Astrogem Web Advisor — Plan 2: Vision Recognizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the Python `arkgrid/vision/` recognizer to OpenCV.js under `web/src/lib/cv/`, plus a `DetectionResult → engine inputs` adapter, validated by Python golden vectors over the 60 `examples/` screenshots and capped by an end-to-end `screenshot → detect → adapt → advise()` test.

**Architecture:** A headless-testable TypeScript vision layer. `@techstark/opencv-js` (WASM) runs in vitest/Node; example JPEGs and template PNGs decode to `cv.Mat`s. The recognizer is a faithful port of `template_recognizer.py`/`matcher.py`/`constants.py`; the adapter ports `automation.py`'s per-frame builder. Python stays the source of truth — `tools/export_vision_golden.py` dumps golden `DetectionResult`s and the TS recognizer must reproduce the detected values/keys exactly. Stacks on Plan 1's engine (`web/src/lib/engine/`).

**Tech Stack:** TypeScript, Vite, Vitest, `@techstark/opencv-js`, Node ≥20. Python 3 + `opencv-python` for the exporter.

## The port model (read before starting)

Same as Plan 1. This is a **faithful port of existing, working code**:

- The **source of truth** for each TS unit is the named Python file + line range. Transcribe the algorithm — preserve structure, names, arithmetic. Do not redesign.
- The **binding contract** is the test: unit tests *plus* the Python golden-vector parity over `examples/`.
- Plan code blocks give the **complete TS public interface** (signatures/types) and **complete test code**. Implementation steps point at the exact Python source; they do not re-paste large bodies the Python already defines.

## Global Constraints

- **Source of truth:** `arkgrid/vision/{constants,matcher,template_recognizer}.py` and the adapter pieces in `arkgrid/automation.py` (`_analyze_frame` state/turn build, `_detected_to_options`, `_parse_view_delta`). Never modify `arkgrid/*.py`.
- **Validation = Python golden vectors:** assert the TS recognizer reproduces the detected **values/keys** for every `examples/` image **exactly** (`gemType`, `willpower`, `chaos`, `first/secondEffect`, `first/secondLevel`, `rerolls`, `currentStep`, `totalSteps`, each option `nameKey`/`deltaKey`). Match **scores are recorded, NOT asserted**. A value/key mismatch is a finding to investigate — never loosen to a score tolerance, never edit a fixture to match the port.
- **Examples are 1920×1080 (FHD):** the `REF_WIDTH×REF_HEIGHT` resize is a no-op for them. (Keep the resize in `detect()` for faithfulness/non-FHD captures, but it never fires on the test set.)
- **Reference resolution:** `REF_WIDTH=1920`, `REF_HEIGHT=1080`. ROI offsets are anchor-relative `(dx,dy,w,h)`; anchor is found in `ANCHOR_SEARCH_ROI=(650,20,700,80)` with `THRESHOLD_ANCHOR=0.70`.
- **Matching:** `cv.matchTemplate(crop, tmpl, cv.TM_CCOEFF_NORMED)` then `cv.minMaxLoc`; best score over a template set wins; skip a template larger than the crop. `_match` with `strip_variants` collapses `additional_damage_01` → `additional_damage`.
- **Adapter conventions (verbatim from `automation.py`):** `turnsLeft = det.currentStep`; `turnsTotal = det.totalSteps`; `turn = turnsTotal − turnsLeft + 1`. Offer keys built per `_detected_to_options` (`will`/`chaos`/`first`/`second` → `` `${kind}${delta:+d}` ``; cost → `deltaKey`; effect_changed → `change_${slot}_effect`; maintained → `maintain`; else `nameKey`). `Option(key, weight=1.0, kind, delta)`.
- **Test runtime = vitest BROWSER mode** (`@vitest/browser` + `playwright`, Chromium, headless). DECIDED after the Task 1 spike showed opencv.js 4.12's WASM init crashes/hangs under vitest's Node/vite-node loader on Node v26.3.0 (it works only in plain Node). opencv.js is browser-native, so the browser is the correct runtime and it aligns with Plan 3's browser worker. Tests run IN Chromium.
- **opencv.js init:** `initOpenCv()`/`getCv()` singleton (import `@techstark/opencv-js`; in the browser the module resolves to a `cv` handle, init via `onRuntimeInitialized` or the module Promise). Tests `await initOpenCv()` in `beforeAll`.
- **Decoder = browser-native (no jpeg-js/pngjs).** `cv.imdecode` is absent from the @techstark build; in the browser, decode images by loading them onto an `ImageBitmap`/`<canvas>` and reading them with `cv.imread(canvas)` (or `cv.matFromImageData`) → a BGR/RGBA Mat → `cv.cvtColor` to gray. Chromium's decoder may differ slightly from cv2's libjpeg; parity asserts detected values/keys (not scores), so small pixel drift is tolerated and only a value/key flip is a finding.
- **Asset loading:** `examples/` JPEGs and `arkgrid/vision/templates/` PNGs are loaded as **vite-served assets** — enumerate via `import.meta.glob('<relpath>/**/*.{jpg,png}', { eager: true, query: '?url', import: 'default' })` and `fetch` each URL → `createImageBitmap` → canvas → Mat. The golden fixture `detection.json` is loaded via a normal JSON `import`. Configure vite so `examples/` and `arkgrid/vision/templates/` are reachable (e.g. `server.fs.allow` includes the repo root). Do NOT copy images into `web/` and do NOT use `node:fs` in test code (it runs in the browser).
- **TemplateStore takes an injected loader** (a `Map<string, Mat>` of already-decoded gray templates, or an async loader the test supplies) rather than reading the filesystem itself — so the same class is reused by Plan 3's browser/atlas loader. The test builds the template map from the `import.meta.glob` URLs.
- **Do not modify Plan 1's engine** (`web/src/lib/engine/`); the adapter/e2e only import it.
- **Out of scope (Plan 3):** `detect_finish`, live `getDisplayMedia` capture, Web Worker, anchor-ROI caching, sprite atlas, UI, deploy.

## File structure

```
web/
  src/lib/cv/
    cvRuntime.ts     # initOpenCv()/getCv() — opencv.js singleton (Node + browser)
    constants.ts     # <- arkgrid/vision/constants.py (ROIs, thresholds, maps)
    matcher.ts       # <- arkgrid/vision/matcher.py (findTemplate/findBestMatch)
    templates.ts     # <- template_recognizer._load/TemplateStore (PNG -> gray Mat)
    recognizer.ts    # <- template_recognizer.py (detect + parse helpers)
    adapter.ts       # <- automation.py builder (DetectionResult -> engine inputs)
  vitest.workspace.ts          # two projects: node (pure logic) + browser (opencv)
  tests/
    helpers/loadImage.ts       # browser image URL -> gray cv.Mat (test-only)
    cv/spike.test.ts           # Task 1 browser feasibility spike
    vision/parse.test.ts       # parse-helper unit/golden tests
    vision/recognizer.test.ts  # detect() golden parity over examples/
    vision/adapter.test.ts     # adapter unit tests
    vision/e2e.test.ts         # screenshot -> detect -> adapt -> advise
    fixtures/detection.json    # golden DetectionResults (from Python)
tools/
  export_vision_golden.py      # NEW: Python detection golden exporter
```

---

### Task 1: Browser-mode spike — vitest + Playwright + opencv.js

**Why this shape:** opencv.js 4.12 will not initialize under vitest's Node/vite-node loader in this environment (Node v26.3.0) — it crashes/hangs in every pool config, working only in plain Node. opencv.js is browser-native, so we run the opencv-dependent tests in a real headless Chromium via `@vitest/browser` + `playwright`. But Plan 1's engine tests use `node:fs` and must stay in Node — so the config is **two projects**: a `node` project (engine + pure-logic vision tests) and a `browser` project (opencv-dependent vision tests). This spike proves the browser project runs end-to-end in this env.

**Files:**
- Modify: `web/package.json` (add `@vitest/browser`, `playwright`; remove `jpeg-js`/`pngjs` if present)
- Rewrite: `web/vitest.config.ts` → **`web/vitest.workspace.ts`** (two projects: node + browser)
- Keep/verify: `web/src/lib/cv/cvRuntime.ts` (browser-compatible init)
- Replace `web/tests/helpers/decodeImage.ts` with: `web/tests/helpers/loadImage.ts` (browser image → gray Mat)
- Rewrite: `web/tests/cv/spike.test.ts` (browser spike)

**Interfaces:**
- Produces:
  ```ts
  // cvRuntime.ts (unchanged from the first attempt if it still works in-browser)
  export async function initOpenCv(): Promise<void>;
  export function getCv(): any;
  // loadImage.ts (browser test util)
  export async function loadGrayMat(url: string): Promise<any>;  // fetch -> ImageBitmap -> canvas -> cv.imread -> RGBA2GRAY gray Mat
  ```

- [ ] **Step 1: Install browser-mode deps + Chromium**

```bash
cd web && npm install -D @vitest/browser playwright && npx playwright install chromium && (npm uninstall jpeg-js pngjs 2>/dev/null || true)
```
If `npx playwright install chromium` cannot download the browser (network), report BLOCKED with the exact error — browser mode needs it.

- [ ] **Step 2: Rewrite as `web/vitest.workspace.ts` (two projects)**

Delete the old `web/vitest.config.ts` (or leave it minimal); add `web/vitest.workspace.ts`:

```ts
import { defineWorkspace } from 'vitest/config';
import { resolve } from 'node:path';

// opencv-dependent test files run in a real browser; everything else in Node.
const BROWSER_TESTS = [
  'tests/cv/**/*.test.ts',
  'tests/vision/matcher.test.ts',
  'tests/vision/templates.test.ts',
  'tests/vision/recognizer.test.ts',
  'tests/vision/e2e.test.ts',
];

export default defineWorkspace([
  {
    // NODE: Plan 1 engine + Plan 2 pure-logic (constants, parse, adapter-unit)
    test: {
      name: 'node',
      globals: true,
      environment: 'node',
      include: ['tests/**/*.test.ts'],
      exclude: [...BROWSER_TESTS, '**/node_modules/**'],
    },
  },
  {
    // BROWSER: opencv-dependent vision tests, in headless Chromium
    optimizeDeps: { exclude: ['@techstark/opencv-js'] },
    server: { fs: { allow: [resolve(__dirname, '..')] } }, // serve repo root: examples/, arkgrid/vision/templates/
    test: {
      name: 'browser',
      globals: true,
      include: BROWSER_TESTS,
      browser: {
        enabled: true,
        provider: 'playwright',
        headless: true,
        instances: [{ browser: 'chromium' }],
      },
    },
  },
]);
```
Update `package.json` scripts if needed so `npm test` runs `vitest run` (it auto-discovers the workspace). `npm run check` (tsc) is unchanged.

- [ ] **Step 3: Verify `cvRuntime.ts` works in-browser**

The first-attempt `cvRuntime.ts` (`import cvModule from '@techstark/opencv-js'`; init via `onRuntimeInitialized`/Promise; `getCv()` singleton) should work in the browser. Keep it; only adjust if browser init needs it.

- [ ] **Step 4: Write `loadGrayMat` (browser canvas decode)**

```ts
import { getCv } from '../../src/lib/cv/cvRuntime';

// Browser-only: fetch an image URL, decode via canvas, return a grayscale cv.Mat.
export async function loadGrayMat(url: string): Promise<any> {
  const cv = getCv();
  const blob = await (await fetch(url)).blob();
  const bmp = await createImageBitmap(blob);
  const canvas = document.createElement('canvas');
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  canvas.getContext('2d')!.drawImage(bmp, 0, 0);
  const rgba = cv.imread(canvas);            // 4-channel RGBA Mat
  const gray = new cv.Mat();
  cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY); // same luminance as cv2 BGR2GRAY
  rgba.delete();
  return gray;
}
```

- [ ] **Step 5: Write the browser spike test**

Load one example + the anchor template as vite assets (`?url` imports — vite serves them via the `server.fs.allow` repo-root grant), and confirm opencv inits, decodes, and matches:

```ts
import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv, getCv } from '../../src/lib/cv/cvRuntime';
import { loadGrayMat } from '../helpers/loadImage';
// vite asset URLs (served from repo root via server.fs.allow):
import exampleUrl from '../../../examples/20260401130608_1.jpg?url';
import anchorUrl from '../../../arkgrid/vision/templates/anchor/processing.png?url';

describe('opencv.js browser spike', () => {
  beforeAll(async () => { await initOpenCv(); }, 60_000);

  it('initializes and exposes matchTemplate + minMaxLoc', () => {
    const cv = getCv();
    expect(typeof cv.matchTemplate).toBe('function');
    expect(typeof cv.minMaxLoc).toBe('function');
  });

  it('decodes an example to a 1920x1080 gray Mat', async () => {
    const m = await loadGrayMat(exampleUrl);
    expect(m.cols).toBe(1920);
    expect(m.rows).toBe(1080);
    m.delete();
  });

  it('matches the anchor template inside its example with a high score', async () => {
    const cv = getCv();
    const gray = await loadGrayMat(exampleUrl);
    const tmpl = await loadGrayMat(anchorUrl);
    const res = new cv.Mat();
    cv.matchTemplate(gray, tmpl, res, cv.TM_CCOEFF_NORMED);
    const mm = cv.minMaxLoc(res);
    expect(mm.maxVal).toBeGreaterThan(0.7);
    [gray, tmpl, res].forEach((m) => m.delete());
  });
});
```

- [ ] **Step 6: Run the spike (browser project only)**

Run: `cd web && npx vitest run --project browser tests/cv/spike.test.ts`
Expected: Chromium launches headless; all 3 pass (maxVal > 0.7 — the standalone Node check earlier saw 0.9963).
If the asset `?url` imports 404, confirm `server.fs.allow` includes the repo root and the relative paths resolve from `web/tests/cv/`.

- [ ] **Step 7: Confirm the node project (Plan 1) still passes**

Run: `cd web && npx vitest run --project node`
Expected: Plan 1's engine suites (16 tests) green in Node, untouched by the browser config.

- [ ] **Step 8: Commit**

```bash
cd web && npm run check   # tsc clean
git add web/package.json web/package-lock.json web/vitest.workspace.ts web/src/lib/cv/cvRuntime.ts web/tests/helpers/loadImage.ts web/tests/cv/spike.test.ts
git rm -f web/vitest.config.ts web/tests/helpers/decodeImage.ts 2>/dev/null || true
git commit -m "feat(web): browser-mode vitest (node+browser projects) + opencv.js spike"
```

> **If browser mode cannot run in this environment** (Playwright won't install/launch, or opencv.js fails to init in Chromium) after genuine effort, STOP and report BLOCKED with the exact failure — do not silently fall back to a different runtime; that is a plan-level decision for the controller/human.

---

### Task 2: Python vision golden exporter

**Files:**
- Create: `tools/export_vision_golden.py`
- Create (generated, committed): `web/tests/fixtures/detection.json`

**Interfaces:**
- Produces: `detection.json` = `{ meta, records: [...] }`; one record per `examples/` image: `{ file, expected: { found, gem_type, gem_type_score, willpower, willpower_score, chaos, chaos_score, first_effect, first_effect_score, first_level, first_level_score, second_effect, second_effect_score, second_level, second_level_score, rerolls, rerolls_score, current_step, step_score, total_steps, rarity_score, options: [{name_key,name_score,delta_key,delta_score} x4] } }`.

- [ ] **Step 1: Write the exporter**

```python
"""Export golden DetectionResults for the TS vision parity suite.

Run from repo root:  source .venv/Scripts/activate && python tools/export_vision_golden.py
Writes web/tests/fixtures/detection.json. Commit the output. Requires opencv-python.
"""
from __future__ import annotations
import json, glob, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
from arkgrid.vision.template_recognizer import detect

FIX = Path("web/tests/fixtures")
SCHEMA_VERSION = 1

def _sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"

def rec(file: str) -> dict:
    frame = cv2.imread(file)
    d = detect(frame)
    return {
        "file": os.path.basename(file),
        "expected": {
            "found": d.found,
            "gem_type": d.gem_type, "gem_type_score": d.gem_type_score,
            "willpower": d.willpower, "willpower_score": d.willpower_score,
            "chaos": d.chaos, "chaos_score": d.chaos_score,
            "first_effect": d.first_effect, "first_effect_score": d.first_effect_score,
            "first_level": d.first_level, "first_level_score": d.first_level_score,
            "second_effect": d.second_effect, "second_effect_score": d.second_effect_score,
            "second_level": d.second_level, "second_level_score": d.second_level_score,
            "rerolls": d.rerolls, "rerolls_score": d.rerolls_score,
            "current_step": d.current_step, "step_score": d.step_score,
            "total_steps": d.total_steps, "rarity_score": d.rarity_score,
            "options": [
                {"name_key": o.name_key, "name_score": o.name_score,
                 "delta_key": o.delta_key, "delta_score": o.delta_score}
                for o in d.options
            ],
        },
    }

def main():
    FIX.mkdir(parents=True, exist_ok=True)
    files = sorted(glob.glob("examples/*.jpg")) + sorted(glob.glob("examples/*.png"))
    records = [rec(f) for f in files]
    payload = {"meta": {"schema": SCHEMA_VERSION, "arkgrid_sha": _sha(),
                        "n": len(records)}, "records": records}
    (FIX / "detection.json").write_text(json.dumps(payload, indent=1))
    print(f"wrote detection.json ({len(records)} records)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the exporter**

Run: `source .venv/Scripts/activate && python tools/export_vision_golden.py`
Expected: `wrote detection.json (60 records)` (or however many images exist).

- [ ] **Step 3: Sanity-check and commit**

Run: `python -c "import json; d=json.load(open('web/tests/fixtures/detection.json')); print(d['meta']['n'], 'records'); print('found:', sum(r['expected']['found'] for r in d['records']))"`
Expected: positive record count; most records `found=True`.

```bash
git add tools/export_vision_golden.py web/tests/fixtures/detection.json
git commit -m "test(web): python vision golden exporter + detection fixtures"
```

---

### Task 3: Port `constants.ts`

**Files:**
- Create: `web/src/lib/cv/constants.ts`
- Test: `web/tests/vision/constants.test.ts`

**Source:** `arkgrid/vision/constants.py` (all). Port the ROI tuples as `readonly [number, number, number, number]`, thresholds, REF dims, `OPTION_CARD_POSITIONS`, `OPTION_CARD_Y_OFFSET/HEIGHT`, `RARITY_TOTAL_STEPS`, `RARITY_FROM_TOTAL_STEPS`, `GEM_TYPE_TEMPLATE_TO_DOMAIN`. `FINISH_STAT_POSITIONS` and the finish threshold may be **omitted** (detect_finish is Plan 3).

**Interfaces:**
- Produces (names mirror the Python, camelCased):
  ```ts
  export type Roi = readonly [number, number, number, number];
  export const REF_WIDTH = 1920, REF_HEIGHT = 1080;
  export const THRESHOLD_ANCHOR = 0.70;
  export const ANCHOR_SEARCH_ROI: Roi;
  export const ROI_GEM_TYPE: Roi, ROI_STAT_WILLPOWER: Roi, ROI_STAT_CHAOS: Roi,
    ROI_STAT_FIRST: Roi, ROI_STAT_SECOND: Roi, ROI_REROLL: Roi, ROI_PROCESS_STEPS: Roi;
  export const OPTION_CARD_Y_OFFSET = 520, OPTION_CARD_HEIGHT = 70;
  export const OPTION_CARD_POSITIONS: ReadonlyArray<readonly [number, number]>;
  export const RARITY_TOTAL_STEPS: Readonly<Record<string, number>>;
  export const RARITY_FROM_TOTAL_STEPS: Readonly<Record<number, string>>;
  export const GEM_TYPE_TEMPLATE_TO_DOMAIN: Readonly<Record<string, string>>;
  ```

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest';
import * as C from '../../src/lib/cv/constants';

describe('vision constants', () => {
  it('matches reference dims and anchor', () => {
    expect([C.REF_WIDTH, C.REF_HEIGHT]).toEqual([1920, 1080]);
    expect(C.ANCHOR_SEARCH_ROI).toEqual([650, 20, 700, 80]);
    expect(C.THRESHOLD_ANCHOR).toBe(0.70);
  });
  it('has 4 option cards and the willpower/chaos ROIs', () => {
    expect(C.OPTION_CARD_POSITIONS).toEqual([[-172,117],[-55,117],[62,117],[179,117]]);
    expect(C.ROI_STAT_WILLPOWER).toEqual([56, 309, 16, 16]);
    expect(C.ROI_STAT_CHAOS).toEqual([56, 427, 16, 16]);
  });
  it('maps gem-type templates to domain and rarity to steps', () => {
    expect(C.GEM_TYPE_TEMPLATE_TO_DOMAIN['order_solidity']).toBe('order_fortitude');
    expect(C.GEM_TYPE_TEMPLATE_TO_DOMAIN['chaos_corrosion']).toBe('chaos_erosion');
    expect(C.RARITY_TOTAL_STEPS['epic']).toBe(9);
    expect(C.RARITY_FROM_TOTAL_STEPS[7]).toBe('rare');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/vision/constants.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `constants.ts`** — transcribe `vision/constants.py` value-for-value (ROIs, maps). Use the exact numbers.

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/vision/constants.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/cv/constants.ts web/tests/vision/constants.test.ts
git commit -m "feat(web): port vision constants.py (ROIs, thresholds, maps)"
```

---

### Task 4: Port `matcher.ts`

**Files:**
- Create: `web/src/lib/cv/matcher.ts`
- Test: `web/tests/vision/matcher.test.ts`

**Source:** `arkgrid/vision/matcher.py` (`find_template`, `find_best_match`). Skip `find_all_matches` (unused by `detect`). ROI clamping matches `find_template` (clamp to frame bounds; return score 0 if template larger than target).

**Interfaces:**
- Consumes: `getCv` (Task 1), `Roi` (Task 3).
- Produces:
  ```ts
  export interface MatchResult { key: string; score: number; loc: { x: number; y: number }; }
  // best score over a template set, above threshold; null if none clears it
  export function findBestMatch(frame: any, templates: Map<string, any>, roi?: Roi, threshold?: number): MatchResult | null;
  // raw single-template score + location (full-frame coords)
  export function findTemplate(frame: any, template: any, roi?: Roi): { score: number; x: number; y: number };
  ```

- [ ] **Step 1: Write the failing test**

This is a **browser-project** test (in the `BROWSER_TESTS` allowlist). Use `loadGrayMat` (Task 1) + `?url` asset imports — NOT `node:fs`. `loadGrayMat` returns a grayscale Mat directly.

```ts
import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { loadGrayMat } from '../helpers/loadImage';
import { findBestMatch, findTemplate } from '../../src/lib/cv/matcher';
import exampleUrl from '../../../examples/20260401130608_1.jpg?url';
import anchorUrl from '../../../arkgrid/vision/templates/anchor/processing.png?url';

describe('matcher', () => {
  beforeAll(async () => { await initOpenCv(); }, 60_000);

  it('finds the anchor in its example via findTemplate', async () => {
    const frame = await loadGrayMat(exampleUrl);
    const anchor = await loadGrayMat(anchorUrl);
    const r = findTemplate(frame, anchor, [650, 20, 700, 80]);
    expect(r.score).toBeGreaterThan(0.7);
    [frame, anchor].forEach((m) => m.delete());
  });

  it('findBestMatch returns null where the template is absent', async () => {
    const frame = await loadGrayMat(exampleUrl);
    const anchor = await loadGrayMat(anchorUrl);
    // search a bottom-screen ROI where the "Processing" anchor text is not present
    const res = findBestMatch(frame, new Map([['anchor', anchor]]), [100, 900, 400, 120], 0.70);
    expect(res).toBeNull();
    [frame, anchor].forEach((m) => m.delete());
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run --project browser tests/vision/matcher.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `matcher.ts`** — transcribe `matcher.py`: `findTemplate` (ROI clamp via `frame.roi(rect)`, `cv.matchTemplate`+`cv.minMaxLoc`, add ROI offset back, return 0 if template larger than target), `findBestMatch` (iterate templates, keep best ≥ threshold). Delete intermediate `Mat`s (`result`, ROI sub-mat) to avoid WASM leaks. `matcher.ts` imports `getCv` from `cvRuntime` and `Roi` from `constants` — it is environment-agnostic (no `node:fs`).

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run --project browser tests/vision/matcher.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/cv/matcher.ts web/tests/vision/matcher.test.ts
git commit -m "feat(web): port vision matcher.py (findTemplate/findBestMatch)"
```

---

### Task 5: Port `templates.ts` (TemplateStore)

**Files:**
- Create: `web/src/lib/cv/templates.ts` (env-agnostic — NO fs/glob)
- Create: `web/tests/helpers/loadTemplates.ts` (browser loader via `import.meta.glob` + `loadGrayMat`; reused by Tasks 7/8)
- Test: `web/tests/vision/templates.test.ts` (browser project)

**Source:** `template_recognizer._load` + `_strip_variant` + the template-dir layout. In the browser there is no `readdirSync`, so `TemplateStore` holds **pre-decoded** sets and the enumeration/decoding lives in the test loader (`import.meta.glob` → `loadGrayMat`). This injected-loader shape is exactly what Plan 3's browser/atlas loader will reuse. Sets used by `detect`: `anchor`, `gem_type`, `willpower`, `chaos`, `rerolls`, `steps`, `rarity`, `side_nodes/names`, `side_nodes/deltas`, `options/names`, `options/deltas`.

**Interfaces:**
- Consumes: nothing at runtime (env-agnostic). The loader helper consumes `getCv`/`loadGrayMat`.
- Produces:
  ```ts
  // templates.ts (env-agnostic)
  export function stripVariant(key: string): string;  // 'additional_damage_01' -> 'additional_damage'
  // group flat [relPath-without-ext, grayMat] entries into sets by parent dir, keyed by filename stem
  export function groupBySet(entries: Array<[string, any]>): Map<string, Map<string, any>>;
  export class TemplateStore {
    constructor(sets: Map<string, Map<string, any>>);  // pre-decoded sets
    get(setName: string): Map<string, any>;            // throws if the set wasn't loaded
    has(setName: string): boolean;
    setNames(): string[];
  }
  // loadTemplates.ts (browser test helper)
  export async function loadTemplateStore(): Promise<TemplateStore>;
  ```
- `groupBySet`: for each `[rel, mat]` (rel e.g. `"willpower/1"` or `"side_nodes/names/attack_power"`), split at the LAST `/` → `setName` = everything before, `stem` = after. So `side_nodes/names/foo` → set `"side_nodes/names"`, stem `"foo"`.

- [ ] **Step 1: Write the browser loader helper**

`web/tests/helpers/loadTemplates.ts`:

```ts
import { groupBySet, TemplateStore } from '../../src/lib/cv/templates';
import { loadGrayMat } from './loadImage';

// vite enumerates the PNGs at build time; keys are the matched paths, values are served URLs.
const TEMPLATE_URLS = import.meta.glob(
  '../../../arkgrid/vision/templates/**/*.png',
  { eager: true, query: '?url', import: 'default' },
) as Record<string, string>;

export async function loadTemplateStore(): Promise<TemplateStore> {
  const entries: Array<[string, any]> = [];
  for (const [path, url] of Object.entries(TEMPLATE_URLS)) {
    const rel = path.split('/templates/')[1].replace(/\.png$/, ''); // "willpower/1", "side_nodes/names/foo"
    entries.push([rel, await loadGrayMat(url)]);
  }
  return new TemplateStore(groupBySet(entries));
}
```

- [ ] **Step 2: Write the failing test**

```ts
import { describe, it, expect, beforeAll } from 'vitest';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { stripVariant, TemplateStore } from '../../src/lib/cv/templates';
import { loadTemplateStore } from '../helpers/loadTemplates';

describe('TemplateStore', () => {
  let store: TemplateStore;
  beforeAll(async () => { await initOpenCv(); store = await loadTemplateStore(); }, 120_000);

  it('strips numeric variant suffixes', () => {
    expect(stripVariant('additional_damage_01')).toBe('additional_damage');
    expect(stripVariant('attack_power')).toBe('attack_power');
  });

  it('loads grayscale templates for the willpower set (keys 1..5)', () => {
    const wp = store.get('willpower');
    expect(wp.size).toBe(5);
    expect([...wp.keys()].sort()).toEqual(['1', '2', '3', '4', '5']);
    expect(wp.get('1')!.channels()).toBe(1);   // grayscale
  });

  it('exposes every set detect() needs, each non-empty', () => {
    for (const name of ['anchor', 'gem_type', 'willpower', 'chaos', 'rerolls', 'steps',
                        'rarity', 'side_nodes/names', 'side_nodes/deltas',
                        'options/names', 'options/deltas']) {
      expect(store.has(name)).toBe(true);
      expect(store.get(name).size).toBeGreaterThan(0);
    }
  });
});
```

- [ ] **Step 3: Run to verify it fails** — `cd web && npx vitest run --project browser tests/vision/templates.test.ts` → FAIL (module not found).

- [ ] **Step 4: Implement `templates.ts`** — `stripVariant` (regex `/_\d+$/` → ''), `groupBySet` (split at last `/`), and `TemplateStore` (wraps the pre-decoded `Map<setName, Map<stem, Mat>>`; `get` throws on a missing set, `has`, `setNames`). No `fs`, no `import.meta.glob` in `templates.ts` itself — keep it env-agnostic. Then write the loader helper from Step 1.

- [ ] **Step 5: Run to verify it passes** — `cd web && npx vitest run --project browser tests/vision/templates.test.ts` → PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
cd web && npm run check
git add web/src/lib/cv/templates.ts web/tests/helpers/loadTemplates.ts web/tests/vision/templates.test.ts
git commit -m "feat(web): TemplateStore (pre-decoded sets) + browser glob loader"
```

---

### Task 6: Port the parse helpers (`recognizer.ts` part 1)

**Files:**
- Create: `web/src/lib/cv/recognizer.ts` (parse helpers + `DetectionResult`/`OptionDetection` types this task; `detect()` added in Task 7)
- Test: `web/tests/vision/parse.test.ts`

**Source:** `template_recognizer.py` — `parse_rerolls` (312-332), `parse_delta` (335-380), `determine_option_kind` (383-424), `_side_node_level` (168-173). Reuse `stripVariant` from `templates.ts`.

**Interfaces:**
- Produces:
  ```ts
  export interface OptionDetection { nameKey: string | null; nameScore: number; deltaKey: string | null; deltaScore: number; }
  export interface DetectionResult { found: boolean;
    gemType: string | null; gemTypeScore: number;
    willpower: number | null; willpowerScore: number;
    chaos: number | null; chaosScore: number;
    firstEffect: string | null; firstEffectScore: number; firstLevel: number | null; firstLevelScore: number;
    secondEffect: string | null; secondEffectScore: number; secondLevel: number | null; secondLevelScore: number;
    rerolls: string | null; rerollsScore: number;
    currentStep: number | null; stepScore: number; totalSteps: number | null; rarityScore: number;
    options: OptionDetection[]; }
  export function parseRerolls(rerollKey: string | null, extraTicket?: boolean): number;
  export type DeltaKind = 'lvl' | 'points' | 'cost' | 'reroll' | 'effect_changed' | 'maintained' | null;
  export function parseDelta(deltaKey: string | null): [DeltaKind, number | null];
  export function determineOptionKind(nameKey: string | null, deltaKey: string | null,
    firstEffect: string, secondEffect: string): ['will'|'chaos'|'first'|'second'|'cost'|'view'|'other', number | null];
  export function sideNodeLevel(deltaKey: string | null): number | null;
  ```

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest';
import { parseRerolls, parseDelta, determineOptionKind, sideNodeLevel } from '../../src/lib/cv/recognizer';

describe('parse helpers', () => {
  it('parseRerolls', () => {
    expect(parseRerolls(null)).toBe(0);
    expect(parseRerolls('0_ticket_not_available')).toBe(0);
    expect(parseRerolls('0_ticket_available')).toBe(0);
    expect(parseRerolls('0_ticket_available', true)).toBe(1);
    expect(parseRerolls('2')).toBe(2);
    expect(parseRerolls('1_01')).toBe(1);
    expect(parseRerolls('2', true)).toBe(3);
  });
  it('parseDelta', () => {
    expect(parseDelta('1_line_lvl+3')).toEqual(['lvl', 3]);
    expect(parseDelta('2_line_+2')).toEqual(['points', 2]);
    expect(parseDelta('1_line_-1')).toEqual(['points', -1]);
    expect(parseDelta('cost+100')).toEqual(['cost', null]);
    expect(parseDelta('reroll+1')).toEqual(['reroll', null]);
    expect(parseDelta('1_line_effect_changed')).toEqual(['effect_changed', null]);
    expect(parseDelta('maintained')).toEqual(['maintained', null]);
    expect(parseDelta(null)).toEqual([null, null]);
  });
  it('determineOptionKind', () => {
    expect(determineOptionKind('will', '1_line_lvl+2', 'attack_power', 'ally_damage')).toEqual(['will', 2]);
    expect(determineOptionKind('chaos', '1_line_lvl+1', 'attack_power', 'ally_damage')).toEqual(['chaos', 1]);
    expect(determineOptionKind('attack_power', '1_line_lvl+3', 'attack_power', 'ally_damage')).toEqual(['first', 3]);
    expect(determineOptionKind('ally_damage', '2_line_lvl+1', 'attack_power', 'ally_damage')).toEqual(['second', 1]);
    expect(determineOptionKind('cost', 'cost+100', 'attack_power', 'ally_damage')).toEqual(['cost', null]);
    expect(determineOptionKind('view', 'reroll+1', 'attack_power', 'ally_damage')).toEqual(['view', null]);
  });
  it('sideNodeLevel', () => {
    expect(sideNodeLevel('2_line_lvl3')).toBe(3);
    expect(sideNodeLevel(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module not found).

- [ ] **Step 3: Implement the parse helpers + the `DetectionResult`/`OptionDetection` types** in `recognizer.ts`. Transcribe the four Python functions exactly (regex semantics: `parseDelta` strips `1_line_`/`2_line_` prefix; `lvl([+-]?\d+)`; the `effect_changed`/`maintained`/`cost`/`reroll` branches; else `([+-]?\d+)` → points). `determineOptionKind` maps `will`→will, `chaos`/`order`→chaos, `cost`→cost, `view`→view, `maintain`→other, `effect_changed`→other, else first/second by effect-name equality, fallback other. `parseRerolls` handles the two `0_ticket_*` keys + variant strip + `+1` for extra ticket.

- [ ] **Step 4: Run to verify it passes** — PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/cv/recognizer.ts web/tests/vision/parse.test.ts
git commit -m "feat(web): port vision parse helpers (rerolls/delta/option-kind)"
```

---

### Task 7: Port `detect()` (`recognizer.ts` part 2) + golden parity

**Files:**
- Modify: `web/src/lib/cv/recognizer.ts` (add `detect`, `_cropRoi`, `_match`)
- Test: `web/tests/vision/recognizer.test.ts`

**Source:** `template_recognizer.detect` (180-305) + `_crop_roi` (154-165) + `_match` (133-151). Uses constants (Task 3), matcher/`findBestMatch` for the anchor (Task 4), `TemplateStore` (Task 5), parse helpers (Task 6).

**Interfaces:**
- Consumes: all of the above + `getCv`.
- Produces:
  ```ts
  // detect takes a BGR cv.Mat (like cv2 frame_bgr); resizes to FHD if needed, grayscales, matches.
  export function detect(frameBgr: any, store: TemplateStore): DetectionResult;
  ```
- Note: `_match(crop, templates, stripVariants?)` returns `[key|null, score]` — best `matchTemplate` score over the set (skip templates larger than the crop), optionally variant-stripped. This is the per-set best-match used for every ROI except the anchor (which uses `findBestMatch` with `ANCHOR_SEARCH_ROI`+threshold).

- [ ] **Step 1: Write the golden parity test**

```ts
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { decodeToBgrMat } from '../helpers/decodeImage';
import { TemplateStore } from '../../src/lib/cv/templates';
import { detect } from '../../src/lib/cv/recognizer';

const REPO = resolve(__dirname, '../../..');
const records = JSON.parse(readFileSync(resolve(__dirname, '../fixtures/detection.json'), 'utf8')).records;

describe('detect() golden parity', () => {
  let store: TemplateStore;
  beforeAll(async () => { await initOpenCv(); store = new TemplateStore(resolve(REPO, 'arkgrid/vision/templates')); }, 60_000);

  it('reproduces the Python detected values/keys for every example', () => {
    const mismatches: string[] = [];
    for (const r of records) {
      const e = r.expected;
      const frame = decodeToBgrMat(resolve(REPO, 'examples', r.file));
      const d = detect(frame, store);
      frame.delete();
      const got = {
        found: d.found, gem_type: d.gemType, willpower: d.willpower, chaos: d.chaos,
        first_effect: d.firstEffect, first_level: d.firstLevel,
        second_effect: d.secondEffect, second_level: d.secondLevel,
        rerolls: d.rerolls, current_step: d.currentStep, total_steps: d.totalSteps,
        options: d.options.map((o) => ({ name_key: o.nameKey, delta_key: o.deltaKey })),
      };
      const want = {
        found: e.found, gem_type: e.gem_type, willpower: e.willpower, chaos: e.chaos,
        first_effect: e.first_effect, first_level: e.first_level,
        second_effect: e.second_effect, second_level: e.second_level,
        rerolls: e.rerolls, current_step: e.current_step, total_steps: e.total_steps,
        options: e.options.map((o: any) => ({ name_key: o.name_key, delta_key: o.delta_key })),
      };
      if (JSON.stringify(got) !== JSON.stringify(want)) {
        mismatches.push(`${r.file}\n  got : ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
      }
    }
    if (mismatches.length) throw new Error(`${mismatches.length}/${records.length} mismatched:\n` + mismatches.join('\n'));
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `cd web && npx vitest run tests/vision/recognizer.test.ts` → FAIL (`detect` not exported).

- [ ] **Step 3: Implement `detect()` + `_cropRoi` + `_match`** — transcribe `template_recognizer.detect`: resize-if-needed → `cvtColor` BGR2GRAY → anchor via `findBestMatch(gray, store.load('anchor'), ANCHOR_SEARCH_ROI, THRESHOLD_ANCHOR)` (return `found=false` if null) → set `found=true`, `(ax,ay)=anchor.loc` → for each ROI, `_cropRoi(gray, ax, ay, roi)` then `_match` against the right set. Map gem_type/willpower/chaos/rerolls/steps/rarity, side nodes (first/second name+delta → `sideNodeLevel`), and the 4 option cards (`OPTION_CARD_POSITIONS`/`OPTION_CARD_Y_OFFSET`/`OPTION_CARD_HEIGHT`). `willpower`/`chaos`/`current_step` only set when the matched key is all-digits (`/^\d+$/`). Delete every intermediate `Mat`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/vision/recognizer.test.ts`
Expected: PASS — 0 mismatches over all records.

> If a small number of records mismatch on a borderline ROI (decoder/score flip), do NOT loosen the test. Investigate per the Global Constraints: confirm grayscale code, ROI numbers, and `_match` skip-if-larger logic match Python; verify the decoder path (Task 1). If a genuine cv2-vs-opencv.js ambiguity remains on a specific ROI after that, STOP and report it (file + ROI + both keys/scores) for the controller to adjudicate — it is a finding, not a tolerance to add.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/cv/recognizer.ts web/tests/vision/recognizer.test.ts
git commit -m "feat(web): port detect() with Python golden-vector parity over examples/"
```

---

### Task 8: Adapter (`adapter.ts`) + end-to-end test

**Files:**
- Create: `web/src/lib/cv/adapter.ts`
- Test: `web/tests/vision/adapter.test.ts`, `web/tests/vision/e2e.test.ts`

**Source:** `automation.py` — `_analyze_frame` state/turn build (430-450), `_detected_to_options` (522-550), `_parse_view_delta` (412-417). Consumes Plan 1 engine types (`GemState`, `Option`, `makeOption`, `AstroGem`, `buildEngineContext`, `advise`).

**Interfaces:**
- Produces:
  ```ts
  export function parseViewDelta(deltaKey: string | null): number;   // signed int from 'reroll+1'
  export interface EngineInputs {
    gem: AstroGem;            // gemType domain-mapped, first/second effect, optimize
    state: GemState;          // will/chaos/first/second/rerolls/effects
    offers: Option[];         // 4 offers, weight 1.0
    turn: number; turnsLeft: number; turnsTotal: number; rerolls: number;
    resetAvailable: boolean;
  }
  // optimize + extraTicket + resetAvailable come from the caller's config (detection can't supply them).
  export function detectionToEngineInputs(det: DetectionResult,
    opts: { optimize: 'dps' | 'support'; extraTicket?: boolean; resetAvailable?: boolean }): EngineInputs;
  ```
- Conventions (verbatim): `turnsLeft = det.currentStep`; `turnsTotal = det.totalSteps`; `turn = turnsTotal − turnsLeft + 1`. Offer key per `_detected_to_options`. `rerolls = parseRerolls(det.rerolls, extraTicket)`.

- [ ] **Step 1: Write the adapter unit test**

```ts
import { describe, it, expect } from 'vitest';
import { detectionToEngineInputs, parseViewDelta } from '../../src/lib/cv/adapter';
import type { DetectionResult } from '../../src/lib/cv/recognizer';

const baseDet = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'chaos_distortion', gemTypeScore: 1,
  willpower: 3, willpowerScore: 1, chaos: 2, chaosScore: 1,
  firstEffect: 'attack_power', firstEffectScore: 1, firstLevel: 2, firstLevelScore: 1,
  secondEffect: 'ally_damage', secondEffectScore: 1, secondLevel: 1, secondLevelScore: 1,
  rerolls: '1', rerollsScore: 1, currentStep: 4, stepScore: 1, totalSteps: 9, rarityScore: 1,
  options: [
    { nameKey: 'will', nameScore: 1, deltaKey: '1_line_lvl+2', deltaScore: 1 },
    { nameKey: 'attack_power', nameScore: 1, deltaKey: '1_line_lvl+3', deltaScore: 1 },
    { nameKey: 'view', nameScore: 1, deltaKey: 'reroll+1', deltaScore: 1 },
    { nameKey: 'cost', nameScore: 1, deltaKey: 'cost+100', deltaScore: 1 },
  ], ...over,
});

describe('adapter', () => {
  it('parseViewDelta', () => {
    expect(parseViewDelta('reroll+1')).toBe(1);
    expect(parseViewDelta('reroll+2')).toBe(2);
    expect(parseViewDelta(null)).toBe(0);
  });

  it('maps turns via turnsLeft = currentStep', () => {
    const i = detectionToEngineInputs(baseDet(), { optimize: 'dps' });
    expect(i.turnsLeft).toBe(4);
    expect(i.turnsTotal).toBe(9);
    expect(i.turn).toBe(6);            // 9 - 4 + 1
  });

  it('domain-maps the gem type and builds state', () => {
    const i = detectionToEngineInputs(baseDet({ gemType: 'order_solidity' }), { optimize: 'dps' });
    expect(i.gem.gemType).toBe('order_fortitude');
    expect(i.state.will).toBe(3); expect(i.state.chaos).toBe(2);
    expect(i.state.first).toBe(2); expect(i.state.second).toBe(1);
    expect(i.state.firstEffect).toBe('attack_power');
  });

  it('builds offers with the right keys/kinds/deltas', () => {
    const i = detectionToEngineInputs(baseDet(), { optimize: 'dps' });
    const byKind = Object.fromEntries(i.offers.map((o) => [o.kind, o]));
    expect(byKind['will']).toMatchObject({ key: 'will+2', delta: 2 });
    expect(byKind['first']).toMatchObject({ key: 'first+3', delta: 3 });  // attack_power == firstEffect
    expect(byKind['view']).toMatchObject({ delta: 1 });
    expect(byKind['cost']).toMatchObject({ key: 'cost+100', delta: 0 });
    expect(i.offers).toHaveLength(4);
  });

  it('rerolls from parseRerolls', () => {
    expect(detectionToEngineInputs(baseDet({ rerolls: '2' }), { optimize: 'dps' }).rerolls).toBe(2);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module not found).

- [ ] **Step 3: Implement `adapter.ts`** — transcribe the three Python pieces. `detectionToEngineInputs`: domain-map gemType (`GEM_TYPE_TEMPLATE_TO_DOMAIN`), build `AstroGem` (effects from det, optimize from opts), build `GemState` (`first/second = level ?? 1`, rerolls via `parseRerolls`), build `offers` per `_detected_to_options` (use `determineOptionKind` + `parseDelta` kind-hint; `view` delta via `parseViewDelta`; otherwise delta = `delta_val ?? 0`), compute turn fields, set `resetAvailable = opts.resetAvailable ?? false`.

- [ ] **Step 4: Run to verify it passes** — PASS (5 tests).

- [ ] **Step 5: Write the end-to-end test**

```ts
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { initOpenCv } from '../../src/lib/cv/cvRuntime';
import { decodeToBgrMat } from '../helpers/decodeImage';
import { TemplateStore } from '../../src/lib/cv/templates';
import { detect } from '../../src/lib/cv/recognizer';
import { detectionToEngineInputs } from '../../src/lib/cv/adapter';
import { buildEngineContext, advise } from '../../src/lib/engine';

const REPO = resolve(__dirname, '../../..');
const records = JSON.parse(readFileSync(resolve(__dirname, '../fixtures/detection.json'), 'utf8')).records;

describe('e2e: screenshot -> detect -> adapt -> advise', () => {
  let store: TemplateStore;
  beforeAll(async () => { await initOpenCv(); store = new TemplateStore(resolve(REPO, 'arkgrid/vision/templates')); }, 60_000);

  it('produces a coherent recommendation for detected cutting frames', () => {
    // pick the first few records the Python detected as a full cutting screen
    const cutting = records.filter((r: any) => r.expected.found && r.expected.gem_type
      && r.expected.total_steps && r.expected.current_step
      && r.expected.first_effect && r.expected.second_effect).slice(0, 5);
    expect(cutting.length).toBeGreaterThan(0);

    for (const r of cutting) {
      const frame = decodeToBgrMat(resolve(REPO, 'examples', r.file));
      const det = detect(frame, store); frame.delete();
      const inputs = detectionToEngineInputs(det, { optimize: 'dps' });
      const rarity = ({ 5: 'common', 7: 'rare', 9: 'epic' } as const)[inputs.turnsTotal as 5|7|9];
      const ctx = buildEngineContext(inputs.gem, { rarity: rarity!, minWill: 4, minChaos: 5 });
      const out = advise(ctx, { state: inputs.state, offers: inputs.offers,
        turn: inputs.turn, turnsLeft: inputs.turnsLeft, rerolls: inputs.rerolls,
        resetAvailable: inputs.resetAvailable });
      expect(['process', 'reroll', 'reset', 'finish', 'fail']).toContain(out.action);
      expect(out.pGoal).toBeGreaterThanOrEqual(0); expect(out.pGoal).toBeLessThanOrEqual(1);
      expect(out.pRelic).toBeGreaterThanOrEqual(out.pAncient);
      expect(out.perOffer).toHaveLength(4);
    }
  });
});
```

- [ ] **Step 6: Run the full suite + typecheck**

Run: `cd web && npx vitest run tests/vision/e2e.test.ts && npm test && npm run check`
Expected: e2e PASS; full suite (Plan 1 + Plan 2) green; tsc clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/cv/adapter.ts web/tests/vision/adapter.test.ts web/tests/vision/e2e.test.ts
git commit -m "feat(web): DetectionResult->engine adapter + end-to-end detect->adapt->advise test"
```

---

## Self-review

**Spec coverage (against `2026-06-24-astrogem-web-vision-design.md`):**
- §1 components (cvRuntime/constants/matcher/templates/recognizer/adapter) → Tasks 1,3,4,5,6,7,8. ✓
- `DetectionResult` shape → Task 6. ✓
- §2 adapter (turnsLeft=currentStep, offer build, parseViewDelta) → Task 8. ✓
- §3 data flow → exercised by Task 8 e2e. ✓
- §4 validation (Python golden vectors, values/keys exact, scores not asserted) → Task 2 (exporter) + Task 7 (parity). ✓
- §5 e2e → Task 8. ✓
- §6 testing/runtime (opencv.js in Node, decoder decision, relative-path reads) → Task 1; deps added Task 1. ✓
- §7 risks (init, decoder/resize drift, adapter fidelity) → Task 1 spike, Task 7 investigate-don't-loosen, Task 8 unit tests. ✓
- §8 out of scope (detect_finish, capture, worker, atlas, UI, deploy) → omitted; `detect_finish`/`FINISH_*` explicitly skipped in Tasks 3/7. ✓

**Placeholder scan:** No "TBD"/"implement later". Task 1 Step 6 is a *conditional* path gated on a spike outcome, not a placeholder. The `anchor/processing.png` filename caveat instructs verifying the actual file (the templates/anchor dir has exactly 1 PNG per Plan 1's listing).

**Type consistency:** `DetectionResult`/`OptionDetection` (Task 6) are consumed identically in Tasks 7/8. `detect(frameBgr, store)`, `findBestMatch`, `TemplateStore.load`, `parseRerolls`/`parseDelta`/`determineOptionKind`, `detectionToEngineInputs` names match across defining and consuming tasks. Engine imports (`buildEngineContext`/`advise`/`GemState`/`Option`/`AstroGem`) match Plan 1's exported surface.

**Known risk to watch:** the decoder choice (Task 1) is the parity linchpin — if `cv.imdecode` is unavailable and `jpeg-js` decode drifts from cv2 enough to flip a borderline template, Task 7 surfaces it as a mismatch to investigate (not tolerate).
