# web/ — Astrogem Cutter Web Advisor (client-side, in progress)

A fully client-side browser advisor for Lost Ark astrogem cutting, destined for GitHub
Pages. It will watch your shared game screen and show — read-only, like `arkgrid auto
--dry-run` — the recommended action plus goal / relic+ / ancient probabilities and the
expected end coefficient. It never controls the game; you do the clicking.

> **Status: engine only.** This folder currently contains just the **decision engine** (a
> TypeScript port of the Python `arkgrid` "brains") and its parity test harness. There is
> **no UI, screen capture, or dev server yet** — those arrive in later plans. Today the only
> way to exercise `web/` is to run its tests.

Built across three plans (see `../docs/superpowers/`):

- **Plan 1 — decision engine + parity harness** ✅ *(this folder; done)*
- **Plan 2 — vision recognizer** (OpenCV.js screen detection) — not started
- **Plan 3 — Svelte app shell + screen capture + UI + GitHub Pages deploy** — not started

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
npm install
npm test         # vitest — unit + golden-vector parity (16 tests)
npm run check    # tsc --noEmit — type check
```

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
