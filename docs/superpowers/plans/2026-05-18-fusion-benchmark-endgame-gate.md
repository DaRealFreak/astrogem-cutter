# Fusion-derived tier value + endgame-risk grade gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-derive the side-value DP's relic/ancient tier value from the gem fusion mechanic, and gate the unattended endgame-risk finish so below-average gems protect their grade.

**Architecture:** `relic_coeff` / `ancient_coeff` stop defaulting to `0` and start defaulting to a fusion-derived per-gem-type average (`pool_coeff_sum * E[points|grade] / 8`). They keep feeding `gem_value = side_coeff + tier_bonus` and additionally serve as a benchmark: when `--endgame-risk` is omitted, a goal-met gem whose side coefficient is below its grade's benchmark finishes to protect the grade instead of chasing more coefficient. All three CLI knobs gain a `None` sentinel meaning "auto".

**Tech Stack:** Python 3 stdlib only; `unittest`. Run tests with `python -m unittest`. No build step, no linter.

Design doc: `docs/superpowers/specs/2026-05-18-fusion-benchmark-endgame-gate-design.md`.

**Branch:** Create a feature branch before Task 1 (e.g. `git checkout -b fusion-benchmark-endgame-gate`). For this project the full git workflow is delegated — commit per task.

---

## File Structure

- `arkgrid/constants.py` — gains `FUSION_E_POINTS` and `fusion_avg_coeff()`. (modify)
- `arkgrid/probability.py` — `SideValueTable` resolves the fusion default and exposes public `relic_coeff`/`ancient_coeff`. (modify)
- `arkgrid/decision.py` — `DecisionContext.endgame_risk` becomes `Optional[float]`; `_side_value_finish_decision` gains the grade gate. (modify)
- `arkgrid/simulator.py` — `GemSimulator` accepts `Optional` knobs; relic display table always builds. (modify)
- `arkgrid/automation.py` — `run_auto` accepts `Optional` knobs; relic display table always builds. (modify)
- `arkgrid/cli.py` — three flags default to `None`; `_print_config` and the `live` finish hint handle `None`. (modify)
- `tests/test_constants.py` — new tests for `fusion_avg_coeff`. (create)
- `tests/test_probability.py` — new tests for `SideValueTable` fusion-default resolution. (modify)
- `tests/test_decision.py` — new `TestEndgameGate` class. (modify)
- `tests/test_cli.py` — new tests for the `None` arg defaults. (modify)
- `CLAUDE.md` — documentation update. (modify)

---

### Task 1: `fusion_avg_coeff` helper

**Files:**
- Modify: `arkgrid/constants.py` (append after `change_dest_max_coeff`, end of file)
- Test: `tests/test_constants.py` (create — if it already exists, add the class to it)

- [ ] **Step 1: Write the failing test**

Create `tests/test_constants.py`:

```python
"""Tests for arkgrid.constants helpers."""
from __future__ import annotations

import unittest

from arkgrid.constants import FUSION_E_POINTS, fusion_avg_coeff


class TestFusionAvgCoeff(unittest.TestCase):
    """fusion_avg_coeff = pool_coeff_sum * E[points|grade] / 8."""

    def test_dps_immutability(self):
        # order_immutability DPS pool = additional_damage 700 + boss_damage 1000
        # relic:  1700 * 16.25 / 8 = 3453.125 -> 3453
        # ancient: 1700 * 19.05 / 8 = 4048.125 -> 4048
        self.assertEqual(fusion_avg_coeff("order_immutability", "dps", "relic"), 3453)
        self.assertEqual(fusion_avg_coeff("order_immutability", "dps", "ancient"), 4048)

    def test_dps_fortitude(self):
        # order_fortitude DPS pool = attack_power 400 + boss_damage 1000 = 1400
        self.assertEqual(fusion_avg_coeff("order_fortitude", "dps", "relic"), 2844)
        self.assertEqual(fusion_avg_coeff("order_fortitude", "dps", "ancient"), 3334)

    def test_support_fortitude(self):
        # order_fortitude SUPPORT pool = ally_damage 600 + ally_attack 1500 = 2100
        self.assertEqual(fusion_avg_coeff("order_fortitude", "support", "relic"), 4266)
        self.assertEqual(fusion_avg_coeff("order_fortitude", "support", "ancient"), 5001)

    def test_order_chaos_pairs_share_pool(self):
        # order/chaos pairs share an effect pool -> identical averages
        self.assertEqual(
            fusion_avg_coeff("order_stability", "dps", "relic"),
            fusion_avg_coeff("chaos_erosion", "dps", "relic"),
        )

    def test_unknown_gem_type_returns_zero(self):
        self.assertEqual(fusion_avg_coeff("", "dps", "relic"), 0)

    def test_e_points_keys(self):
        self.assertEqual(set(FUSION_E_POINTS), {"legendary", "relic", "ancient"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_constants -v`
Expected: FAIL — `ImportError: cannot import name 'FUSION_E_POINTS'`.

- [ ] **Step 3: Implement the helper**

Append to `arkgrid/constants.py` (after the `change_dest_max_coeff` function):

```python


# -----------------------------
# Fusion-derived average gem value
# -----------------------------

# Expected total gem points per grade, from the processed-fusion point
# distribution in documentation/official_probability_info_en.md
# (Gem Fusion: Processed Gems -> Gem Points). Recipe-independent: the
# doc states points are determined by the result grade.
#   legendary: 4-15 pts   relic: 16(80%)/17(15%)/18(5%)   ancient: 19(95%)/20(5%)
FUSION_E_POINTS: Dict[str, float] = {
    "legendary": 9.62,
    "relic": 16.25,
    "ancient": 19.05,
}


def fusion_avg_coeff(gem_type: str, optimize: str, grade: str) -> int:
    """Average side coefficient of a fused gem of `grade` for `gem_type`.

    Closed form derived from the processed-fusion mechanic: a gem of a
    given grade has `FUSION_E_POINTS[grade]` total points spread uniformly
    over the 4 options (each option averages E[points]/4 by exchange-
    ability), and 2 effects drawn uniformly from the gem type's 4-effect
    pool (each pool member is a given slot with probability 1/4). This
    reduces to `pool_coeff_sum * E[points|grade] / 8`, where pool_coeff_sum
    sums the optimize-side coefficients over the gem type's 4 effects
    (non-target effects contribute 0).

    Returns 0 when the gem type is unknown.
    """
    pool = GEM_TYPES.get(gem_type)
    if not pool:
        return 0
    coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
    pool_sum = sum(coeff_map.get(e, 0) for e in pool)
    return round(pool_sum * FUSION_E_POINTS[grade] / 8)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_constants -v`
Expected: PASS — 6 tests OK.

- [ ] **Step 5: Commit**

```bash
git add arkgrid/constants.py tests/test_constants.py
git commit -m "$(cat <<'EOF'
feat: add fusion_avg_coeff — fusion-derived average gem coefficient

Closed-form average side coefficient of a fused gem per grade, from the
processed-fusion point distribution. Used as the side-value tier value
and the endgame-risk benchmark.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `SideValueTable` resolves the fusion default

**Files:**
- Modify: `arkgrid/probability.py` — `SideValueTable.__init__` (~881-922), `_tier_bonus` (~926-932)
- Test: `tests/test_probability.py`

The constructor params `relic_coeff` / `ancient_coeff` become `Optional[int]`. `None` means "resolve the fusion default from the gem type"; an explicit int (including `0`) is used as-is. The resolved values are stored as **public** `self.relic_coeff` / `self.ancient_coeff` (the decision-layer gate reads them).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_probability.py` (new test class — place near the other `SideValueTable` tests; imports `SideValueTable`, `OptionPool`, `LastTurnGoal` should already exist in the file — add any that are missing):

```python
class TestSideValueTableFusionDefault(unittest.TestCase):
    """SideValueTable resolves relic/ancient coeff from the fusion default."""

    def test_resolves_fusion_default_when_omitted(self):
        pool = OptionPool()
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        svt = SideValueTable(goal, 9, pool,
                             gem_type="order_immutability", optimize="dps")
        self.assertEqual(svt.relic_coeff, 3453)
        self.assertEqual(svt.ancient_coeff, 4048)

    def test_explicit_coeff_overrides_fusion_default(self):
        pool = OptionPool()
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        svt = SideValueTable(goal, 9, pool,
                             gem_type="order_immutability", optimize="dps",
                             relic_coeff=500, ancient_coeff=900)
        self.assertEqual(svt.relic_coeff, 500)
        self.assertEqual(svt.ancient_coeff, 900)

    def test_explicit_zero_is_respected(self):
        pool = OptionPool()
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        svt = SideValueTable(goal, 9, pool,
                             gem_type="order_immutability", optimize="dps",
                             relic_coeff=0, ancient_coeff=0)
        self.assertEqual(svt.relic_coeff, 0)
        self.assertEqual(svt.ancient_coeff, 0)

    def test_tier_bonus_uses_resolved_values(self):
        pool = OptionPool()
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        svt = SideValueTable(goal, 9, pool,
                             gem_type="order_immutability", optimize="dps")
        # relic band (16-18 total points)
        self.assertEqual(svt._tier_bonus(17), 3453)
        # ancient band (>=19)
        self.assertEqual(svt._tier_bonus(20), 4048)
        # below relic
        self.assertEqual(svt._tier_bonus(12), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_probability.TestSideValueTableFusionDefault -v`
Expected: FAIL — `test_resolves_fusion_default_when_omitted` asserts `svt.relic_coeff == 3453` but the current default is `0`.

- [ ] **Step 3: Implement the resolution**

In `arkgrid/probability.py`, add `fusion_avg_coeff` to the existing `from arkgrid.constants import (...)` import.

Change the `SideValueTable.__init__` signature defaults (currently `relic_coeff: int = 0`, `ancient_coeff: int = 0`):

```python
        relic_coeff: Optional[int] = None,
        ancient_coeff: Optional[int] = None,
```

Replace the current assignment lines `self._relic_coeff = relic_coeff` / `self._ancient_coeff = ancient_coeff` with resolution into **public** attributes:

```python
        if gem_type in GEM_TYPES:
            self.relic_coeff = (
                relic_coeff if relic_coeff is not None
                else fusion_avg_coeff(gem_type, optimize, "relic"))
            self.ancient_coeff = (
                ancient_coeff if ancient_coeff is not None
                else fusion_avg_coeff(gem_type, optimize, "ancient"))
        else:
            # Table self-disables when the gem type is unknown; the gate
            # never reads these, but keep them well-defined ints.
            self.relic_coeff = relic_coeff or 0
            self.ancient_coeff = ancient_coeff or 0
```

Update `_tier_bonus` to use the public attributes:

```python
    def _tier_bonus(self, total_points: int) -> int:
        """Additive grade weight: ancient (>=19) or relic+ (>=16) or 0."""
        if total_points >= 19:
            return self.ancient_coeff
        if total_points >= 16:
            return self.relic_coeff
        return 0
```

`Optional` is already imported in `probability.py`. Verify there are no other references to `self._relic_coeff` / `self._ancient_coeff` in the file (`grep -n _relic_coeff arkgrid/probability.py`) — there should be none after this change.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m unittest tests.test_probability.TestSideValueTableFusionDefault -v`
Expected: PASS — 4 tests OK.

- [ ] **Step 5: Run the full probability suite and fix fallout**

Run: `python -m unittest tests.test_probability -v`

Existing `SideValueTable` tests that construct the table **without** `relic_coeff` / `ancient_coeff` previously got `0` (no tier bonus) and now get the fusion default. For each failure, decide by the test's intent:
- If the test pins behaviour that should be tier-free (e.g. asserts `gem_value == side_coeff`), add explicit `relic_coeff=0, ancient_coeff=0` to that `SideValueTable(...)` call.
- If the test exercises tier/grade behaviour, update the expected number to include the resolved `_tier_bonus`.

Re-run until the file is green.

- [ ] **Step 6: Commit**

```bash
git add arkgrid/probability.py tests/test_probability.py
git commit -m "$(cat <<'EOF'
feat: SideValueTable resolves relic/ancient tier value from fusion

relic_coeff / ancient_coeff now accept None and default to the
fusion-derived average gem coefficient for the gem type. Resolved
values are exposed as public attributes for the decision-layer gate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Endgame-risk grade gate in the decision layer

**Files:**
- Modify: `arkgrid/decision.py` — `DecisionContext.endgame_risk` (line 93), `_side_value_finish_decision` no-reroll branch (~400-421)
- Test: `tests/test_decision.py` — `build_ctx` signature types (~60-62), new `TestEndgameGate` class

`DecisionContext.endgame_risk` becomes `Optional[float]`. `None` = auto-gate; a float = manual margin (today's behaviour). The gate: when `endgame_risk is None` and the confirmation gate is off, a goal-met gem of relic/ancient grade whose side coefficient is below the grade benchmark (`svt.relic_coeff` / `svt.ancient_coeff`) **finishes** to protect the grade.

- [ ] **Step 1: Write the failing test**

In `tests/test_decision.py`, change the `build_ctx` parameter type annotations so callers may pass `None` (keep the default values unchanged):

```python
    confirm_min_coeff: Optional[int] = None,
    endgame_risk: Optional[float] = 0.0,
    relic_coeff: Optional[int] = 0,
    ancient_coeff: Optional[int] = 0,
```

Then add this test class at the end of the file (before the `if __name__ == "__main__":` block):

```python
class TestEndgameGate(unittest.TestCase):
    """Endgame-risk grade gate: below-benchmark gems protect the grade
    when --endgame-risk is omitted (endgame_risk=None)."""

    def _ctx(self, **kw):
        kw.setdefault("gem_type", "order_fortitude")
        kw.setdefault("optimize", "dps")
        kw.setdefault("goal", LastTurnGoal(min_will=4, min_chaos=4))
        return build_ctx(**kw)

    def test_below_benchmark_relic_gem_finishes_to_protect_grade(self):
        # order_fortitude relic benchmark (DPS) = 2844.
        # Gem: will5 chaos5 first3 second3 -> total 16 (relic).
        # first=attack_power L3 -> 1200 ; second=ally_damage (non-target) -> 0.
        # side_coeff 1200 < 2844 -> grade-protect FINISH despite a +EV offer.
        ctx = self._ctx(endgame_risk=None, relic_coeff=None, ancient_coeff=None)
        st = GemState(will=5, chaos=5, first=3, second=3,
                      first_effect="attack_power", second_effect="ally_damage")
        ti = build_ti(state=st,
                      offers=make_offers("first+2", "second+2",
                                         "will+1", "chaos+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = _side_value_finish_decision(ctx, ti, TurnMetrics(0, 0, 0, 0, 0))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertEqual(d.branch, "side_value_finish")
        self.assertTrue(d.metrics["grade_protect"])

    def test_above_benchmark_relic_gem_continues(self):
        # Same shape but first=boss_damage L3 + second=attack_power L3:
        # side_coeff = 3000 + 1200 = 4200 > 2844 -> no grade-protect;
        # margin 0 EV-optimal, improvable offers -> defer (None -> PROCESS).
        ctx = self._ctx(endgame_risk=None, relic_coeff=None, ancient_coeff=None)
        st = GemState(will=5, chaos=5, first=3, second=3,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("first+2", "second+2",
                                         "will+1", "chaos+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = _side_value_finish_decision(ctx, ti, TurnMetrics(0, 0, 0, 0, 0))
        self.assertIsNone(d)

    def test_explicit_endgame_risk_disables_the_gate(self):
        # Same below-benchmark gem as test 1, but endgame_risk is an explicit
        # float (user took manual control) -> no grade-protect, margin 0,
        # improvable offer -> defer (None -> PROCESS).
        ctx = self._ctx(endgame_risk=0.0, relic_coeff=None, ancient_coeff=None)
        st = GemState(will=5, chaos=5, first=3, second=3,
                      first_effect="attack_power", second_effect="ally_damage")
        ti = build_ti(state=st,
                      offers=make_offers("first+2", "second+2",
                                         "will+1", "chaos+1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = _side_value_finish_decision(ctx, ti, TurnMetrics(0, 0, 0, 0, 0))
        self.assertIsNone(d)

    def test_legacy_float_margin_path_unchanged(self):
        # endgame_risk as a float still drives the finish_val >= process_ev +
        # margin comparison: a played-out maxed gem still finishes.
        ctx = self._ctx(endgame_risk=0.0)
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = _side_value_finish_decision(ctx, ti, TurnMetrics(0, 0, 0, 0, 0))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_decision.TestEndgameGate -v`
Expected: FAIL — `test_below_benchmark_relic_gem_finishes_to_protect_grade` fails with `KeyError: 'grade_protect'` (the metric does not exist yet), and the below-benchmark gem does not finish.

- [ ] **Step 3: Implement the gate**

In `arkgrid/decision.py`, change the `DecisionContext` field (line 93):

```python
    endgame_risk: Optional[float] = None
```

Replace the no-reroll branch of `_side_value_finish_decision` (everything from the `# No reroll available` comment through the final `return Decision(...)`, currently lines ~400-421) with:

```python
    # No reroll available (exhausted, or turn 1): finish vs process.
    # Auto-gate fires only when the player did not pass --endgame-risk
    # (endgame_risk is None) and the confirmation gate is off.
    auto_gate = ctx.endgame_risk is None and not ctx.confirm_active
    grade_protect = False
    benchmark = 0
    if auto_gate:
        total = ti.state.total_points()
        if total >= 19:
            benchmark = svt.ancient_coeff
        elif total >= 16:
            benchmark = svt.relic_coeff
        # benchmark stays 0 for legendary grade -> no grade to protect.
        if benchmark > 0 and _side_coeff(ctx, ti.state) < benchmark:
            grade_protect = True

    margin = (0.0 if (ctx.confirm_active or ctx.endgame_risk is None)
              else ctx.endgame_risk)
    metrics = {"finish_val": finish_val, "process_ev": process_ev,
               "margin": margin, "grade_protect": grade_protect}

    if not grade_protect and finish_val < process_ev + margin:
        return None  # PROCESS — continuing beats finishing

    if grade_protect:
        reason = (f"goal met, no rerolls left, side coeff "
                  f"{_side_coeff(ctx, ti.state)} below grade benchmark "
                  f"{benchmark} — finishing to protect the grade")
    else:
        reason = (f"goal met, no rerolls left, finish_val={finish_val:.0f} "
                  f">= process_ev={process_ev:.0f}+margin={margin:.0f}")
    if (ctx.confirm_active
            and _side_coeff(ctx, ti.state) >= ctx.confirm_min_coeff):
        return Decision(
            action=ActionKind.FINISH, branch="side_value_finish",
            reason=reason + " — player confirmation required",
            metrics=metrics,
            needs_confirmation=True,
            confirm_choices=_legal_actions(ti),
        )
    return Decision(
        action=ActionKind.FINISH, branch="side_value_finish",
        reason=reason, metrics=metrics,
    )
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python -m unittest tests.test_decision.TestEndgameGate -v`
Expected: PASS — 4 tests OK.

- [ ] **Step 5: Run the full decision suite**

Run: `python -m unittest tests.test_decision -v`
Expected: PASS. `build_ctx` keeps `endgame_risk=0.0` / `relic_coeff=0` / `ancient_coeff=0` defaults, so existing tests pass a float margin and explicit `0` coeffs — their behaviour is unchanged. If anything fails, fix the test only if its intent is preserved; otherwise the implementation is wrong.

- [ ] **Step 6: Commit**

```bash
git add arkgrid/decision.py tests/test_decision.py
git commit -m "$(cat <<'EOF'
feat: endgame-risk grade gate in the side-value finish

When --endgame-risk is omitted (endgame_risk is None), a goal-met gem
whose side coefficient is below its grade benchmark finishes to protect
the grade instead of chasing more coefficient. Passing --endgame-risk
keeps the legacy float-margin behaviour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Thread `Optional` knobs through `GemSimulator`

**Files:**
- Modify: `arkgrid/simulator.py` — `GemSimulator.__init__` signature (~44-46) and relic-table build (~140)
- Test: `tests/test_simulator.py`

- [ ] **Step 1: Change the signature and the relic-table build**

In `arkgrid/simulator.py`, change the `GemSimulator.__init__` parameter defaults (currently `endgame_risk: float = 0.0`, `relic_coeff: int = 0`, `ancient_coeff: int = 0`):

```python
            endgame_risk: Optional[float] = None,
            relic_coeff: Optional[int] = None,
            ancient_coeff: Optional[int] = None,
```

`Optional` is already imported in `simulator.py`. The stored attributes (`self.endgame_risk = endgame_risk`, etc.) and `_get_side_value_table` (which already passes `relic_coeff=self.relic_coeff, ancient_coeff=self.ancient_coeff`) need no change — `SideValueTable` resolves `None`.

Replace the relic display-table build condition (currently `if relic_reroll_threshold > 0.0 or relic_coeff > 0 or ancient_coeff > 0:`) with an unconditional build — the coeffs may now be `None`, and grade is always part of `gem_value`, so `P(relic+)` / `P(ancient)` should be consistently available:

```python
        # Relic+ (>=16 total points) DP table for probability tracking.
        # Built unconditionally: grade is always part of the side-value
        # gem_value now, so P(relic+) / P(ancient) are always shown.
        self._relic_prob_table = GoalProbabilityTable(
            LastTurnGoal(min_total=16), self.turns_total, self.pool,
            early_finish=False,
            max_rerolls=dp_max_rerolls,
        )
```

(Delete the `if` line and the `self._relic_prob_table: Optional[GoalProbabilityTable] = None` placeholder line above it that the `if` guarded — the table is now always assigned. Keep the surrounding comment about reroll-awareness.)

- [ ] **Step 2: Run the simulator suite and fix fallout**

Run: `python -m unittest tests.test_simulator -v`

`GemSimulator` constructed without `relic_coeff` / `ancient_coeff` now gets the fusion default tier bonus, and without `endgame_risk` now auto-gates. This changes side-value finish timing (not the goal DP, so goal **success-rate** assertions are largely unaffected; **avg side coeff**, **relic/ancient rate**, and finish-related assertions may shift). For each failure:
- If the test's intent is goal success independent of grade, add explicit `relic_coeff=0, ancient_coeff=0, endgame_risk=0.0` to that `GemSimulator(...)` call to pin legacy behaviour.
- If the test exercises finish/grade behaviour, update the expected numbers.

Re-run until green.

- [ ] **Step 3: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: OK. Fix any cross-module fallout the same way (e.g. `tests/test_scenarios.py`, which drives `should_early_finish`).

- [ ] **Step 4: Commit**

```bash
git add arkgrid/simulator.py tests/
git commit -m "$(cat <<'EOF'
feat: GemSimulator accepts Optional fusion-default knobs

relic_coeff / ancient_coeff / endgame_risk accept None (auto). The
relic+ display DP now always builds since grade is always valued.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Thread `Optional` knobs through `run_auto`

**Files:**
- Modify: `arkgrid/automation.py` — `run_auto` signature (~554-556), relic-table build (~807-810)

- [ ] **Step 1: Change the signature and the relic-table build**

In `arkgrid/automation.py`, change the `run_auto` parameter defaults (currently `endgame_risk: float = 0.0`, `relic_coeff: int = 0`, `ancient_coeff: int = 0`):

```python
    endgame_risk: Optional[float] = None,
    relic_coeff: Optional[int] = None,
    ancient_coeff: Optional[int] = None,
```

`Optional` is already imported in `automation.py`. The `SideValueTable(...)` construction (~828-834, already passing `relic_coeff=relic_coeff, ancient_coeff=ancient_coeff`) and the `DecisionContext(...)` construction (~914-935, already passing `endgame_risk=endgame_risk`) need no change.

Replace the relic display-table build guard (currently `if relic_table is None and (relic_reroll_threshold > 0.0 or relic_coeff > 0 or ancient_coeff > 0):`) with:

```python
                # Relic+ table: built once. Always built — grade is part of
                # the side-value gem_value, so P(relic+)/P(ancient) always show.
                if relic_table is None:
```

(Keep the `GoalProbabilityTable(LastTurnGoal(min_total=16), ...)` body that follows unchanged.)

- [ ] **Step 2: Verify imports compile**

Run: `python -c "import arkgrid.automation"`
Expected: no output, exit 0 (no syntax/import error).

- [ ] **Step 3: Run the full suite**

Run: `python -m unittest discover -s tests`
Expected: OK (automation has no dedicated unit tests that exercise `run_auto`; this confirms nothing else broke).

- [ ] **Step 4: Commit**

```bash
git add arkgrid/automation.py
git commit -m "$(cat <<'EOF'
feat: run_auto accepts Optional fusion-default knobs

relic_coeff / ancient_coeff / endgame_risk accept None (auto); the
relic+ display DP always builds.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: CLI flag defaults → `None`; config display and `live` hint

**Files:**
- Modify: `arkgrid/cli.py` — flag definitions (~101-116 and ~235-237), `_print_config` (~357-358), `cmd_live` finish hint (~1005-1041), `cmd_live` MC `getattr` calls (~1016-1017, ~1069-1071)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (new class):

```python
class TestFusionAutoDefaults(unittest.TestCase):
    """The three fusion/endgame knobs default to None (auto)."""

    def _parse_sim(self, extra=None):
        parser = _build_parser()
        argv = ["sim", "--min-will", "4", "--min-chaos", "3", "--rarity", "epic"]
        if extra:
            argv.extend(extra)
        return parser.parse_args(argv)

    def test_defaults_are_none(self):
        args = self._parse_sim()
        self.assertIsNone(args.endgame_risk)
        self.assertIsNone(args.relic_coeff)
        self.assertIsNone(args.ancient_coeff)

    def test_explicit_values_parse(self):
        args = self._parse_sim(["--endgame-risk", "500",
                                "--relic-coeff", "3000",
                                "--ancient-coeff", "8000"])
        self.assertEqual(args.endgame_risk, 500.0)
        self.assertEqual(args.relic_coeff, 3000)
        self.assertEqual(args.ancient_coeff, 8000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_cli.TestFusionAutoDefaults -v`
Expected: FAIL — `test_defaults_are_none` fails (`args.endgame_risk` is `0.0`, not `None`).

- [ ] **Step 3: Change the flag definitions**

In `arkgrid/cli.py`, in `add_common` change the three flags (currently ~101-116). Set `default=None` and rewrite the help:

```python
        p.add_argument("--endgame-risk", type=float, default=None, metavar="F",
                        help="Risk margin for the side-value finish, in "
                             "coefficient units. Omitted (default): the engine "
                             "auto-gates — a goal-met gem whose side coefficient "
                             "is below its grade's fusion-derived average "
                             "finishes to protect the grade; at or above it, "
                             "EV-optimal play continues. Pass a float to take "
                             "manual control of the margin for every gem. "
                             "No effect when --confirm-min-coeff is set.")
        p.add_argument("--relic-coeff", type=int, default=None, metavar="N",
                        help="Coefficient-equivalent worth of the relic+ grade "
                             "(>=16 total points), added to gem_value in the "
                             "side-value DP and used as the relic grade "
                             "benchmark. Default: the fusion-derived average "
                             "relic gem coefficient for the gem type.")
        p.add_argument("--ancient-coeff", type=int, default=None, metavar="N",
                        help="Coefficient-equivalent worth of the ancient grade "
                             "(>=19 total points). Default: the fusion-derived "
                             "average ancient gem coefficient for the gem type.")
```

In the `auto` subparser block, change the three duplicate definitions (currently ~235-237) to `default=None`:

```python
    p.add_argument("--endgame-risk", type=float, default=None, metavar="F")
    p.add_argument("--relic-coeff", type=int, default=None, metavar="N")
    p.add_argument("--ancient-coeff", type=int, default=None, metavar="N")
```

- [ ] **Step 4: Update `_print_config`**

In `arkgrid/cli.py`, replace the endgame-risk lines in `_print_config` (currently ~357-358):

```python
    er = getattr(args, "endgame_risk", None)
    if er is None:
        print("Endgame risk:   auto (grade-gated side-value finish)")
    else:
        print(f"Endgame risk:   {er:.0f} (side-value finish margin)")
    rc = getattr(args, "relic_coeff", None)
    ac = getattr(args, "ancient_coeff", None)
    print(f"Tier value:     relic={'auto' if rc is None else rc}, "
          f"ancient={'auto' if ac is None else ac}")
```

- [ ] **Step 5: Update the `cmd_live` finish hint**

In `arkgrid/cli.py`, the `live` finish-hint block builds a `SideValueTable` and computes `should_early_finish` (~1005-1041). Change the `SideValueTable(...)` call to pass the `None`-able args, and replace the `should_early_finish` computation and its print with the grade-gate logic:

```python
        from arkgrid.probability import SideValueTable
        from arkgrid.analyzer import GemAnalyzer
        svt = SideValueTable(
            goal, current_turn + turns_left - 1, pool,
            gem_type=gem_type_domain,
            optimize=getattr(args, "optimize", "dps"),
            min_side_coeff=getattr(args, "min_side_coeff", 0),
            relic_coeff=getattr(args, "relic_coeff", None),
            ancient_coeff=getattr(args, "ancient_coeff", None),
        )
        finish_val = svt.gem_value(state)
        process_ev = svt.expected_value_after_click(
            state, pool_options, turns_left - 1)
        can_reroll_sv = reroll_count > 0 and current_turn != 1
        endgame_risk = getattr(args, "endgame_risk", None)
        finish_reason = ""
        if can_reroll_sv:
            # Engine never finishes while a free reroll is available.
            should_early_finish = False
        elif endgame_risk is None:
            # Auto-gate: below the grade benchmark -> protect the grade.
            total = state.total_points()
            benchmark = (svt.ancient_coeff if total >= 19
                         else svt.relic_coeff if total >= 16 else 0)
            side_c = GemAnalyzer._side_coeff(
                state, getattr(args, "optimize", "dps"))
            if benchmark > 0 and side_c < benchmark:
                should_early_finish = True
                finish_reason = (f"side coeff {side_c} below grade "
                                 f"benchmark {benchmark}")
            else:
                should_early_finish = finish_val >= process_ev
                finish_reason = (f"finish_val={finish_val:.0f} "
                                 f">= process_ev={process_ev:.0f}")
        else:
            should_early_finish = finish_val >= process_ev + endgame_risk
            finish_reason = (f"finish_val={finish_val:.0f} >= "
                             f"process_ev={process_ev:.0f}+{endgame_risk:.0f}")
```

Replace the existing `if should_early_finish:` print (currently ~1032-1035) with:

```python
    if should_early_finish:
        print(f"  >>> Finish (side-value DP: {finish_reason})")
```

In the `cmd_live` MC-simulation block, change the `getattr` calls that read these knobs (currently ~1069-1071) so they default to `None`:

```python
            endgame_risk=getattr(args, "endgame_risk", None),
            relic_coeff=getattr(args, "relic_coeff", None),
            ancient_coeff=getattr(args, "ancient_coeff", None),
```

- [ ] **Step 6: Run the CLI test and the full suite**

Run: `python -m unittest tests.test_cli -v`
Expected: PASS — including the new `TestFusionAutoDefaults`.

Run: `python -m unittest discover -s tests`
Expected: OK.

- [ ] **Step 7: Smoke-test the CLI end to end**

Run: `python -m arkgrid sim --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --rarity epic --seed 1`
Expected: a turn-by-turn log prints, the config block shows `Endgame risk:   auto (grade-gated side-value finish)` and a `Tier value:` line, and the run finishes without an exception.

Run: `python -m arkgrid sim --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --rarity epic --seed 1 --endgame-risk 500`
Expected: runs cleanly; the config block shows `Endgame risk:   500 (side-value finish margin)`.

- [ ] **Step 8: Commit**

```bash
git add arkgrid/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat: --relic-coeff/--ancient-coeff/--endgame-risk default to auto

Omitted, the three knobs resolve to fusion-derived defaults and the
endgame finish auto-gates by grade. Explicit values still override.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Monte-Carlo validation and documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full test suite once more**

Run: `python -m unittest discover -s tests`
Expected: OK — record the total test count.

- [ ] **Step 2: Monte-Carlo before/after check**

Capture the baseline from `master` and compare to the branch.

Baseline (run once, on a clean `master` checkout or note it from a stash):
```bash
git stash && git checkout master
python -m arkgrid stats --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --rarity epic --trials 50000 --reset-ticket --seed 7
git checkout - && git stash pop
```

Branch:
```bash
python -m arkgrid stats --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --rarity epic --trials 50000 --reset-ticket --seed 7
```

Acceptance criteria (record both outputs in the commit message or task notes):
- Main-goal **success rate** must not regress by more than ~1pp (the goal DP is unchanged; any movement is finish-timing noise).
- **Avg side coefficient** and **relic+/ancient rates** are expected to move — the side-value finish now protects grade on below-average gems. Confirm the direction is sane (below-average gems finishing earlier should, if anything, slightly lift relic/ancient retention and not collapse avg side coeff).
- If success rate regresses materially, stop and investigate before continuing.

- [ ] **Step 3: Update `CLAUDE.md`**

In `CLAUDE.md`, update the **Relic+ tracking** and **Ancient tracking** bullets and the `probability.py` / `decision.py` module descriptions to state:
- `--relic-coeff` / `--ancient-coeff` default to the fusion-derived average gem coefficient for the gem type (computed by `constants.fusion_avg_coeff`), not `0`; passing the flag overrides.
- `SideValueTable` resolves those defaults and exposes public `relic_coeff` / `ancient_coeff`.
- `--endgame-risk` omitted means the side-value finish auto-gates: a goal-met gem whose side coefficient is below its grade benchmark finishes to protect the grade; a passed value restores the manual float margin.
- The relic+ display DP now always builds when a gem type is known.

Keep the edits factual and consistent with the existing wording style. Reference the design doc `docs/superpowers/specs/2026-05-18-fusion-benchmark-endgame-gate-design.md`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: document fusion-derived tier value and endgame grade gate

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review notes

- **Spec coverage:** §1 fusion math → Task 1; §1 tier_bonus keeps fusion value → Task 2; §2 per-gem-type resolution → Task 2 (`SideValueTable` is built per gem type) + Tasks 4/5; §3 endgame gate → Task 3; CLI knobs kept + auto defaults → Task 6; integration points → Tasks 4/5/6; validation → Task 7.
- **Type consistency:** `relic_coeff` / `ancient_coeff` are `Optional[int]` in `SideValueTable.__init__`, `GemSimulator.__init__`, `run_auto`, and the CLI; resolved to plain `int` public attributes `SideValueTable.relic_coeff` / `.ancient_coeff`. `endgame_risk` is `Optional[float]` in `DecisionContext`, `GemSimulator`, `run_auto`, and the CLI. The gate reads `svt.relic_coeff` / `svt.ancient_coeff` and the `grade_protect` metric key is written in Task 3 and asserted in the Task 3 test.
- **Ordering:** sim/auto accept `None` (Tasks 4/5) before the CLI emits `None` (Task 6), so the suite stays green between tasks.
