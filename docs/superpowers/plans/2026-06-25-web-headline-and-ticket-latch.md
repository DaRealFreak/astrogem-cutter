# Web Advisor: Action-Conditioned Headline, Ticket-Spent Latch, Copy-JSON — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the advisor headline (and turn log) show the recommended action's odds for the offers actually on the table, fix stateless over-lending of the once-per-cutting-process extra ticket, clarify the with/without-ticket captions, and add a Copy-JSON button.

**Architecture:** Pure functions where possible (engine `advise()`, `ticketLatch`, `buildAdvisorSnapshot`) with thin reactive Svelte-5 wrappers (`ticketRun.state.svelte.ts`) and components. The ticket latch reuses the existing `classifyRunTransition` so it clears on new-gem *and* reset (both start a fresh cutting process). `ticketSpent` is threaded as a parameter through `computeAdvice` → `syncAdvice` → `CaptureControls`, mirroring how `resetObserved` already flows.

**Tech Stack:** TypeScript (strict), Svelte 5 (runes: `$state`, `$props`, `$effect`), Vitest + @testing-library/svelte.

## Global Constraints

- All commands run from the `web/` directory.
- Run a single test file: `npx vitest run <path>`. Run all: `npm test`. Typecheck: `npm run check`.
- No new npm dependencies.
- Svelte stores live in `src/lib/state/*.svelte.ts`; pure logic in `src/lib/app/*.ts`; pure CV types in `src/lib/cv/*.ts`.
- The extra reroll ticket is **once per cutting process** and **renews on a reset**; the reset ticket is once per gem. The latch therefore clears on `'new-gem'` *and* `'reset'` transitions.
- Commit message style: `feat(web): …` / `fix(web): …` / `refactor(web): …`.

---

### Task 1: Action-conditioned headline in `advise()`

**Files:**
- Modify: `web/src/lib/engine/index.ts:316-381` (the `advise` function)
- Test: `web/tests/advise.test.ts`

**Interfaces:**
- Consumes: existing `decidePostRoll`, `ActionKind` (already imported at `index.ts:19`), the `processM`/`rerollM`/`resetM` `ActionMetrics | null` locals.
- Produces: `advise()` returns the same `AdvisorOutput` shape, but `pGoal/pRelic/pAncient/eValue` now equal the recommended action's row when the action is `PROCESS`/`REROLL`/`RESET` (else the position-value fallback).

- [ ] **Step 1: Write the failing test**

Add to `web/tests/advise.test.ts` inside `describe('advise()', …)`:

```ts
it('headline equals the recommended action row (process/reroll/reset)', () => {
  const st = new GemState({ firstEffect: 'attack_power', secondEffect: 'ally_damage' });
  const offers = ['will+1', 'chaos+1', 'first+1', 'second+1'].map(k => byKey.get(k)!);
  const out = advise(ctx, { state: st, offers, turn: 1, turnsLeft: 9, rerolls: 1, resetAvailable: false });
  const row = out.action === 'process' ? out.actions.process
    : out.action === 'reroll' ? out.actions.reroll
    : out.action === 'reset' ? out.actions.reset : null;
  if (row) {
    expect(out.pGoal).toBe(row.pGoal);
    expect(out.pRelic).toBe(row.pRelic);
    expect(out.pAncient).toBe(row.pAncient);
    expect(out.eValue).toBe(row.eValue);
  } else {
    // FINISH/FAIL: headline falls back to the position value (>= 0)
    expect(out.pGoal).toBeGreaterThanOrEqual(0);
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/advise.test.ts`
Expected: FAIL — `out.pGoal` is the position value, not `row.pGoal` (mismatch in the `if (row)` branch).

- [ ] **Step 3: Implement**

In `web/src/lib/engine/index.ts`, rename the four position-value lookups (currently around lines 323-326) to `pos*` and keep them as the fallback:

```ts
  // Position value of the current state — the fallback headline for FINISH/FAIL,
  // where there is no projected action row (stopping locks in the current gem).
  const posPGoal = dc.probTable.lookup(state, turnsLeft, rerolls);
  const posRelic = ctx._relicProbTable.lookup(state, turnsLeft, rerolls);
  const posAncient = ctx._ancientProbTable.lookup(state, turnsLeft, rerolls);
  const posEValue = ctx._sideValueTable.lookup(state, turnsLeft);
```

Then, immediately before the `return { … }` (after `processM`/`rerollM`/`resetM` are built), add:

```ts
  // Headline = the recommended action's projected row, so the big P(click) block
  // matches the advice (recommend Process → show the Process odds for THESE
  // offers). Only PROCESS/REROLL/RESET have a row; FINISH/FAIL fall back to the
  // position value.
  const recRow =
    decision.action === ActionKind.PROCESS ? processM :
    decision.action === ActionKind.REROLL ? rerollM :
    decision.action === ActionKind.RESET ? resetM : null;
  const pGoal = recRow ? recRow.pGoal : posPGoal;
  const pRelic = recRow ? recRow.pRelic : posRelic;
  const pAncient = recRow ? recRow.pAncient : posAncient;
  const eValue = recRow ? recRow.eValue : posEValue;
```

Leave the `return { action: decision.action, …, pGoal, pRelic, pAncient, eValue, perOffer, actions: {…} }` unchanged — it already references `pGoal`/etc.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/advise.test.ts`
Expected: PASS — including the existing `'reports goal met at the cap'` test (FINISH → `posPGoal === 1`).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/engine/index.ts web/tests/advise.test.ts
git commit -m "feat(web): headline odds follow the recommended action"
```

---

### Task 2: Extract `turnFromDetection` helper

**Files:**
- Modify: `web/src/lib/app/runTransition.ts` (add export)
- Modify: `web/src/lib/state/turnLog.state.svelte.ts:19` (use the helper)
- Test: `web/tests/app/runTransition.test.ts`

**Interfaces:**
- Produces: `export function turnFromDetection(det: DetectionResult): number` — `(totalSteps ?? 0) - (currentStep ?? 0) + 1`. Consumed by `turnLog` (Task 2) and `ticketLatch` (Task 3).

- [ ] **Step 1: Write the failing test**

Add to `web/tests/app/runTransition.test.ts`:

```ts
import { turnFromDetection } from '../../src/lib/app/runTransition';
import type { DetectionResult } from '../../src/lib/cv/types';

describe('turnFromDetection', () => {
  const base = { totalSteps: 9, currentStep: 8 } as unknown as DetectionResult;
  it('maps step 8/9 to turn 2', () => {
    expect(turnFromDetection(base)).toBe(2);
  });
  it('maps step total/total to turn 1 (run start / post-reset)', () => {
    expect(turnFromDetection({ totalSteps: 7, currentStep: 7 } as unknown as DetectionResult)).toBe(1);
  });
  it('treats missing steps as 0 → turn 1', () => {
    expect(turnFromDetection({} as DetectionResult)).toBe(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/app/runTransition.test.ts`
Expected: FAIL — `turnFromDetection` is not exported.

- [ ] **Step 3: Implement**

In `web/src/lib/app/runTransition.ts`, add an import and the helper at the top (after the existing `RunIdentity` interface):

```ts
import type { DetectionResult } from '../cv/types';

/** Turn number from the on-screen step counter (mirrors turnLog's formula). */
export function turnFromDetection(det: DetectionResult): number {
  return (det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1;
}
```

In `web/src/lib/state/turnLog.state.svelte.ts`, replace line 19:

```ts
    const turn = turnFromDetection(det);
```

and extend the existing import on line 3:

```ts
import { classifyRunTransition, turnFromDetection, type RunIdentity } from '../app/runTransition';
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/app/runTransition.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/app/runTransition.ts web/src/lib/state/turnLog.state.svelte.ts web/tests/app/runTransition.test.ts
git commit -m "refactor(web): extract turnFromDetection helper"
```

---

### Task 3: Pure extra-ticket-spent latch

**Files:**
- Create: `web/src/lib/app/ticketLatch.ts`
- Test: `web/tests/app/ticketLatch.test.ts`

**Interfaces:**
- Consumes: `classifyRunTransition`, `turnFromDetection`, `RunIdentity` from `runTransition` (Task 2).
- Produces:
  - `interface TicketLatch { spent: boolean; prev: { turn: number; id: RunIdentity } | null }`
  - `function initTicketLatch(): TicketLatch`
  - `function observeTicketLatch(s: TicketLatch, det: DetectionResult, freeRerolls: number): TicketLatch`

- [ ] **Step 1: Write the failing test**

Create `web/tests/app/ticketLatch.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { initTicketLatch, observeTicketLatch } from '../../src/lib/app/ticketLatch';
import type { DetectionResult } from '../../src/lib/cv/types';

function det(over: Partial<DetectionResult> = {}): DetectionResult {
  return {
    found: true, gemType: 'order_solidity', gemTypeScore: 1,
    willpower: 1, willpowerScore: 1, chaos: 1, chaosScore: 1,
    firstEffect: 'attack_power', firstEffectScore: 1, firstLevel: 1, firstLevelScore: 1,
    secondEffect: 'boss_damage', secondEffectScore: 1, secondLevel: 1, secondLevelScore: 1,
    rerolls: '0', rerollsScore: 1, currentStep: 5, stepScore: 1, totalSteps: 7, rarityScore: 1,
    options: [], ...over,
  };
}

describe('ticketLatch', () => {
  it('latches spent when Charge is greyed with no free rerolls', () => {
    const s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false }), 0);
    expect(s.spent).toBe(true);
  });

  it('does not latch while free rerolls remain', () => {
    const s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false }), 2);
    expect(s.spent).toBe(false);
  });

  it('does not latch when Charge is still available', () => {
    const s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: true }), 0);
    expect(s.spent).toBe(false);
  });

  // REGRESSION: stateless over-lending. Spend the charge (free 0, greyed), then
  // free rerolls replenish (+N pool option) so Charge is no longer shown. The
  // latch must REMEMBER spent within the same cutting process.
  it('keeps spent after free rerolls replenish in the same run', () => {
    let s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false, currentStep: 5 }), 0);
    s = observeTicketLatch(s, det({ chargeEnabled: null, currentStep: 4 }), 2);
    expect(s.spent).toBe(true);
  });

  it('clears spent on a new gem', () => {
    let s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false, currentStep: 5 }), 0);
    s = observeTicketLatch(s, det({ gemType: 'chaos_distortion', currentStep: 7 }), 0);
    expect(s.spent).toBe(false);
  });

  it('clears spent on a reset (fresh cutting process → fresh ticket)', () => {
    let s = observeTicketLatch(initTicketLatch(), det({ chargeEnabled: false, currentStep: 3 }), 0); // turn 5
    s = observeTicketLatch(s, det({ chargeEnabled: null, currentStep: 7 }), 1); // turn 1 → reset
    expect(s.spent).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/app/ticketLatch.test.ts`
Expected: FAIL — module `ticketLatch` does not exist.

- [ ] **Step 3: Implement**

Create `web/src/lib/app/ticketLatch.ts`:

```ts
import type { DetectionResult } from '../cv/types';
import { classifyRunTransition, turnFromDetection, type RunIdentity } from './runTransition';

export interface TicketLatch {
  spent: boolean;
  prev: { turn: number; id: RunIdentity } | null;
}

export function initTicketLatch(): TicketLatch {
  return { spent: false, prev: null };
}

/**
 * Advance the once-per-cutting-process extra-ticket latch by one observed frame.
 *
 * Clears `spent` on a new gem OR a reset — both start a fresh cutting process,
 * which grants a fresh extra reroll ticket. Latches `spent` the first frame the
 * Charge button is greyed with no free rerolls left (spent this run, or never
 * owned). This is what the stateless `ticketAvailableFromDetection` heuristic
 * cannot remember once free rerolls replenish.
 */
export function observeTicketLatch(
  s: TicketLatch, det: DetectionResult, freeRerolls: number,
): TicketLatch {
  const turn = turnFromDetection(det);
  const id: RunIdentity = {
    gemType: det.gemType, firstEffect: det.firstEffect, secondEffect: det.secondEffect,
  };
  const transition = classifyRunTransition(s.prev, { turn, id });
  let spent = transition === 'new-gem' || transition === 'reset' ? false : s.spent;
  if (freeRerolls <= 0 && det.chargeEnabled === false) spent = true;
  return { spent, prev: { turn, id } };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/app/ticketLatch.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/app/ticketLatch.ts web/tests/app/ticketLatch.test.ts
git commit -m "feat(web): pure extra-ticket-spent latch (clears on new-gem/reset)"
```

---

### Task 4: Thread `ticketSpent` into `computeAdvice` + add `spent` to the comparison

**Files:**
- Modify: `web/src/lib/engine/index.ts` (add `spent: boolean` to `TicketComparison`)
- Modify: `web/src/lib/app/computeAdvice.ts` (new `ticketSpent` param; suppress lend; set `spent`)
- Test: `web/tests/app/computeAdvice.test.ts`

**Interfaces:**
- Consumes: existing `ticketEnabled`, `ticketAvailableFromDetection`.
- Produces:
  - `TicketComparison` gains `spent: boolean`.
  - `computeAdvice(det, stored, resetObserved = false, ticketSpent = false)` — when `ticketSpent` is true, the ticket is never lent and `output.ticket.spent === true`.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/app/computeAdvice.test.ts` (inside `describe('computeAdvice', …)`):

```ts
it('ticketSpent=true suppresses lending and flags the ticket spent', () => {
  // A low relic bar makes the per-turn enabler fire, so the ticket IS lent by default.
  const cfg = { ...DEFAULT_CONFIG, relicRerollThreshold: 0.01 };
  const lentByDefault = computeAdvice(complete, cfg).output!.ticket!;
  expect(lentByDefault.lent).toBe(true);
  expect(lentByDefault.spent).toBe(false);

  const spent = computeAdvice(complete, cfg, false, true).output!.ticket!;
  expect(spent.lent).toBe(false);
  expect(spent.spent).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/app/computeAdvice.test.ts`
Expected: FAIL — `computeAdvice` ignores the 4th arg and `ticket.spent` is `undefined`.

- [ ] **Step 3: Implement**

In `web/src/lib/engine/index.ts`, add `spent` to the `TicketComparison` type:

```ts
export type TicketComparison = {
  owned: boolean; lent: boolean; spent: boolean; free: number;
  withoutTicket: ActionsSnapshot; withTicket: ActionsSnapshot;
};
```

In `web/src/lib/app/computeAdvice.ts`:

Change the signature (line 13-15):

```ts
export function computeAdvice(
  det: DetectionResult, stored: AdvisorStoredConfig, resetObserved = false, ticketSpent = false,
): { ready: boolean; output: AdvisorOutput | null } {
```

Change the `available` line (currently line 44) to also require `!ticketSpent`:

```ts
  const available = owned && !ticketSpent && ticketAvailableFromDetection(det, free);
```

Add `spent: ticketSpent` to the ticket object (currently lines 63-66):

```ts
    output.ticket = {
      owned: true, lent, spent: ticketSpent, free,
      withoutTicket: snap(outFree), withTicket: snap(outTicket),
    };
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/app/computeAdvice.test.ts`
Expected: PASS (existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/engine/index.ts web/src/lib/app/computeAdvice.ts web/tests/app/computeAdvice.test.ts
git commit -m "feat(web): thread ticketSpent through computeAdvice; add spent to comparison"
```

---

### Task 5: Thread `ticketSpent` through `syncAdvice`

**Files:**
- Modify: `web/src/lib/app/adviceSync.ts` (signature + forward)
- Modify: `web/src/components/CaptureControls.svelte:40,55` (pass a `false` placeholder for now — Task 6 swaps it for `ticketRun.spent`)
- Test: `web/tests/app/adviceSync.test.ts`

**Interfaces:**
- Produces: `syncAdvice(det, config, resetObserved, ticketSpent, logTurn, sink)` — `ticketSpent` inserted after `resetObserved` (both are run-state flags).

- [ ] **Step 1: Write the failing test**

Update the three existing `syncAdvice(…)` calls in `web/tests/app/adviceSync.test.ts` to insert `false` after the `resetObserved` arg, and add a forwarding test:

```ts
// line 46:
const ok = syncAdvice(complete, easyGoal, false, false, true, sink);
// line 55:
syncAdvice(complete, easyGoal, false, false, true, sink);
// line 57:
const ok = syncAdvice(complete, harderGoal, false, false, false, sink);
// line 67:
const ok = syncAdvice({ ...complete, found: false }, easyGoal, false, false, true, sink);
```

Add a new test:

```ts
it('forwards ticketSpent so an already-used ticket is not lent', () => {
  const cfg: AdvisorStoredConfig = { ...DEFAULT_CONFIG, relicRerollThreshold: 0.01 };
  const lent = recordingSink();
  syncAdvice(complete, cfg, false, false, true, lent.sink);
  expect(lent.applied[0].ticket!.lent).toBe(true);

  const spent = recordingSink();
  syncAdvice(complete, cfg, false, true, true, spent.sink);
  expect(spent.applied[0].ticket!.lent).toBe(false);
  expect(spent.applied[0].ticket!.spent).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/app/adviceSync.test.ts`
Expected: FAIL — `syncAdvice` has arity 5; the 6-arg calls/`ticketSpent` forwarding don't compile/behave.

- [ ] **Step 3: Implement**

In `web/src/lib/app/adviceSync.ts`, change the signature and the `computeAdvice` call:

```ts
export function syncAdvice(
  det: DetectionResult,
  config: AdvisorStoredConfig,
  resetObserved: boolean,
  ticketSpent: boolean,
  logTurn: boolean,
  sink: AdviceSink,
): boolean {
  const { ready, output } = computeAdvice(det, config, resetObserved, ticketSpent);
  if (!ready || !output) return false;
  sink.applyAdvice(det, output);
  if (logTurn) sink.observeTurn(det, output);
  return true;
}
```

In `web/src/components/CaptureControls.svelte`, update both call sites to pass a `false` placeholder (Task 6 replaces it):

```ts
// in commit():
    syncAdvice(det, config.current, turnLog.resetObserved, false, true, sink);
// in the config-recompute $effect:
      if (det) syncAdvice(det, config.current, turnLog.resetObserved, false, false, sink);
```

- [ ] **Step 4: Run tests + typecheck**

Run: `npx vitest run tests/app/adviceSync.test.ts`
Expected: PASS.
Run: `npm run check`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/app/adviceSync.ts web/src/components/CaptureControls.svelte web/tests/app/adviceSync.test.ts
git commit -m "feat(web): thread ticketSpent through syncAdvice"
```

---

### Task 6: `ticketRun` store + wire into `CaptureControls`

**Files:**
- Create: `web/src/lib/state/ticketRun.state.svelte.ts`
- Modify: `web/src/components/CaptureControls.svelte` (observe before advice; pass `ticketRun.spent`)

**Interfaces:**
- Consumes: `initTicketLatch`/`observeTicketLatch` (Task 3), `parseRerolls` (`src/lib/cv/parse`), `syncAdvice` (Task 5).
- Produces: `export const ticketRun` with `observe(det, freeRerolls)`, reactive `spent: boolean`, and `clear()`.

> No new unit test: this is a thin reactive wrapper with no logic of its own — the latch behaviour (incl. the over-lending regression) is covered by Task 3. Verification is typecheck + the full suite staying green.

- [ ] **Step 1: Create the store**

Create `web/src/lib/state/ticketRun.state.svelte.ts`:

```ts
import type { DetectionResult } from '../cv/types';
import { initTicketLatch, observeTicketLatch, type TicketLatch } from '../app/ticketLatch';

/**
 * Run-scoped latch for the once-per-cutting-process extra reroll ticket. Observed
 * once per committed frame BEFORE computeAdvice reads `spent`, so the advice never
 * lends a ticket we've seen spent. Clears on new-gem/reset (handled in the latch).
 */
class TicketRun {
  spent = $state(false);
  #latch: TicketLatch = initTicketLatch();

  observe(det: DetectionResult, freeRerolls: number): void {
    this.#latch = observeTicketLatch(this.#latch, det, freeRerolls);
    this.spent = this.#latch.spent;
  }

  clear(): void {
    this.#latch = initTicketLatch();
    this.spent = false;
  }
}

export const ticketRun = new TicketRun();
```

- [ ] **Step 2: Wire into `CaptureControls`**

In `web/src/components/CaptureControls.svelte`, add imports (after the existing `turnLog` import on line 9):

```ts
  import { ticketRun } from '../lib/state/ticketRun.state.svelte';
  import { parseRerolls } from '../lib/cv/parse';
```

Replace `commit` (lines 39-41) so it observes the latch first, then passes `ticketRun.spent`:

```ts
  /** Update the advisor + turn log from a settled detection (a real turn). */
  function commit(det: DetectionResult) {
    ticketRun.observe(det, parseRerolls(det.rerolls, false));
    syncAdvice(det, config.current, turnLog.resetObserved, ticketRun.spent, true, sink);
  }
```

In the config-recompute `$effect`, swap the `false` placeholder (set in Task 5) for `ticketRun.spent` (do **not** re-observe — same frame):

```ts
      if (det) syncAdvice(det, config.current, turnLog.resetObserved, ticketRun.spent, false, sink);
```

- [ ] **Step 3: Typecheck + full suite**

Run: `npm run check`
Expected: no errors.
Run: `npm test`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/state/ticketRun.state.svelte.ts web/src/components/CaptureControls.svelte
git commit -m "feat(web): latch extra-ticket-spent per cutting process; stop re-lending after replenish"
```

---

### Task 7: ActionMatrix caption rework (recommended badge + spent greying)

**Files:**
- Modify: `web/src/components/ActionMatrix.svelte:34-49` (the `{#if ticket}` block) + add a `<style>` block
- Test: `web/tests/components/actionMatrix.test.ts`

**Interfaces:**
- Consumes: `ticket.lent`, `ticket.spent` (Task 4).

- [ ] **Step 1: Write the failing test**

Add to `web/tests/components/actionMatrix.test.ts`:

```ts
it('flags a spent ticket and marks the recommended budget', () => {
  const withoutTicket = { pGoal: 0.5, pRelic: 0.3, pAncient: 0.05, eValue: 1001,
    actions: { ...actions, reroll: { pGoal: 0.5, pRelic: 0.3, pAncient: 0.05, eValue: 1001 } } };
  const withTicket = { pGoal: 0.7, pRelic: 0.6, pAncient: 0.12, eValue: 1301,
    actions: { ...actions, reroll: { pGoal: 0.7, pRelic: 0.6, pAncient: 0.12, eValue: 1301 } } };
  render(ActionMatrix, { props: {
    actions: withoutTicket.actions, recommended: 'PROCESS' as any,
    ticket: { owned: true, lent: false, spent: true, free: 0, withoutTicket, withTicket } as any,
  } });
  expect(screen.getByText(/already used this gem/i)).toBeTruthy();
  expect(screen.getByText(/without extra reroll.*recommended/i)).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/components/actionMatrix.test.ts`
Expected: FAIL — captions still say "— used", no "already used this gem" / "recommended" text.

- [ ] **Step 3: Implement**

In `web/src/components/ActionMatrix.svelte`, replace the `{#if ticket}` block (lines 34-49) with:

```svelte
{#if ticket}
  <!-- Owned extra ticket: show both budgets. A "✓ recommended" badge marks the
       budget the advice actually used; when the ticket is known spent this run,
       the With-extra column is greyed and captioned "already used". -->
  <div class="matrix-pair">
    <div class="matrix-variant">
      <div class="matrix-caption">Without extra reroll{!ticket.lent ? ' ✓ recommended' : ''}</div>
      {@render matrix(ticket.withoutTicket.actions, !ticket.lent)}
    </div>
    <div class="matrix-variant" class:spent={ticket.spent}>
      <div class="matrix-caption">With extra reroll{ticket.lent ? ' ✓ recommended' : ''}{ticket.spent ? ' — already used this gem' : ''}</div>
      {@render matrix(ticket.withTicket.actions, ticket.lent)}
    </div>
  </div>
{:else}
  {@render matrix(actions, true)}
{/if}

<style>
  .matrix-variant.spent { opacity: 0.5; }
  .matrix-variant.spent .matrix-caption { font-style: italic; }
</style>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/components/actionMatrix.test.ts`
Expected: PASS — the new test and both existing ticket tests (prefix/substring caption matches still hold).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ActionMatrix.svelte web/tests/components/actionMatrix.test.ts
git commit -m "feat(web): clearer ticket captions — recommended badge + spent greying"
```

---

### Task 8: Copy-JSON snapshot builder + button

**Files:**
- Create: `web/src/lib/app/snapshot.ts`
- Create: `web/src/components/CopyJsonButton.svelte`
- Modify: `web/src/App.svelte` (render the button under the advisor)
- Test: `web/tests/app/snapshot.test.ts`, `web/tests/components/copyJsonButton.test.ts`

**Interfaces:**
- Consumes: `effectiveConfig` (`src/lib/state/config`), `parseRerolls`, `AdvisorOutput`, `TurnLogEntry`.
- Produces: `buildAdvisorSnapshot(det, stored, output, turnLogEntries): object` — a curated, JSON-serializable object.

- [ ] **Step 1: Write the failing snapshot test**

Create `web/tests/app/snapshot.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { buildAdvisorSnapshot } from '../../src/lib/app/snapshot';
import { computeAdvice, resetAdviceCache } from '../../src/lib/app/computeAdvice';
import { DEFAULT_CONFIG } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';

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

describe('buildAdvisorSnapshot', () => {
  it('produces a curated, serializable snapshot', () => {
    resetAdviceCache();
    const out = computeAdvice(complete, DEFAULT_CONFIG).output!;
    const snap = buildAdvisorSnapshot(complete, DEFAULT_CONFIG, out, []) as any;
    expect(snap.gem.gemType).toBe('order_stability');
    expect(snap.gem.first.effect).toBe('attack_power');
    expect(snap.gem.first.level).toBe(1);
    expect(snap.gem.freeRerolls).toBe(1);
    expect(snap.advice.action).toBe(out.action);
    expect(snap.advice.headline.pGoal).toBe(out.pGoal);
    expect(snap.advice.perOffer).toHaveLength(4);
    expect(snap.turnLog).toEqual([]);
    expect(() => JSON.stringify(snap)).not.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/app/snapshot.test.ts`
Expected: FAIL — module `snapshot` does not exist.

- [ ] **Step 3: Implement the builder**

Create `web/src/lib/app/snapshot.ts`:

```ts
import type { DetectionResult } from '../cv/types';
import type { AdvisorOutput } from '../engine';
import { effectiveConfig, type AdvisorStoredConfig } from '../state/config';
import { parseRerolls } from '../cv/parse';
import type { TurnLogEntry } from '../state/turnLog.state.svelte';

/** Curated, human-readable snapshot of the current advice for copy-to-clipboard. */
export function buildAdvisorSnapshot(
  det: DetectionResult,
  stored: AdvisorStoredConfig,
  output: AdvisorOutput,
  turnLogEntries: TurnLogEntry[],
): object {
  const eff = effectiveConfig(stored, det);
  return {
    gem: {
      gemType: det.gemType,
      optimize: eff.optimize,
      willpower: det.willpower,
      chaos: det.chaos,
      first: { effect: det.firstEffect, level: det.firstLevel },
      second: { effect: det.secondEffect, level: det.secondLevel },
      freeRerolls: parseRerolls(det.rerolls, false),
      resetAvailable: output.actions.reset !== null,
      chargeEnabled: det.chargeEnabled ?? null,
      step: { current: det.currentStep, total: det.totalSteps },
    },
    goal: eff.advisorConfig,
    advice: {
      action: output.action,
      branch: output.branch,
      reason: output.reason,
      headline: {
        pGoal: output.pGoal, pRelic: output.pRelic, pAncient: output.pAncient, eValue: output.eValue,
      },
      actions: output.actions,
      perOffer: output.perOffer,
    },
    ticket: output.ticket ?? null,
    turnLog: turnLogEntries,
  };
}
```

- [ ] **Step 4: Run the snapshot test**

Run: `npx vitest run tests/app/snapshot.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the button render test**

Create `web/tests/components/copyJsonButton.test.ts`:

```ts
import { render, screen, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach } from 'vitest';
import CopyJsonButton from '../../src/components/CopyJsonButton.svelte';
import { advisor } from '../../src/lib/state/advisor.state.svelte';

afterEach(() => { cleanup(); advisor.output = null; });

describe('CopyJsonButton', () => {
  it('is disabled while there is no advice', () => {
    advisor.output = null;
    render(CopyJsonButton);
    const btn = screen.getByRole('button', { name: /copy json/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
```

- [ ] **Step 6: Run the button test to verify it fails**

Run: `npx vitest run tests/components/copyJsonButton.test.ts`
Expected: FAIL — component does not exist.

- [ ] **Step 7: Implement the button + wire into App**

Create `web/src/components/CopyJsonButton.svelte`:

```svelte
<script lang="ts">
  import { advisor } from '../lib/state/advisor.state.svelte';
  import { config } from '../lib/state/config.state.svelte';
  import { turnLog } from '../lib/state/turnLog.state.svelte';
  import { buildAdvisorSnapshot } from '../lib/app/snapshot';

  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function copy() {
    const det = advisor.detection, output = advisor.output;
    if (!det || !output) return;
    const snap = buildAdvisorSnapshot(det, config.current, output, turnLog.entries);
    try {
      await navigator.clipboard.writeText(JSON.stringify(snap, null, 2));
      copied = true;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => (copied = false), 1500);
    } catch {
      // Clipboard blocked (insecure context / permissions) — no flash, no throw.
    }
  }
</script>

<button class="copy-json" onclick={copy} disabled={!advisor.output}>
  {copied ? 'Copied!' : 'Copy JSON'}
</button>
```

In `web/src/App.svelte`, import the component (after the `ActionMatrix` import on line 8):

```svelte
  import CopyJsonButton from './components/CopyJsonButton.svelte';
```

and render it directly under the `AdvisorPanel` (after line 29):

```svelte
        <AdvisorPanel output={advisor.output} waiting={advisor.waiting} recomputing={advisor.recomputing} />
        <CopyJsonButton />
```

- [ ] **Step 8: Run both tests + full suite + typecheck**

Run: `npx vitest run tests/components/copyJsonButton.test.ts tests/app/snapshot.test.ts`
Expected: PASS.
Run: `npm test && npm run check`
Expected: all green, no type errors.

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/app/snapshot.ts web/src/components/CopyJsonButton.svelte web/src/App.svelte web/tests/app/snapshot.test.ts web/tests/components/copyJsonButton.test.ts
git commit -m "feat(web): Copy JSON button — curated advice snapshot to clipboard"
```

---

## Self-Review

**Spec coverage:**
- Headline follows recommendation → Task 1. ✓
- Turn log action-conditioned (inherits) → Task 1 (turnLog feeds on `output.pGoal`). ✓
- Ticket-spent latch, clears on new-gem AND reset → Task 3 (pure) + Task 6 (store/wiring). ✓
- `ticketSpent` threaded → Task 4 (computeAdvice) + Task 5 (syncAdvice) + Task 6 (CaptureControls). ✓
- Caption rework (recommended badge + spent greying) → Task 7. ✓
- Copy-JSON curated builder + button → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows the full code. The only intentional placeholder is the literal `false` passed in Task 5's `CaptureControls`, explicitly swapped for `ticketRun.spent` in Task 6 (each task stays green).

**Type consistency:** `TicketComparison` gains `spent: boolean` in Task 4 and is read in Task 7; `turnFromDetection` defined in Task 2, consumed in Task 3; `initTicketLatch`/`observeTicketLatch`/`TicketLatch` defined in Task 3, consumed in Task 6; `buildAdvisorSnapshot` signature `(det, stored, output, turnLogEntries)` consistent between Task 8's builder and test and the button call. `syncAdvice(det, config, resetObserved, ticketSpent, logTurn, sink)` consistent across Task 5's impl, tests, and Task 6's call sites.

**Out of scope (unchanged):** Python sim ticket-persists-across-reset bug (flagged in spec only); `--reroll-goal` web exposure.
