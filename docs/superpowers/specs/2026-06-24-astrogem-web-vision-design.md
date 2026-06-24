# Astrogem Web Advisor — Plan 2: Vision Recognizer (Design)

**Date:** 2026-06-24
**Status:** Approved (design); pending implementation plan
**Depends on:** Plan 1 (`web/src/lib/engine/`, the ported decision engine) — see
`2026-06-23-astrogem-cutter-web-design.md` §2a and the Plan 1 spec/plan.

## Summary

A headless-testable TypeScript **vision layer** that turns a captured Lost Ark
gem-cutting frame into engine-ready inputs. It is a faithful port of the Python
`arkgrid/vision/` recognizer (`template_recognizer.py` + `matcher.py` +
`constants.py`) to OpenCV.js, plus a thin adapter that feeds Plan 1's `advise()`.

Plan 2 scope (locked during brainstorming): **detect → adapt → end-to-end.**
Live screen capture, Web Worker, anchor-ROI caching, the sprite atlas, config UI,
and deploy are **Plan 3**.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Validation | **Python golden vectors** | Run the production Python `detect()` on the 60 `examples/` images, dump golden `DetectionResult`s, assert the TS recognizer reproduces the detected values/keys exactly. Scores recorded, not asserted (cv2 vs opencv.js differ). Mirrors Plan 1; the Python recognizer is already production-validated in `auto`. |
| Scope boundary | **Detect + adapter + e2e** | Plan 2 ends with a proven `screenshot → recommendation` pipeline, de-risking Plan 3's wiring. |
| Test runtime | **opencv.js headless in vitest/Node** | `@techstark/opencv-js` (WASM) runs in Node; example JPEGs and template PNGs decoded to `cv.Mat`. Task 1 spike proves init before building the rest. |
| Templates | **Individual PNGs from `arkgrid/vision/templates/`** | Already in the repo; loaded directly. Sprite atlas (1-request browser perf) deferred to Plan 3. |
| Decoder | **Prefer `cv.imdecode`; fall back to pure-JS** | If the `@techstark` build ships imgcodecs, decode with opencv.js's own decoder (same codebase as cv2) to minimize pixel drift; else `jpeg-js`/`pngjs`. Task 1 spike settles which. |

## 1. Components (`web/src/lib/cv/`)

Ported module-for-module from the Python vision package:

| TS module | Python source | Contents |
|-----------|---------------|----------|
| `cvRuntime.ts` | (locator-v2 `cvRuntime.ts`/`cvLoader.ts`) | `getCv()` — async opencv.js init/handle. |
| `constants.ts` | `vision/constants.py` | `REF_WIDTH/HEIGHT`, thresholds, `ANCHOR_SEARCH_ROI`, all anchor-relative ROIs, `OPTION_CARD_POSITIONS`, `OPTION_CARD_Y_OFFSET/HEIGHT`, `FINISH_STAT_POSITIONS`, `RARITY_TOTAL_STEPS`/`RARITY_FROM_TOTAL_STEPS`, `GEM_TYPE_TEMPLATE_TO_DOMAIN`. |
| `matcher.ts` | `vision/matcher.py` | `findTemplate`/`findBestMatch` (`cv.matchTemplate` TM_CCOEFF_NORMED + `cv.minMaxLoc`, ROI clamp). |
| `templates.ts` | `template_recognizer._load`/`TemplateStore` | `TemplateStore`: load PNGs from `arkgrid/vision/templates/<set>/` → grayscale `Mat`s keyed by filename stem; `_strip_variant` (`additional_damage_01` → `additional_damage`). |
| `recognizer.ts` | `template_recognizer.py` | `detect(grayMat) → DetectionResult`; `parseRerolls`, `parseDelta`, `determineOptionKind`; `_cropRoi`, `_match`, `_sideNodeLevel`. |
| `adapter.ts` | `automation.py` per-frame builder | `detectionToEngineInput(det, config) → AdvisorRunInput`. |

### `DetectionResult` (mirrors `template_recognizer.DetectionResult`)

```ts
interface OptionDetection { nameKey: string | null; nameScore: number; deltaKey: string | null; deltaScore: number; }
interface DetectionResult {
  found: boolean;
  gemType: string | null; gemTypeScore: number;          // template key, e.g. "chaos_distortion"
  willpower: number | null; willpowerScore: number;       // 1-5
  chaos: number | null; chaosScore: number;
  firstEffect: string | null; firstEffectScore: number;   // "attack_power", ...
  firstLevel: number | null; firstLevelScore: number;
  secondEffect: string | null; secondEffectScore: number;
  secondLevel: number | null; secondLevelScore: number;
  rerolls: string | null; rerollsScore: number;           // key e.g. "0_ticket_available", "1", "2"
  currentStep: number | null; stepScore: number;          // detected number (see adapter: this IS turns_left)
  totalSteps: number | null; rarityScore: number;         // 5/7/9
  options: OptionDetection[];                              // 4 cards
}
```

### `detect()` pipeline (port of `template_recognizer.detect`)

1. Resize frame to `REF_WIDTH × REF_HEIGHT` if needed (`cv.resize`, INTER_AREA — match cv2).
2. Grayscale (`cv.cvtColor` BGR2GRAY).
3. Find anchor: `findBestMatch(gray, anchorTemplates, ANCHOR_SEARCH_ROI, THRESHOLD_ANCHOR)`. If none → `found=false`.
4. Anchor-relative ROI crops → `_match` against each template set: gem_type, willpower, chaos, rerolls, steps+rarity (same crop), side nodes (first/second: name + delta), and the 4 option cards (name + delta).
5. `strip_variants` on name/level/type/step/rarity/reroll matches; `_sideNodeLevel(deltaKey)` extracts side-node levels.

`detect_finish` (the result-screen detector) is **deferred to Plan 3** — the
advisor watches the cutting screen; the finish screen is only needed by the live
loop. (Noted so it isn't mistaken for a gap.)

## 2. Adapter (`adapter.ts`, port of `automation.py`)

`detectionToEngineInput(det, config)` builds the inputs `advise()` consumes:

- **gem**: `gemType = GEM_TYPE_TEMPLATE_TO_DOMAIN[det.gemType] ?? det.gemType`;
  `firstEffect`/`secondEffect` from detected side-node names; `optimize` from config.
- **state** (`GemState`): `will`/`chaos`/`first`/`second` from detected levels;
  `firstEffect`/`secondEffect`; `rerolls = parseRerolls(det.rerolls, extraTicket)`.
- **offers** (`Option[]`): for each of the 4 cards, `determineOptionKind(nameKey,
  deltaKey, firstEffect, secondEffect)` → `(kind, delta)`; build
  `Option(key, weight=1.0, kind, delta, resolvedEffect)` (uniform weight is fine —
  `expectedProbAfterClick` weights offers 1/N). `resolvedEffect` set for
  change-effect cards from the detected target name.
- **turn**: **`turnsLeft = det.currentStep`** (the detected number is turns-left,
  per `automation.py:433` and the `current_step == turns_left` comment);
  `turnsTotal = det.totalSteps`; `turn = turnsTotal − turnsLeft + 1`.
- **rerolls**: `parseRerolls(det.rerolls, extraTicket)`.
- **resetAvailable**: inferred (config toggle / first-turn heuristic, per the
  main design §4) — detection alone can't always determine it.

`config` (the user goal/knobs, `AdvisorConfig` from Plan 1) is supplied by the
caller; in Plan 2's e2e test it is a fixed goal. `rarity` may be derived from
`det.totalSteps` via `RARITY_FROM_TOTAL_STEPS`, but the goal itself is user input.

## 3. Data flow

```
example JPEG ─decode→ cv.Mat(BGR) ─detect()→ DetectionResult
                                      │ detectionToEngineInput(det, config)
                                      ▼
                 { gem, state, offers, turn, turnsLeft, rerolls, resetAvailable }
                                      │ buildEngineContext(gem, config) (cached) + advise(ctx, input)
                                      ▼
                 AdvisorOutput { action, branch, pGoal, pRelic, pAncient, eValue, perOffer }
```

## 4. Validation — Python golden vectors

`tools/export_vision_golden.py` (new): runs the production Python
`vision.template_recognizer.detect()` on every image in `examples/` and writes
`web/tests/fixtures/detection.json` — one record per image: the source filename
plus every detected field (gem type, will/chaos, first/second effect+level,
rerolls key, current_step, total_steps, and the 4 option `name_key`/`delta_key`
with scores). Run from repo root with the venv active (needs `opencv-python`).

The TS parity test (`web/tests/vision/recognizer.test.ts`):
- decodes each `examples/` image, runs the TS `detect()`,
- asserts the **detected values/keys match the golden record exactly** —
  `gemType`, `willpower`, `chaos`, `first/secondEffect`, `first/secondLevel`,
  `rerolls`, `currentStep`, `totalSteps`, and each option's `nameKey`/`deltaKey`;
- **match scores are recorded for diagnostics but not asserted** (cv2 vs
  opencv.js scores differ). A genuine key/value mismatch is a finding to
  investigate (decoder/resize/threshold parity), not silently tolerated.

Parse-helper and adapter unit tests cover `parseRerolls`/`parseDelta`/
`determineOptionKind` and the `turnsLeft = currentStep` mapping against known
inputs (a small golden set can be emitted from the Python helpers too).

## 5. End-to-end test (`web/tests/vision/e2e.test.ts`)

For a handful of representative `examples/` cutting-screen images: decode →
`detect` → `detectionToEngineInput(det, fixedGoal)` → `buildEngineContext` +
`advise` → assert a coherent `AdvisorOutput` (valid action, `0 ≤ pGoal ≤ 1`,
`pRelic ≥ pAncient`, `perOffer.length === 4`). Proves the full
`screenshot → recommendation` pipeline headlessly.

## 6. Testing & runtime

- **Task 1 spike** (de-risk first): in vitest/Node, init opencv.js, decode one
  template PNG + one example JPEG into `cv.Mat`s, run one `matchTemplate`, assert
  a sane score and that `cv.imdecode` is/ isn't available. Settles the decoder
  choice and the WASM-init approach before any recognizer code.
- **Dependencies**: `@techstark/opencv-js` added as a dependency (Plan 3 runtime
  too). Pure-JS decoders (`jpeg-js`, `pngjs`) as devDependencies, used only if
  `cv.imdecode` is unavailable.
- Tests read `examples/` and `arkgrid/vision/templates/` via relative paths — no
  duplication into `web/`. Plan 3 bundles them for the browser.
- `npm test` (vitest) + `npm run check` (tsc) stay green, including Plan 1's
  suites.

## 7. Risks & mitigations

1. **opencv.js WASM init in Node/vitest** — async init, memory. *Mitigation:*
   Task 1 spike; fallback is vitest browser mode if Node init proves intractable.
2. **Decoder/resize pixel drift** flips a borderline template vs cv2.
   *Mitigation:* prefer `cv.imdecode` (cv2's decoder); assert values not scores;
   most examples are already FHD (resize a no-op). Genuine flips → investigate.
3. **Adapter fidelity** (the `turnsLeft = currentStep` convention, change-effect
   offer construction). *Mitigation:* port `automation.py`'s builder faithfully;
   the e2e test + adapter unit tests catch divergence.

## 8. Out of scope (Plan 3)

Live `getDisplayMedia` capture, `MediaStreamTrackProcessor`, Web Worker,
anchor-ROI caching, sprite atlas, `detect_finish` result-screen detection, the
config/advisor UI, and GitHub Pages deploy.

## 9. Module/file layout (proposed)

```
web/
  src/lib/cv/
    cvRuntime.ts  constants.ts  matcher.ts  templates.ts  recognizer.ts  adapter.ts
  tests/
    cv/spike.test.ts                 # Task 1 feasibility spike
    vision/recognizer.test.ts        # golden-vector parity over examples/
    vision/adapter.test.ts           # parse helpers + adapter unit tests
    vision/e2e.test.ts               # screenshot → detect → adapt → advise
    fixtures/detection.json          # golden DetectionResults (from Python)
    helpers/decodeImage.ts           # Node JPEG/PNG → cv.Mat (test-only)
tools/
  export_vision_golden.py            # NEW: Python detection golden exporter
```
