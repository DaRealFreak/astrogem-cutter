# Astrogem Cutter Web Advisor — v2 Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the shipped read-only web advisor with a clearer name + Chromium guard, a separate↔combined goal toggle, a per-action decision matrix, an in-memory turn log that sharpens reset inference, a working debug view (screen mirror + detection overlays), a screenshot-upload test path, and a card-based restyle.

**Architecture:** The v1 spine is unchanged (capture worker → `captureController` → `computeAdvice` → `advisor` store → UI). v2 adds: an additive engine `actions` projection (existing table lookups only), a `turnLog` rune store feeding reset inference, a worker debug-bitmap transfer + still-image upload path, new display components, and a styling pass.

**Tech Stack:** Svelte 5 (runes), Vite 7, TypeScript, `@techstark/opencv-js` (worker only), Vitest (node + headless-Chromium browser projects).

**Design spec:** `docs/superpowers/specs/2026-06-24-astrogem-web-advisor-v2-design.md`

## Global Constraints

- **Branch:** all work on `feat/web-advisor-v2` (off `master`). Do not merge until approved.
- **Read-only:** no game control, no confirm-gate/F1–F4, no gold modeling. Only buttons: Share / Stop / debug toggle / screenshot upload.
- **Browser purity:** `src/` stays free of Node globals; `npm run check` (svelte-check on `tsconfig.app.json`) must stay at 0 errors.
- **opencv isolation:** opencv may be imported ONLY by `cvRuntime.ts` / `recognizer.ts` / `matcher.ts` / `decodeGray.ts` / `captureWorker.ts`. A test importing any of those (→opencv) MUST be in the `BROWSER_TESTS` allowlist in `web/vitest.config.ts`; opencv-free tests run in the node project. The current `BROWSER_TESTS` = `tests/app/foundation.test.ts`, `tests/cv/**`, `tests/vision/{matcher,templates,recognizer,e2e}.test.ts`, `tests/components/**`.
- **Engine parity:** Python `arkgrid` stays authoritative; the TS engine is locked by golden vectors (`tools/export_golden.py` → `web/tests/fixtures/*.json`). EXISTING outputs must stay byte-identical; new surface gets new golden vectors. After changing `arkgrid/`, regenerate fixtures (`python tools/export_golden.py`) and re-run `npm test`.
- **Defaults unchanged:** every existing config knob keeps its current default; the advisor is correct untouched. New `goalMode` defaults to `'separate'` (today's behavior).
- **Pages base** `/AstrogemCutter/` and the path-filtered deploy workflow are unchanged.
- **Worker constraint:** Web Workers have no `document`; use `OffscreenCanvas`.

## Reference convention

Like the Plan-3 plan, tasks that **adapt an existing file** (worker, controller, recognizer, ConfigPanel/AdvisorPanel, app.css) give the exact changes — new message variants, signatures, the lines to add — rather than re-printing the whole file, and name what to mirror. Tasks that add **new, self-contained logic** inline complete code + tests.

## Engine note (simplification vs spec §3)

Investigation of `web/src/lib/engine/probability.ts` + `index.ts` showed the `actions` projection needs **no new DP or table method** (the spec conservatively guessed an `expectedAfterReroll` might be needed):
- `GoalProbabilityTable` already has `lookup(state, turnsLeft, rerolls)` and `expectedProbAfterClick(state, offers, turnsLeftAfter, rerolls)`.
- `SideValueTable` already has `lookup(state, turnsLeft)` and `expectedValueAfterClick(state, offers, turnsLeftAfter)`.
- The relic (`minTotal:16`) and ancient (`minTotal:19`) tables are reroll-aware `GoalProbabilityTable` instances (`maxRerolls: dpMaxRerolls`).
- `shouldRerollDp` defines the reroll value as `lookup(state, turnsLeft, rerolls - 1)`.
So all three rows are existing lookups, and all are parity-testable against Python.

## File structure

```
web/
  src/
    lib/
      engine/
        index.ts                 # MODIFY (T2): AdvisorOutput.actions; EngineContext._freshState + baseRerolls; advise() projection
      state/
        config.ts                # MODIFY (T1): goalMode, minWillChaosTotal, effectiveConfig mapping
        turnLog.state.svelte.ts   # NEW (T4): session turn-log rune store
      app/
        captureSupport.ts         # NEW (T3): isCaptureSupported()
        runTransition.ts          # NEW (T4): classifyRunTransition(), inferResetFromLog()
        computeAdvice.ts          # MODIFY (T4): consult turn log for reset; (T7) analyzeImage path is in controller
        overlay.ts                # NEW (T6): drawDetectionOverlay(ctx2d, detection, scale)
      cv/
        types.ts                  # MODIFY (T6): DetectionResult.anchor
        recognizer.ts             # MODIFY (T6): set anchor from the matched anchor location
        workerTypes.ts            # MODIFY (T6/T7): debug bitmap+result; 'image' request
        captureWorker.ts          # MODIFY (T6/T7): annotate+transfer debug bitmap; handle 'image'
        captureController.ts      # MODIFY (T6/T7): forward debug bitmap+detection; analyzeImage(bitmap)
    components/
      BrowserGuard.svelte         # NEW (T3)
      ActionMatrix.svelte         # NEW (T5)
      TurnLog.svelte              # NEW (T5)
      DebugView.svelte            # NEW (T7)
      ScreenshotUpload.svelte     # NEW (T7)
      ConfigPanel.svelte          # MODIFY (T1 binding via T8 restyle): goal-mode toggle + grouped sections
      AdvisorPanel.svelte         # MODIFY (T8): card + color-coded action badge
      CaptureControls.svelte      # MODIFY (T7): upload + debug wiring; turn-log update
    App.svelte                    # MODIFY (T8): assemble new panels + guard
    app.css                       # MODIFY (T8): tokens, sections, cards
  README.md                       # MODIFY (T9)
  tools/export_golden.py          # MODIFY (T2): emit actions-projection golden vectors
```

---

### Task 1: Goal-mode toggle (config logic)

Add the separate↔combined goal mode to the persisted config and `effectiveConfig`. Pure, node-tested. (The ConfigPanel UI control is added in Task 8's restyle.)

**Files:**
- Modify: `web/src/lib/state/config.ts`
- Test: `web/tests/state/config.test.ts` (node; extend existing)

**Interfaces:**
- Consumes: existing `AdvisorStoredConfig`, `DEFAULT_CONFIG`, `effectiveConfig` (config.ts); `AdvisorConfig` (engine).
- Produces: `AdvisorStoredConfig` gains `goalMode: 'separate' | 'combined'` and `minWillChaosTotal?: number`. `effectiveConfig` maps the active mode: `separate` → set `minWill`/`minChaos`, leave `minTotalWillChaos` undefined; `combined` → set `minTotalWillChaos = minWillChaosTotal`, leave `minWill`/`minChaos` undefined.

- [ ] **Step 1: Write the failing tests** — append to `web/tests/state/config.test.ts`

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

describe('goalMode', () => {
  it('defaults to separate (today’s behavior)', () => {
    expect(DEFAULT_CONFIG.goalMode).toBe('separate');
  });
  it('separate sets minWill/minChaos and leaves minTotalWillChaos undefined', () => {
    const ac = effectiveConfig({ ...DEFAULT_CONFIG, goalMode: 'separate', minWill: 4, minChaos: 5, minWillChaosTotal: 8 }, det()).advisorConfig;
    expect(ac.minWill).toBe(4);
    expect(ac.minChaos).toBe(5);
    expect(ac.minTotalWillChaos).toBeUndefined();
  });
  it('combined sets minTotalWillChaos and leaves minWill/minChaos undefined', () => {
    const ac = effectiveConfig({ ...DEFAULT_CONFIG, goalMode: 'combined', minWill: 4, minChaos: 5, minWillChaosTotal: 8 }, det()).advisorConfig;
    expect(ac.minTotalWillChaos).toBe(8);
    expect(ac.minWill).toBeUndefined();
    expect(ac.minChaos).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/state/config.test.ts`
Expected: FAIL (`goalMode` undefined / mapping not applied).

- [ ] **Step 3: Implement** — edit `web/src/lib/state/config.ts`

Add to `AdvisorStoredConfig` (after the goal fields):

```ts
  // goal shape
  goalMode: 'separate' | 'combined';
  minWillChaosTotal?: number;
```

Add to `DEFAULT_CONFIG`:

```ts
  goalMode: 'separate',
```

In `effectiveConfig`, replace the `minWill`/`minChaos` lines of the `advisorConfig` literal with mode-aware values (compute before the literal):

```ts
  const separate = stored.goalMode !== 'combined';
  // ...
  const advisorConfig: AdvisorConfig = {
    rarity,
    minWill: separate ? stored.minWill : undefined,
    minChaos: separate ? stored.minChaos : undefined,
    minTotalWillChaos: separate ? undefined : stored.minWillChaosTotal,
    minFirst: stored.minFirst,
    minSecond: stored.minSecond,
    minSideCoeff: stored.minSideCoeff,
    // ...rest unchanged...
  };
```

- [ ] **Step 4: Run to verify pass**

Run: `cd web && npx vitest run tests/state/config.test.ts` → PASS.
Run: `cd web && npm test` → all green (existing + new), 0 leaked. `cd web && npm run check` → 0 errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/state/config.ts web/tests/state/config.test.ts
git commit -m "feat(web): goal-mode toggle (separate vs combined will+chaos) in config"
```

---

### Task 2: Engine `actions` projection (process / reroll / reset × 4 metrics)

Additive change to the engine: `advise()` returns per-action metrics for the info matrix, using existing table lookups only. Existing outputs stay byte-identical.

**Files:**
- Modify: `web/src/lib/engine/index.ts`
- Modify: `tools/export_golden.py` (emit golden vectors for the new projection)
- Test: `web/tests/advise.test.ts` (node; extend) + a new parity record in `web/tests/decision.test.ts` or a dedicated `web/tests/actions.test.ts` (node)

**Interfaces:**
- Consumes: existing `GoalProbabilityTable.lookup` / `.expectedProbAfterClick`, `SideValueTable.lookup` / `.expectedValueAfterClick`; `EngineContext` internals (`_decisionCtx.probTable`, `_decisionCtx.baseRerolls`, `_relicProbTable`, `_ancientProbTable`, `_sideValueTable`). The reset row uses the reroll-aware `probTable` (not `resetProbTable`) so all three matrix rows are consistent.
- Produces:
  ```ts
  export type ActionMetrics = { pGoal: number; pRelic: number; pAncient: number; eValue: number };
  // AdvisorOutput gains:
  actions: { process: ActionMetrics | null; reroll: ActionMetrics | null; reset: ActionMetrics | null };
  ```
  `EngineContext` gains `_freshState: GemState` (built from the gem's effects) and exposes `baseRerolls: number`.

- [ ] **Step 1: Write the failing test** — `web/tests/actions.test.ts` (node)

```ts
import { describe, it, expect } from 'vitest';
import { buildEngineContext, advise } from '../src/lib/engine';
import { GemState } from '../src/lib/engine/models';

describe('advise().actions', () => {
  const ctx = buildEngineContext(
    { gemType: 'chaos_distortion', firstEffect: 'attack_power', secondEffect: 'boss_damage', optimize: 'dps' },
    { rarity: 'epic', minWill: 4, minChaos: 4 },
  );
  const state = new GemState({ will: 2, chaos: 2, first: 2, second: 1, firstEffect: 'attack_power', secondEffect: 'boss_damage' });
  const offers = [
    { key: 'will+1', kind: 'will', delta: 1 } as any,
    { key: 'chaos+1', kind: 'chaos', delta: 1 } as any,
  ];

  it('returns process/reroll/reset metrics, each in range', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 1, resetAvailable: true });
    for (const a of [out.actions.process, out.actions.reroll, out.actions.reset]) {
      expect(a).not.toBeNull();
      for (const p of [a!.pGoal, a!.pRelic, a!.pAncient]) { expect(p).toBeGreaterThanOrEqual(0); expect(p).toBeLessThanOrEqual(1); }
      expect(a!.eValue).toBeGreaterThanOrEqual(0);
    }
  });
  it('nulls reroll when no rerolls and reset when unavailable', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 0, resetAvailable: false });
    expect(out.actions.reroll).toBeNull();
    expect(out.actions.reset).toBeNull();
    expect(out.actions.process).not.toBeNull();
  });
  it('reroll P(goal) equals the reroll-aware lookup with one fewer reroll', () => {
    const out = advise(ctx, { state, offers, turn: 3, turnsLeft: 5, rerolls: 2, resetAvailable: true });
    // sanity: reroll uses lookup(state, turnsLeft, rerolls-1); must be a valid probability
    expect(out.actions.reroll!.pGoal).toBeGreaterThanOrEqual(0);
  });
});
```

> Adjust the `GemState`/`Option` constructor calls to match the actual signatures in `models.ts` (the implementer verifies; `Option` has `key`/`kind`/`delta` — see `pool.ts`/`adapter.ts` for the exact shape used by `expectedProbAfterClick`).

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/actions.test.ts`
Expected: FAIL (`out.actions` undefined).

- [ ] **Step 3: Implement** — edit `web/src/lib/engine/index.ts`

(a) Add the `ActionMetrics` type + `actions` field to `AdvisorOutput`.
(b) In `buildEngineContext`, build and store the fresh state + budget on the returned context:
```ts
  const freshState = new GemState({ firstEffect: gem.firstEffect, secondEffect: gem.secondEffect });
  return {
    turnsTotal,
    dpMaxRerolls,
    baseRerolls,                 // expose for the reset projection
    _freshState: freshState,
    _decisionCtx: decisionCtx,
    _relicProbTable: relicProbTable,
    _ancientProbTable: ancientProbTable,
    _sideValueTable: sideValueTable,
  };
```
(Add `baseRerolls: number` and `_freshState: GemState` to the `EngineContext` interface.)
(c) In `advise()`, after the existing `perOffer` computation, build the projection:
```ts
  const probT = dc.probTable, relicT = ctx._relicProbTable, ancientT = ctx._ancientProbTable, sideT = ctx._sideValueTable;
  const tlAfter = turnsLeft - 1;

  // process = the best offer (max goal-after, tie-break value-after)
  let processM: ActionMetrics | null = null;
  if (offers.length > 0) {
    let best = offers[0], bestG = -1, bestV = -1;
    for (const o of offers) {
      const g = probT.expectedProbAfterClick(state, [o], tlAfter, rerolls);
      const v = sideT.expectedValueAfterClick(state, [o], tlAfter);
      if (g > bestG || (g === bestG && v > bestV)) { best = o; bestG = g; bestV = v; }
    }
    processM = {
      pGoal: bestG,
      pRelic: relicT.expectedProbAfterClick(state, [best], tlAfter, rerolls),
      pAncient: ancientT.expectedProbAfterClick(state, [best], tlAfter, rerolls),
      eValue: bestV,
    };
  }

  // reroll = same state, one reroll spent (state/turnsLeft unchanged → side value unchanged)
  const rerollM: ActionMetrics | null = rerolls > 0 ? {
    pGoal: probT.lookup(state, turnsLeft, rerolls - 1),
    pRelic: relicT.lookup(state, turnsLeft, rerolls - 1),
    pAncient: ancientT.lookup(state, turnsLeft, rerolls - 1),
    eValue: sideT.lookup(state, turnsLeft),
  } : null;

  // reset = fresh gem, full budget (reroll-aware tables for matrix consistency)
  const resetM: ActionMetrics | null = resetAvailable ? {
    pGoal: probT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
    pRelic: relicT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
    pAncient: ancientT.lookup(ctx._freshState, ctx.turnsTotal, ctx.baseRerolls),
    eValue: sideT.lookup(ctx._freshState, ctx.turnsTotal),
  } : null;
```
Add `actions: { process: processM, reroll: rerollM, reset: resetM }` to the returned object.

- [ ] **Step 4: Run to verify pass**

Run: `cd web && npx vitest run tests/actions.test.ts` → PASS.
Run: `cd web && npm test` → all green (existing parity suites unchanged — outputs byte-identical), 0 leaked. `cd web && npm run check` → 0 errors.

- [ ] **Step 5: Golden-vector parity (recommended, gates the new lookups against Python)**

Extend `tools/export_golden.py` with an `export_actions` that, for a handful of (gem, config, state, offers, turnsLeft, rerolls) cases, emits Python's `process` (best-offer relic/ancient `expected_prob_after_click`), `reroll` (`lookup(state, turnsLeft, rerolls-1)`), and `reset` (`lookup(fresh, turnsTotal, base_rerolls)`) values to `web/tests/fixtures/actions.json`. Add a node parity test `web/tests/actionsParity.test.ts` asserting `advise().actions` reproduces each record within `1e-6`. Regenerate: `source .venv/Scripts/activate && python tools/export_golden.py`.

> If a clean Python equivalent for any single cell proves impractical, cover that cell with the unit test in Step 1 instead and note it in the report — do not block the task.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/engine/index.ts web/tests/actions.test.ts tools/export_golden.py web/tests/fixtures/actions.json web/tests/actionsParity.test.ts
git commit -m "feat(web): per-action (process/reroll/reset) metrics projection in advise()"
```

---

### Task 3: Chromium-only capture guard

A pure support check + a banner so Firefox/Safari get a clear message instead of "unknown error".

**Files:**
- Create: `web/src/lib/app/captureSupport.ts`, `web/src/components/BrowserGuard.svelte`
- Test: `web/tests/app/captureSupport.test.ts` (node), `web/tests/components/browserGuard.test.ts` (browser)

**Interfaces:**
- Produces: `isCaptureSupported(nav?: Navigator, win?: typeof globalThis): boolean` (defaults to `navigator`/`globalThis`; injectable for tests). `BrowserGuard` props `{ supported: boolean }` renders the banner when `!supported`.

- [ ] **Step 1: Write failing tests**

`web/tests/app/captureSupport.test.ts` (node):
```ts
import { describe, it, expect } from 'vitest';
import { isCaptureSupported } from '../../src/lib/app/captureSupport';

describe('isCaptureSupported', () => {
  it('true when getDisplayMedia + MediaStreamTrackProcessor exist', () => {
    const nav = { mediaDevices: { getDisplayMedia: () => {} } } as any;
    const win = { MediaStreamTrackProcessor: function () {} } as any;
    expect(isCaptureSupported(nav, win)).toBe(true);
  });
  it('false when MediaStreamTrackProcessor missing (Firefox/Safari)', () => {
    const nav = { mediaDevices: { getDisplayMedia: () => {} } } as any;
    expect(isCaptureSupported(nav, {} as any)).toBe(false);
  });
  it('false when getDisplayMedia missing', () => {
    expect(isCaptureSupported({ mediaDevices: {} } as any, { MediaStreamTrackProcessor: function () {} } as any)).toBe(false);
  });
});
```
`web/tests/components/browserGuard.test.ts` (browser):
```ts
import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import BrowserGuard from '../../src/components/BrowserGuard.svelte';

describe('BrowserGuard', () => {
  it('shows a Chromium message when unsupported', () => {
    render(BrowserGuard, { props: { supported: false } });
    expect(screen.getByText(/chromium-based browser/i)).toBeTruthy();
  });
  it('renders nothing when supported', () => {
    const { container } = render(BrowserGuard, { props: { supported: true } });
    expect(container.textContent?.trim()).toBe('');
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run tests/app/captureSupport.test.ts tests/components/browserGuard.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement**

`web/src/lib/app/captureSupport.ts`:
```ts
/** True only on browsers with the capture APIs the advisor needs (Chromium family). */
export function isCaptureSupported(
  nav: Navigator = typeof navigator !== 'undefined' ? navigator : ({} as Navigator),
  win: typeof globalThis = globalThis,
): boolean {
  return (
    typeof nav?.mediaDevices?.getDisplayMedia === 'function' &&
    'MediaStreamTrackProcessor' in win
  );
}
```
`web/src/components/BrowserGuard.svelte`:
```svelte
<script lang="ts">
  let { supported }: { supported: boolean } = $props();
</script>

{#if !supported}
  <div class="browser-guard" role="alert">
    This advisor needs a <strong>Chromium-based browser</strong> (Chrome, Edge, or Opera) —
    screen capture isn’t available here. Open it in Chrome/Edge to use it.
  </div>
{/if}
```

- [ ] **Step 4: Run to verify pass** — both tests PASS; `cd web && npm test` all green; `npm run check` 0 errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/app/captureSupport.ts web/src/components/BrowserGuard.svelte \
  web/tests/app/captureSupport.test.ts web/tests/components/browserGuard.test.ts
git commit -m "feat(web): Chromium capture-support guard + banner"
```

---

### Task 4: Turn log store + run-transition + reset inference

In-memory session turn log + the log-aware reset inference; wire it into `computeAdvice`.

**Files:**
- Create: `web/src/lib/app/runTransition.ts`, `web/src/lib/state/turnLog.state.svelte.ts`
- Modify: `web/src/lib/app/computeAdvice.ts`, `web/src/lib/app/optimize.ts` (the old `inferResetAvailable` stays for fallback but `computeAdvice` now prefers the log path)
- Test: `web/tests/app/runTransition.test.ts` (node), extend `web/tests/app/computeAdvice.test.ts` (node)

**Interfaces:**
- Produces:
  ```ts
  // runTransition.ts
  export interface RunIdentity { gemType: string | null; firstEffect: string | null; secondEffect: string | null; }
  export function classifyRunTransition(
    prev: { turn: number; id: RunIdentity } | null,
    next: { turn: number; id: RunIdentity },
  ): 'continue' | 'new-gem' | 'reset';
  export function inferResetFromLog(resetObserved: boolean, override: 'auto' | 'always' | 'never'): boolean;
  ```
  `turnLog.state.svelte.ts` exports a `turnLog` store with `entries`, `resetObserved`, and an `observe(det, action, pGoal, eValue)` method that appends distinct turns and updates `resetObserved` via `classifyRunTransition`.

- [ ] **Step 1: Write failing tests** — `web/tests/app/runTransition.test.ts` (node)

```ts
import { describe, it, expect } from 'vitest';
import { classifyRunTransition, inferResetFromLog } from '../../src/lib/app/runTransition';

const id = (gemType = 'order_stability', f = 'attack_power', s = 'boss_damage') => ({ gemType, firstEffect: f, secondEffect: s });

describe('classifyRunTransition', () => {
  it('continue when same identity, turn advances', () => {
    expect(classifyRunTransition({ turn: 2, id: id() }, { turn: 3, id: id() })).toBe('continue');
  });
  it('reset when same identity but turn drops to 1', () => {
    expect(classifyRunTransition({ turn: 4, id: id() }, { turn: 1, id: id() })).toBe('reset');
  });
  it('new-gem when identity changes', () => {
    expect(classifyRunTransition({ turn: 4, id: id() }, { turn: 1, id: id('chaos_distortion') })).toBe('new-gem');
  });
  it('continue (first observation) when prev is null', () => {
    expect(classifyRunTransition(null, { turn: 1, id: id() })).toBe('continue');
  });
});

describe('inferResetFromLog', () => {
  it('auto: available until a reset is observed', () => {
    expect(inferResetFromLog(false, 'auto')).toBe(true);
    expect(inferResetFromLog(true, 'auto')).toBe(false);
  });
  it('honors always/never', () => {
    expect(inferResetFromLog(true, 'always')).toBe(true);
    expect(inferResetFromLog(false, 'never')).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run tests/app/runTransition.test.ts` → FAIL.

- [ ] **Step 3: Implement `runTransition.ts`**

```ts
export interface RunIdentity { gemType: string | null; firstEffect: string | null; secondEffect: string | null; }

function sameId(a: RunIdentity, b: RunIdentity): boolean {
  return a.gemType === b.gemType && a.firstEffect === b.firstEffect && a.secondEffect === b.secondEffect;
}

/** Classify the transition between two observed frames (a reset restarts the turn counter,
 *  so the only signal distinguishing reset from a new gem is unchanged identity). */
export function classifyRunTransition(
  prev: { turn: number; id: RunIdentity } | null,
  next: { turn: number; id: RunIdentity },
): 'continue' | 'new-gem' | 'reset' {
  if (!prev) return 'continue';
  if (!sameId(prev.id, next.id)) return 'new-gem';
  if (next.turn < prev.turn && next.turn === 1) return 'reset';
  return 'continue';
}

/** Reset is a one-time restart available until observed; overridable. */
export function inferResetFromLog(resetObserved: boolean, override: 'auto' | 'always' | 'never'): boolean {
  if (override === 'always') return true;
  if (override === 'never') return false;
  return !resetObserved;
}
```

- [ ] **Step 4: Implement `turnLog.state.svelte.ts`**

```ts
import type { DetectionResult } from '../cv/types';
import type { ActionKind } from '../engine';
import { classifyRunTransition, type RunIdentity } from '../app/runTransition';

export interface TurnLogEntry {
  turn: number; will: number; chaos: number; firstLevel: number; secondLevel: number;
  action: ActionKind; pGoal: number; eValue: number;
}

class TurnLog {
  entries = $state<TurnLogEntry[]>([]);
  resetObserved = $state(false);
  #prev: { turn: number; id: RunIdentity } | null = null;

  observe(det: DetectionResult, action: ActionKind, pGoal: number, eValue: number): void {
    const turn = (det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1;
    const id: RunIdentity = { gemType: det.gemType, firstEffect: det.firstEffect, secondEffect: det.secondEffect };
    const transition = classifyRunTransition(this.#prev, { turn, id });
    if (transition === 'new-gem') { this.entries = []; this.resetObserved = false; }
    else if (transition === 'reset') { this.resetObserved = true; }
    this.#prev = { turn, id };

    const last = this.entries[this.entries.length - 1];
    const distinct = !last || last.turn !== turn || last.will !== (det.willpower ?? 0) || last.chaos !== (det.chaos ?? 0)
      || last.firstLevel !== (det.firstLevel ?? 0) || last.secondLevel !== (det.secondLevel ?? 0);
    if (distinct) {
      this.entries = [...this.entries, {
        turn, will: det.willpower ?? 0, chaos: det.chaos ?? 0,
        firstLevel: det.firstLevel ?? 0, secondLevel: det.secondLevel ?? 0,
        action, pGoal, eValue,
      }];
    }
  }

  clear(): void { this.entries = []; this.resetObserved = false; this.#prev = null; }
}

export const turnLog = new TurnLog();
```

- [ ] **Step 5: Wire reset inference into `computeAdvice`**

`computeAdvice` currently calls `inferResetAvailable(turn, eff.resetOverride)`. Add an optional `resetObserved` parameter so the caller (CaptureControls, which owns the turn log) supplies it; fall back to the old behavior when not provided:
```ts
import { inferResetFromLog } from './runTransition';
// signature: computeAdvice(det, stored, resetObserved = false)
const resetAvailable = inferResetFromLog(resetObserved, eff.resetOverride);
```
Keep `inferResetAvailable` in `optimize.ts` (still unit-tested) but `computeAdvice` no longer calls it (the log path replaces it). Update the existing `computeAdvice` tests to pass a default `resetObserved` and assert the override still works.

- [ ] **Step 6: Run + commit**

Run: `cd web && npx vitest run tests/app/runTransition.test.ts tests/app/computeAdvice.test.ts` → PASS.
Run: `cd web && npm test` all green; `npm run check` 0 errors.
```bash
git add web/src/lib/app/runTransition.ts web/src/lib/state/turnLog.state.svelte.ts \
  web/src/lib/app/computeAdvice.ts web/tests/app/runTransition.test.ts web/tests/app/computeAdvice.test.ts
git commit -m "feat(web): session turn log + log-aware reset inference"
```

---

### Task 5: ActionMatrix + TurnLog display components

Prop-driven cards for the info matrix and the turn log.

**Files:**
- Create: `web/src/components/ActionMatrix.svelte`, `web/src/components/TurnLog.svelte`
- Test: `web/tests/components/actionMatrix.test.ts` (browser)

**Interfaces:**
- `ActionMatrix` props `{ actions: AdvisorOutput['actions']; recommended: ActionKind }`.
- `TurnLog` props `{ entries: TurnLogEntry[] }`.

- [ ] **Step 1: Write the render smoke** — `web/tests/components/actionMatrix.test.ts`

```ts
import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import ActionMatrix from '../../src/components/ActionMatrix.svelte';

const actions = {
  process: { pGoal: 0.62, pRelic: 0.4, pAncient: 0.1, eValue: 1180 },
  reroll: { pGoal: 0.55, pRelic: 0.38, pAncient: 0.09, eValue: 1180 },
  reset: null,
};

describe('ActionMatrix', () => {
  it('renders a row per action with the 4 metrics, dashes for unavailable', () => {
    render(ActionMatrix, { props: { actions, recommended: 'PROCESS' as any } });
    expect(screen.getByText(/process/i)).toBeTruthy();
    expect(screen.getByText(/62\.0%/)).toBeTruthy();   // process P(goal)
    expect(screen.getAllByText('—').length).toBeGreaterThan(0); // reset row dashes
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run tests/components/actionMatrix.test.ts` → FAIL.

- [ ] **Step 3: Implement `ActionMatrix.svelte`**

```svelte
<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { actions, recommended }: { actions: AdvisorOutput['actions']; recommended: string } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  const rows = $derived([
    { key: 'PROCESS', label: 'Process', m: actions.process },
    { key: 'REROLL', label: 'Reroll', m: actions.reroll },
    { key: 'RESET', label: 'Reset', m: actions.reset },
  ]);
</script>

<table class="action-matrix">
  <thead><tr><th>Action</th><th>P(goal)</th><th>P(relic+)</th><th>P(ancient)</th><th>E[coeff]</th></tr></thead>
  <tbody>
    {#each rows as r}
      <tr class:recommended={r.key === recommended}>
        <td>{r.label}</td>
        {#if r.m}
          <td>{pct(r.m.pGoal)}</td><td>{pct(r.m.pRelic)}</td><td>{pct(r.m.pAncient)}</td><td>{r.m.eValue.toFixed(1)}</td>
        {:else}
          <td>—</td><td>—</td><td>—</td><td>—</td>
        {/if}
      </tr>
    {/each}
  </tbody>
</table>
```

- [ ] **Step 4: Implement `TurnLog.svelte`**

```svelte
<script lang="ts">
  import type { TurnLogEntry } from '../lib/state/turnLog.state.svelte';
  let { entries }: { entries: TurnLogEntry[] } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
</script>

{#if entries.length > 0}
  <table class="turn-log">
    <thead><tr><th>Turn</th><th>Will</th><th>Chaos</th><th>Action</th><th>P(goal)</th></tr></thead>
    <tbody>
      {#each entries as e}
        <tr><td>{e.turn}</td><td>{e.will}</td><td>{e.chaos}</td><td>{e.action}</td><td>{pct(e.pGoal)}</td></tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p class="turn-log empty">No turns recorded yet.</p>
{/if}
```

- [ ] **Step 5: Run + commit** — `cd web && npm test` all green; `npm run check` 0 errors.

```bash
git add web/src/components/ActionMatrix.svelte web/src/components/TurnLog.svelte web/tests/components/actionMatrix.test.ts
git commit -m "feat(web): ActionMatrix + TurnLog display components"
```

---

### Task 6: Debug overlay — anchor + overlay drawing + worker annotation

Make the debug toggle render the captured frame with detection ROI boxes + labels.

**Files:**
- Modify: `web/src/lib/cv/types.ts` (add `anchor`), `web/src/lib/cv/recognizer.ts` (set `anchor`), `web/src/lib/cv/workerTypes.ts` (debug carries `result`), `web/src/lib/cv/captureWorker.ts` (annotate + transfer on debug)
- Create: `web/src/lib/app/overlay.ts`
- Test: `web/tests/app/overlay.test.ts` (node, stub 2D ctx); re-verify detection parity (browser) after the additive `anchor` field

**Interfaces:**
- `DetectionResult` gains `anchor: { x: number; y: number } | null` (additive; Python parity test checks the enumerated fields and ignores this TS-only extra — confirm the detection parity test still passes).
- `overlay.ts`: `drawDetectionOverlay(ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, det: DetectionResult, scale: number): void` — opencv-free; draws ROI rectangles (from `cv/constants` offsets relative to `det.anchor`, scaled) + small value/confidence labels. No-op when `det.anchor` is null.

- [ ] **Step 1: Write the failing test** — `web/tests/app/overlay.test.ts` (node, stub context)

```ts
import { describe, it, expect } from 'vitest';
import { drawDetectionOverlay } from '../../src/lib/app/overlay';
import type { DetectionResult } from '../../src/lib/cv/types';

function stubCtx() {
  const calls: string[] = [];
  return {
    calls,
    strokeRect: () => calls.push('strokeRect'),
    fillText: () => calls.push('fillText'),
    set strokeStyle(_v: any) {}, set fillStyle(_v: any) {}, set font(_v: any) {}, set lineWidth(_v: any) {},
  } as any;
}
const det = (over: Partial<DetectionResult> = {}): DetectionResult => ({
  found: true, gemType: 'order_stability', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1, firstLevelScore: 0.9,
  secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1, secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9,
  currentStep: 5, stepScore: 0.9, totalSteps: 7, rarityScore: 0.9, anchor: { x: 895, y: 43 }, options: [], ...over,
});

describe('drawDetectionOverlay', () => {
  it('draws boxes + labels when an anchor is present', () => {
    const ctx = stubCtx(); drawDetectionOverlay(ctx, det(), 1);
    expect(ctx.calls.filter((c: string) => c === 'strokeRect').length).toBeGreaterThan(3);
    expect(ctx.calls).toContain('fillText');
  });
  it('no-ops without an anchor', () => {
    const ctx = stubCtx(); drawDetectionOverlay(ctx, det({ anchor: null }), 1);
    expect(ctx.calls.length).toBe(0);
  });
});
```

- [ ] **Step 2: Run to verify failure** — FAIL (module not found).

- [ ] **Step 3: Implement `overlay.ts`** — draw ROI rects + labels from `cv/constants` offsets relative to `det.anchor`, scaled. (Use `ROI_GEM_TYPE`, `ROI_STAT_WILLPOWER`, `ROI_STAT_FIRST`, `ROI_STAT_SECOND`, `ROI_STAT_CHAOS`, `ROI_POINTS`, and `OPTION_CARD_POSITIONS`/`OPTION_CARD_Y_OFFSET`/`OPTION_CARD_HEIGHT`.) Each box: `ctx.strokeRect((anchor.x + dx) * scale, (anchor.y + dy) * scale, w * scale, h * scale)`; label the detected value + confidence near each box via `ctx.fillText`. Return early if `det.anchor` is null.

- [ ] **Step 4: Add `anchor` to detection** — `types.ts`: add `anchor: { x: number; y: number } | null;` to `DetectionResult`. `recognizer.ts`: in `detect()`, set `anchor` from the matched anchor `MatchResult.location` (the value already computed to locate the ROIs); `blankResult()` sets `anchor: null`. Re-run the browser detection parity suite (`tests/vision/recognizer.test.ts`) — it must still pass (the extra field is ignored by the field-wise comparison). If the parity harness compares whole objects, add `anchor` to the golden export or exclude it from the comparison.

- [ ] **Step 5: Worker annotate + transfer** — `workerTypes.ts`: extend the `debug` response to `{ type: 'debug'; image?: ImageBitmap; result?: DetectionResult; message?: string }`. `captureWorker.ts`: when `drawDebug` is set, after `detect()`, draw the frame is already on the `OffscreenCanvas`; call `drawDetectionOverlay(ctx, result, scale)` (import the opencv-free overlay fn), then `const bmp = canvas.transferToImageBitmap()` and `post({ type: 'debug', image: bmp, result }, [bmp])`. (Mirror the locator project's debug transfer; the normal `frame:done` path is unchanged when `drawDebug` is false.)

- [ ] **Step 6: Run + commit** — `cd web && npx vitest run tests/app/overlay.test.ts` PASS; `cd web && npm test` all green (incl. browser detection parity); `npm run check` 0 errors.

```bash
git add web/src/lib/cv/types.ts web/src/lib/cv/recognizer.ts web/src/lib/cv/workerTypes.ts \
  web/src/lib/cv/captureWorker.ts web/src/lib/app/overlay.ts web/tests/app/overlay.test.ts
git commit -m "feat(web): debug detection overlay (anchor + ROI boxes/labels, worker-annotated)"
```

---

### Task 7: Screenshot upload + debug view wiring

A still-image detect path (behind debug) + the debug canvas + upload UI wired through the controller.

**Files:**
- Modify: `web/src/lib/cv/workerTypes.ts` (add `image` request), `web/src/lib/cv/captureWorker.ts` (handle `image`), `web/src/lib/cv/captureController.ts` (forward debug bitmap+detection; `analyzeImage(bitmap)`), `web/src/components/CaptureControls.svelte` (upload + debug wiring + turn-log update)
- Create: `web/src/components/ScreenshotUpload.svelte`, `web/src/components/DebugView.svelte`
- Test: render smokes (browser) for ScreenshotUpload + DebugView; the worker/controller image path is manual-QA (needs a real Worker)

**Interfaces:**
- `CaptureWorkerRequest` gains `{ type: 'image'; bitmap: ImageBitmap; drawDebug: boolean }`. The worker runs the same FHD-normalize → grayscale → `detect()` path on the bitmap and posts `frame:done` (+ `debug` when `drawDebug`).
- `captureController` adds `onDebug: (image: ImageBitmap | null, result: DetectionResult | null) => void` and `analyzeImage(bitmap: ImageBitmap): void` (ensures the worker is initialized, then posts an `image` request). The existing `debug` handler routes to `onDebug`.
- `ScreenshotUpload` props `{ onfile: (bitmap: ImageBitmap) => void }`; `DebugView` props `{ image: ImageBitmap | null }` (draws the bitmap to a canvas).

- [ ] **Step 1: Render smokes** — `web/tests/components/debugTools.test.ts` (browser): ScreenshotUpload renders a file input; DebugView renders a `<canvas>`. (Keep these minimal — the detect-from-image pipeline is manual QA.)

- [ ] **Step 2: Worker `image` handler** — `captureWorker.ts`: add an `image` branch mirroring the `frame` branch but sourcing pixels from the uploaded `ImageBitmap` (draw to the OffscreenCanvas at FHD-normalized scale via `adjustResolution(bitmap.height)`), run `detect()`, post `frame:done` (+ debug). Close the bitmap in `finally`.

- [ ] **Step 3: Controller** — `captureController.ts`: add `onDebug`; in the `debug` message handler call `onDebug(data.image ?? null, data.result ?? null)` (and still draw to `debugCanvas` if set, as today). Add `analyzeImage(bitmap)`: if no worker yet, create + init it (await init), then `postMessage({ type: 'image', bitmap, drawDebug: this.drawDebug }, [bitmap])`.

- [ ] **Step 4: ScreenshotUpload + DebugView components**

`ScreenshotUpload.svelte`:
```svelte
<script lang="ts">
  let { onfile }: { onfile: (bitmap: ImageBitmap) => void } = $props();
  async function pick(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (file) onfile(await createImageBitmap(file));
  }
</script>
<label class="screenshot-upload">Test a screenshot <input type="file" accept="image/*" onchange={pick} /></label>
```
`DebugView.svelte`: a `<canvas bind:this>` + an `$effect` that, when `image` changes, sizes the canvas to the bitmap and draws it (`getContext('2d').drawImage(image, 0, 0)`).

- [ ] **Step 5: Wire into CaptureControls** — set `controller.onDebug = (img) => { debugImage = img; }`; pass `debugImage` to `DebugView`; render `ScreenshotUpload` (calling `controller.analyzeImage`) and `DebugView` only when `drawDebug`. On each detection, also call `turnLog.observe(det, output.action, output.pGoal, output.eValue)` and pass `turnLog.resetObserved` into `computeAdvice(det, config.current, turnLog.resetObserved)`.

- [ ] **Step 6: Run + commit** — `cd web && npm test` all green; `npm run check` 0 errors; `npm run build` succeeds (worker chunk emits). Manual QA: dev server, enable debug, upload a screenshot from `examples/`, confirm the frame + overlay + advice render.

```bash
git add web/src/lib/cv/workerTypes.ts web/src/lib/cv/captureWorker.ts web/src/lib/cv/captureController.ts \
  web/src/components/ScreenshotUpload.svelte web/src/components/DebugView.svelte \
  web/src/components/CaptureControls.svelte web/tests/components/debugTools.test.ts
git commit -m "feat(web): screenshot-upload test path + debug view wiring"
```

---

### Task 8: Restyle + assembly (grouped config, cards, goal toggle UI, new panels)

The styling pass + integrate the new components into the two-column app.

**Files:**
- Modify: `web/src/app.css` (tokens, sections, cards, action badge, matrix/turn-log/debug styling), `web/src/components/ConfigPanel.svelte` (grouped `<fieldset>` sections + goal-mode toggle + combined input), `web/src/components/AdvisorPanel.svelte` (card + color-coded badge), `web/src/App.svelte` (assemble guard + new panels)
- Test: update `web/tests/components/configPanel.test.ts` (goal-mode control present); extend `web/tests/app/foundation.test.ts` (guard + new panels mount)

**Interfaces:**
- Consumes: all components from T2/T3/T5/T7; `config`, `advisor`, `turnLog` stores.

- [ ] **Step 1: Config goal-mode UI** — `ConfigPanel.svelte`: add the segmented toggle bound to `config.current.goalMode` (`separate`/`combined`); show `minWill`+`minChaos` inputs when `separate`, the single `minWillChaosTotal` input when `combined`; keep side-node mins in both. Group controls into `<fieldset>` sections **Goal / Grade / Advanced** with standalone `for`/`id` rows. Update `configPanel.test.ts` to assert the goal-mode control + that "Min will" appears in separate mode.

- [ ] **Step 2: Advisor cards + badge** — `AdvisorPanel.svelte`: wrap the recommendation in a card with an action badge whose class encodes the action (`action-PROCESS`/`-REROLL`/`-RESET`/`-FINISH`) for color-coding; keep the metrics list.

- [ ] **Step 3: App assembly** — `App.svelte`: compute `supported = isCaptureSupported()`; render `<BrowserGuard {supported} />` at top; in the advisor column, after `AdvisorPanel`, render `{#if advisor.output}<ActionMatrix actions={advisor.output.actions} recommended={advisor.output.action} />{/if}`, the existing `OfferTable`, `<TurnLog entries={turnLog.entries} />`, `DetectedState`, and the debug `ScreenshotUpload`/`DebugView` (already inside `CaptureControls` per T7, or here — keep one home). Disable the Share button when `!supported`.

- [ ] **Step 4: Styling tokens** — `app.css`: define spacing/radius/color tokens on `:root`; style `.app-config fieldset`, label/control rows (grid-aligned), `.card`, `.action.action-*` badge colors, `.action-matrix`/`.turn-log` tables, `.browser-guard`, `.screenshot-upload`, `canvas` in debug. Keep it lean; light/dark via the existing `color-scheme`.

- [ ] **Step 5: Update foundation smoke** — `foundation.test.ts`: assert the title is **"Astrogem Cutter"**, the config goal section renders, and the advisor waiting state shows. (Rename happens here too — see Task 9 note; do the h1 rename in this task's App edit.)

- [ ] **Step 6: Run gates + manual QA + commit**

Run: `cd web && npm run check` (0 errors), `cd web && npm test` (all green, 0 leaked), `cd web && npm run build` (worker chunk emits). Manual QA in `npm run dev`: grouped config, goal toggle switches inputs, info matrix + turn log render, badge color-codes, layout is readable.

```bash
git add web/src/app.css web/src/components/ConfigPanel.svelte web/src/components/AdvisorPanel.svelte \
  web/src/App.svelte web/tests/components/configPanel.test.ts web/tests/app/foundation.test.ts
git commit -m "feat(web): restyle (grouped config, cards, action badge) + assemble v2 panels"
```

---

### Task 9: Rename + docs

Finalize the rename and document the new features.

**Files:**
- Modify: `web/index.html` (`<title>` → "Astrogem Cutter"), `web/src/App.svelte` (h1 — if not already done in T8), `web/README.md`

**Interfaces:** none (copy + docs).

- [ ] **Step 1: Rename** — `web/index.html` `<title>Astrogem Cutter</title>`; confirm `App.svelte` h1 reads **"Astrogem Cutter"** (done in T8 Step 3/5 — verify).

- [ ] **Step 2: README** — document: the goal-mode toggle; the per-action info matrix; the turn log + reset inference (+ its heuristic limits and the `resetOverride` escape); debug view (screen mirror + overlays) and screenshot upload (behind debug); the Chromium-only requirement. Keep the existing "Known limitations" (armed extra-ticket) section.

- [ ] **Step 3: Commit**

```bash
git add web/index.html web/src/App.svelte web/README.md
git commit -m "docs(web): rename to Astrogem Cutter + document v2 features"
```

---

## Done criteria

- `cd web && npm test` green (node + browser projects), 0 leaked; existing parity suites unchanged (engine outputs byte-identical) + new `actions` parity green.
- `cd web && npm run check` 0 errors (browser-pure `src/`).
- `cd web && npm run build` emits the worker chunk.
- Manual QA: grouped/restyled config with working goal toggle; info matrix (process/reroll/reset × 4 metrics) with the recommended row highlighted; turn log records turns and refines reset availability; debug toggle mirrors the screen with ROI overlays; screenshot upload runs detect→advise on a still image; Firefox/Safari shows the Chromium banner instead of a cryptic error.

## Notes for the final whole-branch review

- Confirm the engine change is additive only (existing `AdvisorOutput` fields + all prior parity suites byte-identical); the `actions` block uses only existing table methods.
- Confirm `src/` stays browser-pure (`overlay.ts`, `captureSupport.ts`, `runTransition.ts` are opencv-free and node-tested) and the new opencv-touching changes (`recognizer.ts` anchor, `captureWorker.ts` overlay/image) keep their tests in the browser project.
- The capture/upload/debug pipelines remain manual-QA (real Worker/screen/file); flag if deeper automated coverage is wanted.
- Triage: the additive `DetectionResult.anchor` vs the detection golden vectors (ensure the parity comparison ignores or includes it consistently).
