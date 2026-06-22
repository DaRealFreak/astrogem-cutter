# Design: extra reroll ticket off by default, enabled by any ticket argument

**Date:** 2026-06-23
**Status:** Approved (design)
**Supersedes:** the `--extra-ticket-thresholds-only` opt-in flag design (dropped).

## Problem

The extra reroll ticket is available by default (`extra_ticket=True`). The threshold
flags `--relic-reroll-threshold` and `--reroll-goal` / `--reroll-goal-threshold` are
*re-enable overrides*: they only take effect after `--reroll-min-coeff` has already
gated the ticket off. Without `--reroll-min-coeff`, `extra_ticket_active` is never gated
off, the override branches never run, and the ticket is spent by ordinary reroll logic
regardless of the thresholds.

Observed: a run with `--relic-reroll-threshold 0.1 --reroll-goal 9
--reroll-goal-threshold 0.15` but **no** `--reroll-min-coeff` spent (and confirmed) the
extra ticket on a 400-coeff gem whose goal had cratered to ~6% and whose P(relic+) was
0.1% — far below either threshold. The thresholds were silently inert because nothing
gated the ticket off first.

## Goal

Invert the model so the extra ticket is **off by default** and *any* ticket argument
turns it on. This makes the thresholds first-class enablers (never silently inert) and
makes the reported over-spend impossible without an explicit opt-in.

## Design

### Behavior table

| Argument(s) | Effect on the `+1` ticket |
|---|---|
| *(none)* | **Off** — never granted. |
| `--extra-ticket` (explicit) | **Always on** — unconditional `+1` from turn 1; ignores all conditions. |
| `--reroll-min-coeff N` (N>0) | On at run start if the gem's target-effect coeff ≥ N. |
| `--relic-reroll-threshold F` (F>0) | On mid-run once P(relic+ ≥ 16) ≥ F. |
| `--reroll-goal N` + `--reroll-goal-threshold F` (F>0) | On mid-run once P(will+chaos ≥ N) ≥ F. |
| `--no-extra-ticket` | **Hard off** — overrides and disarms all enablers. |

Enablers are OR'd: whichever fires first grants the single ticket; once granted it stays
granted. `--extra-ticket` (force-on) outranks everything except… nothing — it is
absolute on; `--no-extra-ticket` is absolute off (last-on-command-line wins between the
two, via the shared argparse dest).

Key compatibility property: **`--reroll-min-coeff N` (N>0) behaves identically to
today** — ticket on for coeff ≥ N, off below. The only behavior that changes is the
*no-ticket-flag* default, which flips on→off. Existing `--reroll-min-coeff` / threshold
configs keep working; the thresholds simply stop being silently inert.

### Tri-state representation

`--extra-ticket` argparse default changes from `True` to `None` (in `add_common`).
`--no-extra-ticket` stays `store_false` on the same dest. So `args.extra_ticket` is:

- `True` — explicit `--extra-ticket` → **force-on**
- `False` — `--no-extra-ticket` → **hard-off**
- `None` — default → **off, enablers armed**

Two derived predicates used throughout:

- `force_on = (extra_ticket is True)`
- `ownable = (extra_ticket is not False)` — `True` for `True`/`None`; `False` only for
  `--no-extra-ticket`.

The `report` command's filter copy of `--extra-ticket` already defaults to `None`
(`_add_report_filter_args`) and is unchanged.

### Per-run state machine (identical in simulator and automation)

```
extra_ticket_active = force_on            # active at start only if forced
ownable             = (extra_ticket is not False)

# coeff enabler — start of run, once total_coeff is known:
if ownable and not extra_ticket_active and reroll_min_coeff > 0 and total_coeff >= reroll_min_coeff:
    extra_ticket_active = True

# relic / goal threshold enablers — armed only when ownable and not yet active;
# fire per-turn when their probability crosses (existing override code path):
relic_pending = ownable and not extra_ticket_active and relic_reroll_threshold > 0.0
goal_pending  = ownable and not extra_ticket_active and <reroll_goal table built>
```

This is the minimal change from today: the coeff check flips from *disable-if-below* to
*enable-if-at-or-above* (guarded by `not extra_ticket_active`, so it's monotonic/grant-only),
and the override-arming predicates key off `ownable` instead of the old
`use_extra_ticket` truthiness.

### DP table sizing

The reroll-aware DP tables must cover the max reachable reroll count so
`GoalProbabilityTable.lookup` never clamps a granted ticket. The ticket adds at most
`+1`. Size for it whenever the ticket is ownable and any enabler/force could grant it:

- **Simulator** (`__init__`): `base_rerolls = RARITY_REROLLS[rarity] + (1 if (use_extra_ticket is not False) else 0)`. The existing `dp_max_rerolls = base_rerolls + (1 if (relic_reroll_threshold > 0.0 or goal_reroll_active) else 0)` formula is unchanged (it already over-approximates safely). For `True`/`False` this matches today's sizing exactly; for `None` it adds the `+1` (the ticket may be granted), which is correct.
- **Automation** (first-detection table build): currently
  `total_rerolls = base + (1 if extra_ticket_active else 0)` then
  `dp_max = total_rerolls + (1 if relic/goal threshold else 0)`. Extend the second `+1`
  so it also covers the coeff-enabler grant path (which fires *after* the table is
  built): add the `+1` when the ticket is ownable, not yet active, and any of
  `reroll_min_coeff > 0` / `relic_reroll_threshold > 0` / goal-threshold-active holds.

### `parse_rerolls`

No change. It uses a truthy check on `extra_ticket`; tri-state `None` is falsy → no
phantom `+1`, which is correct for the off-by-default state. In automation the function
is fed the *computed active state* at its call site, not the raw param, so the phantom
`+1` follows `extra_ticket_active` automatically.

### No validation needed

The off-by-default model removes the footgun entirely: thresholds are now the primary
on-switch and always work, so there is nothing to error about. No hard-error checks are
added. (`--extra-ticket` + enablers is harmless — force-on wins; `--extra-ticket` +
`--no-extra-ticket` resolves by argparse last-wins.)

### Display

`_print_config` (and the `live` status line) show three states:
- `args.extra_ticket is True` → `Extra ticket: always (forced)`
- `args.extra_ticket is False` → `Extra ticket: no`
- `args.extra_ticket is None` → `Extra ticket: conditional (enabled by --reroll-min-coeff / --relic-reroll-threshold / --reroll-goal)`

## Touch-points

- **`arkgrid/cli.py`** — `add_common` `--extra-ticket` default `True`→`None`; stats DP
  `base_rerolls` sizing uses `args.extra_ticket is not False`; `_print_config` + `live`
  status three-state display. The `GemSimulator(...)` / `run_auto(...)` call sites are
  unchanged — they already pass `args.extra_ticket`, now tri-state.
- **`arkgrid/simulator.py`** — `use_extra_ticket: bool` → `Optional[bool]`; `base_rerolls`
  sizing; `simulate_one` force-on/ownable init, coeff enabler (invert), pending predicates.
- **`arkgrid/automation.py`** — `run_auto` `extra_ticket: bool` → `Optional[bool]`;
  `ownable` derivation; init `extra_ticket_active = (extra_ticket is True)`; DP sizing for
  the coeff-enabler grant; coeff gate inversion; override-block guard `extra_ticket` →
  `ownable`.
- **`arkgrid/vision/template_recognizer.py`** — none.
- **Docs** — `README.md` flag table (`--extra-ticket`, `--no-extra-ticket`,
  `--reroll-min-coeff`, the thresholds) and `CLAUDE.md` ticket discussion.

### Out of scope

- The reroll-aware DP's clamping of *earned* rerolls (pool `reroll+1` picks) beyond
  `dp_max_rerolls` is pre-existing accepted behavior — unchanged.
- `report` / `log_analyzer` filtering: `extra_ticket` is already a tri-state-aware
  nullable filter there; no change.

## Testing

- **Existing tests updated** (they used `use_extra_ticket=True` + `reroll_min_coeff=N` to
  gate the ticket *off*, which now means force-on):
  - `tests/test_simulator.py::TestRerollGoalThreshold._sim` — `use_extra_ticket=True,
    reroll_min_coeff=99999` → `use_extra_ticket=None` (armed; drop `reroll_min_coeff`).
    Bodies unchanged: no-flag → off; threshold crosses → on; threshold unreachable → off;
    `use_extra_ticket=False` → hard-off.
  - `tests/test_scenarios.py::TestExtraTicketRelicOverride` (3 sims) —
    `use_extra_ticket=True, reroll_min_coeff=2000` → `use_extra_ticket=None` (drop
    `reroll_min_coeff`). The no-relic sim (no enabler) → ticket never used; the relic sim
    → used when P(relic+) crosses.
- **Unchanged sizing tests** stay green: `tests/test_simulator.py::TestRelicRerollTableSizing`
  uses explicit `True`/`False`, whose `base_rerolls` sizing is identical under the new rule.
- **New simulator tests** (`tests/test_simulator.py`, new class):
  - default `None`, no enabler → `extra_ticket_used` False; turn-1 rerolls == rarity base
    (the reported-bug regression).
  - `None` + `reroll_min_coeff=N`, gem coeff ≥ N → ticket on at start (turn-1 rerolls ==
    base + 1).
  - `None` + `reroll_min_coeff=N`, gem coeff < N, no other enabler → off.
  - `True` (force-on), no enabler → on; and `True` + `reroll_min_coeff` huge on a
    low-coeff gem → still on (force ignores conditions).
  - `False` (hard-off) + `relic_reroll_threshold` high → still off (enablers disarmed).
- **New CLI tests** (`tests/test_cli.py`): `--extra-ticket` parses to `True`;
  `--no-extra-ticket` to `False`; default to `None`.
- Full suite (`python -m unittest discover -s tests`) green after each task.
