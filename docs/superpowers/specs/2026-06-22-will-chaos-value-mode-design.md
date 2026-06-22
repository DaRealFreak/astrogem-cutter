# Will/chaos value mode — design

**Date:** 2026-06-22
**Status:** Approved (pending spec review)

## Problem

The simulator/automation are built around DPS/support *side-node* goals: the
gem's worth is `side_coeff + grade tier_bonus`, and even a pure will/chaos run
keeps cutting to improve grade because `--relic-coeff` / `--ancient-coeff`
default to fusion-derived values.

A **new character** has the opposite priority. Willpower on the gem reduces the
willpower *cost* of slotting it (more gems fit per core); chaos contributes the
points that hit a core's breakpoints (10, 14, 17, 18, 19, 20). Such a player
wants to maximise will + chaos and does **not** care about the gem's grade or
its side-node effects.

Two things are missing for this player:

1. A way to express a **combined will/chaos** goal — e.g. "total ≥ 8", met by
   5-3, 4-4, 3-5, or anything higher.
2. A way to tell the engine to **ignore side-node / grade value** and optimise
   purely for will/chaos.

## Goals

- Add `--min-total-will-chaos N`: success requires `will + chaos ≥ N`.
- Add `--ignore-side-node-values`: switch the gem *value model* from
  `side_coeff + tier_bonus` to `will + chaos`, so the engine pushes will/chaos
  as high as it safely can after the goal is met.
- Preserve all existing behaviour when neither flag is set.

## Non-goals

- No `--exact-total-will-chaos` (YAGNI; only the "or better" form was asked
  for).
- No re-weighting of will vs chaos — the value is the plain sum `will + chaos`,
  matching how the combined goal is framed.
- No change to what counts as **success**: the will/chaos goal still defines it.
  `--ignore-side-node-values` only changes finish / continue / dead-goal value
  decisions.

## Background: where value enters today

The combined-total goal is *already* modelled end-to-end and only needs CLI
wiring:

- `LastTurnGoal.min_total_will_chaos` exists; `satisfied()` and `feasible()`
  already handle it, as do the DP terminal conditions and
  `decision.has_progress_offer`.
- It is simply not reachable from the CLI (`_resolve_args` never populates it).

Side-node / grade value enters per-turn decisions in exactly two places, both
via `SideValueTable` instances on `DecisionContext`:

| Table | Built with | Value today | Drives |
|---|---|---|---|
| `side_value_table` | the real goal (goal-conditioned: 0 when goal broken) | `side_coeff + tier_bonus` | **Goal met:** finish vs continue/reroll (`_side_value_finish_decision`) |
| `grade_value_table` | a trivial always-satisfied goal (goal-independent) | `side_coeff + tier_bonus` | **Dead goal:** maximise gem value (`_grade_value_decision`) |

The goal-probability DP (`prob_table` / `reset_prob_table`) already ignores side
nodes entirely when the goal carries no `min_first` / `min_second` /
`min_side_coeff` constraint, so pre-goal pursuit needs no change.

## Approach

### Flag 1 — `--min-total-will-chaos N`

Pure wiring:

- `cli.py`: populate `LastTurnGoal(min_total_will_chaos=args.min_total_will_chaos)`
  in `_resolve_args`; add the flag to `add_common` and to the `report` filter
  args; render it in `_print_config` and the `live` / `sim` goal summaries.
- `models.py`: add a `> 10` infeasibility guard in `LastTurnGoal.feasible()`
  for `min_total_will_chaos` and `exact_total_will_chaos` (will + chaos cap at
  5 + 5 = 10), mirroring the existing `> 5` guards for `min_will` / `min_chaos`.

### Flag 2 — `--ignore-side-node-values`

Add a `value_mode` parameter to `SideValueTable`:

- `"side"` (default) — current behaviour: `gem_value = side_coeff + tier_bonus`.
- `"will_chaos"` — `gem_value = will + chaos`; `relic_coeff` and `ancient_coeff`
  are forced to `0` for this table (no grade contribution), and the
  `min_side_coeff` floor in `_gem_value_idx` is ignored (we are ignoring side
  nodes). The backward-induction DP, the `max(finish, process)` structure, and
  the effect-change transitions (value no-ops for will/chaos) are otherwise
  unchanged.

When `--ignore-side-node-values` is set, only **one** of the two tables changes:

| Table | Under the flag | Rationale |
|---|---|---|
| `side_value_table` (goal-conditioned) | `value_mode="will_chaos"` | After the goal is met, push will + chaos higher; the goal condition still protects the threshold so the engine won't gamble below it. |
| `grade_value_table` (goal-independent) | **unchanged** (`value_mode="side"`) | Once the will/chaos goal is *fully infeasible*, there's nothing to lose — fall back to chasing grade so the gem isn't wasted. |

### Resulting behaviour under `--ignore-side-node-values`

- **Goal not yet met, still feasible** — unchanged; the goal-probability DP
  pursues the will/chaos goal.
- **Goal met, rerolls / turns remain** — keep cutting and rerolling to push
  `will + chaos` higher (e.g. 4-4 → 5-4 → 5-5). The goal-conditioned table
  protects the threshold: a forced `will-1` / `chaos-1` that would drop the
  total below the goal scores 0, so the engine only takes it when it still
  pays off. It finishes once no safe upside remains (or rerolls run out / it's
  turn 1). The grade-protect auto-gate in `_side_value_finish_decision` reads
  `svt.relic_coeff` / `svt.ancient_coeff`, which are `0` in this mode, so it
  never fires — correct, since grade is not being protected here.
- **Goal fully infeasible (dead goal)** — reset if a ticket is available (still
  a goal-pursuit move), otherwise fall back to the **existing grade chase** via
  the unchanged `grade_value_table` (maximise `side_coeff + tier_bonus`,
  finishing when there's no grade upside).
- `relic_prob_table` is still built so `P(relic+)` keeps showing in logs, but it
  no longer feeds decisions on the goal-met path (the will/chaos table does).

### Interactions

- `--relic-coeff` / `--ancient-coeff` **still apply** even with
  `--ignore-side-node-values`: they tune the dead-goal grade chase, which is the
  only place grade value is consulted under the flag.
- `--min-side-coeff` / `--min-first` / `--min-second` combined with
  `--ignore-side-node-values` is contradictory. The flag is intended for
  will/chaos-only goals; document that the will/chaos value model ignores side
  nodes regardless. (Success is still whatever the goal says, so a stray
  `--min-first` would still gate success — documented, not enforced.)
- `--endgame-risk F` margin, if passed, is interpreted in value units, which
  become will/chaos units (small, 0–10) under this mode. Default (auto, margin
  0) is the intended path; documented.

## Components touched

- `arkgrid/cli.py` — both flags in `add_common`; `--min-total-will-chaos` and
  `--ignore-side-node-values` in the `report` filter; `_resolve_args`,
  `_print_config`, and the `live`/`sim` goal summaries.
- `arkgrid/models.py` — `> 10` guard in `LastTurnGoal.feasible()`.
- `arkgrid/probability.py` — `value_mode` param on `SideValueTable`;
  `_gem_value_idx` / `_tier_bonus` honour it (and `will_chaos` skips the
  `min_side_coeff` floor).
- `arkgrid/simulator.py` — accept an `ignore_side_node_values` constructor knob;
  build `side_value_table` with `value_mode="will_chaos"` when set; leave
  `grade_value_table` as-is.
- `arkgrid/automation.py` — same wiring for `run_auto`.
- `arkgrid/decision.py` — **no change expected.** The grade-protect auto-gate in
  `_side_value_finish_decision` reads `svt.relic_coeff` / `svt.ancient_coeff`,
  which are `0` in `will_chaos` mode, so it disables itself; the dead-goal path
  already uses the unchanged `grade_value_table`. The new behaviour falls out of
  which `value_mode` each table is built with — no branch logic changes. (If a
  `DecisionContext.ignore_side_node_values` field turns out to be convenient for
  logging/assertions during implementation, it can be added, but it is not
  required by the design.)

## Testing

- `tests/test_models.py` — `min_total_will_chaos` `satisfied()` cases (5-3, 4-4,
  3-5 pass at 8; 4-3 fails); `feasible()` `> 10` guard rejects impossible totals.
- `tests/test_probability.py` — `SideValueTable(value_mode="will_chaos")`:
  `gem_value` equals `will + chaos`; a relic/ancient-grade state gets no tier
  bonus; the DP pushes toward higher will/chaos.
- `tests/test_decision.py` (or the relevant decision test module) — with
  `ignore_side_node_values=True`: goal-met state with rerolls left rerolls/
  continues toward higher will/chaos rather than finishing; dead-goal state
  still chases grade via `grade_value_table`.
- A CLI smoke check that `--min-total-will-chaos 8` and
  `--ignore-side-node-values` parse and run on `stats --trials 0`.
