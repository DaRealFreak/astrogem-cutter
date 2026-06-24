# Astrogem Cutter Web Advisor — App Shell (Plan 3 of 3) Design

**Date:** 2026-06-24
**Status:** Approved (design); pending implementation plan
**Branch:** `feat/web-engine-port`
**Parent design:** `docs/superpowers/specs/2026-06-23-astrogem-cutter-web-design.md`

## Summary

Plan 3 is the **app shell** — the runtime that turns the two already-built,
parity-tested libraries into a usable GitHub Pages site. Plan 1 ported the
decision engine (`web/src/lib/engine/`, gated by Python golden vectors) and
Plan 2 ported the vision recognizer (`web/src/lib/cv/`, `detect()` reproduces
Python over all 60 example screenshots). Neither runs anywhere yet: there is no
Svelte app, no `index.html`, no vite build, no screen capture, no UI, and no
deploy.

This plan adds exactly those pieces, mirroring the sibling
`lostark-arkgrid-gem-locator-v2/` project's stack and capture architecture. The
result is the browser equivalent of `python -m arkgrid auto --dry-run`: the user
shares their Lost Ark screen, the app watches the cutting screen and **displays**
the recommended action plus P(goal)/P(relic+)/P(ancient)/E[coefficient]. It
never clicks — a browser cannot control the game.

When this plan ships, the branch reaches its "workable state" and can be merged.

## Decisions (locked during Plan 3 brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deploy | **GitHub Actions auto-deploy** | A workflow builds `web/` and publishes to Pages on push to `master`. Triggers on `master` only ⇒ the site goes live when the branch merges, matching "keep unmerged until workable." |
| Deploy path filter | **`web/**` + `arkgrid/vision/templates/**` + the workflow file** | A push to `master` only redeploys when the app code, the bundled recognition templates, or the workflow itself changed. Docs/Python-only commits don't rebuild. `workflow_dispatch` is a manual escape hatch that ignores the filter. |
| Pages base path | **`/AstrogemCutter/`** | Project page on this repo: `https://darealfreak.github.io/AstrogemCutter/`. vite `base: '/AstrogemCutter/'`. |
| Layout | **Two-column: config left, advisor right** | Config panel pinned left; live capture + recommendation + metrics + offer cards right. Everything visible at once for a desktop streamer. |
| Template delivery | **Reuse the existing `TemplateStore` (no sprite atlas)** | Plan 2 built `TemplateStore` over individually-decoded grayscale Mats and it is fully tested. Building locator-v2's sprite-atlas pipeline would be net-new, untested surface for no benefit. |
| Toast / notifications | **Inline status region (no toast dependency)** | Capture status and permission errors render inline. Avoids an extra dependency; YAGNI. |

## 1. Stack & dependencies

Match `lostark-arkgrid-gem-locator-v2`:

- **Add (devDependencies):** `svelte ^5`, `@sveltejs/vite-plugin-svelte`,
  `svelte-check`, `@tsconfig/svelte`, `@testing-library/svelte` (component smoke
  test). `vite ^7` is already present.
- **Add (dependencies):** `svelte-persisted-state` (config → localStorage),
  `@types/dom-mediacapture-transform` (`MediaStreamTrackProcessor` / `VideoFrame`
  ambient types). `@techstark/opencv-js` is already present.
- **No** `gh-pages` (deploy is via Actions). **No** sprite/atlas tooling
  (`spritesmith`, `generate-sprite.cjs`). **No** toast library.

`web/vite.config.ts` gains `base: '/AstrogemCutter/'`, the `svelte()` plugin, and
`worker: { format: 'es' }` (the capture worker is an ES-module worker).

## 2. New file layout

```
web/
  index.html                       # NEW: app entry
  src/main.ts                      # NEW: mounts App.svelte
  src/App.svelte                   # NEW: two-column shell
  src/app.css                      # NEW: base styling
  vite.config.ts                   # NEW: base + svelte + worker config
  svelte.config.js                 # NEW
  tsconfig.app.json                # NEW: svelte-aware (extends @tsconfig/svelte), src/ + .svelte, browser-pure
  tsconfig.node.json               # NEW: vite/worker/script config files (node)
  # reconcile with Plan 1's existing tsconfig.json (src-only) + tsconfig.check.json + tests/tsconfig.json
  src/lib/cv/
    captureController.ts           # NEW: getDisplayMedia → MediaStreamTrackProcessor → worker loop + debug
    captureWorker.ts               # NEW: init opencv + load templates + per-frame detect()
    workerTypes.ts                 # NEW: request/response message types
    decodeGray.ts                  # NEW: worker-safe PNG bytes → grayscale cv.Mat (OffscreenCanvas)
  src/lib/app/
    optimize.ts                    # NEW: resolveOptimize + inferResetAvailable + detection-completeness gate
  src/lib/state/
    config.state.svelte.ts         # NEW: persisted goal + coeffs + advanced knobs (Python defaults)
    advisor.state.svelte.ts        # NEW: runtime detection/decision/metrics/status (not persisted)
  src/components/
    ConfigPanel.svelte             # NEW: core + advanced (collapsible)
    CaptureControls.svelte         # NEW: Share/Stop, status, debug toggle + canvas
    AdvisorPanel.svelte            # NEW: recommended action + metric block + readout
    OfferTable.svelte              # NEW: 4 detected cards
    DetectedState.svelte           # NEW: detected fields + confidence
  scripts/sync-templates.mjs       # NEW: copy arkgrid/vision/templates → web build assets (predev/prebuild)
.github/workflows/deploy-web.yml   # NEW: build web/ + publish to Pages
```

Existing `web/src/lib/engine/` (Plan 1) and the rest of `web/src/lib/cv/`
(`recognizer.ts`, `adapter.ts`, `matcher.ts`, `templates.ts`, `constants.ts`,
`cvRuntime.ts` — Plan 2) are consumed unchanged.

## 3. Capture worker pipeline

Port `lostark-arkgrid-gem-locator-v2/src/lib/cv/captureController.ts` and the
worker-loop scaffolding of `captureWorker.ts`, but swap locator-v2's gem-grid
recognition for **our** `detect()`. Per frame, the worker does:

1. `VideoFrame` → normalize to FHD. Port locator-v2's `adjustResolution`
   (FHD passthrough; QHD ×3/4; UHD ×1/2; sub-FHD upscale), which matches
   `arkgrid/vision/capture.normalize_to_fhd`. `detect()` expects an FHD
   grayscale Mat.
2. Draw to `OffscreenCanvas` → `cv.matFromImageData` → `cv.cvtColor(RGBA2GRAY)`.
3. **`detect(gray, store)`** (Plan 2, unchanged) → `DetectionResult`.
4. `postMessage(DetectionResult)` to the main thread; if debug is on, also
   transfer a debug `ImageBitmap`.
5. `finally`: delete the gray Mat and `frame.close()`.

**Template loading (worker init).** The single source stays
`arkgrid/vision/templates/`. `scripts/sync-templates.mjs` copies that tree into a
build-visible location under `web/` (git-ignored; regenerated). The npm
`predev`/`prebuild` lifecycle scripts run it automatically, and the GitHub
Actions job runs `npm run build` (so `prebuild` fires there too). The worker
loads the copied PNGs via `import.meta.glob(..., { query: '?url', eager: true })`,
fetches each, and decodes it with `decodeGray.ts` (a worker-safe variant of
Plan 2's `loadGrayMat` that uses `OffscreenCanvas` + `createImageBitmap` —
workers have no `document`). The decoded Mats populate a `TemplateStore`, exactly
as the Plan 2 tests do via `loadTemplates.ts`.

**Tests are unaffected.** They continue to glob `arkgrid/vision/templates/`
directly through `server.fs.allow` (vitest browser project); the synced copy is
a production-build concern only.

## 4. Data flow, caching, and the detection gate

```
Worker:  VideoFrame → FHD gray → detect() → DetectionResult
   │ postMessage(DetectionResult [+ debug ImageBitmap])
   ▼
Main thread (captureController.onFrameDone):
   DetectionResult
     → completeness/confidence gate  ── fail ─▶ render "waiting for cutting screen"
     → detectionToEngineInputs(det, {optimize, resetAvailable})   [Plan 2 adapter]
     → advise(ctx, turnInput)                                     [Plan 1 engine]
     → { action, branch, reason, pGoal, pRelic, pAncient, eValue }
     → advisor.state (runes) → AdvisorPanel re-renders
```

- **Completeness/confidence gate** (`src/lib/app/optimize.ts`): a detection is
  fed to the engine only if it is a real, confident cutting-screen frame — gem
  type known, four option cards present, will/chaos/levels present, and match
  scores above the gate threshold. Partial or low-confidence frames render a
  "waiting" state rather than fabricating engine inputs. This is what closes the
  adapter's `?? 0`/`?? ''` fallback gap noted at the end of Plan 2: the adapter's
  fallbacks now only ever run behind a passed gate.
- **`optimize` resolution:** auto-resolve dps/support from the detected effects'
  domain (`GEM_TYPE_TEMPLATE_TO_DOMAIN` / effect coefficients in
  `engine/constants.ts`); an advanced config field overrides (default = auto).
- **`resetAvailable` inference:** default = `turn === 1` (a reset is offered only
  before any processing on a fresh run); an advanced config field overrides
  (auto / always / never). Low-stakes for read-only advice.
- **DecisionContext caching:** built via `buildEngineContext()` (Plan 1) and
  cached, rebuilt **only when the gem type *or* the config changes** (mirrors the
  Python `_DP_CACHE`). One effect-aware table set per gem type covers all effect
  configs.
- **Debounce:** `advise()` recomputes only when the *stable* detected state
  actually changes between frames, so a 30 fps stream does not thrash the engine.

## 5. Config surface (two-column; core visible, advanced collapsible)

Persisted to localStorage via `svelte-persisted-state`. Every knob defaults to
the Python default so the tool advises correctly untouched.

- **Core (always visible):**
  - Goal: `min_will`, `min_chaos`, side-node goals `min_first` / `min_second` /
    `min_side_coeff`.
  - Rarity: common (5 turns) / rare (7) / epic (9).
  - Tier valuation: `relic_coeff`, `ancient_coeff` (default = fusion-derived
    average for the detected gem type — resolved by the engine when left unset).
- **Advanced (collapsible expander):**
  - `endgame_risk`, `relic_reroll_threshold`, `force_reroll_no_progress`.
  - Extra-ticket enablers: `extra_ticket` (tri-state on/off/armed),
    `reroll_min_coeff`, `reroll_goal` + `reroll_goal_threshold`.
  - `optimize` override (default auto), `ignore_side_node_values`,
    `resetAvailable` override (default auto).

Config changes invalidate the cached `DecisionContext` and trigger a rebuild +
re-advise on the current detection.

## 6. UI layout & components

Two-column shell (`App.svelte`):

- **Left — `ConfigPanel.svelte`:** core knobs, then an `▸ advanced` expander.
  Bound directly to the persisted config store.
- **Right (top) — `CaptureControls.svelte`:** "Share screen" / "Stop" button,
  capture status (Idle → Loading → Recording), inline permission/error message,
  debug-canvas toggle and the debug `<canvas>`.
- **Right (main) — `AdvisorPanel.svelte`:**
  - Recommended action prominent (PROCESS / REROLL / RESET / FINISH) + one-line
    `reason`.
  - Metric block: P(goal), P(relic+ ≥16), P(ancient ≥19), E[coefficient].
  - `OfferTable.svelte`: the 4 detected cards with deltas; highlight the offer
    the recommendation favors.
  - `DetectedState.svelte`: detected gem type / will / chaos / levels / effects /
    rerolls / step, each with its confidence score.
  - When the gate fails: a single "waiting for cutting screen" state.

Runtime (non-persisted) state lives in `advisor.state.svelte.ts` (runes):
current `DetectionResult`, derived `Decision` + metrics, and capture status.

## 7. Deployment — GitHub Actions

`.github/workflows/deploy-web.yml`:

```yaml
on:
  push:
    branches: [master]
    paths:
      - 'web/**'
      - 'arkgrid/vision/templates/**'
      - '.github/workflows/deploy-web.yml'
  workflow_dispatch:
```

Job: checkout → setup Node → `cd web && npm ci && npm run build` (this fires
`prebuild` → `sync-templates.mjs`) → `actions/upload-pages-artifact` (path
`web/dist`) → `actions/deploy-pages`. Pages source = GitHub Actions; permissions
`pages: write` + `id-token: write`; a single `concurrency` group so overlapping
pushes don't race. The site only goes live once this branch is merged to
`master` (the trigger branch); `workflow_dispatch` allows a manual deploy.

## 8. Testing

The existing 38 tests (Plan 1 engine + Plan 2 vision, node + headless Chromium)
remain green as a gate. New coverage targets the **pure** additions only:

- `optimize.ts`: dps/support resolution from detected effects; `resetAvailable`
  inference; the completeness/confidence gate (passes a full confident
  detection, rejects partial/low-confidence ones).
- `config.state.svelte.ts`: defaults equal the Python defaults; persist/restore
  round-trip.
- `workerTypes.ts`: request/response message-type coherence (compile-time;
  a tiny structural test).
- A light Svelte component smoke (vitest browser + `@testing-library/svelte`):
  `App` mounts, config defaults render, idle state shows the "Share screen"
  prompt.

The capture loop itself (real `getDisplayMedia` + worker) is manual/QA — the
recognizer pipeline it drives is already e2e-tested in Plan 2
(`detect → adapt → advise`). New opencv/worker-importing tests, if any, follow
the Plan 2 rule: they go in the vitest **browser** project allowlist.

This plan also finalizes the **browser-purity** scoping left partial after
Plan 1: `svelte-check` runs against the svelte-aware `tsconfig.app.json`
(src + `.svelte`, no node types), so `src/` is verified free of Node globals.

## 9. Out of scope (YAGNI)

- Sprite atlas / template-coords pipeline (we reuse `TemplateStore`).
- Manual gem-state entry form (detection is the only input — locked).
- Clicking / controlling the game; confirm gate; F1–F4 hotkeys.
- Multi-character profiles / persistence beyond the config panel's localStorage.
- Modeling gold / cost-per-tap (the project intentionally does not).

## 10. Risks & mitigations

1. **Worker template decode** — workers have no `document`, so Plan 2's
   `loadGrayMat` (uses `document.createElement('canvas')`) cannot run in the
   worker. *Mitigation:* `decodeGray.ts` uses `OffscreenCanvas` +
   `createImageBitmap`, both available in workers; same decode path otherwise.
2. **Real-time DP rebuild on gem-type change** — must stay under a frame.
   *Mitigation:* per-gem-type / per-config caching (as Python already does);
   measure the TS build early.
3. **Detection flicker across frames** — a 30 fps stream produces many partial
   frames. *Mitigation:* the completeness gate + stable-state debounce; only
   confident, changed detections re-advise.
4. **Template sync drift** — the synced copy could go stale. *Mitigation:* it is
   git-ignored and regenerated by `predev`/`prebuild` every dev/build, so it can
   never diverge from `arkgrid/vision/templates/` in a build.
