# Maxed will/chaos side/grade chase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under `--ignore-side-node-values`, once will/chaos is capped at 5/5 (goal locked), chase `side_coeff + grade tier_bonus` via free rerolls and safe-hand processing — holding will/chaos firm — instead of scoring every action 10 and burning rerolls to finish at a legendary gem.

**Architecture:** A new decision branch `_maxed_hold_decision` (in `arkgrid/decision.py`) fires only when `ctx.maxed_value_table is not None` (the flag signal) and `will == 5 and chaos == 5`. It consults a third per-gem-type cached `SideValueTable` built in `value_mode="side"` (the "maxed oracle"), gates `PROCESS` on a will/chaos-safe hand, rerolls freely while upside remains, and finishes the moment the oracle sees no reachable upside. The existing `will_chaos` (below-cap) and `grade_only` (dead-goal) tables are untouched.

**Tech Stack:** Python 3 stdlib only. Tests via `unittest`. Activate the venv first: `source .venv/Scripts/activate`.

## Global Constraints

- No external dependencies for the simulator/decision/probability modules — stdlib only.
- Run tests with: `source .venv/Scripts/activate && python -m unittest <target> -v`.
- No linter configured; "quality gate" = the full test suite passes (`python -m unittest discover -s tests`).
- Commit messages use `feat:` / `test:` / `docs:` prefixes and end with the trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Work happens on branch `feat/maxed-wc-side-grade-chase` (already created; spec already committed there).
- `value_mode` string values are exactly `"side"`, `"will_chaos"`, `"grade_only"` — used identically across `SideValueTable`, simulator, automation, and the `build_ctx` test helper.
- Effect-aware DP self-disables when the gem type is unknown; the new oracle is only built/passed for a known gem type under the flag, so it is `None` otherwise.

---

## File Structure

- `arkgrid/decision.py` — new field `DecisionContext.maxed_value_table`, helper `_hand_is_wc_safe`, branch `_maxed_hold_decision`, wiring at the top of `_side_value_finish_decision`.
- `arkgrid/simulator.py` — `_maxed_value_table_cache` + `_maxed_value_table` attrs, `_get_maxed_value_table()`, per-run set in `simulate_one`, resolve+pass in `_decision_context`.
- `arkgrid/automation.py` — build the oracle inline (flag-gated) next to the existing two tables, pass into `DecisionContext`.
- `tests/test_decision.py` — `build_ctx` fixture builds the maxed oracle under `will_chaos`; `_hand_is_wc_safe` unit tests; `TestMaxedHoldDecision` branch tests.
- `tests/test_simulator.py` — maxed-oracle table tests (side mode under flag; `None` without flag).
- `README.md`, `CLAUDE.md` — document the maxed-state behavior.

---

## Task 1: decision.py plumbing — field, hand-safety helper, fixture

**Files:**
- Modify: `arkgrid/decision.py` (add `DecisionContext.maxed_value_table`; add `_hand_is_wc_safe`)
- Modify: `tests/test_decision.py` (import `_hand_is_wc_safe`; `build_ctx` builds the maxed oracle; add helper tests)

**Interfaces:**
- Produces: `DecisionContext.maxed_value_table: Optional[SideValueTable] = None`
- Produces: `decision._hand_is_wc_safe(offers: List[Option]) -> bool` — `True` when no offer reduces will or chaos.
- Produces: `build_ctx(...)` now sets `maxed_value_table` to a `value_mode="side"` `SideValueTable` whenever `side_value_mode == "will_chaos"`, else `None`.

- [ ] **Step 1: Write the failing helper tests**

In `tests/test_decision.py`, add `_hand_is_wc_safe` to the import block from `arkgrid.decision` (the one ending `_side_coeff, _legal_actions,`):

```python
from arkgrid.decision import (
    ActionKind, Decision, DecisionContext, TurnInput,
    compute_post_roll_metrics, decide_post_roll,
    early_finish_decision, has_progress_offer,
    infeasibility_decision, last_turn_reset_decision,
    no_feasible_offer_decision, prob_reset_decision,
    _side_coeff, _legal_actions, _hand_is_wc_safe,
)
```

Add this test class at the end of `tests/test_decision.py`:

```python
class TestHandIsWcSafe(unittest.TestCase):
    def test_safe_without_wc_negative(self):
        offers = make_offers("second+3", "first+1", "cost+100", "maintain")
        self.assertTrue(_hand_is_wc_safe(offers))

    def test_unsafe_with_will_negative(self):
        offers = make_offers("will-1", "second+3", "first+1", "maintain")
        self.assertFalse(_hand_is_wc_safe(offers))

    def test_unsafe_with_chaos_negative(self):
        offers = make_offers("chaos-1", "second+3", "first+1", "maintain")
        self.assertFalse(_hand_is_wc_safe(offers))
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision.TestHandIsWcSafe -v`
Expected: FAIL — `ImportError: cannot import name '_hand_is_wc_safe'`.

- [ ] **Step 3: Add the `maxed_value_table` field to `DecisionContext`**

In `arkgrid/decision.py`, in the `DecisionContext` dataclass, after the `grade_value_table` field (the last field, ending `grade_value_table: Optional[SideValueTable] = None`), add:

```python
    # Side-mode value oracle (`side_coeff + tier_bonus`) consulted only at
    # the will/chaos cap under --ignore-side-node-values, where the
    # `will_chaos` `side_value_table` is degenerate (every state scores 10).
    # Its presence is the flag signal — None unless the flag is set.
    maxed_value_table: Optional[SideValueTable] = None
```

- [ ] **Step 4: Add the `_hand_is_wc_safe` helper**

In `arkgrid/decision.py`, add this function just above `def _legal_actions(`:

```python
def _hand_is_wc_safe(offers: List[Option]) -> bool:
    """True when no offer can reduce will or chaos.

    `Process` applies a uniformly random one of the 4 offers, so a hand
    that contains any `will-`/`chaos-` offer carries a real risk of
    dropping off the will/chaos cap. `_maxed_hold_decision` never processes
    such a hand.
    """
    return not any(o.kind in ("will", "chaos") and o.delta < 0
                   for o in offers)
```

- [ ] **Step 5: Run the helper tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision.TestHandIsWcSafe -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Update `build_ctx` to build the maxed oracle under `will_chaos`**

In `tests/test_decision.py`, inside `build_ctx`, immediately after the `side_value_table = SideValueTable(...)` assignment block (the one ending `value_mode=side_value_mode,\n    )`), add:

```python
    # Mirror production: under --ignore-side-node-values the side-value table
    # is will_chaos, and a parallel side-mode "maxed oracle" is built for the
    # will/chaos cap. Without the flag the maxed branch never fires.
    maxed_value_table = None
    if side_value_mode == "will_chaos":
        maxed_value_table = SideValueTable(
            g, turns_total, _POOL, gem_type=gem_type, optimize=optimize,
            min_side_coeff=min_side_coeff,
            relic_coeff=relic_coeff, ancient_coeff=ancient_coeff,
            value_mode="side",
        )
```

Then, in the `return DecisionContext(...)` call in `build_ctx`, add the argument after `grade_value_table=grade_value_table,`:

```python
        grade_value_table=grade_value_table,
        maxed_value_table=maxed_value_table,
    )
```

- [ ] **Step 7: Run the full decision + simulator suites to confirm no regressions**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision tests.test_simulator -v`
Expected: PASS (all existing tests still green — the new field defaults to `None`, the maxed oracle is built but unused because no branch reads it yet, and no existing `will_chaos` test is at 5/5).

- [ ] **Step 8: Commit**

```bash
git add arkgrid/decision.py tests/test_decision.py
git commit -m "$(printf 'feat: add maxed_value_table field + hand-safety helper\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: decision.py logic — `_maxed_hold_decision` + wiring

**Files:**
- Modify: `arkgrid/decision.py` (add `_maxed_hold_decision`; wire into `_side_value_finish_decision`)
- Modify: `tests/test_decision.py` (add `TestMaxedHoldDecision`)

**Interfaces:**
- Consumes: `DecisionContext.maxed_value_table` (Task 1); `_hand_is_wc_safe` (Task 1); `_GRADE_VALUE_EPS` (existing, `arkgrid/decision.py`); `SideValueTable.gem_value(state)`, `.expected_value_after_click(state, offers, turns_left)`, `.lookup(state, turns_left)` (existing).
- Produces: `decision._maxed_hold_decision(ctx, ti) -> Decision` with `branch == "maxed_hold"`, returning `PROCESS` / `REROLL` / `FINISH`. Wired as the first check inside `_side_value_finish_decision`.

- [ ] **Step 1: Write the failing branch tests**

Add this test class at the end of `tests/test_decision.py`:

```python
class TestMaxedHoldDecision(unittest.TestCase):
    """will==5 chaos==5 under --ignore-side-node-values: hold will/chaos
    firm and chase side+grade via the maxed oracle, instead of the
    degenerate will_chaos 'reroll then finish'."""

    def _ctx(self):
        return build_ctx(
            goal=LastTurnGoal(min_total_will_chaos=8),
            gem_type="order_fortitude", optimize="dps",
            side_value_mode="will_chaos",
            relic_coeff=3000, ancient_coeff=8000,
        )

    def test_safe_hand_with_reroll_chases_not_finishes(self):
        # Reproduces the reported run: 5/5, boss_damage low, rerolls in hand.
        st = GemState(will=5, chaos=5, first=1, second=2, rerolls=2,
                      first_effect="attack_power", second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("second+3", "second+1",
                                         "first+1", "maintain"),
                      turn=5, turns_left=5, rerolls=2, reset_available=False)
        d = decide_post_roll(self._ctx(), ti)
        self.assertEqual(d.branch, "maxed_hold")
        self.assertIn(d.action, (ActionKind.PROCESS, ActionKind.REROLL))
        self.assertNotEqual(d.action, ActionKind.FINISH)

    def test_unsafe_hand_with_reroll_rerolls(self):
        st = GemState(will=5, chaos=5, first=1, second=2, rerolls=2,
                      first_effect="attack_power", second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "second+3",
                                         "second+1", "cost+100"),
                      turn=5, turns_left=5, rerolls=2, reset_available=False)
        d = decide_post_roll(self._ctx(), ti)
        self.assertEqual(d.branch, "maxed_hold")
        self.assertEqual(d.action, ActionKind.REROLL)

    def test_unsafe_hand_no_reroll_finishes(self):
        st = GemState(will=5, chaos=5, first=1, second=2, rerolls=0,
                      first_effect="attack_power", second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "second+3",
                                         "second+1", "cost+100"),
                      turn=9, turns_left=3, rerolls=0, reset_available=False)
        d = decide_post_roll(self._ctx(), ti)
        self.assertEqual(d.branch, "maxed_hold")
        self.assertEqual(d.action, ActionKind.FINISH)

    def test_safe_hand_no_reroll_processes(self):
        st = GemState(will=5, chaos=5, first=1, second=2, rerolls=0,
                      first_effect="attack_power", second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("second+3", "second+1",
                                         "first+1", "maintain"),
                      turn=9, turns_left=3, rerolls=0, reset_available=False)
        d = decide_post_roll(self._ctx(), ti)
        self.assertEqual(d.branch, "maxed_hold")
        self.assertEqual(d.action, ActionKind.PROCESS)

    def test_no_upside_finishes_even_with_rerolls(self):
        # Fully maxed gem (5/5/5/5): nothing left to improve -> FINISH
        # despite a free reroll (the old will_chaos model would reroll).
        st = GemState(will=5, chaos=5, first=5, second=5, rerolls=2,
                      first_effect="attack_power", second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("first-1", "second-1",
                                         "maintain", "cost+100"),
                      turn=5, turns_left=5, rerolls=2, reset_available=False)
        d = decide_post_roll(self._ctx(), ti)
        self.assertEqual(d.branch, "maxed_hold")
        self.assertEqual(d.action, ActionKind.FINISH)

    def test_below_cap_does_not_use_maxed_branch(self):
        # 5/4 (total 9, goal met) is NOT the cap -> will_chaos behavior.
        st = GemState(will=5, chaos=4, first=1, second=2, rerolls=2,
                      first_effect="attack_power", second_effect="boss_damage")
        ti = build_ti(state=st,
                      offers=make_offers("chaos+1", "second+1",
                                         "first+1", "maintain"),
                      turn=5, turns_left=5, rerolls=2, reset_available=False)
        d = decide_post_roll(self._ctx(), ti)
        self.assertNotEqual(d.branch, "maxed_hold")
```

- [ ] **Step 2: Run the branch tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision.TestMaxedHoldDecision -v`
Expected: FAIL — most cases assert `d.branch == "maxed_hold"` but the current code returns `side_value_finish` / other branches (the maxed branch does not exist yet).

- [ ] **Step 3: Add `_maxed_hold_decision`**

In `arkgrid/decision.py`, add this function immediately above `def _side_value_finish_decision(`:

```python
def _maxed_hold_decision(ctx: DecisionContext, ti: TurnInput) -> Decision:
    """will==5 and chaos==5 under --ignore-side-node-values.

    Will/chaos is capped and the goal is locked, so chase
    `side_coeff + grade tier_bonus` as free upside via the side-mode
    oracle (`ctx.maxed_value_table`) — while holding will/chaos firm:

    * Reroll is free and never changes state, so fish for a safe hand
      while any upside remains.
    * Process only a hand that can't reduce will/chaos (`_hand_is_wc_safe`),
      and only when it improves expected value.
    * Finish the moment the oracle sees no reachable upside (mirrors the
      dead-goal `_grade_value_decision` finish-early guard) — this kills
      the pointless-reroll churn the `will_chaos` model produced at the cap.
    """
    oracle = ctx.maxed_value_table
    finish_val = oracle.gem_value(ti.state)
    process_ev = oracle.expected_value_after_click(
        ti.state, ti.offers, ti.turns_left - 1)
    hand_safe = _hand_is_wc_safe(ti.offers)
    can_reroll = ti.rerolls > 0 and ti.turn != 1
    metrics = {"finish_val": finish_val, "process_ev": process_ev,
               "hand_safe": hand_safe}

    if can_reroll:
        reroll_val = oracle.lookup(ti.state, ti.turns_left)
        metrics["reroll_val"] = reroll_val
        best_continue = (max(reroll_val, process_ev) if hand_safe
                         else reroll_val)
        if best_continue <= finish_val + _GRADE_VALUE_EPS:
            return Decision(
                action=ActionKind.FINISH, branch="maxed_hold",
                reason=(f"will/chaos maxed, no side/grade upside left "
                        f"(finish_val={finish_val:.0f} >= "
                        f"continue={best_continue:.0f})"),
                metrics=metrics,
            )
        if hand_safe and process_ev >= reroll_val:
            return Decision(
                action=ActionKind.PROCESS, branch="maxed_hold",
                reason=(f"will/chaos maxed, processing safe hand for "
                        f"side/grade (process_ev={process_ev:.0f} >= "
                        f"reroll_val={reroll_val:.0f})"),
                metrics=metrics,
            )
        reason = (f"will/chaos maxed, rerolling for side/grade "
                  f"(reroll_val={reroll_val:.0f})" if hand_safe else
                  "will/chaos maxed, rerolling — hand can reduce will/chaos")
        return Decision(
            action=ActionKind.REROLL, branch="maxed_hold",
            reason=reason, metrics=metrics,
        )

    # No reroll (exhausted / turn 1): process a safe improving hand, else stop.
    if hand_safe and process_ev > finish_val + _GRADE_VALUE_EPS:
        return Decision(
            action=ActionKind.PROCESS, branch="maxed_hold",
            reason=(f"will/chaos maxed, processing safe hand for side/grade "
                    f"(process_ev={process_ev:.0f} > "
                    f"finish_val={finish_val:.0f})"),
            metrics=metrics,
        )
    return Decision(
        action=ActionKind.FINISH, branch="maxed_hold",
        reason=(f"will/chaos maxed, holding — no safe improvement "
                f"(finish_val={finish_val:.0f})"),
        metrics=metrics,
    )
```

- [ ] **Step 4: Wire it into `_side_value_finish_decision`**

In `arkgrid/decision.py`, in `_side_value_finish_decision`, immediately after the docstring and before the line `svt = ctx.side_value_table`, insert:

```python
    # At the will/chaos cap under --ignore-side-node-values the will_chaos
    # side-value table is degenerate (every state scores 10). Delegate to the
    # side-mode maxed oracle, which chases side+grade while holding the cap.
    if (ctx.maxed_value_table is not None
            and ti.state.will == 5 and ti.state.chaos == 5):
        return _maxed_hold_decision(ctx, ti)
```

- [ ] **Step 5: Run the branch tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision.TestMaxedHoldDecision -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Run the full decision suite to confirm no regressions**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_decision -v`
Expected: PASS (all tests, including the existing `TestIgnoreSideNodeValuesBehaviour` cases — none are at 5/5, so the maxed branch never intercepts them).

- [ ] **Step 7: Commit**

```bash
git add arkgrid/decision.py tests/test_decision.py
git commit -m "$(printf 'feat: chase side/grade at the will/chaos cap (maxed_hold branch)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: simulator wiring

**Files:**
- Modify: `arkgrid/simulator.py` (caches in `__init__`; `_get_maxed_value_table`; per-run set in `simulate_one`; resolve+pass in `_decision_context`)
- Modify: `tests/test_simulator.py` (extend `TestIgnoreSideNodeValuesTables`)

**Interfaces:**
- Consumes: `DecisionContext.maxed_value_table` (Task 1); `SideValueTable(..., value_mode="side")` (existing).
- Produces: `GemSimulator._get_maxed_value_table(gem_type) -> SideValueTable` (value_mode `"side"`, cached); `GemSimulator._maxed_value_table` per-run attr; `_decision_context` passes `maxed_value_table=` (non-`None` only under the flag with a known gem type).

- [ ] **Step 1: Write the failing simulator tests**

In `tests/test_simulator.py`, add these methods to the existing `TestIgnoreSideNodeValuesTables` class:

```python
    def test_maxed_value_table_is_side_mode_when_set(self):
        sim = self._sim(ignore_side_node_values=True)
        mvt = sim._get_maxed_value_table("order_fortitude")
        self.assertEqual(mvt.value_mode, "side")

    def test_maxed_value_table_in_context_under_flag(self):
        sim = self._sim(ignore_side_node_values=True)
        sim.astro_gem = AstroGem("order_fortitude", "boss_damage",
                                 "attack_power", "dps")
        ctx = sim._decision_context(p_fresh=0.5)
        self.assertIsNotNone(ctx.maxed_value_table)
        self.assertEqual(ctx.maxed_value_table.value_mode, "side")

    def test_maxed_value_table_absent_without_flag(self):
        sim = self._sim()  # no ignore_side_node_values
        sim.astro_gem = AstroGem("order_fortitude", "boss_damage",
                                 "attack_power", "dps")
        ctx = sim._decision_context(p_fresh=0.5)
        self.assertIsNone(ctx.maxed_value_table)
```

Confirm `AstroGem` is imported at the top of `tests/test_simulator.py` (the `TestRerollGoalThreshold` class already uses it, so it is). If not, add `AstroGem` to the `from arkgrid.models import ...` line.

- [ ] **Step 2: Run the simulator tests to verify they fail**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_simulator.TestIgnoreSideNodeValuesTables -v`
Expected: FAIL — `AttributeError: 'GemSimulator' object has no attribute '_get_maxed_value_table'` and `TypeError` / missing `maxed_value_table` on the context.

- [ ] **Step 3: Add the cache attributes in `__init__`**

In `arkgrid/simulator.py`, in `__init__`, immediately after the lines:

```python
        self._grade_value_table_cache: Dict[str, SideValueTable] = {}
        self._grade_value_table: Optional[SideValueTable] = None
```

add:

```python
        self._maxed_value_table_cache: Dict[str, SideValueTable] = {}
        self._maxed_value_table: Optional[SideValueTable] = None
```

- [ ] **Step 4: Add `_get_maxed_value_table`**

In `arkgrid/simulator.py`, add this method immediately after `_get_grade_value_table` (after its `return table` line, before `_random_astro_gem`):

```python
    def _get_maxed_value_table(self, gem_type: str) -> SideValueTable:
        """Build/fetch the cached side-mode value table used at the
        will/chaos cap under --ignore-side-node-values.

        This is exactly the table `_get_side_value_table` would build
        *without* the flag (`value_mode="side"`, goal-conditioned). At the
        cap the `will_chaos` model is degenerate (every state scores 10), so
        the maxed-hold decision consults this side+grade oracle instead.
        Only consulted when `ignore_side_node_values` is set.
        """
        cached = self._maxed_value_table_cache.get(gem_type)
        if cached is not None:
            return cached
        table = SideValueTable(
            self.goal, self.turns_total, self.pool,
            gem_type=gem_type, optimize=self.optimize,
            min_side_coeff=self.min_side_coeff,
            relic_coeff=self.relic_coeff,
            ancient_coeff=self.ancient_coeff,
            value_mode="side",
        )
        self._maxed_value_table_cache[gem_type] = table
        return table
```

- [ ] **Step 5: Set the per-run table in `simulate_one`**

In `arkgrid/simulator.py`, in `simulate_one`, immediately after the block:

```python
        self._grade_value_table = (
            self._get_grade_value_table(run_gem.gem_type)
            if run_gem.gem_type in GEM_TYPES else None)
```

add:

```python
        self._maxed_value_table = (
            self._get_maxed_value_table(run_gem.gem_type)
            if (self.ignore_side_node_values
                and run_gem.gem_type in GEM_TYPES) else None)
```

- [ ] **Step 6: Resolve and pass `maxed_value_table` in `_decision_context`**

In `arkgrid/simulator.py`, in `_decision_context`, after the block:

```python
        grade_value_table = self._grade_value_table
        if grade_value_table is None and gem_type:
            grade_value_table = self._get_grade_value_table(gem_type)
```

add:

```python
        maxed_value_table = self._maxed_value_table
        if (maxed_value_table is None and gem_type
                and self.ignore_side_node_values):
            maxed_value_table = self._get_maxed_value_table(gem_type)
```

Then, in the `return DecisionContext(...)` call, add the argument after `grade_value_table=grade_value_table,`:

```python
            grade_value_table=grade_value_table,
            maxed_value_table=maxed_value_table,
        )
```

- [ ] **Step 7: Run the simulator tests to verify they pass**

Run: `source .venv/Scripts/activate && python -m unittest tests.test_simulator.TestIgnoreSideNodeValuesTables -v`
Expected: PASS (existing 4 + new 3 = 7 tests).

- [ ] **Step 8: Run the full suite**

Run: `source .venv/Scripts/activate && python -m unittest discover -s tests`
Expected: PASS (no regressions across the whole suite).

- [ ] **Step 9: Commit**

```bash
git add arkgrid/simulator.py tests/test_simulator.py
git commit -m "$(printf 'feat: build/pass maxed side-value oracle in GemSimulator\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 4: automation wiring

**Files:**
- Modify: `arkgrid/automation.py` (build the oracle inline, flag-gated; pass into `DecisionContext`)

**Interfaces:**
- Consumes: `DecisionContext.maxed_value_table` (Task 1); the `ignore_side_node_values` param already present on `run_auto` (`arkgrid/automation.py:569`); `gem_type_domain`, `optimize`, `pool`, `det.total_steps`, `min_side_coeff`, `relic_coeff`, `ancient_coeff` (in scope at the table-build site).
- Produces: `maxed_value_table` local in `run_auto`, passed into the `DecisionContext(...)` construction.

- [ ] **Step 1: Add a `maxed_value_table` accumulator next to the other tables**

In `arkgrid/automation.py`, the run-scoped table locals are declared with type annotations (around lines 631–636):

```python
        # Side-value DP table — built on first detection.
        side_value_table: Optional[SideValueTable] = None

        # Goal-independent grade-value table for dead-goal turns — built on
        # first detection, only when relic/ancient grade has a coefficient.
        grade_value_table: Optional[SideValueTable] = None
```

Immediately after the `grade_value_table: Optional[SideValueTable] = None` line, add:

```python

        # Side-mode oracle for the will/chaos cap under
        # --ignore-side-node-values — built on first detection, flag-gated.
        maxed_value_table: Optional[SideValueTable] = None
```

- [ ] **Step 2: Build the oracle inline (flag-gated)**

In `arkgrid/automation.py`, immediately after the `if grade_value_table is None:` block that builds `grade_value_table` (ends at the closing `)` of its `SideValueTable(...)`, around line 881), add:

```python
                # Side-mode oracle for the will/chaos cap under
                # --ignore-side-node-values (see decision._maxed_hold_decision).
                # Built only under the flag; the maxed branch never fires
                # otherwise, so it stays None for the default value model.
                if maxed_value_table is None and ignore_side_node_values:
                    maxed_value_table = SideValueTable(
                        goal, det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=min_side_coeff,
                        relic_coeff=relic_coeff,
                        ancient_coeff=ancient_coeff,
                        value_mode="side",
                    )
```

- [ ] **Step 3: Pass it into the `DecisionContext` construction**

In `arkgrid/automation.py`, in the `decision_ctx = DecisionContext(...)` call, add the argument after `grade_value_table=grade_value_table,`:

```python
                    grade_value_table=grade_value_table,
                    maxed_value_table=maxed_value_table,
                )
```

- [ ] **Step 4: Verify the module imports and a dry-run starts cleanly**

Run: `source .venv/Scripts/activate && python -c "import arkgrid.automation"`
Expected: no output, no traceback (syntax/name check).

Run: `source .venv/Scripts/activate && python -m arkgrid auto --min-total-will-chaos 8 --optimize dps --ignore-side-node-values --first-effect boss_damage --second-effect attack_power --dry-run 2>&1 | head -20`
Expected: prints config / startup lines (it will then wait for a screen capture or report focus loss). No `TypeError: __init__() got an unexpected keyword argument` and no `NameError`. Stop it with Ctrl-C if it blocks.

- [ ] **Step 5: Commit**

```bash
git add arkgrid/automation.py
git commit -m "$(printf 'feat: build/pass maxed side-value oracle in auto loop\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 5: documentation

**Files:**
- Modify: `README.md` (the `--ignore-side-node-values` row in the flags table)
- Modify: `CLAUDE.md` (the `--ignore-side-node-values` notes in `probability.py`/`decision.py`/Key Domain Concepts)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README flag description**

In `README.md`, find the `--ignore-side-node-values` table row (around line 135). Append to its description cell:

```
Once will and chaos are both maxed (5/5), the goal is locked and the engine switches to chasing side-node levels + grade (relic+/ancient) as free upside — holding will/chaos firm (it only rerolls or processes hands that cannot reduce will/chaos) and finishing the moment no further upside is reachable.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In `CLAUDE.md`, in the `decision.py` module bullet, after the sentence describing `_side_value_finish_decision`'s endgame-risk grade gate, add a sentence:

```
On goal-met turns at the will/chaos cap (`will==5 and chaos==5`) under `--ignore-side-node-values`, `_side_value_finish_decision` delegates to `_maxed_hold_decision`, which consults a side-mode "maxed oracle" (`ctx.maxed_value_table`) to chase `side_coeff + tier_bonus` while holding the cap firm — it never processes a hand containing a `will-`/`chaos-` offer (`_hand_is_wc_safe`), rerolls freely while upside remains, and finishes when the oracle sees no reachable upside.
```

In `CLAUDE.md`, in the `simulator.py` module bullet, after the grade-value table sentence, add:

```
Under `--ignore-side-node-values` it also builds a side-mode "maxed oracle" (`_get_maxed_value_table`, cached per gem type, `value_mode="side"`), used by the maxed-hold decision at the will/chaos cap.
```

In `CLAUDE.md`, in the **Key Domain Concepts** section, in the `--ignore-side-node-values` discussion (the dead-goal grade-value paragraph), add a sentence:

```
Separately, once will and chaos are both at the cap (5/5) the goal is locked, so the goal-met decision switches from the degenerate `will_chaos` value model to a side-mode oracle that chases side-node levels + grade as free upside, while holding will/chaos firm (only free rerolls and will/chaos-safe hands) and finishing when no further upside is reachable.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "$(printf 'docs: document maxed will/chaos side/grade chase\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Final verification

- [ ] **Run the full suite once more**

Run: `source .venv/Scripts/activate && python -m unittest discover -s tests`
Expected: OK (all tests pass).

- [ ] **Spot-check the reported scenario via `sim`**

Run: `source .venv/Scripts/activate && python -m arkgrid sim --min-total-will-chaos 8 --optimize dps --ignore-side-node-values --first-effect boss_damage --second-effect attack_power --rarity epic --seed 7`
Expected: a turn-by-turn log that, on any turn reaching `w=5 c=5` with a low side node and rerolls/turns left, shows side/grade-chasing actions tagged `maxed_hold` (rerolling toward / processing side-node gains) rather than value-neutral rerolls, and finishes once no upside remains.
