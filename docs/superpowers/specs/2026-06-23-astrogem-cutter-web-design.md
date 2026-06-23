# Astrogem Cutter Web Advisor — Design

**Date:** 2026-06-23
**Status:** Approved (design); pending implementation plan

## Summary

A fully client-side web app, hosted on GitHub Pages, that watches the player's
shared Lost Ark screen and gives **live, read-only advice** for astrogem
cutting — the recommended action, the goal/relic/ancient probabilities, and the
expected end coefficient. It is the browser equivalent of `python -m arkgrid
auto --dry-run`: it reads the cutting screen and recommends, but never clicks
(a browser cannot control the game).

Lives in a new `web/` folder of this repository. Vite + Svelte + TypeScript,
matching the sibling `lostark-arkgrid-gem-locator-v2/` project's stack and
deployment model.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Brains language | **Port to TypeScript** | Single clean codebase matching locator-v2, fast, tiny bundle, no WASM. Python stays source of truth; parity enforced via golden vectors (see §5). |
| Repo location | **`web/` folder in this repo** | Keeps Python brains and TS port physically side-by-side, making golden-vector parity testing against Python trivial. |
| Build sequencing | **Streaming-first, all at once** | First usable version auto-detects from the shared screen, like dry-run auto. No manual-entry form; detection is the only input. |
| Config surface | **Core + advanced (collapsible)** | Core knobs always visible; advanced behind an expander; Python defaults everywhere so it works out of the box. |
| Confirm gate | **Dropped** | No clicking ⇒ nothing to confirm. We always display the recommended action plus alternative metrics. |

## 1. Goal & interaction model

The user clicks "Share screen", picks their Lost Ark window/monitor, and opens
the astrogem cutting screen in-game. The app then, for every detected frame:

- Detects the cutting state (gem type, will/chaos/first/second levels, starting
  effects, rerolls remaining, current step / total steps, and the 4 offer cards).
- Computes and **displays**:
  - **Recommended action**: PROCESS / REROLL / RESET / FINISH — identical logic
    to `decide_post_roll` used by `auto`/`sim`.
  - **Metrics**: P(goal), P(relic+ ≥16 pts), P(ancient ≥19 pts), expected end
    **coefficient / gem value**.
  - **Per-offer breakdown**: the 4 detected cards with their deltas and which
    offer the recommendation favors (and post-click metrics where relevant).

The tool is **stateless per frame**: the player drives the game, so each stable
detection is analyzed independently against the configured goal. There is no
internal RNG, no run state machine, no clicking, and no confirm gate.

## 2. Architecture — three layers

### (a) Vision layer (JS/TS)

Copy locator-v2's capture scaffolding (`src/lib/cv/`) as the starting point:

- `getDisplayMedia()` → `MediaStreamTrackProcessor` → VideoFrame stream.
- Web Worker running OpenCV.js (`@techstark/opencv-js`); zero-copy VideoFrame
  ownership transfer to the worker.
- Anchor-caching ROI optimization (first match is global; subsequent frames
  search the cached region — locator-v2 reports ~80% latency reduction).
- OffscreenCanvas debug rendering back to the main thread for a debug view.

Reuse the **existing `arkgrid/vision/templates/` set** (anchor, gem_type×6,
willpower×5, chaos×5, option names×14, option deltas×27, side-node names/deltas,
rerolls×10, steps×9, points×3, rarity×3, finish×5). Pack them into a sprite
atlas with locator-v2's `scripts/generate-sprite.cjs` and generate a
template-coords map (mirroring locator-v2's `opencv-template-coords/`).

Port the matching/parsing logic from `arkgrid/vision/template_recognizer.py`
(ROI offsets/thresholds from `arkgrid/vision/constants.py`). Output is a
`DetectionResult` mirroring the Python dataclass: `gem_type`, `willpower`,
`chaos`, `first_effect`/`first_level`, `second_effect`/`second_level`,
`rerolls`, `current_step`/`total_steps`, and `options[]`
(`name_key`, `delta_key`, scores), each with a confidence score. Helpers
`parse_rerolls`, `parse_delta`, `determine_option_kind` port alongside.

### (b) Brains layer (TS port of `arkgrid` core)

Ported module-for-module so it tracks the Python:

| TS module | Python source | Contents |
|-----------|---------------|----------|
| `constants.ts` | `constants.py` | Effect definitions, coefficients, priorities, gem-type maps, `FUSION_E_POINTS`, `fusion_avg_coeff()`. |
| `models.ts` | `models.py` | `Option`, `LastTurnGoal`, `GemState`, `AstroGem`. |
| `pool.ts` | `pool.py` | `OptionPool`: 27-entry weighted pool, per-turn eligibility filtering, the transition weights the DP consumes. |
| `probability.ts` | `probability.py` | `GoalProbabilityTable` (effect-aware + reroll-aware DP, the default mode), `SideValueTable`. `lookup`, `expected_prob_after_click`, `should_reroll_dp`, `gem_value`, `expected_value_after_click`. |
| `decision.ts` | `decision.py` | `DecisionContext`, `TurnInput`, `Decision`, `compute_post_roll_metrics`, the branch helpers, and `decide_post_roll`. |

The effect-aware + reroll-aware DP is the only runtime mode (per CLAUDE.md), so
the port targets that mode plus the `SideValueTable` variants
(side-value-finish, goal-independent grade-value, maxed oracle). BIS-aware mode
is a documented no-op and is **out of scope** for the port.

### (c) UI layer (Svelte)

- **Config panel** (state persisted to localStorage via `svelte-persisted-state`,
  as locator-v2 does):
  - *Core (always visible):* goal (min will, min chaos, side-node goals
    `min_first`/`min_second`/`min_side_coeff`), gem rarity (common 5 / rare 7 /
    epic 9 turns), relic/ancient coefficient valuation (`--relic-coeff` /
    `--ancient-coeff`; default = fusion-derived average for the gem type).
  - *Advanced (collapsible expander):* `endgame_risk`,
    `relic_reroll_threshold`, `force_reroll_no_progress`, extra-ticket
    enablers (`extra_ticket` tri-state, `reroll_min_coeff`, `reroll_goal` +
    `reroll_goal_threshold`), `optimize` (dps/support — usually auto-resolved
    from detected effects), `ignore_side_node_values`.
  - All knobs default to the Python defaults so the tool works untouched.
- **Capture controls:** Start/Stop screen share, debug canvas toggle, capture
  status (Idle → Loading → Recording), and detection-confidence indicators.
- **Advisor panel:** detected state (with per-field confidence), the
  recommended action prominently, the metric block (P(goal) / P(relic+) /
  P(ancient) / E[value]), and the per-offer table.

## 3. Data flow

```
Worker: VideoFrame → OpenCV template match → DetectionResult
   │ postMessage(DetectionResult + debug ImageBitmap)
   ▼
Main thread:
   DetectionResult → GemState + offers[] (Option) + TurnInput
   on gem-type change → (re)build DP tables → DecisionContext   [cached per gem type]
   decide_post_roll(ctx, ti) → Decision + metrics
   render advisor panel
```

DP tables are cached per gem type (mirroring the Python `_DP_CACHE` in
`automation.py`): one effect-aware table per gem type covers all effect configs.
Decision recomputation is debounced so it only fires when the detected state
actually changes between frames.

## 4. Configuration → engine mapping

Detected `DetectionResult` maps to engine inputs:

- `gem_type` + detected `first_effect`/`second_effect` → `AstroGem` (drives
  effect-aware DP table selection and `optimize` auto-resolution).
- `willpower`/`chaos`/`first_level`/`second_level`/`rerolls` → `GemState`.
- `current_step`/`total_steps` → `turn` / `turns_left`.
- `options[]` → `Option[]` via `determine_option_kind` + `parse_delta`.
- Reset availability: inferred from step (a reset is offered only before any
  processing on a fresh run) — surfaced as a config toggle if detection can't
  determine it reliably.

User config (`LastTurnGoal`, coeffs, advanced knobs) is combined with the
detected gem to build the `DecisionContext` once per gem type.

## 5. Parity strategy (critical)

Python remains the source of truth; the TS port must not silently drift.

- **Golden-vector export:** a new `tools/export_golden.py` enumerates many
  `(gem config, goal, state, offers, rerolls, turn)` inputs, runs them through
  the **real** `decide_post_roll` + DP lookups, and dumps JSON records of
  `{inputs, action, branch, p_goal, p_relic, p_ancient, e_value}`.
- **TS golden suite:** a Vitest suite in `web/` loads that JSON and asserts the
  TS port reproduces each record — **action and branch exactly**, probabilities
  and expected value within a small tolerance (e.g. 1e-6 for DP lookups; the DP
  is deterministic so tolerance covers float formatting only).
- Coverage spans: every gem type, goal shapes (will/chaos mins, side-node
  goals, min_total), every decision branch (reroll/reset/finish/process/
  infeasibility/dead-goal grade chase/maxed-hold), reroll-budget variations,
  and the relic/ancient-coeff defaults.
- Regenerating golden vectors is a documented step; CI/check runs the suite so
  any Python change that isn't mirrored in TS fails fast.

## 6. Testing

- **Brains:** Vitest unit tests per module (pool weights, DP lookups on known
  states, decision branches) **plus** the golden-vector parity suite (§5).
- **Vision:** run the TS recognizer against a subset of the ~60 `examples/`
  screenshots (ported as fixtures) and compare the produced `DetectionResult`
  to Python's detection on the same images.
- `web/` gets its own `npm test` / `npm run check` (svelte-check + tsc), mirroring
  locator-v2.

## 7. Deployment

GitHub Pages, fully client-side, via `gh-pages -d web/dist` (as locator-v2 uses
`gh-pages -d dist`). Vite `base` set to the Pages subpath for this repo
(exact path confirmed when wiring deploy — likely `/AstrogemCutter/` or a
dedicated project path). No server, no backend.

## 8. Risks & mitigations

1. **Port fidelity** — `probability.py` + `decision.py` are ~2,200 lines of
   subtle DP/decision logic. *Mitigation:* golden-vector harness (§5) gates the
   port; build the export script and a first parity test before porting the bulk.
2. **Real-time DP rebuilds** — must stay under a frame on gem-type change.
   *Mitigation:* per-gem-type caching (as Python already does); measure the TS
   build time early and confirm it's well under budget.
3. **Detection accuracy across resolutions** — locator-v2 already solves
   FHD→4K scaling; reuse its `normalize_to_fhd`/scaling approach.

## 9. Out of scope (YAGNI)

- Manual gem-state entry form (detection is the only input — locked decision).
- Clicking / controlling the game; confirm gate; F1–F4 hotkeys.
- BIS-aware DP mode (documented no-op in the Python).
- Modeling gold/cost-per-tap (the project intentionally does not model gold;
  gem supply is the bottleneck).
- Multi-character profiles / persistence beyond the config panel's localStorage.

## 10. Module/file layout (proposed)

```
web/
  index.html
  package.json  vite.config.ts  tsconfig*.json  svelte.config.js
  public/                       # sprite atlas + template-coords output
  src/
    main.ts  App.svelte  app.css
    lib/
      engine/                   # the TS port of the brains
        constants.ts  models.ts  pool.ts  probability.ts  decision.ts
      cv/                       # ported from locator-v2 + arkgrid/vision
        captureController.ts  captureWorker.ts  recognizer.ts
        atlas.ts  matcher.ts  templateCoords.ts  cvLoader.ts
      state/                    # svelte-persisted config stores
    components/                 # config panel, capture controls, advisor panel
  tests/                        # vitest: unit + golden parity + recognizer fixtures
tools/
  export_golden.py             # NEW: Python golden-vector exporter
```
