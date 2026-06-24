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
npm run build    # Production build → dist/ with base path /AstrogemCutter/
```

## Deployment

The app deploys to GitHub Pages automatically on push to `master` (when the `feat/web-engine-port` branch is merged). A GitHub Actions workflow is path-filtered to rebuild only when `web/**`, `arkgrid/vision/templates/**`, or `.github/workflows/deploy-web.yml` change.

**One-time setup (manual):** After the first merge to `master`, go to the repo's GitHub settings → Pages and set the source to "GitHub Actions" (instead of Branch).

**Live site:** [`https://darealfreak.github.io/AstrogemCutter/`](https://darealfreak.github.io/AstrogemCutter/)

**Triggering a deploy manually:** Push to `master` (or trigger `workflow_dispatch` from the Actions tab).

The app is **read-only and advisory** — it never controls the game. It watches your shared screen, detects gem stats and offers via OpenCV template matching, runs the DP decision engine, and displays the recommended action and probabilities. You do the clicking in-game.

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
