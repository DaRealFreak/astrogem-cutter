# Extra reroll ticket off-by-default — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the extra reroll ticket off by default and granted only by an enabler argument (`--reroll-min-coeff`, `--relic-reroll-threshold`, `--reroll-goal`+threshold) or forced on with explicit `--extra-ticket`; `--no-extra-ticket` is a hard off.

**Architecture:** `--extra-ticket` becomes tri-state via an argparse default of `None`: `True`=force-on, `False`=hard-off, `None`=off-but-enabler-armed. The simulator and automation derive `force_on = (x is True)` and `ownable = (x is not False)`, start `extra_ticket_active = force_on`, flip the `--reroll-min-coeff` check from *disable-if-below* to *enable-if-at-or-above*, and arm the relic/goal threshold overrides off `ownable`. DP tables stay sized to cover the single grantable ticket.

**Tech Stack:** Python 3 stdlib only. `unittest`. Activate the venv first: `source .venv/Scripts/activate`.

## Global Constraints

- No new third-party dependencies (simulator/CLI are stdlib-only).
- Tri-state semantics, exact: `extra_ticket is True` → force-on (unconditional +1); `extra_ticket is False` → hard-off (disarms all enablers); `extra_ticket is None` → off, enablers armed.
- `force_on = (extra_ticket is True)`; `ownable = (extra_ticket is not False)`.
- The coeff check is an **enabler**: enable when `ownable and not extra_ticket_active and reroll_min_coeff > 0 and total_coeff >= reroll_min_coeff`. It only ever sets active `True` (monotonic).
- Relic/goal overrides arm off `ownable` (not the old `use_extra_ticket` truthiness).
- **Behavior-preserving:** `--reroll-min-coeff N` (N>0) and the thresholds keep working exactly as before; only the *no-ticket-flag* default flips on→off.
- No validation / hard-errors are added.
- DP reroll-aware tables must cover the single grantable ticket so `GoalProbabilityTable.lookup` never clamps a granted reroll.
- Run tests with the venv active, e.g. `python -m unittest tests.test_simulator -v`.

---

### Task 1: Simulator — tri-state ticket, coeff enabler, ownable-armed overrides

The behavioral core and the regression lock. Changing the simulator's ticket semantics also breaks two existing test classes (they used `use_extra_ticket=True` + `reroll_min_coeff=N` to gate the ticket *off*, which now means force-on) — this task updates both and adds the new-behavior tests, so the full suite stays green.

**Files:**
- Modify: `arkgrid/simulator.py` (`GemSimulator.__init__` param + `base_rerolls`; `simulate_one` ticket init, coeff check, pending predicates)
- Modify: `tests/test_simulator.py` (`TestRerollGoalThreshold._sim` helper; new `TestExtraTicketOffByDefault` class)
- Modify: `tests/test_scenarios.py` (`TestExtraTicketRelicOverride` — three `GemSimulator` constructions)

**Interfaces:**
- Produces: `GemSimulator(use_extra_ticket: Optional[bool], ...)` — `True`=force-on, `False`=hard-off, `None`=off-but-armed. `self.base_rerolls = RARITY_REROLLS[rarity] + (1 if use_extra_ticket is not False else 0)`.
- Consumes: existing `RunResult.extra_ticket_used` (bool) and `turn_log[i]["rerolls_available"]` (int).

- [ ] **Step 1: Update the two breaking test classes and write the new tests (RED)**

In `tests/test_simulator.py`, change the `TestRerollGoalThreshold._sim` helper. Replace its `defaults` dict and docstring:

```python
class TestRerollGoalThreshold(unittest.TestCase):
    """--reroll-goal / --reroll-goal-threshold enables the off-by-default
    extra reroll ticket when P(will+chaos >= reroll_goal) crosses the
    threshold."""

    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_extra_ticket=None, use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=7),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            optimize="dps", effect_aware=True,
        )
        defaults.update(kw)
        return GemSimulator(**defaults)
```

(The four test bodies below it are unchanged: `_sim()` with no enabler → ticket off; `reroll_goal=8, reroll_goal_threshold=0.01` → granted; `=2.0` → never; `use_extra_ticket=False, ...` → hard-off. Also update the stale comment on the `test_grants_ticket_when_prob_crosses` body from "ticket gated off by reroll_min_coeff" to "ticket off by default".)

Append a new class to `tests/test_simulator.py`:

```python
class TestExtraTicketOffByDefault(unittest.TestCase):
    """The extra reroll ticket is off by default (use_extra_ticket=None) and
    granted only by an enabler (--reroll-min-coeff / threshold) or forced on
    (use_extra_ticket=True). --no-extra-ticket (False) is a hard off that
    disarms enablers. The gem here has DPS coeff boss_damage(1000) +
    attack_power(400) = 1400; epic base rerolls = 2."""

    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=7),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            optimize="dps", effect_aware=True,
        )
        defaults.update(kw)
        return GemSimulator(**defaults)

    def test_default_none_no_enabler_holds_ticket(self):
        # Reported-bug regression: no ticket flag, no enabler -> never granted.
        sim = self._sim(use_extra_ticket=None)
        r = sim.simulate_one(seed=1)
        self.assertFalse(r.extra_ticket_used)
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)

    def test_force_on_grants_without_enabler(self):
        # Explicit --extra-ticket (True) = always on, no enabler needed.
        sim = self._sim(use_extra_ticket=True)
        r = sim.simulate_one(seed=1)
        self.assertEqual(r.turn_log[0]["rerolls_available"], 3)

    def test_force_on_ignores_low_coeff(self):
        # Force-on outranks --reroll-min-coeff: on even below the coeff floor.
        sim = self._sim(use_extra_ticket=True, reroll_min_coeff=99999)
        r = sim.simulate_one(seed=1)
        self.assertEqual(r.turn_log[0]["rerolls_available"], 3)

    def test_coeff_enabler_at_or_above_grants_at_start(self):
        # 1400 >= 1000 -> ticket enabled at run start.
        sim = self._sim(use_extra_ticket=None, reroll_min_coeff=1000)
        r = sim.simulate_one(seed=1)
        self.assertEqual(r.turn_log[0]["rerolls_available"], 3)

    def test_coeff_enabler_below_threshold_stays_off(self):
        # 1400 < 2000 and no other enabler -> ticket stays off.
        sim = self._sim(use_extra_ticket=None, reroll_min_coeff=2000)
        r = sim.simulate_one(seed=1)
        self.assertFalse(r.extra_ticket_used)
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)

    def test_hard_off_disarms_enablers(self):
        # --no-extra-ticket (False) overrides a trivially-crossable relic enabler.
        sim = self._sim(use_extra_ticket=False, relic_reroll_threshold=0.0001)
        r = sim.simulate_one(seed=1)
        self.assertFalse(r.extra_ticket_used)
        self.assertEqual(r.turn_log[0]["rerolls_available"], 2)
```

In `tests/test_scenarios.py`, `TestExtraTicketRelicOverride`: in all three `GemSimulator(...)` constructions (`sim` in `test_extra_ticket_granted_mid_run`, `sim_no_relic` in the same test, and `sim` in `test_print_details`), change `use_extra_ticket=True` to `use_extra_ticket=None` and **delete the `reroll_min_coeff=2000` line**. Update the two stale comments ("boss_damage=1000 is the only DPS effect → total_coeff=1000 < 2000" and "Without relic override: extra ticket disabled (coeff 1000 < 2000)") to "ticket off by default; relic override is the only enabler".

- [ ] **Step 2: Run the tests to verify they fail (RED)**

Run: `python -m unittest tests.test_simulator.TestExtraTicketOffByDefault -v`
Expected: FAILs. (A few cases pass coincidentally today because `bool(None)` is falsy and `True` already means ticket-on.) The decisive REDs are:
- `test_coeff_enabler_at_or_above_grants_at_start` — expects 3; today `--reroll-min-coeff` only *disables*, never enables, so the ticket stays off → 2.
- `test_force_on_ignores_low_coeff` — expects 3; today the coeff gate disables the ticket even when "on" → 2.

Also run: `python -m unittest tests.test_simulator.TestRerollGoalThreshold -v`
Expected: `test_grants_ticket_when_prob_crosses` FAILs — with the helper now `use_extra_ticket=None`, today's override-arming predicate (`not extra_ticket_active and self.use_extra_ticket and …`) is falsy because `self.use_extra_ticket` is `None`, so the ticket is never granted (the test expects it granted).

- [ ] **Step 3: Change the constructor param + base_rerolls sizing**

In `arkgrid/simulator.py`, change the `__init__` signature param (currently `use_extra_ticket: bool,`) to:

```python
            use_extra_ticket: Optional[bool],
```

(`Optional` is already imported.) The `self.use_extra_ticket = use_extra_ticket` storage line is unchanged. Change the `base_rerolls` line (currently `self.base_rerolls = self.RARITY_REROLLS[rarity] + (1 if use_extra_ticket else 0)`) to:

```python
        self.base_rerolls = self.RARITY_REROLLS[rarity] + (
            1 if use_extra_ticket is not False else 0)
```

- [ ] **Step 4: Force-on init + coeff enabler + ownable-armed overrides**

In `arkgrid/simulator.py`, `simulate_one`, change the ticket init (currently `extra_ticket_active = bool(self.use_extra_ticket)`) to:

```python
        extra_ticket_active = (self.use_extra_ticket is True)
        ownable = (self.use_extra_ticket is not False)
```

Replace the coeff gate (currently):

```python
        if extra_ticket_active and self.reroll_min_coeff > 0:
            if total_coeff < self.reroll_min_coeff:
                extra_ticket_active = False
```

with the enabler:

```python
        if (ownable and not extra_ticket_active
                and self.reroll_min_coeff > 0
                and total_coeff >= self.reroll_min_coeff):
            extra_ticket_active = True
```

Change the two pending predicates (currently each starts `not extra_ticket_active and self.use_extra_ticket`) to use `ownable`:

```python
        relic_reroll_pending = (
            not extra_ticket_active and ownable
            and self.relic_reroll_threshold > 0.0
        )
        goal_reroll_pending = (
            not extra_ticket_active and ownable
            and self._reroll_goal_prob_table is not None
        )
```

(The `dp_max_rerolls` formula in `__init__` is unchanged — `base_rerolls` now already includes the `+1` for any ownable ticket, which covers the coeff-enabler grant.)

- [ ] **Step 5: Run the tests to verify they pass (GREEN)**

Run: `python -m unittest tests.test_simulator.TestExtraTicketOffByDefault tests.test_simulator.TestRerollGoalThreshold -v`
Expected: PASS (all).

- [ ] **Step 6: Run the full simulator + scenarios suites**

Run: `python -m unittest tests.test_simulator tests.test_scenarios -v`
Expected: PASS (all, including `TestExtraTicketRelicOverride` and `TestRelicRerollTableSizing`).

- [ ] **Step 7: Commit**

```bash
git add arkgrid/simulator.py tests/test_simulator.py tests/test_scenarios.py
git commit -m "feat: extra reroll ticket off-by-default in GemSimulator

use_extra_ticket is now tri-state: True=force-on, False=hard-off,
None=off-but-enabler-armed. --reroll-min-coeff flips to an enabler
(on if coeff >= N). Relic/goal overrides arm off ownability. Existing
gate-off tests move to use_extra_ticket=None; new tests lock the
off-by-default + enabler behavior (the reported over-spend regression).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Automation — mirror the tri-state ticket in `run_auto`

`run_auto` is the live-screen loop (Windows-only, no unit harness). It mirrors Task 1's semantics: force-on init, `ownable`, coeff enabler, ownable-armed override, plus a DP-sizing tweak because the auto table is built *before* the coeff enabler runs.

**Files:**
- Modify: `arkgrid/automation.py` (`run_auto` signature; init; DP `dp_max_rerolls`; coeff gate; override-block guard)

**Interfaces:**
- Consumes: `GemSimulator` tri-state semantics from Task 1 (same `force_on`/`ownable` rules).
- Produces: `run_auto(extra_ticket: Optional[bool], ...)`.

- [ ] **Step 1: Tri-state param + ownable derivation + force-on init**

In `arkgrid/automation.py`, change the `run_auto` signature param (currently `extra_ticket: bool,`) to:

```python
    extra_ticket: Optional[bool],
```

(`Optional` is already imported.) Change the init (currently `extra_ticket_active = bool(extra_ticket)`) to:

```python
        extra_ticket_active = (extra_ticket is True)
        ownable = (extra_ticket is not False)
```

- [ ] **Step 2: Size the DP tables for the coeff-enabler grant**

In `arkgrid/automation.py`, the first-detection table-build block computes `dp_max_rerolls`. Replace (currently):

```python
                total_rerolls = base_rerolls + (1 if extra_ticket_active else 0)
                # The relic+ reroll override grants one extra reroll mid-run
                # (state.rerolls += 1).  Size all reroll-aware tables to cover
                # the post-override maximum so GoalProbabilityTable.lookup
                # never clamps the granted reroll.
                goal_reroll_active = (reroll_goal is not None
                                      and reroll_goal_threshold > 0.0)
                dp_max_rerolls = total_rerolls + (
                    1 if (relic_reroll_threshold > 0.0 or goal_reroll_active)
                    else 0)
```

with:

```python
                total_rerolls = base_rerolls + (1 if extra_ticket_active else 0)
                # The single ticket may still be granted after this table is
                # built — by the coeff enabler (start of run) or the relic/goal
                # threshold override (mid-run), each adding at most +1. Size for
                # it whenever the ticket is ownable, not yet active, and some
                # enabler could fire, so GoalProbabilityTable.lookup never clamps
                # the granted reroll.
                goal_reroll_active = (reroll_goal is not None
                                      and reroll_goal_threshold > 0.0)
                grant_possible = (ownable and not extra_ticket_active and (
                    reroll_min_coeff > 0 or relic_reroll_threshold > 0.0
                    or goal_reroll_active))
                dp_max_rerolls = total_rerolls + (1 if grant_possible else 0)
```

- [ ] **Step 3: Coeff gate inversion (disable→enable)**

In `arkgrid/automation.py`, inside the coeff-gating block, replace the reroll gate (currently):

```python
                    if reroll_min_coeff > 0 and total_coeff < reroll_min_coeff:
                        extra_ticket_active = False
                        print(f"  [info] Extra reroll ticket disabled "
                              f"(coeff {total_coeff} < {reroll_min_coeff})")
```

with:

```python
                    if (ownable and not extra_ticket_active
                            and reroll_min_coeff > 0
                            and total_coeff >= reroll_min_coeff):
                        extra_ticket_active = True
                        print(f"  [info] Extra reroll ticket enabled "
                              f"(coeff {total_coeff} >= {reroll_min_coeff})")
```

- [ ] **Step 4: Override-block guard uses ownable**

In `arkgrid/automation.py`, change the relic/goal override guard (currently `if not extra_ticket_active and extra_ticket and (relic_armed or goal_armed):`) to:

```python
            if not extra_ticket_active and ownable and (relic_armed or goal_armed):
```

- [ ] **Step 5: Verify the module imports cleanly**

Run: `source .venv/Scripts/activate && python -c "import arkgrid.automation"`
Expected: no output, exit 0.

- [ ] **Step 6: Run the full test suite (no regressions)**

Run: `python -m unittest discover -s tests`
Expected: OK (automation is not unit-tested for this path; this confirms nothing else broke).

- [ ] **Step 7: Commit**

```bash
git add arkgrid/automation.py
git commit -m "feat: mirror off-by-default extra ticket in run_auto

Force-on init, ownable-derived enabler arming, coeff gate inverted to an
enabler, and DP sizing extended to cover the coeff-enabler grant path.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: CLI — flip the default, tri-state display, stats DP sizing

Flips `--extra-ticket`'s argparse default to `None` (the actual user-facing default change), shows the three states in the config banner, and sizes the `stats` display DP for an ownable ticket. The `GemSimulator(...)` / `run_auto(...)` call sites are unchanged — they already pass `args.extra_ticket`, now tri-state.

**Files:**
- Modify: `arkgrid/cli.py` (`add_common` default; `_print_config`; `cmd_stats` DP `base_rerolls`; `live` status line)
- Test: `tests/test_cli.py` (new `TestExtraTicketTriState` class)

**Interfaces:**
- Consumes: tri-state `GemSimulator` / `run_auto` from Tasks 1-2.
- Produces: `args.extra_ticket` defaults to `None`; `True` on `--extra-ticket`; `False` on `--no-extra-ticket`.

- [ ] **Step 1: Write the failing CLI tests (RED)**

Append to `tests/test_cli.py` (already imports `_build_parser`):

```python
class TestExtraTicketTriState(unittest.TestCase):
    """--extra-ticket is tri-state: None default (off, enabler-armed),
    True on --extra-ticket (forced on), False on --no-extra-ticket (hard off)."""

    def _parse(self, extra):
        return _build_parser().parse_args(
            ["sim", "--min-total-will-chaos", "7"] + extra)

    def test_default_is_none(self):
        self.assertIsNone(self._parse([]).extra_ticket)

    def test_explicit_extra_ticket_is_true(self):
        self.assertIs(self._parse(["--extra-ticket"]).extra_ticket, True)

    def test_no_extra_ticket_is_false(self):
        self.assertIs(self._parse(["--no-extra-ticket"]).extra_ticket, False)
```

- [ ] **Step 2: Run to verify it fails (RED)**

Run: `python -m unittest tests.test_cli.TestExtraTicketTriState -v`
Expected: `test_default_is_none` FAILs (default is `True` today, not `None`).

- [ ] **Step 3: Flip the argparse default to None**

In `arkgrid/cli.py`, `add_common`, change the `--extra-ticket` argument (currently `p.add_argument("--extra-ticket", action="store_true", default=True,`) to default `None`:

```python
        p.add_argument("--extra-ticket", action="store_true", default=None,
                        help="Force the extra reroll ticket ON for every gem "
                             "(unconditional +1). Default (omitted): the ticket "
                             "is OFF unless enabled by --reroll-min-coeff, "
                             "--relic-reroll-threshold, or --reroll-goal + "
                             "--reroll-goal-threshold. --no-extra-ticket is a "
                             "hard off that disarms those enablers.")
```

(The `--no-extra-ticket` line directly below, `action="store_false", dest="extra_ticket"`, is unchanged.)

- [ ] **Step 4: Run the CLI tests to verify they pass (GREEN)**

Run: `python -m unittest tests.test_cli.TestExtraTicketTriState -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Three-state config banner**

In `arkgrid/cli.py`, `_print_config`, replace the line `print(f"Extra ticket: {'yes' if args.extra_ticket else 'no'}")` with:

```python
    if args.extra_ticket is True:
        extra_ticket_str = "always (forced)"
    elif args.extra_ticket is False:
        extra_ticket_str = "no"
    else:
        extra_ticket_str = ("conditional (enabled by --reroll-min-coeff / "
                            "--relic-reroll-threshold / --reroll-goal)")
    print(f"Extra ticket: {extra_ticket_str}")
```

- [ ] **Step 6: Size the stats display DP for an ownable ticket**

In `arkgrid/cli.py`, `cmd_stats`, change the `base_rerolls` line (currently `+ (1 if args.extra_ticket else 0))`) to:

```python
            base_rerolls = (GemSimulator.RARITY_REROLLS[rarity]
                            + (1 if args.extra_ticket is not False else 0))
```

- [ ] **Step 7: Three-state live status line**

In `arkgrid/cli.py`, `cmd_live`, replace the line `print(f"Tickets:    reset={reset_str}  extra_reroll={'yes' if args.extra_ticket else 'no'}")` with:

```python
    if args.extra_ticket is True:
        extra_reroll_str = "always"
    elif args.extra_ticket is False:
        extra_reroll_str = "no"
    else:
        extra_reroll_str = "conditional"
    print(f"Tickets:    reset={reset_str}  extra_reroll={extra_reroll_str}")
```

- [ ] **Step 8: Smoke-test the wired CLI paths**

Run (default — ticket conditional, off without enabler; the reported scenario):

```bash
source .venv/Scripts/activate && python -m arkgrid sim --min-total-will-chaos 8 --optimize dps --gem-type order_fortitude --first-effect boss_damage --second-effect attack_power --seed 42 | grep "Extra ticket"
```
Expected: `Extra ticket: conditional (enabled by ...)`.

Run (forced on):

```bash
python -m arkgrid sim --min-total-will-chaos 8 --optimize dps --gem-type order_fortitude --first-effect boss_damage --second-effect attack_power --extra-ticket --seed 42 | grep "Extra ticket"
```
Expected: `Extra ticket: always (forced)`.

- [ ] **Step 9: Run the full test suite**

Run: `python -m unittest discover -s tests`
Expected: OK (all).

- [ ] **Step 10: Commit**

```bash
git add arkgrid/cli.py tests/test_cli.py
git commit -m "feat: flip --extra-ticket default to off (tri-state)

--extra-ticket now defaults to None (ticket off, enabler-armed); explicit
--extra-ticket forces it on; --no-extra-ticket is a hard off. Config
banner and live status show the three states; stats DP sizes for an
ownable ticket.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Documentation

Update the README flag table and `CLAUDE.md` so the off-by-default model and the enabler list are accurate.

**Files:**
- Modify: `README.md` (flag table: `--extra-ticket` / `--no-extra-ticket`, `--reroll-min-coeff`, the two threshold rows)
- Modify: `CLAUDE.md` (the ticket discussion in Key Domain Concepts)

- [ ] **Step 1: Update the README flag rows**

In `README.md`, update/replace the `--extra-ticket` / `--no-extra-ticket` rows (and adjust the `--reroll-min-coeff`, `--relic-reroll-threshold`, `--reroll-goal-threshold` row text) so they read as an off-by-default model. Use this `--extra-ticket` block as the anchor:

```markdown
| `--extra-ticket` | Force the extra reroll ticket ON for every gem (unconditional +1 from turn 1). **Default (omitted): the ticket is OFF** and granted only by an enabler — `--reroll-min-coeff N` (coeff ≥ N), `--relic-reroll-threshold F` (P(relic+) ≥ F), or `--reroll-goal N`+`--reroll-goal-threshold F` (P(will+chaos ≥ N) ≥ F). Enablers are OR'd. |
| `--no-extra-ticket` | Hard off: the extra ticket is never granted and all enablers are disarmed. |
```

Also adjust the `--reroll-min-coeff` row to describe it as an enabler ("enable the extra reroll ticket when starting target-effect coeff ≥ N"), and drop the now-stale "even when --reroll-min-coeff disabled it" phrasing from the `--relic-reroll-threshold` / `--reroll-goal-threshold` rows (they are now plain enablers on the off-by-default ticket).

- [ ] **Step 2: Update CLAUDE.md ticket discussion**

In `CLAUDE.md`, update the **Ticket confirmation** bullet (Key Domain Concepts) to state the new model:

```markdown
The extra reroll ticket is **off by default**. It is granted by any enabler — `--reroll-min-coeff N` (coeff ≥ N, evaluated at run start), `--relic-reroll-threshold F` (P(relic+) ≥ F, mid-run), or `--reroll-goal N` + `--reroll-goal-threshold F` (P(will+chaos ≥ N) ≥ F, mid-run) — OR'd together. Explicit `--extra-ticket` forces it unconditionally on; `--no-extra-ticket` is a hard off that disarms all enablers. Internally `use_extra_ticket` / `extra_ticket` is tri-state (`True`=force-on, `False`=hard-off, `None`=off-but-armed); the simulator and `run_auto` derive `force_on`/`ownable`, start `extra_ticket_active = force_on`, treat `--reroll-min-coeff` as an enable-if-≥ check, and arm the relic/goal overrides off ownability.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: extra reroll ticket is off by default

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage**
- Tri-state default flip → Task 3 Step 3 + `TestExtraTicketTriState`.
- `force_on`/`ownable`, force-on init → Task 1 Step 4, Task 2 Step 1.
- Coeff enabler (invert) → Task 1 Step 4, Task 2 Step 3; tests `test_coeff_enabler_at_or_above_grants_at_start` / `_below_threshold_stays_off`.
- Relic/goal overrides arm off `ownable` → Task 1 Step 4 (pending), Task 2 Step 4 (guard); `TestRerollGoalThreshold`, `TestExtraTicketRelicOverride`.
- `--extra-ticket` force-on, ignores conditions → `test_force_on_grants_without_enabler`, `test_force_on_ignores_low_coeff`.
- `--no-extra-ticket` hard-off disarms enablers → `test_hard_off_disarms_enablers`.
- Off-by-default regression → `test_default_none_no_enabler_holds_ticket`.
- DP sizing covers the grant → Task 1 base_rerolls (`is not False`), Task 2 Step 2 `grant_possible`; `TestRelicRerollTableSizing` stays green (Task 1 Step 6).
- `parse_rerolls` unchanged → not touched (spec: truthy check, `None` falsy).
- No validation → none added.
- Behavior-preserving for configured runs → reasoned in Global Constraints; `--reroll-min-coeff N` enabler matches old gate-on outcome.
- Display three-state → Task 3 Steps 5, 7.

**2. Placeholder scan** — none; every code/test step carries concrete content.

**3. Type consistency** — `use_extra_ticket: Optional[bool]` (simulator) / `extra_ticket: Optional[bool]` (automation) / `args.extra_ticket ∈ {True,False,None}` are consistent. `force_on = (x is True)`, `ownable = (x is not False)` identical in both modules. `base_rerolls` uses `is not False` in simulator and stats. `RunResult.extra_ticket_used` / `turn_log[i]["rerolls_available"]` match existing usage.
