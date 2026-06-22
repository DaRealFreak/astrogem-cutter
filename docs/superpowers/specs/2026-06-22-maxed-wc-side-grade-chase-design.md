# Design: risk-free side/grade chase at the will/chaos cap

**Date:** 2026-06-22
**Status:** Approved (pre-implementation)
**Flag affected:** `--ignore-side-node-values`

## Problem

Under `--ignore-side-node-values`, the goal-conditioned `side_value_table` is
built in `value_mode="will_chaos"` (`probability.py:962`): `gem_value = will +
chaos`, with grade and side-node coefficients forced to `0`.

Once a run reaches **will = 5 and chaos = 5**, `will + chaos = 10` is the cap.
Every state, every offer, and every redraw then evaluates to exactly `10`, so in
`_side_value_finish_decision`:

- `finish_val == process_ev == reroll_val == 10`.
- With a free reroll in hand, `reroll_val >= process_ev` (10 ≥ 10) → the
  "never finish with a free reroll" rule rerolls pointlessly.
- Rerolls exhausted → `finish_val >= process_ev` → finish.

The engine is blind to the fact that the gem still has turns/rerolls and that
pushing a side node (e.g. `boss_damage` 2→5) would lift total points 13→16+
(**relic+ / ancient**) at no risk to the already-secured will/chaos goal.

Observed run: goal `--min-total-will-chaos 8`, gem reached `w=5 c=5 1st=1 2nd=2`
(total 13, legendary), then rerolled twice and finished — leaving relic+ on the
table.

## Goal

Once will/chaos is capped (and the goal is therefore locked), switch the
goal-met decision from the degenerate `will_chaos` value model to chasing
`side_coeff + grade tier_bonus`, **while holding will/chaos firm** — never
risking a drop off the cap.

### Decisions locked with the user

1. **What to chase when maxed:** `side_coeff + grade tier_bonus` (the same value
   model the engine uses *without* the flag). Most literal reading of "go for
   side node values anyway." Conceptual rule: `--ignore-side-node-values` applies
   only *while will/chaos is still improvable*; at the cap, side values stop being
   ignored.
2. **Risk posture:** *Hold the max firmly.* Will/chaos is pinned at 5/5 — chase
   upside only via free rerolls and by processing hands that contain no
   `will-`/`chaos-` offer. (`Process` applies a uniformly random one of the 4
   offers, so any negative will/chaos offer in the hand is a real drop risk.)
3. **Continuation oracle:** a DP table (one extra cached `SideValueTable` per gem
   type), reusing the existing finish/reroll/process comparison machinery, rather
   than a closed-form heuristic.

## Non-goals

- No change below the cap (`will + chaos < 10`): the `will_chaos` model still
  pushes toward 10.
- No change without the flag: the default `side` value model already chases
  side+grade everywhere; "hold the will/chaos cap absolutely" is a flag-specific
  preference, not EV-optimal, so it stays scoped to the flag.
- No change to the dead-goal path: it keeps `grade_only` under the flag (the
  user opted into that — chase grade only, finish when no higher grade reachable).
- No confirm-gate (`--confirm-min-coeff`) wiring into the new branch for now
  (post-goal, low-stakes; can be added later).

## Mechanism

### Trigger

The new branch `_maxed_hold_decision` fires when **all** hold:

- `ctx.maxed_value_table is not None` (its presence is the flag signal — the
  table is built only under `--ignore-side-node-values`), **and**
- `ti.state.will == 5 and ti.state.chaos == 5`.

The goal is already known satisfied at this point (`early_finish_decision`
guards `_goal_fully_satisfied` before calling `_side_value_finish_decision`, and
`min_total_will_chaos <= 10` is met at 5/5).

### New oracle table

A third per-gem-type cached `SideValueTable`, built **only under the flag**, in
`value_mode="side"` (goal-conditioned; same `min_side_coeff` / `relic_coeff` /
`ancient_coeff` resolution as `_get_side_value_table`). It is exactly the
side-value table the engine would build *without* the flag, valuing
`side_coeff + tier_bonus`. The existing `will_chaos` (`side_value_table`) and
`grade_only` (`grade_value_table`) tables are untouched.

Because will/chaos is held at 5/5 in this branch, the oracle is only queried in
goal-satisfied territory, so goal-conditioning never zeros the queried region;
its internal backward induction stays consistent with the other tables.

### The decision

`_maxed_hold_decision` mirrors the existing `_grade_value_decision` shape —
including its finish-early-when-no-upside guard — with two additions: the
side-mode oracle and a hand-safety gate.

```
oracle      = ctx.maxed_value_table
finish_val  = oracle.gem_value(state)                              # side+grade now
process_ev  = oracle.expected_value_after_click(state, offers, turns_left - 1)
hand_safe   = no offer has kind in {will, chaos} with delta < 0    # can't drop the cap
can_reroll  = rerolls > 0 and turn != 1

if can_reroll:
    reroll_val    = oracle.lookup(state, turns_left)
    best_continue = max(reroll_val, process_ev) if hand_safe else reroll_val
    if best_continue <= finish_val + EPS:        return FINISH    # no upside → stop
    if hand_safe and process_ev >= reroll_val:   return PROCESS   # safe hand beats a redraw
    return REROLL                                                 # unsafe hand, or fishing
else:                                                             # rerolls exhausted / turn 1
    if hand_safe and process_ev > finish_val + EPS: return PROCESS
    return FINISH
```

`EPS` reuses `_GRADE_VALUE_EPS` (1e-9). Branch tag: `"maxed_hold"`.

### Behavioral consequences

- **Unsafe hands are never processed** — they become REROLL (rerolls left) or
  FINISH (none left). This is the hard "hold the max firmly" guarantee:
  will/chaos can never drop off 5/5.
- **No more pointless rerolling**: when the oracle sees no reachable upside
  (`best_continue <= finish_val`), the branch finishes even with rerolls in hand
  — the same guard the dead-goal grade path already uses. A fully-maxed gem stops
  instead of churning rerolls.
- **The reported run** (`5/5, boss_damage = 2`): the oracle sees large upside
  (`boss_damage +N` ≈ +1000 coeff/level and lifts total toward relic+/ancient),
  so it rerolls toward safe `boss_damage +N` hands and processes them, instead of
  finishing at legendary 13.

### Interaction with the reroll loop

`decide_reroll_only` consults `early_finish_decision` and acts only on a REROLL
result. At 5/5 the new branch returns:
- REROLL → the reroll loop spends a reroll and redraws (fishing for a safe hand).
  Each REROLL decrements rerolls, so the loop terminates when rerolls hit 0.
- PROCESS / FINISH → the reroll loop ignores it (not REROLL), exits, and the main
  `decide_post_roll` re-runs `_maxed_hold_decision`, returning the same
  PROCESS / FINISH. Consistent across both call sites.

## Files touched

- `arkgrid/decision.py`
  - `DecisionContext`: add `maxed_value_table: Optional[SideValueTable] = None`.
  - Add `_hand_is_wc_safe(offers)` helper.
  - Add `_maxed_hold_decision(ctx, ti, m)`.
  - Wire it at the top of `_side_value_finish_decision` (before the
    `side_value_table` block).
- `arkgrid/simulator.py`
  - `__init__`: add `_maxed_value_table_cache` and `_maxed_value_table`.
  - Add `_get_maxed_value_table(gem_type)` (mirrors `_get_side_value_table`,
    forces `value_mode="side"`).
  - `simulate_one`: set `self._maxed_value_table` per run, only under the flag.
  - `_build_context`: resolve and pass `maxed_value_table` (flag-gated).
- `arkgrid/automation.py`
  - Build the oracle inline alongside the existing two tables (≈ lines 858–881),
    flag-gated.
  - Pass `maxed_value_table=` into the `DecisionContext` construction (≈ line 981).
- `tests/test_decision.py`
  - `build_ctx`: accept/construct a `maxed_value_table`.
  - Cases: unsafe hand → REROLL; unsafe hand, no rerolls → FINISH; safe improving
    hand → PROCESS; no-upside maxed gem → FINISH despite rerolls; below-cap (5/4)
    still `will_chaos`; **regression** for the reported run (5/5 + low side node →
    chases side/grade, not a value-neutral reroll-to-finish).
- `tests/test_simulator.py`
  - `_get_maxed_value_table` built in `side` mode under the flag; not built (or
    `None`) without the flag.
- `README.md` and `CLAUDE.md`
  - Document the maxed-state behavior under `--ignore-side-node-values`.

## Risks & edge cases

- **Oracle pool-average limitation:** `SideValueTable.lookup` has no reroll
  dimension and its process arm is the pool average (includes will/chaos
  negatives). At the cap in `side` mode this can mildly *underestimate*
  safe-hand-only value, occasionally finishing slightly early when only rare
  safe gains remain. Accepted: it directly prevents the pointless-reroll
  complaint, and for target-effect side nodes (the common case) the side+ upside
  dominates so upside is detected and chased.
- **Goal with no buffer (`min_total_will_chaos = 10`):** the cap *is* the goal,
  with zero margin. Hold-firm + hand-safety still apply unchanged; the branch
  simply chases side/grade via safe moves and finishes when none remain.
- **`exact_total_will_chaos`:** an exact goal is satisfied only at the exact
  value; at 5/5 it requires `exact == 10`. Hand-safety already forbids dropping
  will/chaos, so an exact-10 goal is never broken. (Exact goals below 10 never
  reach the 5/5 trigger.)
- **Both side nodes non-target (side_coeff stays 0):** the oracle then values
  only grade (`tier_bonus`), so it chases relic+/ancient via total points and
  finishes once no higher grade is reachable — still correct, just grade-only in
  effect.
