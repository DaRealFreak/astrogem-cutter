# web/ — Astrogem Cutter Web Advisor (client-side, in progress)

A fully client-side browser advisor for Lost Ark astrogem cutting, destined for GitHub
Pages. It will watch your shared game screen and show — read-only, like `arkgrid auto
--dry-run` — the recommended action plus goal / relic+ / ancient probabilities and the
expected end coefficient. It never controls the game; you do the clicking.

> **Status: engine + UI + capture complete.** Plans 1, 2, and 3 are now implemented. The advisor is a fully functional Svelte app with live screen capture, OpenCV.js vision, and automatic decision recommendations. It publishes to GitHub Pages on merge to `master`.

Built across three plans (see `../docs/superpowers/`):

- **Plan 1 — decision engine + parity harness** ✅ *(done)*
- **Plan 2 — vision recognizer** (OpenCV.js screen detection) ✅ *(done)*
- **Plan 3 — Svelte app shell + screen capture + UI + GitHub Pages deploy** ✅ *(done)*

## Layout

```
web/
  src/lib/engine/      # TypeScript port of the arkgrid decision brains
    constants.ts       # <- arkgrid/constants.py  (effects, coefficients, gem types)
    models.ts          # <- arkgrid/models.py      (Option, LastTurnGoal, GemState, AstroGem)
    pool.ts            # <- arkgrid/pool.py        (27-entry weighted option pool + eligibility)
    probability.ts     # <- arkgrid/probability.py (GoalProbabilityTable, SideValueTable DPs)
    decision.ts        # <- arkgrid/decision.py    (decide_post_roll branch tree)
    index.ts           # buildEngineContext() + advise() — the advisor entry point
  tests/               # vitest unit + golden-vector parity suites
    fixtures/          # golden vectors emitted by the Python (see fixtures/README.md)
```

## Developer usage

Requires Node >= 20.

```bash
cd web
npm install      # Install dependencies (one-time)
npm run dev      # Run local dev server with Svelte app + live capture/advisor
npm test         # vitest — unit + golden-vector parity + e2e (69 tests)
npm run check    # tsc --noEmit — type check on src/ and browser-compatible globals
npm run build    # Production build → dist/ with base path /astrogem-cutter/
```

## Deployment

The app deploys to GitHub Pages automatically on push to `master` (when the `feat/web-engine-port` branch is merged). A GitHub Actions workflow is path-filtered to rebuild only when `web/**`, `arkgrid/vision/templates/**`, or `.github/workflows/deploy-web.yml` change.

**One-time setup (manual):** After the first merge to `master`, go to the repo's GitHub settings → Pages and set the source to "GitHub Actions" (instead of Branch).

**Live site:** [`https://darealfreak.github.io/astrogem-cutter/`](https://darealfreak.github.io/astrogem-cutter/)

**Triggering a deploy manually:** Push to `master` (or trigger `workflow_dispatch` from the Actions tab).

The app is **read-only and advisory** — it never controls the game. It watches your shared screen, detects gem stats and offers via OpenCV template matching, runs the DP decision engine, and displays the recommended action and probabilities. You do the clicking in-game.

## Features

### Goal-mode toggle

The **Goal Mode** dropdown in the configuration panel supports two modes:

- **Separate (min will + min chaos):** Independent targets for will and chaos levels. E.g., min will = 4, min chaos = 5.
- **Combined (min total will+chaos):** A single combined target for the sum of will and chaos. E.g., min total = 9 means will + chaos ≥ 9.

The advisor recalculates probabilities and recommendations automatically when you switch modes.

### Info matrix (Action Decision Panel)

After analyzing a detected screen, the advisor displays an **Action Decision Panel** matrix with four metrics across three actions (Process / Reroll / Reset):

- **P(Goal):** Probability of achieving your configured goal from the current state.
- **P(Relic+):** Probability of reaching relic+ grade (total points ≥ 16) by gem completion.
- **P(Ancient):** Probability of reaching ancient grade (total points ≥ 19) by gem completion.
- **E[Coeff]:** Expected side-coefficient value of the final gem.

The **recommended row** (from the DP engine) is **highlighted** to draw your attention. Use this matrix to evaluate risk/reward trade-offs; the advisor shows all three paths so you can override if you prefer a different risk tolerance.

### Turn log and reset inference

The **Turn Log** panel records every detected turn in your session:

- Each entry shows the turn number, gem stats, offers, detected action, and the branch reason.
- **Reset availability** is **inferred from the log:** by default, you have one reset ticket available until you observe a reset being used. The advisor tracks whether a reset is still available based on the session history.
- **Heuristic limits:** The inference has two known edge cases:
  - **Identical back-to-back gems:** Two consecutive detected screens with the same gem stats may be interpreted as a reset (if in-game UI quirk causes a re-detection); this can slightly miscount reset availability.
  - **Mid-run joins:** If you start advising mid-run (joining an existing gem), the advisor defaults reset as available. You can override this if you know the reset was already used.
- **Manual override:** The **resetOverride** dropdown (under the Capture controls) lets you manually set reset availability to:
  - **Auto:** Infer from the session log (default).
  - **Always:** Assume the reset ticket is always available.
  - **Never:** Assume no reset ticket is available.

### Debug view and screenshot upload

Behind an optional **Debug** toggle in the Capture controls:

- **Screen Mirror + ROI Overlays:** When live capture is active, the debug panel mirrors your captured screen with OpenCV detection overlays — bounding boxes for gem stats, options, buttons, and effect ROI regions. This helps verify that detection is working correctly.
- **Screenshot Upload:** A file input to upload a `.png` screenshot (e.g., a saved frame of your game) runs the same detect→advise pipeline on the still image. Useful for testing without a live share or replaying specific scenarios.

### Chromium-only requirement

The advisor requires a **Chromium-based browser** (Chrome, Edge, Opera, Brave) for full functionality:

- **Screen capture API:** Used to record your shared screen or capture window.
- **OffscreenCanvas + WebWorker:** Used to run the OpenCV.js template-matching pipeline off the main thread without blocking the UI.

**If you open the app in Firefox or Safari,** a guidance banner appears asking you to use a Chromium browser. The app displays read-only results if detection fails, but live capture and advisor features are unavailable in those browsers.

## Known limitations

**Armed extra-ticket under advanced reroll knobs.** The web advisor is *stateless per frame*: each detected screen is advised independently, with no memory of earlier turns. The Python `auto` loop, by contrast, tracks the extra reroll ticket statefully — when the ticket is merely *armed* (the default, off-but-enableable), `auto` keeps it inactive until an enabler fires mid-run (`--relic-reroll-threshold` P(relic+) crossing, a `--reroll-goal` threshold, or a coeff enabler), then counts it from that point on. The stateless port can't reproduce that mid-run flip, so when you set one of those advanced enablers, the advisor's reroll-budget assumptions can differ slightly from `auto --dry-run` and it may recommend a different action on some frames. **With the defaults (extra ticket armed, `relic-reroll-threshold` 0, no coeff/goal enabler), behavior matches `auto` exactly** — the divergence is confined to those advanced configurations. Because the app only *advises*, the practical impact is a possible reroll-vs-process/finish recommendation difference under those settings; you remain free to reroll manually. A fuller fidelity fix (per-frame ticket-active derivation) is a possible follow-up.

## The engine API

`buildEngineContext(gem, config)` builds the DP tables once per gem type; `advise(ctx, input)`
returns the per-turn recommendation for a detected state:

```ts
import { buildEngineContext, advise } from './src/lib/engine';

const ctx = buildEngineContext(
  { gemType: 'chaos_distortion', firstEffect: 'attack_power',
    secondEffect: 'ally_damage', optimize: 'dps' },
  { rarity: 'epic', minWill: 4, minChaos: 5 });

const out = advise(ctx, { state, offers, turn, turnsLeft, rerolls, resetAvailable });
// -> { action, branch, reason, pGoal, pRelic, pAncient, eValue, perOffer[] }
```

## Parity: Python is the source of truth

The TypeScript engine is a faithful port of the Python `arkgrid` package, which stays
authoritative. The port is locked to it by **golden vectors**: `../tools/export_golden.py`
runs many inputs through the real Python `decide_post_roll` + DP lookups and dumps the results
to `tests/fixtures/*.json`. The vitest parity suites assert the TypeScript reproduces every
record — actions/branches exactly, probabilities within `1e-6`.

**After changing any `arkgrid/` decision or probability logic**, regenerate the fixtures and
re-run the tests (see `tests/fixtures/README.md`):

```bash
source .venv/Scripts/activate
python tools/export_golden.py
cd web && npm test
```

## Reference

- Design: `../docs/superpowers/specs/2026-06-23-astrogem-cutter-web-design.md`
- Plan 1 (this folder): `../docs/superpowers/plans/2026-06-24-astrogem-web-engine-port.md`
