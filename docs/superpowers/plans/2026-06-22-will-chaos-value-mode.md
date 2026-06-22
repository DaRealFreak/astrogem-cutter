# Will/chaos value mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a combined will/chaos goal (`--min-total-will-chaos N`) and a will/chaos-only value mode (`--ignore-side-node-values`) so new characters can optimise purely for willpower + chaos.

**Architecture:** `--min-total-will-chaos` is pure CLI wiring — the model/DP already support `LastTurnGoal.min_total_will_chaos`. `--ignore-side-node-values` adds a `value_mode="will_chaos"` to `SideValueTable` (`gem_value = will + chaos`, no grade/side-coeff) and builds the *goal-conditioned* `side_value_table` in that mode; the *goal-independent* `grade_value_table` stays in `"side"` mode so a fully-dead goal still chases grade. `decision.py` needs no branch changes — the behaviour falls out of which `value_mode` each table is built with.

**Tech Stack:** Python 3 stdlib only (no new deps in touched modules). Tests use `unittest`. Spec: `docs/superpowers/specs/2026-06-22-will-chaos-value-mode-design.md`.

## Global Constraints

- Stdlib only for the simulator core (`dataclasses`, `random`, `math`, `typing`) — do not add dependencies.
- No linter configured; verification = the full `unittest` suite must pass.
- Tests run with the venv active: `source .venv/Scripts/activate` then `python -m unittest ...`.
- Every commit message ends with the trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Follow existing patterns; do not restructure unrelated code.
- `--min-total-will-chaos` is **decision-neutral on its own**: it only extends the success condition. Only `--ignore-side-node-values` changes decision-making.
- will + chaos each cap at 5 (combined cap 10). The value under `will_chaos` mode is the plain equal-weighted sum `will + chaos`.

---

## Task 1: Combined will/chaos goal (`--min-total-will-chaos`)

**Files:**
- Modify: `arkgrid/models.py` (`LastTurnGoal.feasible` — add the `> 10` guard)
- Modify: `arkgrid/cli.py` (`add_common`, `_resolve_args`, `_print_config`, `cmd_live` goal + display, `_add_report_filter_args`)
- Modify: `arkgrid/log_analyzer.py` (`_NULLABLE_INT_FILTERS`)
- Test: `tests/test_models.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `LastTurnGoal(min_total_will_chaos=...)` field, `satisfied()`/`feasible()` (already handle it), `cli._resolve_args(args) -> (goal, astro_gem, rarities, reset_variants)`.
- Produces: a `--min-total-will-chaos` CLI flag on `stats`/`sim`/`live`/`auto`/`report`; `_resolve_args` and `cmd_live` populate `LastTurnGoal.min_total_will_chaos`.

- [ ] **Step 1: Write the failing feasibility-guard test**

In `tests/test_models.py`, inside `class TestLastTurnGoal`, add:

```python
    def test_feasible_total_will_chaos_above_cap(self) -> None:
        # will+chaos cap at 5+5=10; a total goal above 10 is impossible.
        g = LastTurnGoal(min_total_will_chaos=11)
        self.assertFalse(g.feasible(1, 1, 9))

    def test_feasible_exact_total_will_chaos_above_cap(self) -> None:
        g = LastTurnGoal(exact_total_will_chaos=11)
        self.assertFalse(g.feasible(1, 1, 9))

    def test_feasible_total_will_chaos_reachable(self) -> None:
        g = LastTurnGoal(min_total_will_chaos=8)
        # at 1+1=2 need +6, max +4/turn => 2 turns minimum
        self.assertTrue(g.feasible(1, 1, 2))
        self.assertFalse(g.feasible(1, 1, 1))
```

- [ ] **Step 2: Run the tests to verify the cap tests fail**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_models.TestLastTurnGoal.test_feasible_total_will_chaos_above_cap tests.test_models.TestLastTurnGoal.test_feasible_exact_total_will_chaos_above_cap -v`
Expected: both FAIL (they currently return `True` — no `> 10` guard). `test_feasible_total_will_chaos_reachable` already passes.

- [ ] **Step 3: Add the `> 10` guard in `LastTurnGoal.feasible`**

In `arkgrid/models.py`, in `feasible()`, immediately after the existing chaos-cap guard:

```python
        if target_c is not None and target_c > 5:
            return False
```

add:

```python
        if self.min_total_will_chaos is not None and self.min_total_will_chaos > 10:
            return False
        if self.exact_total_will_chaos is not None and self.exact_total_will_chaos > 10:
            return False
```

- [ ] **Step 4: Run the model tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_models -v`
Expected: PASS (all, including the three new cases).

- [ ] **Step 5: Add the `--min-total-will-chaos` CLI flag**

In `arkgrid/cli.py`, in `add_common`, right after the `--exact-chaos` argument:

```python
        p.add_argument("--exact-chaos", type=int, default=None, metavar="N")
```

add:

```python
        p.add_argument("--min-total-will-chaos", type=int, default=None,
                        metavar="N",
                        help="Minimum combined willpower+chaos total (e.g. 8 = "
                             "met by 5-3, 4-4, 3-5, or higher). A general goal "
                             "constraint, useful to endgame players too; on its "
                             "own it does not change decision-making.")
```

- [ ] **Step 6: Populate the goal in `_resolve_args`**

In `arkgrid/cli.py`, in `_resolve_args`, change the `goal = LastTurnGoal(...)` construction to include the new field:

```python
    goal = LastTurnGoal(
        min_will=args.min_will,
        min_chaos=args.min_chaos,
        exact_will=args.exact_will,
        exact_chaos=args.exact_chaos,
        min_total_will_chaos=getattr(args, "min_total_will_chaos", None),
        min_first=getattr(args, "min_first", None),
        min_second=getattr(args, "min_second", None),
    )
```

- [ ] **Step 7: Show it in `_print_config`**

In `arkgrid/cli.py`, in `_print_config`, after the `exact_chaos` block:

```python
    if goal.exact_chaos is not None:
        parts.append(f"exact_chaos={goal.exact_chaos}")
```

add:

```python
    if goal.min_total_will_chaos is not None:
        parts.append(f"min_total_will_chaos={goal.min_total_will_chaos}")
```

- [ ] **Step 8: Wire it into `cmd_live` (goal + display)**

In `arkgrid/cli.py`, in `cmd_live`, change the `goal = LastTurnGoal(...)` construction to include the field:

```python
    goal = LastTurnGoal(
        min_will=args.min_will,
        min_chaos=args.min_chaos,
        exact_will=args.exact_will,
        exact_chaos=args.exact_chaos,
        min_total_will_chaos=getattr(args, "min_total_will_chaos", None),
        min_first=getattr(args, "min_first", None),
        min_second=getattr(args, "min_second", None),
    )
```

and in the `goal_parts` block, after the `exact_chaos` append:

```python
    if goal.exact_chaos is not None:
        goal_parts.append(f"exact_chaos={goal.exact_chaos}")
```

add:

```python
    if goal.min_total_will_chaos is not None:
        goal_parts.append(f"min_total_will_chaos={goal.min_total_will_chaos}")
```

- [ ] **Step 9: Add the report filter arg + nullable filter**

In `arkgrid/cli.py`, in `_add_report_filter_args`, after the `--exact-chaos` line:

```python
    p.add_argument("--exact-chaos", type=int, default=None, metavar="N")
```

add:

```python
    p.add_argument("--min-total-will-chaos", type=int, default=None, metavar="N")
```

In `arkgrid/log_analyzer.py`, add `"min_total_will_chaos"` to `_NULLABLE_INT_FILTERS`:

```python
_NULLABLE_INT_FILTERS = (
    "min_will", "min_chaos", "exact_will", "exact_chaos",
    "min_total_will_chaos",
    "min_first", "min_second",
)
```

- [ ] **Step 10: Write the CLI parse/resolve test**

In `tests/test_cli.py`, add a new test class:

```python
class TestWillChaosTotalGoal(unittest.TestCase):
    def test_min_total_will_chaos_parses_and_resolves(self):
        parser = _build_parser()
        args = parser.parse_args(["sim", "--min-total-will-chaos", "8"])
        goal, _, _, _ = _resolve_args(args)
        self.assertEqual(goal.min_total_will_chaos, 8)
        self.assertTrue(goal.satisfied(4, 4))
        self.assertTrue(goal.satisfied(3, 5))
        self.assertFalse(goal.satisfied(3, 4))

    def test_min_total_will_chaos_default_none(self):
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertIsNone(args.min_total_will_chaos)
        goal, _, _, _ = _resolve_args(args)
        self.assertIsNone(goal.min_total_will_chaos)
```

`tests/test_cli.py` already imports `_build_parser` and `_resolve_args` and `import unittest` at the top — no new imports needed.

- [ ] **Step 11: Run the full suite**

Run: `source .venv/Scripts/activate && python -m unittest discover -s tests -q`
Expected: OK (no failures/errors).

- [ ] **Step 12: Smoke-check the flag end to end**

Run: `source .venv/Scripts/activate && python -m arkgrid stats --min-total-will-chaos 8 --first-effect boss_damage --second-effect attack_power --trials 0`
Expected: prints `Goal: ..., min_total_will_chaos=8` and a DP probability line per rarity, no traceback.

- [ ] **Step 13: Commit**

```bash
git add arkgrid/models.py arkgrid/cli.py arkgrid/log_analyzer.py tests/test_models.py tests/test_cli.py
git commit -m "$(printf 'feat: add --min-total-will-chaos combined goal flag\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: `value_mode` on `SideValueTable`

**Files:**
- Modify: `arkgrid/probability.py` (`SideValueTable.__init__`, `_gem_value_idx`)
- Test: `tests/test_probability.py`

**Interfaces:**
- Consumes: existing `SideValueTable(goal, max_turns, pool, *, gem_type, optimize, min_side_coeff, relic_coeff, ancient_coeff)`.
- Produces: new keyword-only param `value_mode: str = "side"`. When `value_mode == "will_chaos"`, `gem_value(state) == will + chaos` for goal-met states (0 otherwise), the `min_side_coeff` floor is skipped, and `relic_coeff`/`ancient_coeff` are forced to `0`. Public attribute `value_mode` is readable.

- [ ] **Step 1: Write the failing tests**

In `tests/test_probability.py`, after `class TestSideValueTableFusionDefault`, add:

```python
class TestSideValueTableWillChaosMode(unittest.TestCase):
    """value_mode='will_chaos': gem_value = will+chaos, no grade/side value."""

    POOL = OptionPool()

    def _table(self, **kw):
        defaults = dict(
            goal=LastTurnGoal(min_total_will_chaos=8),
            max_turns=9, pool=self.POOL,
            gem_type="order_fortitude", optimize="dps",
            value_mode="will_chaos",
        )
        defaults.update(kw)
        return SideValueTable(**defaults)

    def test_gem_value_is_will_plus_chaos(self):
        t = self._table()
        st = GemState(will=5, chaos=3, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        # will+chaos = 8; side coeff and grade tier are ignored.
        self.assertEqual(t.gem_value(st), 8.0)

    def test_relic_ancient_forced_to_zero(self):
        t = self._table(relic_coeff=3000, ancient_coeff=8000)
        self.assertEqual(t.relic_coeff, 0)
        self.assertEqual(t.ancient_coeff, 0)

    def test_no_tier_bonus_at_relic_total(self):
        # total points 18 (relic band) but value is will+chaos only.
        t = self._table(relic_coeff=3000, ancient_coeff=8000)
        st = GemState(will=4, chaos=4, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertEqual(t.gem_value(st), 8.0)

    def test_zero_when_goal_broken(self):
        t = self._table()
        st = GemState(will=3, chaos=4, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        # will+chaos = 7 < 8 -> goal broken -> value 0.
        self.assertEqual(t.gem_value(st), 0.0)

    def test_ignores_min_side_coeff_floor(self):
        t = self._table(min_side_coeff=99999)
        st = GemState(will=4, chaos=4, first=1, second=1,
                      first_effect="boss_damage", second_effect="attack_power")
        # side coeff tiny but the floor is ignored in will_chaos mode.
        self.assertEqual(t.gem_value(st), 8.0)

    def test_pushes_toward_higher_will_chaos(self):
        # goal comfortably met at 9, room to grow to 10 -> continuing beats
        # finishing now.
        t = self._table()
        st = GemState(will=4, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertGreater(t.lookup(st, 5), t.gem_value(st))

    def test_side_mode_is_default_and_unchanged(self):
        # value_mode defaults to "side": grade bonus applies as before.
        t = SideValueTable(LastTurnGoal(min_total_will_chaos=8), 9, self.POOL,
                           gem_type="order_fortitude", optimize="dps",
                           relic_coeff=3000, ancient_coeff=8000)
        self.assertEqual(t.value_mode, "side")
        st = GemState(will=4, chaos=4, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        # side_coeff = 5*1000 + 5*400 = 7000 ; total 18 -> relic +3000 = 10000.
        self.assertEqual(t.gem_value(st), 10000.0)
```

`tests/test_probability.py` already imports `GemState`, `LastTurnGoal`, `OptionPool`, and `SideValueTable` at the top — no new imports needed.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_probability.TestSideValueTableWillChaosMode -v`
Expected: FAIL/ERROR — `SideValueTable.__init__()` got an unexpected keyword argument `value_mode`.

- [ ] **Step 3: Add `value_mode` to `SideValueTable.__init__`**

In `arkgrid/probability.py`, change the `SideValueTable.__init__` signature to add the keyword-only param (after `ancient_coeff`):

```python
    def __init__(
        self,
        goal: LastTurnGoal,
        max_turns: int,
        pool: OptionPool,
        *,
        gem_type: str,
        optimize: str = "dps",
        min_side_coeff: int = 0,
        relic_coeff: Optional[int] = None,
        ancient_coeff: Optional[int] = None,
        value_mode: str = "side",
    ) -> None:
```

Immediately after `self._min_side_coeff = min_side_coeff`, store the mode:

```python
        self._min_side_coeff = min_side_coeff
        self.value_mode = value_mode
```

Then, after the `if self.enabled: ... else: ...` block that resolves `self.relic_coeff` / `self.ancient_coeff` (just before `self._dp: Dict[tuple, float] = {}`), force them to zero in will/chaos mode:

```python
        if value_mode == "will_chaos":
            # will/chaos value ignores grade entirely.
            self.relic_coeff = 0
            self.ancient_coeff = 0
```

- [ ] **Step 4: Branch `_gem_value_idx` on the mode**

In `arkgrid/probability.py`, replace the body of `_gem_value_idx` with:

```python
    def _gem_value_idx(self, w: int, c: int, f: int, s: int,
                       fi: int, si: int) -> float:
        """Terminal gem value for an effect-indexed state.

        0 when the goal (or the `min_side_coeff` floor) is broken — a
        failed gem is worth nothing, which makes the DP price the risk of
        processing into a goal-break.
        """
        if not self.goal.satisfied(w, c, f, s):
            return 0.0
        if self.value_mode == "will_chaos":
            # New-character value: will + chaos only, no side/grade value
            # and no side-coeff floor.
            return float(w + c)
        coeff = self._effect_coeffs[fi] * f + self._effect_coeffs[si] * s
        if self._min_side_coeff > 0 and coeff < self._min_side_coeff:
            return 0.0
        return float(coeff + self._tier_bonus(w + c + f + s))
```

- [ ] **Step 5: Run the new tests, then the full probability suite**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_probability -v`
Expected: PASS (the new `TestSideValueTableWillChaosMode` and all existing tests, including `TestSideValueTable` / `TestSideValueTableFusionDefault`).

- [ ] **Step 6: Commit**

```bash
git add arkgrid/probability.py tests/test_probability.py
git commit -m "$(printf 'feat: add will_chaos value_mode to SideValueTable\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: `ignore_side_node_values` in `GemSimulator` + decision behaviour

**Files:**
- Modify: `arkgrid/simulator.py` (`GemSimulator.__init__`, `_get_side_value_table`)
- Test: `tests/test_simulator.py`, `tests/test_decision.py`

**Interfaces:**
- Consumes: `SideValueTable(..., value_mode=...)` (Task 2); `decision.build` fixtures in `tests/test_decision.py` (`build_ctx`, `build_ti`, `make_offers`, `decide_post_roll`).
- Produces: `GemSimulator(..., ignore_side_node_values: bool = False)`; when set, `_get_side_value_table(gem_type).value_mode == "will_chaos"` while `_get_grade_value_table(gem_type).value_mode == "side"`. A `side_value_mode` kwarg added to the `tests/test_decision.py::build_ctx` helper.

- [ ] **Step 1: Write the failing simulator test**

In `tests/test_simulator.py`, add a new test class (the file already imports `unittest`, and `GemSimulator` / `LastTurnGoal` from `arkgrid` — no new imports needed):

```python
class TestIgnoreSideNodeValuesTables(unittest.TestCase):
    def _sim(self, **kw):
        defaults = dict(
            rarity="epic", use_extra_ticket=True, use_reset_ticket=False,
            goal=LastTurnGoal(min_total_will_chaos=8), optimize="dps",
        )
        defaults.update(kw)
        return GemSimulator(**defaults)

    def test_side_value_table_uses_will_chaos_mode_when_set(self):
        sim = self._sim(ignore_side_node_values=True)
        svt = sim._get_side_value_table("order_fortitude")
        self.assertEqual(svt.value_mode, "will_chaos")

    def test_grade_value_table_stays_side_mode_when_set(self):
        sim = self._sim(ignore_side_node_values=True)
        gvt = sim._get_grade_value_table("order_fortitude")
        self.assertEqual(gvt.value_mode, "side")

    def test_default_side_value_table_is_side_mode(self):
        sim = self._sim()
        svt = sim._get_side_value_table("order_fortitude")
        self.assertEqual(svt.value_mode, "side")
```

- [ ] **Step 2: Run to verify it fails**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_simulator.TestIgnoreSideNodeValuesTables -v`
Expected: FAIL/ERROR — `GemSimulator.__init__()` got an unexpected keyword argument `ignore_side_node_values`.

- [ ] **Step 3: Add the constructor knob in `GemSimulator.__init__`**

In `arkgrid/simulator.py`, add the parameter to `__init__` (after `ancient_coeff: Optional[int] = None,`):

```python
            ancient_coeff: Optional[int] = None,
            ignore_side_node_values: bool = False,
    ) -> None:
```

and store it alongside the other knobs (after `self.ancient_coeff = ancient_coeff`):

```python
        self.ancient_coeff = ancient_coeff
        self.ignore_side_node_values = ignore_side_node_values
```

- [ ] **Step 4: Build the side-value table in will/chaos mode when set**

In `arkgrid/simulator.py`, in `_get_side_value_table`, add `value_mode` to the `SideValueTable(...)` construction:

```python
        table = SideValueTable(
            self.goal, self.turns_total, self.pool,
            gem_type=gem_type, optimize=self.optimize,
            min_side_coeff=self.min_side_coeff,
            relic_coeff=self.relic_coeff,
            ancient_coeff=self.ancient_coeff,
            value_mode=("will_chaos" if self.ignore_side_node_values
                        else "side"),
        )
```

Leave `_get_grade_value_table` unchanged (it stays `"side"` mode for the dead-goal grade chase).

- [ ] **Step 5: Run the simulator test to verify it passes**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_simulator.TestIgnoreSideNodeValuesTables -v`
Expected: PASS.

- [ ] **Step 6: Add a `side_value_mode` kwarg to the decision test fixture**

In `tests/test_decision.py`, in `build_ctx`, add a parameter `side_value_mode: str = "side"` (after `ancient_coeff: Optional[int] = 0,`):

```python
    relic_coeff: Optional[int] = 0,
    ancient_coeff: Optional[int] = 0,
    side_value_mode: str = "side",
) -> DecisionContext:
```

and pass it into the `side_value_table` construction:

```python
    side_value_table = SideValueTable(
        g, turns_total, _POOL, gem_type=gem_type, optimize=optimize,
        min_side_coeff=min_side_coeff,
        relic_coeff=relic_coeff, ancient_coeff=ancient_coeff,
        value_mode=side_value_mode,
    )
```

- [ ] **Step 7: Write the decision-behaviour tests**

In `tests/test_decision.py`, add a new test class (the file already imports `ActionKind`, `decide_post_roll`, `GemState`, `LastTurnGoal`, plus `build_ctx`/`build_ti`/`make_offers` are module-level):

```python
class TestIgnoreSideNodeValuesBehaviour(unittest.TestCase):
    """With a will_chaos side-value table, a goal-met gem pushes will/chaos
    higher (never finishes with a free reroll), and a fully-dead goal still
    chases grade via the unchanged grade-value table."""

    def test_goal_met_with_reroll_continues_not_finishes(self):
        g = LastTurnGoal(min_total_will_chaos=8)
        ctx = build_ctx(goal=g, side_value_mode="will_chaos",
                        relic_coeff=0, ancient_coeff=0)
        st = GemState(will=4, chaos=5, first=5, second=5, rerolls=2,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will+1", "chaos+1",
                                         "first-1", "second-1"),
                      turn=5, turns_left=5, rerolls=2,
                      reset_available=False)
        d = decide_post_roll(ctx, ti)
        # Goal met (9), free reroll in hand -> never FINISH.
        self.assertIn(d.action, (ActionKind.REROLL, ActionKind.PROCESS))

    def test_dead_goal_still_chases_grade(self):
        # Goal needs 5-5 (total 10) but state can't reach it in 1 turn ->
        # infeasible. No reset/reroll -> grade chase via grade_value_table
        # (side mode), NOT a FAIL.
        g = LastTurnGoal(min_total_will_chaos=10)
        ctx = build_ctx(goal=g, side_value_mode="will_chaos",
                        relic_coeff=3000, ancient_coeff=8000)
        st = GemState(will=1, chaos=1, first=5, second=5, rerolls=0,
                      first_effect="boss_damage",
                      second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will+1", "chaos+1",
                                         "first+1", "second+1"),
                      turn=9, turns_left=1, rerolls=0,
                      reset_available=False)
        d = decide_post_roll(ctx, ti)
        self.assertIn(d.branch, ("infeasible", "no_feasible_offer"))
        self.assertNotEqual(d.action, ActionKind.FAIL)
```

- [ ] **Step 8: Run the decision suite**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision -v`
Expected: PASS (the new class confirms the behaviour falls out of the value tables — no `decision.py` change was needed).

- [ ] **Step 9: Commit**

```bash
git add arkgrid/simulator.py tests/test_simulator.py tests/test_decision.py
git commit -m "$(printf 'feat: ignore_side_node_values knob on GemSimulator (will_chaos value)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 4: `--ignore-side-node-values` CLI flag + automation wiring

**Files:**
- Modify: `arkgrid/cli.py` (`add_common`, `cmd_stats`, `cmd_sim`, `cmd_live`, `cmd_auto`, `_add_report_filter_args`)
- Modify: `arkgrid/automation.py` (`run_auto` param + side-value table `value_mode`)
- Modify: `arkgrid/log_analyzer.py` (`_matches` bool filter)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `GemSimulator(..., ignore_side_node_values=...)` (Task 3); `SideValueTable(..., value_mode=...)` (Task 2).
- Produces: `--ignore-side-node-values` flag on `stats`/`sim`/`live`/`auto`/`report`, threaded into every `GemSimulator(...)` and `run_auto(...)` construction; `run_auto(..., ignore_side_node_values: bool = False)`.

- [ ] **Step 1: Write the failing CLI test**

In `tests/test_cli.py`, in the `TestWillChaosTotalGoal` class added in Task 1 (or a new class), add:

```python
    def test_ignore_side_node_values_parses(self):
        args = _build_parser().parse_args(
            ["sim", "--min-total-will-chaos", "8", "--ignore-side-node-values"])
        self.assertTrue(args.ignore_side_node_values)

    def test_ignore_side_node_values_default_false(self):
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertFalse(args.ignore_side_node_values)
```

- [ ] **Step 2: Run to verify it fails**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_cli.TestWillChaosTotalGoal.test_ignore_side_node_values_parses -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'ignore_side_node_values'` (argparse stores unknown attrs as absent).

- [ ] **Step 3: Add the flag to `add_common`**

In `arkgrid/cli.py`, in `add_common`, after the `--min-total-will-chaos` argument added in Task 1:

```python
        p.add_argument("--ignore-side-node-values", action="store_true",
                        default=False,
                        help="Optimise purely for willpower/chaos: the gem's "
                             "value becomes will+chaos (no side-node / grade "
                             "value). After the goal is met the engine pushes "
                             "will/chaos higher; only once the goal is fully "
                             "infeasible does it fall back to chasing grade. "
                             "Intended for new characters.")
```

- [ ] **Step 4: Thread it into the three `GemSimulator(...)` constructions**

In `arkgrid/cli.py`, add `ignore_side_node_values=args.ignore_side_node_values,` to the `GemSimulator(...)` call in `cmd_stats` (after `ancient_coeff=args.ancient_coeff,`), and the same in `cmd_sim` (after `ancient_coeff=args.ancient_coeff,`).

In `cmd_live`, the MC `GemSimulator(...)` call uses `getattr` for several args; add:

```python
            ancient_coeff=getattr(args, "ancient_coeff", None),
            ignore_side_node_values=getattr(args, "ignore_side_node_values", False),
        )
```

- [ ] **Step 5: Thread it into `cmd_live`'s inline early-finish `SideValueTable`**

In `arkgrid/cli.py`, in `cmd_live`, in the `SideValueTable(...)` built for the early-finish check, add:

```python
            relic_coeff=getattr(args, "relic_coeff", None),
            ancient_coeff=getattr(args, "ancient_coeff", None),
            value_mode=("will_chaos"
                        if getattr(args, "ignore_side_node_values", False)
                        else "side"),
        )
```

- [ ] **Step 6: Thread it into `cmd_auto` -> `run_auto`**

In `arkgrid/cli.py`, in `cmd_auto`, add to the `run_auto(...)` call (after `ancient_coeff=args.ancient_coeff,`):

```python
        ancient_coeff=args.ancient_coeff,
        ignore_side_node_values=args.ignore_side_node_values,
    )
```

- [ ] **Step 7: Add the param + value_mode to `run_auto`**

In `arkgrid/automation.py`, add the parameter to `run_auto` (after `ancient_coeff: Optional[int] = None,`):

```python
    ancient_coeff: Optional[int] = None,
    ignore_side_node_values: bool = False,
    args=None,
```

and in the `side_value_table = SideValueTable(...)` construction (the goal-conditioned one, NOT the `grade_value_table`), add:

```python
                    side_value_table = SideValueTable(
                        goal, det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=min_side_coeff,
                        relic_coeff=relic_coeff,
                        ancient_coeff=ancient_coeff,
                        value_mode=("will_chaos" if ignore_side_node_values
                                    else "side"),
                    )
```

Leave the `grade_value_table = SideValueTable(LastTurnGoal(), ...)` construction unchanged.

- [ ] **Step 8: Add the report filter arg + bool filter**

In `arkgrid/cli.py`, in `_add_report_filter_args`, after the `--bis-only` argument:

```python
    p.add_argument("--bis-only", action="store_true", default=False)
```

add:

```python
    p.add_argument("--ignore-side-node-values", action="store_true",
                   default=False)
```

In `arkgrid/log_analyzer.py`, in `_matches`, after the `bis_only` filter block:

```python
    bis_only = _filter_value(args, "bis_only", False)
    if bis_only:
        if not bool(a.get("bis_only")):
            return False
```

add:

```python
    ignore_side = _filter_value(args, "ignore_side_node_values", False)
    if ignore_side:
        if not bool(a.get("ignore_side_node_values")):
            return False
```

- [ ] **Step 9: Run the full suite**

Run: `source .venv/Scripts/activate && python -m unittest discover -s tests -q`
Expected: OK (no failures/errors).

- [ ] **Step 10: Smoke-check both flags together**

Run: `source .venv/Scripts/activate && python -m arkgrid sim --min-total-will-chaos 8 --ignore-side-node-values --first-effect boss_damage --second-effect attack_power --rarity epic --seed 7`
Expected: prints the config (`min_total_will_chaos=8`), a turn-by-turn log, and a SUCCESS/FAIL result with no traceback.

Run: `source .venv/Scripts/activate && python -m arkgrid auto --min-total-will-chaos 8 --ignore-side-node-values --dry-run --first-effect boss_damage --second-effect attack_power 2>&1 | head -5`
Expected: prints the auto banner / config without a traceback (it will then wait for a screen; Ctrl-C / Escape is fine — we only verify no import/arg errors). If the environment cannot capture a screen, a clean "no anchor"/capture message is acceptable; an argparse or constructor error is not.

- [ ] **Step 11: Commit**

```bash
git add arkgrid/cli.py arkgrid/automation.py arkgrid/log_analyzer.py tests/test_cli.py
git commit -m "$(printf 'feat: add --ignore-side-node-values flag, wire through sim/live/auto/report\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Self-Review

**Spec coverage:**
- `--min-total-will-chaos N` (success = will+chaos ≥ N) — Task 1 (CLI wiring + model guard + report filter + tests). ✔
- `> 10` infeasibility guard — Task 1 Step 3. ✔
- `value_mode="will_chaos"` on `SideValueTable` (gem_value = will+chaos, relic/ancient forced 0, min_side_coeff floor skipped) — Task 2. ✔
- Goal-conditioned `side_value_table` switches to will_chaos; goal-independent `grade_value_table` stays side mode — Task 3 (simulator) + Task 4 (automation). ✔
- Goal-met → push will/chaos higher; dead goal → chase grade — Task 3 decision-behaviour tests. ✔
- `relic_prob_table` still built for display — unchanged (no task removes it). ✔
- `--relic-coeff`/`--ancient-coeff` still tune the dead-goal grade chase — `grade_value_table` left unchanged in Tasks 3/4. ✔
- `decision.py` needs no change — confirmed by Task 3 Step 8 (behaviour tests pass with no edit). ✔
- Flags reach `stats`/`sim`/`live`/`auto`/`report` — Tasks 1 & 4. ✔

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code. ✔

**Type consistency:** `value_mode: str` (default `"side"`, value `"will_chaos"`) used identically in `SideValueTable.__init__`, `GemSimulator._get_side_value_table`, `run_auto`, `cmd_live`, and the `build_ctx` test helper. `ignore_side_node_values: bool` used identically across `GemSimulator.__init__`, `run_auto`, and CLI threading. Branch names asserted in tests (`"infeasible"`, `"no_feasible_offer"`) match `decision.py`'s existing branch tags. ✔
