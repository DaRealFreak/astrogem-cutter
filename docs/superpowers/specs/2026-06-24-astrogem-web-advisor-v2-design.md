# Astrogem Cutter Web Advisor — v2 Improvements (Design Spec)

**Date:** 2026-06-24
**Branch:** `feat/web-advisor-v2` (off `master`, which holds the merged Plans 1+2+3)
**Status:** approved design, pre-plan

## Goal

Polish and extend the shipped read-only web advisor (`web/`) with: a clearer name,
a goal-mode toggle, a per-action decision matrix, an in-memory turn log that sharpens
reset inference, a working debug view (screen mirror + detection overlays), a
screenshot-upload test path, a Chromium-only browser guard, and a proper styling pass.
It stays a client-side, read-only advisor — it never controls the game.

## Locked decisions (from brainstorming)

- **Info panel:** full **3×4 matrix** — rows `Process / Reroll / Reset` × columns `P(goal) / P(relic+) / P(ancient) / E[coeff]`.
- **Turn log:** **session, in-memory** (clears on reload / new run); it **drives reset inference**.
- **Goal mode:** a **toggle** between *separate* (min will + min chaos) and *combined* (min total will+chaos); side-node mins remain in both.
- **Debug view:** **screen mirror + detection overlays** (ROI boxes + detected value/confidence labels).
- **Styling:** delegated — grouped, card-based, intentional; validated live via `npm run dev`.

## Global constraints (carried from v1, still binding)

- All work on `feat/web-advisor-v2`; do not merge until approved.
- **Read-only:** no game control, no confirm-gate/F1–F4, no gold modeling.
- **Browser purity:** `src/` stays free of Node globals; `npm run check` (svelte-check on `tsconfig.app.json`) is the gate.
- **opencv isolation:** opencv may be imported only by `cvRuntime`/`recognizer`/`matcher`/`decodeGray`/`captureWorker`. Any test importing those (→opencv) goes in the Vitest **browser** project (`BROWSER_TESTS`); opencv-free tests run in the **node** project.
- **Engine parity:** the Python `arkgrid` package stays authoritative; the TS engine is locked to it by golden vectors (`tools/export_golden.py` → `web/tests/fixtures/*.json`). Existing engine outputs must stay byte-identical; new surface gets new golden vectors.
- **Defaults unchanged:** every existing config knob keeps its current default; the advisor is correct untouched.
- **Pages base path** `/AstrogemCutter/` and the path-filtered deploy workflow are unchanged.

---

## 1. Rename + browser guard

- **Rename:** `App.svelte` `<h1>` and `index.html` `<title>` → **"Astrogem Cutter"** (drop "Advisor" from the h1; keep a short tagline if useful).
- **Browser guard:** at startup, feature-detect `navigator.mediaDevices?.getDisplayMedia` and `globalThis.MediaStreamTrackProcessor`. If either is missing, render a clear, non-dismissable banner ("This advisor needs a Chromium-based browser — Chrome, Edge, or Opera") and disable the Share button. This replaces the current cryptic `unknown` error on Firefox/Safari.
  - Implemented as a pure helper `isCaptureSupported(): boolean` (no DOM mutation) so it is node-testable, consumed by `CaptureControls`/`App`.

## 2. Goal-mode toggle

- New persisted field `goalMode: 'separate' | 'combined'` (default `'separate'`, matching today's behavior).
- **Separate:** two inputs `minWill` / `minChaos` (today's behavior).
- **Combined:** one input `minWillChaosTotal` → engine `minTotalWillChaos`.
- Side-node mins (`minFirst` / `minSecond` / `minSideCoeff`) remain visible and editable in both modes.
- `effectiveConfig(stored, det)` maps the **active** mode to the engine and leaves the other field unset:
  - `separate` → set `minWill`/`minChaos`, leave `minTotalWillChaos` undefined.
  - `combined` → set `minTotalWillChaos`, leave `minWill`/`minChaos` undefined.
- The engine already supports `minTotalWillChaos` (in `AdvisorConfig` / `LastTurnGoal`); no engine change needed for this item.

## 3. Engine extension — per-action projections

The single change to the parity-locked engine. Additive only; existing fields unchanged.

- Add to `AdvisorOutput`:
  ```ts
  type ActionMetrics = { pGoal: number; pRelic: number; pAncient: number; eValue: number };
  // new field:
  actions: { process: ActionMetrics | null; reroll: ActionMetrics | null; reset: ActionMetrics | null };
  ```
- **process** = the *best offer* — the offer maximizing `pGoalAfter`, tie-broken by `eValueAfter` — evaluated across all four tables. Requires extending the after-click lookup to the relic & ancient tables (today only goal + side-value have per-offer/after-click methods). `null` only if there are no offers.
- **reroll** = metrics after a redraw (one reroll spent), `null` when `rerolls === 0`. **No new table method needed** (planning discovery): the reroll value is `table.lookup(state, turnsLeft, rerolls - 1)` on the reroll-aware goal/relic/ancient tables — exactly what `shouldRerollDp` already uses. A reroll changes neither `state` nor `turnsLeft`, so the side-value (E[coeff]) is unchanged = `sideValueTable.lookup(state, turnsLeft)`.
- **reset** = fresh-gem metrics: lookups from the initial all-1 `GemState` (with the gem's effect identities) and full reroll budget, on each table. `null` when reset is unavailable (see §5).
- **Parity:** existing outputs stay byte-identical. **All three rows are parity-testable** against Python (every cell is an existing Python table method — `expected_prob_after_click` for process, reroll-aware `lookup` with `rerolls-1` for reroll, fresh-state `lookup` for reset). New golden vectors (`tools/export_golden.py`) cover them; if a single cell has no clean Python equivalent it falls back to a TS unit test.

## 4. Info panel (3×4 matrix)

- A compact card in the advisor column: a table with rows **Process / Reroll / Reset** and columns **P(goal) / P(relic+) / P(ancient) / E[coeff]**.
- Reads directly from `output.actions`. The **recommended action's** row is visually highlighted (matches the recommendation badge). Unavailable actions (`null` reroll/reset) render "—" across the row.
- Probabilities shown as percentages (1 decimal), coefficient as a number (1 decimal), consistent with the existing `AdvisorPanel`.
- New component `ActionMatrix.svelte`, prop-driven `{ actions, recommended: ActionKind }` (no store coupling; render-testable).

## 5. Turn log (session, in-memory) + reset inference

- New rune store `turnLog` (`web/src/lib/state/turnLog.state.svelte.ts`): an array of records
  `{ turn: number; will: number; chaos: number; firstLevel: number; secondLevel: number; action: ActionKind; pGoal: number; eValue: number }`,
  appended when a **new, distinct** turn is observed (de-duped on `(turn, will, chaos, firstLevel, secondLevel)` so repeated frames of the same state don't spam it).
- **Run boundary detection** (a reset restarts the turn counter, so a post-reset gem looks like a fresh turn-1 gem — the only signal is gem **identity**):
  - **New gem** = gem identity changes (type or either starting effect differs) ⇒ a genuinely new run ⇒ **clear the log**, reset available again.
  - **Reset observed** = in a continuous session the detected `turn` drops back to 1 while the gem **identity is unchanged** ⇒ the player used their one-time restart on the same gem.
  - Pure helper `classifyRunTransition(prev, next): 'continue' | 'new-gem' | 'reset'` for testability.
- **Reset inference (the improvement):** replace `inferResetAvailable(turn) = turn===1` with a log-aware rule. Reset is a one-time full restart usable any turn until consumed:
  - `resetObserved` is set when `classifyRunTransition` returns `'reset'`; it clears on `'new-gem'`.
  - `resetAvailable = !resetObserved` — so reset stays available across the *whole* run (fixing v1, which wrongly disabled it after turn 1) and flips off once a reset is detected. Still overridable by `resetOverride: auto/always/never`; `auto` now means "log-inferred."
  - Pure helper `inferResetFromLog(log, override)` so it is node-testable; `computeAdvice` consults it.
  - **Acknowledged heuristic limits** (documented, not a bug): cutting two gems with *identical* type+effects back-to-back is indistinguishable from a reset; and if the advisor joins mid-run (first observed turn > 1) the prior reset history is unknown, so it defaults to available. The `resetOverride` toggle is the manual escape for both.
- **Display:** a small "Turn log" card listing the recorded turns (turn #, will/chaos, action, P(goal)). In-memory only — clears on reload, per the chosen scope.
- The turn log is updated by the capture wiring (`CaptureControls`) as detections arrive, alongside `advisor` state.

## 6. Debug view + screenshot upload (behind the debug toggle)

### Debug rendering
- The worker already accepts a `drawDebug` flag. When set, on each processed frame the worker **also** transfers an `ImageBitmap` of the FHD-normalized frame plus the `DetectionResult` to the main thread (`debug` message, extended to carry the bitmap + result).
- The main thread (controller → a `DebugView.svelte`) draws the frame on a canvas and overlays the recognition **ROI boxes** (from `vision/constants` ROI offsets relative to the anchor) and **detected value + confidence** labels per region. This makes the debug toggle finally mirror the locator project.
- Overlay drawing is a pure-ish function `drawDetectionOverlay(ctx2d, detection, scale)` operating on a 2D context — unit-testable with a stub context (assert the right boxes/labels are emitted), no opencv.

### Screenshot upload
- Shown only when debug is enabled: a file input (`<input type="file" accept="image/*">`).
- On select: decode the file to an `ImageBitmap`, send it to the worker as a new `image` message; the worker runs the same FHD-normalize → grayscale → `detect()` path on the still image and returns the `DetectionResult` (+ debug bitmap when debug is on).
- The main thread then runs `computeAdvice` + renders the advice, info matrix, detected state, and debug overlay — exactly as a live frame would, but from a saved screenshot. This gives a no-live-share test path (and makes the repo's `examples/` screenshots easy to try).

## 7. Styling / layout

Delegated; the implementation iterates live via `npm run dev`. Direction:

- **Config column:** grouped `<fieldset>`/section blocks — **Goal**, **Grade**, **Advanced** (collapsible `<details>`) — with aligned label/control rows on a consistent spacing grid (fixes the ungrouped, unaligned v1 layout). Every control (incl. checkboxes) uses standalone `for`/`id` for alignment and a11y.
- **Advisor column:** card-based — a prominent **Recommendation** badge color-coded per action (process / reroll / reset / finish), then **Info matrix**, **Offers**, **Detected state**, **Turn log**, and **Debug** as distinct cards.
- **Visual language:** one accent color + a neutral surface scale, `system-ui` type with a tight size scale, shared radius/spacing tokens in `app.css`, light/dark via the existing `color-scheme`. Compact and intentional — no UI framework added.
- **Responsive:** single column under ~720px (keep the existing breakpoint).

---

## Architecture / data flow

The v1 spine is unchanged: capture worker → `captureController` → `computeAdvice` → `advisor` store → UI. Additions:

- **Engine (`web/src/lib/engine/`):** `advise()` returns the new `actions` block (pure; new table methods `expectedAfterReroll` and after-click on relic/ancient tables).
- **State (`web/src/lib/state/`):** new `turnLog.state.svelte.ts`; `config` gains `goalMode` (+ `minWillChaosTotal`).
- **App logic (`web/src/lib/app/`):** `effectiveConfig` honors `goalMode`; reset inference moves to `inferResetFromLog`; `computeAdvice` consults the turn log; new pure helpers `isCaptureSupported`, `classifyRunTransition`, `inferResetFromLog`, `drawDetectionOverlay`.
- **Worker (`web/src/lib/cv/`):** `captureWorker` gains a `debug` bitmap transfer and an `image` (upload) message; `captureController` forwards the debug bitmap + detection to the UI and exposes an `analyzeImage(bitmap)` entry for uploads.
- **Components:** new `ActionMatrix.svelte`, `TurnLog.svelte`, `DebugView.svelte`, `ScreenshotUpload.svelte`, `BrowserGuard.svelte` (or a banner in `App`); restyled `ConfigPanel`/`AdvisorPanel` + `app.css`.

## Testing

- **Engine parity (node):** new golden vectors for the per-action projections that have a Python equivalent (process best-offer relic/ancient after-click; reset fresh-start on each table). Existing parity suites must stay green (outputs byte-identical). The reroll projection is unit-tested standalone (goal-table value agrees with the existing `shouldReroll` DP comparison).
- **Node unit tests:** `goalMode` → `effectiveConfig` mapping; `classifyRunTransition` (continue / new-gem / reset); `inferResetFromLog`; `isCaptureSupported`; turn-log de-dup/append; `drawDetectionOverlay` (stub 2D context).
- **Browser render smokes:** `ActionMatrix`, `TurnLog`, restyled `ConfigPanel`/`AdvisorPanel`, the browser-guard banner.
- **Capture loop + live debug/upload pipeline** remain manual-QA (need a real Worker/screen/file), consistent with v1; the recognizer pipeline they drive is covered by the existing detect→adapt→advise e2e. The screenshot-upload path makes manual QA reproducible against saved screenshots.
- Gates per task: full suite green, 0 leaked; `npm run check` 0 errors; `npm run build` emits the worker chunk.

## Out of scope

- Firefox/Safari **capture** support (guard + message only).
- **Persisting** the turn log across reloads.
- Gold/cost modeling; any game control (the app stays read-only).
- A full design system / component library.

## Risks

- **Engine `actions` projection** turned out to need no new DP/table math (planning confirmed every cell is an existing lookup), so the original "new reroll math" risk is largely retired. Residual risk: the reset row uses the reroll-aware tables (matrix consistency) rather than the conservative standard table the reset *decision* uses, so the displayed reset P(goal) can read slightly higher than the internal reset threshold — acceptable for an informational panel. If any matrix cell proves unreliable it degrades to "—" rather than blocking the feature.
- **Debug bitmap transfer** adds per-frame work; gated behind the debug toggle so the normal path is unaffected.
- **Turn-log reset inference** changes a decision input (`resetAvailable`); covered by node unit tests and kept overridable via `resetOverride`.
