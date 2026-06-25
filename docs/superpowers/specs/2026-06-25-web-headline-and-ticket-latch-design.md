# Web advisor: action-conditioned headline, ticket-spent latch, copy-JSON

**Date:** 2026-06-25
**Scope:** `web/` advisor UI + engine. No Python changes.

## Problem

Three issues observed in the web advisor:

1. **Headline doesn't match the recommendation.** The big `P(click)` block
   (`AdvisorPanel.svelte`) shows `output.pGoal/pRelic/pAncient/eValue`, which
   `advise()` (`web/src/lib/engine/index.ts:323-326`) computes as a
   *position-value* DP lookup of the current state — an average over all possible
   offer draws, independent of `decision.action` and of the offers actually on the
   table. So when the hand is better than average (e.g. a juicy `Attack Power +3`),
   the headline (30.5%) sits *below* the action it recommends (Process 31.8%),
   which is confusing. The user expects: recommend Process → show the Process odds;
   recommend Reroll → show the post-reroll odds.

2. **"used" caption is misleading.** `ActionMatrix.svelte:39,43` appends `— used`
   based solely on `ticket.lent` (= "the recommendation's reroll budget included
   the ticket this frame"). It is a per-frame look-ahead lend, not a record that
   the ticket was spent — and the recommended action here was Process, which spends
   no reroll at all. "used" reads as past-tense consumption that never happened.

3. **Stateless ticket over-lending.** The extra reroll ticket is once per cutting
   process. `ticketAvailableFromDetection` (`web/src/lib/app/ticket.ts`) assumes it
   is available whenever free rerolls remain (the in-game "Charge" button only shows
   once free rerolls hit 0). Gap: after the player spends the charge, if free
   rerolls later replenish (a "+N rerolls" pool option), the heuristic returns
   `true` again (free > 0 ⇒ assume available) and **re-lends an already-spent
   ticket**. The immediate-next-frame case is already handled (free stays 0 ⇒
   heuristic consults `chargeEnabled`); the unhandled case is replenishment.

Plus a feature request: a **Copy JSON** button to export all relevant state in a
readable form for sharing/debugging.

## Domain note (corrected mechanic)

- **Extra reroll ticket**: once per *cutting process*. A reset starts a new cutting
  process, so the extra reroll ticket **renews after a reset**.
- **Reset ticket**: once per *gem* (only one reset, ever).

Therefore the ticket-spent latch must clear on **new-gem OR reset** — both restart
the cutting process. (Latent, out-of-scope: the Python sim documents
`ticket_available` as persisting across a reset, which contradicts this; flagged,
not fixed here.)

## Changes

### 1. Headline follows the recommended action — `advise()` in `engine/index.ts`

After building the `actions` map and `decision`, set the returned
`pGoal/pRelic/pAncient/eValue` to the recommended action's row:

- `decision.action === PROCESS` → `actions.process`
- `=== REROLL` → `actions.reroll`
- `=== RESET` → `actions.reset`
- `FINISH` / `FAIL` (or a null row) → fall back to the existing position-value
  lookup (`probTable.lookup(state, turnsLeft, rerolls)` etc.). Finishing locks in
  the current gem, so its position value is the right number; there is no projected
  action row for FINISH/FAIL.

The position-value lookups stay in the function as the fallback. Result: the
headline equals the highlighted cell of the matrix, at the lent budget.

### 2. Turn log → action-conditioned (inherits change 1)

`turnLog.observe` is fed `output.pGoal/…` (`CaptureControls.svelte:34`), so it
becomes action-conditioned automatically. Decision: keep it that way — the log has
an **Action** column, so "turn 2 · process · 31.8%" is a coherent decision history
matching the live panel. No code change beyond change 1. (The row's will/chaos/
levels are the pre-action state while the prob is post-action; the Action column
disambiguates.)

### 3. Ticket-spent latch — new `web/src/lib/state/ticketRun.state.svelte.ts`

A run-scoped latch, separate from `turnLog` to avoid an ordering hazard
(`computeAdvice` must READ the latch before `turnLog.observe` runs).

```ts
class TicketRun {
  spent = $state(false);
  #prev: { turn: number; id: RunIdentity } | null = null;

  /** Call once per committed frame, BEFORE computeAdvice. */
  observe(det: DetectionResult, freeRerolls: number): void {
    const turn = turnFromDetection(det);
    const id: RunIdentity = { gemType: det.gemType, firstEffect: det.firstEffect, secondEffect: det.secondEffect };
    const t = classifyRunTransition(this.#prev, { turn, id });
    if (t === 'new-gem' || t === 'reset') this.spent = false; // fresh cutting process → fresh ticket
    this.#prev = { turn, id };
    // Latch: free rerolls exhausted AND Charge greyed ⇒ spent (or never owned).
    if (freeRerolls <= 0 && det.chargeEnabled === false) this.spent = true;
  }

  clear(): void { this.spent = false; this.#prev = null; }
}
export const ticketRun = new TicketRun();
```

- Reuses `classifyRunTransition` (`app/runTransition.ts`) — single source of
  run-transition truth — so it clears on both new-gem and reset.
- `turnFromDetection(det)` = `(det.totalSteps ?? 0) - (det.currentStep ?? 0) + 1`.
  Extract this one-liner into `app/runTransition.ts` (or a shared helper) and use it
  from both `turnLog` and `ticketRun` so the formula can't drift.
- `freeRerolls` = `parseRerolls(det.rerolls, false)` (free count, ticket excluded).

### 4. Thread the latch into the advice path

- `computeAdvice(det, stored, resetObserved, ticketSpent = false)` gains a
  `ticketSpent` param. Line 44 becomes
  `const available = owned && !ticketSpent && ticketAvailableFromDetection(det, free);`
- `syncAdvice(det, config, resetObserved, ticketSpent, logTurn, sink)` gains the
  param and forwards it.
- `CaptureControls.commit(det)`: parse free rerolls, call `ticketRun.observe(det, free)`
  *before* `syncAdvice`, then pass `ticketRun.spent`. The config-recompute `$effect`
  reuses `ticketRun.spent` **without** re-observing (same frame).

### 5. Caption rework — `TicketComparison` + `ActionMatrix.svelte`

- Add `spent: boolean` to `TicketComparison` (set from `ticketRun.spent` in
  `computeAdvice`, alongside `lent`/`free`).
- Drop the bare `— used`. Instead:
  - Mark the column the recommendation actually used (`lent ? withTicket : withoutTicket`)
    with a "✓ recommended" badge.
  - When `spent`, the **With extra reroll** column is greyed/info-only and captioned
    "— already used this gem" (now "used" is accurate). The column is still rendered
    (what-if), just visibly unavailable. When `spent`, `lent` is false so the
    recommendation is on the **Without** column.

### 6. Copy-JSON button — new `web/src/lib/app/snapshot.ts` + button in `AdvisorPanel`

Pure builder, unit-testable:

```ts
buildAdvisorSnapshot(det: DetectionResult, config: AdvisorStoredConfig, output: AdvisorOutput): object
```

Curated, readable shape (not the raw score-heavy `DetectionResult`):

- `gem`: gemType, optimize, will, chaos, first {effect, level}, second {effect, level},
  freeRerolls, resetAvailable, chargeEnabled, step `{current, total}`.
- `goal`: the effective goal + knobs (from `effectiveConfig`).
- `advice`: action, branch, reason, headline `{pGoal, pRelic, pAncient, eValue}`,
  `actions` (process/reroll/reset), `perOffer`.
- `ticket`: owned, lent, spent, free, withTicket/withoutTicket summaries.
- `turnLog`: the logged entries.

Button lives in the advisor panel header; on click → `JSON.stringify(snapshot, null, 2)`
→ `navigator.clipboard.writeText` (secure context on GitHub Pages / localhost) with a
transient "Copied!" state and a try/catch fallback.

## Module boundaries

- `engine/index.ts` — headline selection (pure, no new deps).
- `state/ticketRun.state.svelte.ts` — new latch store (depends on `runTransition`,
  `cv/types`, `cv/parse`).
- `app/runTransition.ts` — add exported `turnFromDetection` helper.
- `app/ticket.ts` / `app/computeAdvice.ts` / `app/adviceSync.ts` — thread `ticketSpent`.
- `app/snapshot.ts` — new pure JSON builder.
- `components/ActionMatrix.svelte` — caption/greying from `lent` + `spent`.
- `components/AdvisorPanel.svelte` — Copy JSON button.
- `components/CaptureControls.svelte` — wire `ticketRun.observe` + pass `spent`.

## Testing (TDD)

- `engine`: headline equals recommended action's row for PROCESS/REROLL/RESET;
  falls back to position value for FINISH/FAIL.
- `ticketRun`: latches on `free===0 && chargeEnabled===false`; clears on new-gem
  and on reset; persists `spent` across a same-run frame where free replenishes
  (`chargeEnabled` true/null) — the core regression.
- `computeAdvice`: `ticketSpent=true` forces `lent=false` and sets `ticket.spent`.
- `snapshot`: shape + curated fields, stable given a fixed detection/output.
- `ActionMatrix`: caption shows "✓ recommended" on the lent column; "— already used
  this gem" + greyed With column when `spent`.

## Out of scope

- Python sim ticket-persists-across-reset bug (flagged only).
- `--reroll-goal` web exposure (already a documented omission).
