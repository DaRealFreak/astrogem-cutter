# Side-Value DP — Turns-Aware Finish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-turn `_ev_cell` finish heuristic with a turns-aware side-value DP that decides finish-vs-continue correctly at every goal-met turn, pricing relic+/ancient grade as additive coefficient weights.

**Architecture:** A new `SideValueTable` DP (`arkgrid/probability.py`) stores the expected final *gem value* — `side_coeff + tier_bonus(total_points)` — under optimal finish/process/reroll play. One pure decision helper `_side_value_finish_decision` (`arkgrid/decision.py`) compares `finish_val = gem_value(current)` against `continue_val = max(process EV, reroll value)`. The simulator and automation build and cache the table per gem type and thread it through `DecisionContext`. Three finish flags (`--early-finish-coeff`, `--relic-no-early-finish`, `--confirm-risk`) are retired; `--relic-coeff` / `--ancient-coeff` are added and `--endgame-risk` becomes a float margin.

**Tech Stack:** Python 3 stdlib only (`dataclasses`, `random`, `unittest`). No build step, no linter.

**Spec:** `docs/superpowers/specs/2026-05-17-side-value-dp-design.md`

**Git:** The repository owner controls commits. Do **NOT** run `git commit` or `git add`. Each task ends with a verification step; once it passes, pause and let the owner stage and commit before starting the next task.

**Running tests:** activate the venv first.
```bash
source .venv/Scripts/activate
python -m unittest discover -s tests -v          # full suite
python -m unittest tests.test_probability -v     # single file
```

---

## File structure

- `arkgrid/probability.py` — **new** `SideValueTable` class alongside `GoalProbabilityTable`. Self-contained: it duplicates the ~30-line effect-aware transition setup, consistent with the file's existing five near-duplicate `_build*` methods. (Task 1)
- `arkgrid/decision.py` — `DecisionContext` gains `side_value_table`; `endgame_risk` becomes a float; `early_finish_coeff` / `relic_no_early_finish` / `confirm_risk` / `risk_prob_table` are removed. `_ev_cell`, `_relic_chase_active`, `_legacy_early_finish_decision`, `_confirm_finish_decision`, `_change_effect_ev` are deleted; `early_finish_decision` becomes a thin dispatcher onto the new `_side_value_finish_decision`. `TurnMetrics` sheds the EV-only fields. (Tasks 2, 4, 5)
- `arkgrid/simulator.py` — `GemSimulator` builds + caches per-gem-type `SideValueTable`s, gains `relic_coeff` / `ancient_coeff` params, drops `early_finish_coeff` / `relic_no_early_finish` / `confirm_risk`, threads `side_value_table` into `DecisionContext`. (Tasks 2, 5)
- `arkgrid/automation.py` — `run_auto` builds the side-value table on first detection, gains `relic_coeff` / `ancient_coeff`, drops the retired params + the risk table. (Tasks 3, 5)
- `arkgrid/cli.py` — retire 3 flags, add 2, make `--endgame-risk` a float, rewrite the `cmd_live` inline hint, fix `_compute_dp_prob` / `cmd_stats` `early_finish`. (Task 5)
- `tests/test_probability.py`, `tests/test_decision.py`, `tests/test_simulator.py` — new tests + re-baselining. (Tasks 1–5)
- `CLAUDE.md` — documentation. (Task 6)

---

## Task 1: `SideValueTable` — the side-value DP

**Files:**
- Modify: `arkgrid/probability.py` (new class at end of file)
- Test: `tests/test_probability.py` (new test class)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_probability.py` (add `SideValueTable` to the `from arkgrid.probability import ...` line if one exists, otherwise add `from arkgrid.probability import SideValueTable`; ensure `from arkgrid.models import GemState, LastTurnGoal` and `from arkgrid.pool import OptionPool` are imported):

```python
class TestSideValueTable(unittest.TestCase):
    """Task 1: the side-value DP — gem_value terminal, monotonicity,
    and the offer-conditional continuation value."""

    POOL = OptionPool()

    def _table(self, **kw):
        defaults = dict(
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            max_turns=9, pool=self.POOL,
            gem_type="order_fortitude", optimize="dps",
            max_rerolls=2, relic_coeff=3000, ancient_coeff=8000,
        )
        defaults.update(kw)
        return SideValueTable(**defaults)

    def test_gem_value_goal_met_is_side_coeff_plus_tier(self):
        # order_fortitude DPS coeffs: boss_damage=1000, attack_power=400.
        # will5 chaos5 first5 second4 -> total 19 (ancient).
        # side_coeff = 5*1000 + 4*400 = 6600 ; +ancient 8000 -> 14600.
        t = self._table()
        st = GemState(will=5, chaos=5, first=5, second=4,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertAlmostEqual(t.gem_value(st), 14600.0, places=3)

    def test_gem_value_relic_tier(self):
        # will4 chaos4 first5 second3 -> total 16 (relic+, not ancient).
        # side_coeff = 5*1000 + 3*400 = 6200 ; +relic 3000 -> 9200.
        t = self._table()
        st = GemState(will=4, chaos=4, first=5, second=3,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertAlmostEqual(t.gem_value(st), 9200.0, places=3)

    def test_gem_value_zero_when_goal_broken(self):
        # will=3 < min_will 4 -> goal not satisfied -> value 0.
        t = self._table()
        st = GemState(will=3, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertEqual(t.gem_value(st), 0.0)

    def test_lookup_terminal_equals_gem_value(self):
        t = self._table()
        st = GemState(will=4, chaos=4, first=5, second=3,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertAlmostEqual(t.lookup(st, 0, rerolls=0),
                               t.gem_value(st), places=3)

    def test_lookup_floored_by_finish(self):
        # V always >= gem_value(current): finishing now is in the max.
        t = self._table()
        for tl in range(0, 6):
            st = GemState(will=4, chaos=4, first=3, second=2,
                          first_effect="boss_damage",
                          second_effect="attack_power")
            self.assertGreaterEqual(t.lookup(st, tl, rerolls=2) + 1e-6,
                                    t.gem_value(st))

    def test_improvable_state_has_continuation_upside(self):
        # Goal met, side nodes below cap, turns left -> continuing must
        # beat finishing now.
        t = self._table()
        st = GemState(will=4, chaos=4, first=2, second=2,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertGreater(t.lookup(st, 5, rerolls=2), t.gem_value(st))

    def test_expected_value_after_click_averages_offers(self):
        # process EV = mean of V over the 4 applied offers.
        t = self._table()
        st = GemState(will=4, chaos=4, first=3, second=3,
                      first_effect="boss_damage", second_effect="attack_power")
        offers = [t.pool.pool[0]] * 4 if False else None  # see below
        # Build a real 4-offer list from the canonical pool.
        by_key = {o.key: o for o in self.POOL.pool}
        offers = [by_key["will+1"], by_key["chaos+1"],
                  by_key["first+1"], by_key["second+1"]]
        ev = t.expected_value_after_click(st, offers, 4, rerolls=2)
        manual = sum(
            t.lookup(_apply(st, o), 4, rerolls=2) for o in offers) / 4
        self.assertAlmostEqual(ev, manual, places=3)

    def test_disabled_when_gem_type_unknown(self):
        t = self._table(gem_type="")
        self.assertFalse(t.enabled)
        st = GemState(will=4, chaos=4, first=4, second=4,
                      first_effect="boss_damage", second_effect="attack_power")
        self.assertEqual(t.gem_value(st), 0.0)
        self.assertEqual(t.lookup(st, 3, rerolls=1), 0.0)
```

Add this module-level helper near the top of `tests/test_probability.py` (after the imports):

```python
def _apply(state, opt):
    """Apply a level/effect offer to a cloned state — test helper."""
    s = state.clone()
    if opt.kind == "will":
        s.will = min(5, max(1, s.will + opt.delta))
    elif opt.kind == "chaos":
        s.chaos = min(5, max(1, s.chaos + opt.delta))
    elif opt.kind == "first":
        s.first = min(5, max(1, s.first + opt.delta))
    elif opt.kind == "second":
        s.second = min(5, max(1, s.second + opt.delta))
    return s
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_probability.TestSideValueTable -v`
Expected: FAIL — `ImportError: cannot import name 'SideValueTable'`.

- [ ] **Step 3: Implement `SideValueTable`**

Append to `arkgrid/probability.py` (after the `GoalProbabilityTable` class, at module scope). The imports it needs (`DPS_COEFF, DPS_EFFECTS, GEM_TYPES, SUPPORT_COEFF, SUPPORT_EFFECTS`, `Option, LastTurnGoal, GemState`, `OptionPool`) are already imported at the top of the file.

```python
class SideValueTable:
    """Expected final *gem value* under optimal finish / process / reroll play.

    A parallel DP to `GoalProbabilityTable`, consulted once the goal is met
    to decide finish-vs-continue. Effect-aware and reroll-aware; the state
    key is `(w, c, f, s, fi, si, r, tl)` — the same space as the default
    effect-aware reroll table. The stored value is a *coefficient*, not a
    probability:

        gem_value(state) = side_coeff(state) + tier_bonus(total_points)

    with goal-broken states valued 0. Backward induction takes a max over
    the three real actions (finish now / process / reroll), so V always
    floors at `gem_value` — the table is the destination-value oracle for
    `_side_value_finish_decision`, not a value compared directly.

    Self-disables (`enabled is False`, every lookup returns 0.0) when the
    gem type is unknown, mirroring `GoalProbabilityTable`'s effect-aware
    self-disable.
    """

    def __init__(
        self,
        goal: LastTurnGoal,
        max_turns: int,
        pool: OptionPool,
        *,
        gem_type: str,
        optimize: str = "dps",
        min_side_coeff: int = 0,
        max_rerolls: int = 0,
        relic_coeff: int = 0,
        ancient_coeff: int = 0,
    ) -> None:
        self.goal = goal
        self.max_turns = max_turns
        self.pool = pool
        self._gem_type = gem_type
        self._optimize = optimize
        self._min_side_coeff = min_side_coeff
        self._max_rerolls = max_rerolls
        self._relic_coeff = relic_coeff
        self._ancient_coeff = ancient_coeff
        self.enabled = gem_type in GEM_TYPES
        self._dp: Dict[tuple, float] = {}

        if not self.enabled:
            self._effect_tuple: Tuple[str, ...] = ()
            self._effect_coeffs: Tuple[int, ...] = ()
            self._change_dests: Dict[Tuple[int, int], Tuple[int, ...]] = {}
            return

        effects = GEM_TYPES[gem_type]
        coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        target_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        self._effect_tuple = effects
        self._effect_coeffs = tuple(
            coeff_map.get(e, 0) if e in target_set else 0 for e in effects)
        self._change_dests = {}
        for fi in range(4):
            for si in range(4):
                if fi != si:
                    self._change_dests[(fi, si)] = tuple(
                        i for i in range(4) if i != fi and i != si)
        self._build()

    # -- value model -------------------------------------------------

    def _tier_bonus(self, total_points: int) -> int:
        """Additive grade weight: ancient (>=19) or relic+ (>=16) or 0."""
        if total_points >= 19:
            return self._ancient_coeff
        if total_points >= 16:
            return self._relic_coeff
        return 0

    def _gem_value_idx(self, w: int, c: int, f: int, s: int,
                       fi: int, si: int) -> float:
        """Terminal gem value for an effect-indexed state.

        0 when the goal (or the `min_side_coeff` floor) is broken — a
        failed gem is worth nothing, which makes the DP price the risk of
        processing into a goal-break.
        """
        if not self.goal.satisfied(w, c, f, s):
            return 0.0
        coeff = self._effect_coeffs[fi] * f + self._effect_coeffs[si] * s
        if self._min_side_coeff > 0 and coeff < self._min_side_coeff:
            return 0.0
        return float(coeff + self._tier_bonus(w + c + f + s))

    def _effect_indices(self, state: GemState):
        """Translate state.first_effect/second_effect to (fi, si) indices."""
        try:
            fi = self._effect_tuple.index(state.first_effect)
            si = self._effect_tuple.index(state.second_effect)
        except ValueError:
            return None
        if fi == si:
            return None
        return fi, si

    # -- transitions (copy of GoalProbabilityTable._effect_aware_transitions)

    def _transitions(self, w: int, c: int, f: int, s: int,
                     turn: int, turns_left: int):
        """Return [(prob, option_key, option_kind, nw, nc, nf, ns, view_delta)].

        fi/si updates are applied at build time via self._change_dests.
        """
        state = GemState(will=w, chaos=c, first=f, second=s)
        eligible = [o for o in self.pool.pool
                    if self.pool.eligible(o, state, turn, turns_left)]
        if not eligible:
            return [(1.0, "", "", w, c, f, s, 0)]
        total_w = sum(o.weight for o in eligible)
        result = []
        for o in eligible:
            p = o.weight / total_w
            nw, nc, nf, ns = w, c, f, s
            vd = 0
            if o.kind == "will":
                nw = min(5, max(1, w + o.delta))
            elif o.kind == "chaos":
                nc = min(5, max(1, c + o.delta))
            elif o.kind == "first":
                nf = min(5, max(1, f + o.delta))
            elif o.kind == "second":
                ns = min(5, max(1, s + o.delta))
            elif o.kind == "view":
                vd = o.delta
            result.append((p, o.key, o.kind, nw, nc, nf, ns, vd))
        return result

    def _post_val(self, key: str, nw: int, nc: int, nf: int, ns: int,
                  fi: int, si: int, dests: Tuple[int, ...], nd: int,
                  nr: int, tl: int) -> float:
        """V at a transition destination, routing change_effect uniformly
        across the two non-equipped pool members."""
        if key == "change_first_effect":
            return sum(self._dp[(nw, nc, nf, ns, d, si, nr, tl)]
                       for d in dests) / nd
        if key == "change_second_effect":
            return sum(self._dp[(nw, nc, nf, ns, fi, d, nr, tl)]
                       for d in dests) / nd
        return self._dp[(nw, nc, nf, ns, fi, si, nr, tl)]

    def _build(self) -> None:
        dp = self._dp
        mt = self.max_turns
        max_r = self._max_rerolls
        valid_pairs = [(fi, si) for fi in range(4)
                       for si in range(4) if fi != si]

        # Terminal: turns_left == 0 -> gem_value.
        for w in range(1, 6):
            for c in range(1, 6):
                for f in range(1, 6):
                    for s in range(1, 6):
                        for fi, si in valid_pairs:
                            v = self._gem_value_idx(w, c, f, s, fi, si)
                            for r in range(0, max_r + 1):
                                dp[(w, c, f, s, fi, si, r, 0)] = v

        # Option-level transition cache (independent of fi/si and r).
        trans_cache = {}
        for label, turn, tl in [("first", 1, mt),
                                ("last", mt, 1),
                                ("middle", 2, mt - 1 if mt > 2 else 2)]:
            cache = {}
            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            cache[(w, c, f, s)] = self._transitions(
                                w, c, f, s, turn, tl)
            trans_cache[label] = cache

        # Backward induction: V = max(finish, process, reroll).
        for tl in range(1, mt + 1):
            turn_number = mt - tl + 1
            if turn_number == 1:
                tc = trans_cache["first"]
            elif tl == 1:
                tc = trans_cache["last"]
            else:
                tc = trans_cache["middle"]

            for w in range(1, 6):
                for c in range(1, 6):
                    for f in range(1, 6):
                        for s in range(1, 6):
                            trans = tc[(w, c, f, s)]
                            for fi, si in valid_pairs:
                                dests = self._change_dests[(fi, si)]
                                nd = len(dests)
                                finish_val = self._gem_value_idx(
                                    w, c, f, s, fi, si)
                                for r in range(0, max_r + 1):
                                    proc = 0.0
                                    for (p, key, _kind,
                                         nw, nc, nf, ns, vd) in trans:
                                        nr = (min(max_r, r + vd)
                                              if max_r > 0 else 0)
                                        proc += p * self._post_val(
                                            key, nw, nc, nf, ns,
                                            fi, si, dests, nd, nr, tl - 1)
                                    best = finish_val if finish_val > proc \
                                        else proc
                                    if r > 0 and turn_number != 1:
                                        rv = dp[(w, c, f, s,
                                                 fi, si, r - 1, tl)]
                                        if rv > best:
                                            best = rv
                                    dp[(w, c, f, s, fi, si, r, tl)] = best

    # -- public API --------------------------------------------------

    def gem_value(self, state: GemState) -> float:
        """Value of finishing the gem in its current state."""
        if not self.enabled:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        return self._gem_value_idx(state.will, state.chaos,
                                   state.first, state.second, fi, si)

    def lookup(self, state: GemState, turns_left: int,
               rerolls: int = 0) -> float:
        """Expected final gem value under optimal play from this state."""
        if not self.enabled:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        r = min(self._max_rerolls, rerolls if rerolls else 0)
        return self._dp.get(
            (state.will, state.chaos, state.first, state.second,
             fi, si, r, turns_left), 0.0)

    def expected_value_after_click(self, state: GemState,
                                   offers: List[Option],
                                   turns_left_after: int,
                                   rerolls: int = 0) -> float:
        """Mean V across the 4 *actual* visible offers (uniform 25% pick).

        Mirrors `GoalProbabilityTable.expected_prob_after_click` — the
        process-EV term of the finish decision uses the real offers, not
        the pool-model single draw the table is built with.
        """
        if not self.enabled or not offers:
            return 0.0
        idx = self._effect_indices(state)
        if idx is None:
            return 0.0
        fi, si = idx
        dests = self._change_dests[(fi, si)]
        nd = len(dests)
        total = 0.0
        for o in offers:
            nw = (min(5, max(1, state.will + o.delta))
                  if o.kind == "will" else state.will)
            nc = (min(5, max(1, state.chaos + o.delta))
                  if o.kind == "chaos" else state.chaos)
            nf = (min(5, max(1, state.first + o.delta))
                  if o.kind == "first" else state.first)
            ns = (min(5, max(1, state.second + o.delta))
                  if o.kind == "second" else state.second)
            vd = o.delta if o.kind == "view" else 0
            nr = (min(self._max_rerolls, (rerolls or 0) + vd)
                  if self._max_rerolls > 0 else 0)
            if o.key == "change_first_effect":
                total += sum(self._dp.get(
                    (nw, nc, nf, ns, d, si, nr, turns_left_after), 0.0)
                    for d in dests) / nd
            elif o.key == "change_second_effect":
                total += sum(self._dp.get(
                    (nw, nc, nf, ns, fi, d, nr, turns_left_after), 0.0)
                    for d in dests) / nd
            else:
                total += self._dp.get(
                    (nw, nc, nf, ns, fi, si, nr, turns_left_after), 0.0)
        return total / len(offers)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_probability.TestSideValueTable -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS — `SideValueTable` is new code with no callers yet.

- [ ] **Step 6: Verify and pause for commit.**

---

## Task 2: Build & cache the side-value table in `GemSimulator`

The simulator builds one `SideValueTable` per gem type (cached, mirroring `_ea_table_cache`) and threads it into `DecisionContext`. `DecisionContext` gains the `side_value_table` field. No decision logic changes yet — after this task the table is carried but unused, so behavior and the suite are unchanged.

**Files:**
- Modify: `arkgrid/decision.py` (`DecisionContext`)
- Modify: `arkgrid/simulator.py` (`__init__`, `_get_ea_tables`, `simulate_one`, `_decision_context`)
- Test: `tests/test_simulator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_simulator.py` (ensure `from arkgrid.models import LastTurnGoal` and `from arkgrid.simulator import GemSimulator` are available — follow the file's existing import style):

```python
class TestSideValueTableWiring(unittest.TestCase):
    """Task 2: GemSimulator builds a per-gem-type side-value table and
    threads it into the DecisionContext."""

    def test_side_value_table_built_for_configured_gem(self):
        from arkgrid.models import AstroGem
        from arkgrid.probability import SideValueTable
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
            relic_coeff=3000, ancient_coeff=8000,
        )
        sim.simulate_one(seed=1)
        tbl = sim._get_side_value_table("order_fortitude")
        self.assertIsInstance(tbl, SideValueTable)
        self.assertTrue(tbl.enabled)
        # Cached: a second call returns the same object.
        self.assertIs(tbl, sim._get_side_value_table("order_fortitude"))

    def test_decision_context_carries_side_value_table(self):
        from arkgrid.models import AstroGem
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
            astro_gem=AstroGem("order_fortitude", "boss_damage",
                               "attack_power", "dps"),
        )
        sim.simulate_one(seed=1)
        ctx = sim._decision_context()
        self.assertIsNotNone(ctx.side_value_table)

    def test_relic_ancient_coeff_default_zero(self):
        sim = GemSimulator(
            rarity="epic", use_extra_ticket=False, use_reset_ticket=False,
            goal=LastTurnGoal(min_will=4, min_chaos=4),
        )
        self.assertEqual(sim.relic_coeff, 0)
        self.assertEqual(sim.ancient_coeff, 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_simulator.TestSideValueTableWiring -v`
Expected: FAIL — `GemSimulator` has no `relic_coeff` param / no `_get_side_value_table`.

- [ ] **Step 3: Add the `side_value_table` field to `DecisionContext`**

In `arkgrid/decision.py`, add `SideValueTable` to the probability import (line 38):

```python
from arkgrid.probability import GoalProbabilityTable, SideValueTable
```

Append the field to `DecisionContext` (after `endgame_risk` at line 97):

```python
    endgame_risk: bool = False
    side_value_table: Optional[SideValueTable] = None
```

- [ ] **Step 4: Add `relic_coeff` / `ancient_coeff` params + cache to `GemSimulator.__init__`**

In `arkgrid/simulator.py`, add `SideValueTable` to the probability import (line 18):

```python
from arkgrid.probability import GoalProbabilityTable, SideValueTable
```

Add two parameters to `__init__` after `endgame_risk` (line 47):

```python
            endgame_risk: bool = False,
            relic_coeff: int = 0,
            ancient_coeff: int = 0,
    ) -> None:
```

Store them and add the cache dict — insert after `self.endgame_risk = endgame_risk` (line 61):

```python
        self.endgame_risk = endgame_risk
        self.relic_coeff = relic_coeff
        self.ancient_coeff = ancient_coeff
        self._side_value_table_cache: Dict[str, SideValueTable] = {}
```

- [ ] **Step 5: Add `_get_side_value_table` to `GemSimulator`**

In `arkgrid/simulator.py`, add this method immediately after `_get_ea_tables` (after line 208):

```python
    def _get_side_value_table(self, gem_type: str) -> SideValueTable:
        """Build or fetch the cached side-value DP table for a gem type.

        One table per gem type covers all effect configs (the effect pair
        is in the DP state), so `--all` / random-gem runs amortize the
        build the same way `_get_ea_tables` does.
        """
        cached = self._side_value_table_cache.get(gem_type)
        if cached is not None:
            return cached
        table = SideValueTable(
            self.goal, self.turns_total, self.pool,
            gem_type=gem_type, optimize=self.optimize,
            min_side_coeff=self.min_side_coeff,
            max_rerolls=self._dp_max_rerolls,
            relic_coeff=self.relic_coeff,
            ancient_coeff=self.ancient_coeff,
        )
        self._side_value_table_cache[gem_type] = table
        return table
```

- [ ] **Step 6: Hold the active table on the simulator and swap it per run**

In `arkgrid/simulator.py` `__init__`, after the `self._side_value_table_cache` line from Step 4, add:

```python
        self._side_value_table: Optional[SideValueTable] = None
```

In `simulate_one`, the effect-aware swap block (lines 463–468) currently ends with the `_risk_prob_table` assignment. Add the side-value table swap right after it:

```python
        if self.effect_aware and run_gem.gem_type in GEM_TYPES:
            ea_reroll, ea_reset, ea_risk = self._get_ea_tables(run_gem.gem_type)
            self.prob_table = ea_reroll
            self._reset_prob_table = ea_reset
            if self.confirm_active:
                self._risk_prob_table = ea_risk
        self._side_value_table = (
            self._get_side_value_table(run_gem.gem_type)
            if run_gem.gem_type in GEM_TYPES else None)
```

(The side-value table is built for any known gem type — it does not depend on `effect_aware`, which only governs the goal DP.)

- [ ] **Step 7: Pass the table into `DecisionContext`**

In `arkgrid/simulator.py` `_decision_context`, add to the `DecisionContext(...)` constructor (after `endgame_risk=self.endgame_risk,` at line 341):

```python
            endgame_risk=self.endgame_risk,
            side_value_table=self._side_value_table,
        )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m unittest tests.test_simulator.TestSideValueTableWiring -v`
Expected: PASS (3 tests).

- [ ] **Step 9: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS — `side_value_table` is carried but no decision branch reads it yet, so behavior is unchanged.

- [ ] **Step 10: Verify and pause for commit.**

---

## Task 3: Build & thread the side-value table in `run_auto`

`run_auto` builds a per-run `SideValueTable` on first detection and passes it into `DecisionContext`. No automation unit tests exist (Windows `ctypes`/OCR path) — verified by import + inspection.

**Files:**
- Modify: `arkgrid/automation.py` (`run_auto` signature, table build, `DecisionContext` build)

- [ ] **Step 1: Add `SideValueTable` to the automation import**

In `arkgrid/automation.py`, change the probability import to include `SideValueTable` (find the existing `from arkgrid.probability import GoalProbabilityTable` line and extend it):

```python
from arkgrid.probability import GoalProbabilityTable, SideValueTable
```

- [ ] **Step 2: Add `relic_coeff` / `ancient_coeff` parameters to `run_auto`**

In `arkgrid/automation.py` `run_auto`, add two parameters after `endgame_risk` (line 557):

```python
    endgame_risk: bool = False,
    relic_coeff: int = 0,
    ancient_coeff: int = 0,
    args=None,
) -> None:
```

- [ ] **Step 3: Add the per-gem side-value table variable**

In `run_auto`, next to the `risk_table` declaration (line 617), add:

```python
        # Risk (goal, early_finish=False) probability table — built on first
        # detection when confirm gate is active.
        risk_table: Optional[GoalProbabilityTable] = None

        # Side-value DP table — built on first detection.
        side_value_table: Optional[SideValueTable] = None
```

- [ ] **Step 4: Build the side-value table on first detection**

In `run_auto`, after the risk-table build block (lines 829–837, which ends with `risk_table = risk_tbl_result`), add:

```python
                # Side-value DP table: built once per gem type detected.
                if side_value_table is None:
                    side_value_table = SideValueTable(
                        goal, det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=min_side_coeff,
                        max_rerolls=dp_max_rerolls,
                        relic_coeff=relic_coeff,
                        ancient_coeff=ancient_coeff,
                    )
```

- [ ] **Step 5: Pass the table into the `DecisionContext`**

In `run_auto`, the `DecisionContext(...)` constructor (lines 917–941) ends with `endgame_risk=endgame_risk,`. Add the field:

```python
                    endgame_risk=endgame_risk,
                    side_value_table=side_value_table,
                )
```

- [ ] **Step 6: Verify**

Run: `python -c "import arkgrid.automation"`
Expected: no error.
Run: `python -m unittest discover -s tests -v`
Expected: PASS — additive change, no decision logic touched.
Pause for commit.

---

## Task 4: `_side_value_finish_decision` — swap the decision logic

The core behavior change. `early_finish_decision` becomes a thin dispatcher onto a new `_side_value_finish_decision`. `_ev_cell`, `_relic_chase_active`, `_legacy_early_finish_decision`, `_confirm_finish_decision`, `_change_effect_ev` are deleted; `TurnMetrics` sheds the EV-only fields; `endgame_risk` becomes a float.

**Files:**
- Modify: `arkgrid/decision.py`
- Test: `tests/test_decision.py` (delete obsolete classes, add new ones, update `build_ctx`)
- Re-baseline: `tests/test_simulator.py`, `tests/test_scenarios.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_decision.py`, update the imports. Replace the line
`from arkgrid.decision import TurnMetrics, _ev_cell, _relic_chase_active`
with:

```python
from arkgrid.decision import TurnMetrics, _side_value_finish_decision
from arkgrid.probability import SideValueTable
```

Also, in the main `from arkgrid.decision import (...)` block at the top of the file, remove `_continue_has_upside` from the imported names (it sits next to `_side_coeff` / `_legal_actions` on line 22) — that helper is deleted in Step 5.

Update `build_ctx` to build and pass a `side_value_table`. After the `risk_table = (...)` block (ends line 88), add:

```python
    side_value_table = SideValueTable(
        g, turns_total, _POOL, gem_type=gem_type, optimize=optimize,
        min_side_coeff=min_side_coeff, max_rerolls=base_rerolls,
        relic_coeff=relic_coeff, ancient_coeff=ancient_coeff,
    )
```

Add `relic_coeff` / `ancient_coeff` / float `endgame_risk` to the `build_ctx` signature (replace the `endgame_risk: bool = False,` line at 63):

```python
    endgame_risk: float = 0.0,
    relic_coeff: int = 0,
    ancient_coeff: int = 0,
```

Add the field to the `DecisionContext(...)` return inside `build_ctx` (after `endgame_risk=endgame_risk,` at line 107):

```python
        endgame_risk=endgame_risk,
        side_value_table=side_value_table,
    )
```

Add the new test class:

```python
class TestSideValueFinish(unittest.TestCase):
    """Task 4: _side_value_finish_decision — the turns-aware finish."""

    def _ctx(self, **kw):
        kw.setdefault("gem_type", "order_fortitude")
        kw.setdefault("optimize", "dps")
        kw.setdefault("goal", LastTurnGoal(min_will=4, min_chaos=4))
        kw.setdefault("relic_no_early_finish", 0.0)
        return build_ctx(**kw)

    def test_played_out_gem_last_turn_finishes(self):
        # Goal met, sides capped, last turn, no offer can help -> FINISH.
        ctx = self._ctx()
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)

    def test_improvable_gem_continues(self):
        # Goal met early, side nodes low, turns left -> continuing wins,
        # decision defers (None -> PROCESS via the tree).
        ctx = self._ctx()
        st = GemState(will=4, chaos=4, first=2, second=2,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("first+1", "second+1",
                                         "will+1", "chaos+1"),
                      turn=3, turns_left=7, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_no_side_value_table_never_finishes(self):
        # Gem type unknown -> table disabled -> no early finish.
        ctx = self._ctx(gem_type="")
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_goal_not_met_returns_none(self):
        ctx = self._ctx()
        st = GemState(will=2, chaos=2, first=3, second=3,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st, turn=9, turns_left=1, rerolls=0,
                      reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNone(d)

    def test_free_reroll_preferred_over_finish(self):
        # Played-out last turn but a reroll is free -> REROLL, not FINISH.
        ctx = self._ctx()
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=8, turns_left=2, rerolls=2, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.REROLL)

    def test_gate_on_above_floor_prompts_on_finish(self):
        # Confirm gate active, valuable gem, finish call -> F1-F4 prompt.
        ctx = self._ctx(confirm_min_coeff=1000)
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertTrue(d.needs_confirmation)
        self.assertIn(ActionKind.PROCESS, d.confirm_choices)

    def test_gate_on_below_floor_finishes_silently(self):
        ctx = self._ctx(confirm_min_coeff=999999)
        st = GemState(will=5, chaos=5, first=5, second=5,
                      first_effect="boss_damage", second_effect="attack_power")
        ti = build_ti(state=st,
                      offers=make_offers("will-1", "chaos-1",
                                         "first-1", "second-1"),
                      turn=9, turns_left=1, rerolls=0, reset_available=False)
        d = early_finish_decision(ctx, ti, compute_post_roll_metrics(ctx, ti))
        self.assertIsNotNone(d)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertFalse(d.needs_confirmation)
```

- [ ] **Step 2: Delete the obsolete test classes**

In `tests/test_decision.py`, delete these whole test classes (they pin behavior being removed): `TestEvMetrics`, `TestEvCell`, `TestRelicChaseActive`, `TestLegacyEvCell`, `TestConfirmEvCell`, `TestGate1ConfirmFinish`, and any class whose body calls `_ev_cell`, `_relic_chase_active`, `_legacy_early_finish_decision`, `_confirm_finish_decision`, or asserts `early_finish_coeff` / `confirm_risk` behavior. Use `grep -n "_ev_cell\|_relic_chase\|early_finish_coeff\|confirm_risk\|TestEarlyFinish\|TestConfirm" tests/test_decision.py` to locate them; delete each class in full.

In `TestConfirmHelpers`, delete *only* the two `_continue_has_upside` test methods (`test_upside_false_when_no_turns`, `test_upside_true_when_side_below_cap`) — the `_side_coeff` and `_legal_actions` test methods in that class survive (those helpers are kept).

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m unittest tests.test_decision.TestSideValueFinish -v`
Expected: FAIL — `ImportError: cannot import name '_side_value_finish_decision'`.

- [ ] **Step 4: Change `endgame_risk` to a float on `DecisionContext`**

In `arkgrid/decision.py`, change the `DecisionContext` field (line 97):

```python
    endgame_risk: float = 0.0
```

- [ ] **Step 5: Delete the obsolete decision helpers**

In `arkgrid/decision.py`, delete these functions in full: `_ev_cell` (lines 287–313), `_relic_chase_active` (316–328), `_continue_has_upside` (267–284), `_change_effect_ev` (357–380), `_confirm_finish_decision` (496–588), `_legacy_early_finish_decision` (591–674). (`_continue_has_upside` was used only by `_confirm_finish_decision`; `_side_coeff`, `_legal_actions`, and `_maybe_confirm` are kept — gates #2/#3 and `_side_value_finish_decision` still use them.)

- [ ] **Step 6: Replace `early_finish_decision` with the dispatcher + `_side_value_finish_decision`**

In `arkgrid/decision.py`, replace the body of `early_finish_decision` (lines 476–493) with:

```python
def early_finish_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Goal already met — decide finish / continue / reroll via the
    side-value DP. Returns None to defer to the rest of the tree
    (PROCESS) when continuing is best, or when no side-value table is
    available (gem type unknown).
    """
    if not _goal_fully_satisfied(ctx, ti.state):
        return None
    if not ti.offers:
        return None
    return _side_value_finish_decision(ctx, ti, m)


def _side_value_finish_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Turns-aware finish-vs-continue using the side-value DP.

    `finish_val` is the value of stopping now; `continue_val` is the best
    non-finish action (process EV over the *actual* offers, or a reroll).
    The DP is turns-aware, so this finishes mid-run only when the gem is
    genuinely played out — a recoverable gem has `continue_val` high
    enough to defer.

    Gate off: finish iff `finish_val >= continue_val + endgame_risk`
    (the margin, default 0, is the unattended risk-tolerance knob).
    Gate on: the margin is 0, and a finish on a gem above the
    `--confirm-min-coeff` floor is surfaced as an F1-F4 prompt instead of
    finishing silently.
    """
    svt = ctx.side_value_table
    if svt is None or not svt.enabled:
        return None

    finish_val = svt.gem_value(ti.state)
    process_ev = svt.expected_value_after_click(
        ti.state, ti.offers, ti.turns_left - 1, rerolls=ti.rerolls)
    can_reroll = ti.rerolls > 0 and ti.turn != 1
    reroll_val = (svt.lookup(ti.state, ti.turns_left, rerolls=ti.rerolls - 1)
                  if can_reroll else 0.0)
    continue_val = process_ev if process_ev > reroll_val else reroll_val

    margin = 0.0 if ctx.confirm_active else ctx.endgame_risk
    metrics = {
        "finish_val": finish_val,
        "process_ev": process_ev,
        "reroll_val": reroll_val,
        "continue_val": continue_val,
        "margin": margin,
    }

    if finish_val < continue_val + margin:
        # Continuing wins. Reroll if it is the best continuation;
        # otherwise defer to PROCESS.
        if can_reroll and reroll_val > process_ev:
            return Decision(
                action=ActionKind.REROLL, branch="side_value_finish",
                reason=(f"goal met, reroll_val={reroll_val:.0f} > "
                        f"process_ev={process_ev:.0f}"),
                metrics=metrics,
            )
        return None

    # Finishing wins.
    reason = (f"goal met, finish_val={finish_val:.0f} >= "
              f"continue_val={continue_val:.0f}+margin={margin:.0f}")
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

- [ ] **Step 7: Trim the EV-only fields from `TurnMetrics` + `compute_post_roll_metrics`**

In `arkgrid/decision.py`, `TurnMetrics` (lines 171–187) now only needs the probability/feasibility fields. Replace the dataclass body fields with:

```python
@dataclass(frozen=True)
class TurnMetrics:
    """Probabilities and per-offer aggregates the branch helpers need.

    All fields are 0.0 / 0 when not applicable (e.g. no relic table,
    no offers). Callers should never `if metrics.x is not None`.
    """
    p_keep_goal: float            # prob_table.expected_prob_after_click
    p_keep_goal_reset: float      # reset_prob_table.expected_prob_after_click
    p_keep_relic: float           # relic_table.expected_prob_after_click (0 if None)
    p_reroll_relic: float         # relic_table.lookup(state, tl, rerolls-1) (0 if None/no reroll)
    feasible_count: int           # # offers where prob_table DP > 0 after pick
```

In `compute_post_roll_metrics`: change the empty-offers early return (line 391) to five fields:

```python
    if not ti.offers:
        return TurnMetrics(0.0, 0.0, 0.0, 0.0, 0)
```

Delete the EV accumulators and the per-offer EV block. In the accumulator block (lines 417–422) keep only:

```python
    feasible_count = 0
```

In the per-offer loop (lines 424–452), delete everything except the feasibility check — the loop body becomes:

```python
    for o in ti.offers:
        ns = _apply_option_for_metrics(ti.state, o)
        view_delta = o.delta if o.kind == "view" else 0
        nr = (min(max_r, ti.rerolls + view_delta)
              if max_r > 0 else ti.rerolls)
        if ctx.prob_table.lookup(ns, tla, rerolls=nr) > 0:
            feasible_count += 1
```

Delete the now-unused `coeff_map` / `target_set` locals (lines 413–414) and the `avg_coeff_change` / `ev_points` tail (lines 454–455). Replace the `return TurnMetrics(...)` (lines 457–468) with:

```python
    return TurnMetrics(
        p_keep_goal=p_keep_goal,
        p_keep_goal_reset=p_keep_goal_reset,
        p_keep_relic=p_keep_relic,
        p_reroll_relic=p_reroll_relic,
        feasible_count=feasible_count,
    )
```

- [ ] **Step 8: Run the new decision tests**

Run: `python -m unittest tests.test_decision.TestSideValueFinish -v`
Expected: PASS (7 tests).

- [ ] **Step 9: Run the full decision module**

Run: `python -m unittest tests.test_decision -v`
Expected: PASS. If a surviving test references a deleted symbol or `TurnMetrics` field, it belongs to the obsolete set from Step 2 — delete it. Branch tests that build `TurnMetrics` directly (e.g. `infeasibility_decision` tests) must pass the 5-field form.

- [ ] **Step 10: Re-baseline `tests/test_simulator.py` and `tests/test_scenarios.py`**

Run: `python -m unittest tests.test_simulator tests.test_scenarios -v`

The side-value DP changes finish-vs-continue on goal-met runs, so behavioral assertions on final state / `total_points` / turn count / `reset_used` may shift. For each failure: confirm the failing run is goal-met and the change is an earlier/later finish or an added reroll on a goal-met gem (both intended). Verify the new value by hand against the run, then update the expected value in the test. **If a failure is not explainable as a changed goal-met finish/reroll — stop and investigate; it is a real regression.**

`tests/test_policy.py` and `should_early_finish` (the bool wrapper in `simulator.py`) still work — `early_finish_decision` keeps its signature and returns a `Decision`/`None`.

- [ ] **Step 11: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS after the re-baselining in Step 10.

- [ ] **Step 12: Verify and pause for commit.**

---

## Task 5: Retire 3 flags, add `--relic-coeff` / `--ancient-coeff`, `--endgame-risk` → float

Removes the dead `early_finish_coeff` / `relic_no_early_finish` / `confirm_risk` / `risk_prob_table` fields and the CLI flags, adds the two tier-weight flags, makes `--endgame-risk` a float, rewrites the `cmd_live` inline hint, and fixes the `early_finish` argument now that `--early-finish-coeff` is gone.

**Files:**
- Modify: `arkgrid/cli.py`, `arkgrid/decision.py`, `arkgrid/simulator.py`, `arkgrid/automation.py`
- Test: `tests/test_cli.py`, plus full suite

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (follow the file's existing import/style):

```python
class TestTierFlags(unittest.TestCase):
    """Task 5: --relic-coeff / --ancient-coeff parse; retired flags gone."""

    def test_relic_ancient_coeff_default_zero(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertEqual(args.relic_coeff, 0)
        self.assertEqual(args.ancient_coeff, 0)

    def test_relic_ancient_coeff_parse(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(
            ["sim", "--min-will", "4", "--relic-coeff", "3000",
             "--ancient-coeff", "8000"])
        self.assertEqual(args.relic_coeff, 3000)
        self.assertEqual(args.ancient_coeff, 8000)

    def test_endgame_risk_is_float(self):
        from arkgrid.cli import _build_parser
        args = _build_parser().parse_args(
            ["sim", "--min-will", "4", "--endgame-risk", "2000"])
        self.assertEqual(args.endgame_risk, 2000.0)
        args0 = _build_parser().parse_args(["sim", "--min-will", "4"])
        self.assertEqual(args0.endgame_risk, 0.0)

    def test_retired_flags_rejected(self):
        from arkgrid.cli import _build_parser
        for flag in ("--early-finish-coeff", "--relic-no-early-finish",
                     "--confirm-risk"):
            with self.assertRaises(SystemExit):
                _build_parser().parse_args(
                    ["sim", "--min-will", "4", flag, "1"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_cli.TestTierFlags -v`
Expected: FAIL — flags not defined / retired flags still accepted.

- [ ] **Step 3: Update the CLI flags in `add_common`**

In `arkgrid/cli.py` `add_common`: delete the `--early-finish-coeff` block (lines 101–106), the `--relic-no-early-finish` block (117–121), and the `--confirm-risk` block (134–140). Replace the `--endgame-risk` block (107–116) with a float flag, and add the two tier flags. Insert in their place:

```python
        p.add_argument("--endgame-risk", type=float, default=0.0, metavar="F",
                        help="Unattended risk margin for the side-value finish. "
                             "Finish a goal-met gem only when stopping beats the "
                             "best continuation by >= F coefficient. 0 = "
                             "EV-optimal (default); a large F plays to the last "
                             "turn. No effect when --confirm-min-coeff is set.")
        p.add_argument("--relic-coeff", type=int, default=0, metavar="N",
                        help="Coefficient-equivalent worth of holding the relic+ "
                             "grade (>=16 total points), added to gem_value in "
                             "the side-value DP. 0 = relic+ has no pull "
                             "(default).")
        p.add_argument("--ancient-coeff", type=int, default=0, metavar="N",
                        help="Coefficient-equivalent worth of holding the ancient "
                             "grade (>=19 total points). Expected >= --relic-coeff. "
                             "0 = ancient has no pull (default).")
```

In `_add_report_filter_args`, delete the `--early-finish-coeff` line (247) and the `--relic-no-early-finish` line (257–258), replace the `--endgame-risk` line (248–249) with `p.add_argument("--endgame-risk", type=float, default=0.0, metavar="F")`, and add after it:

```python
    p.add_argument("--relic-coeff", type=int, default=0, metavar="N")
    p.add_argument("--ancient-coeff", type=int, default=0, metavar="N")
```

- [ ] **Step 4: Remove the dead fields from `DecisionContext`**

In `arkgrid/decision.py` `DecisionContext`, delete the `early_finish_coeff` field (line 81), the `relic_no_early_finish` field (line 83), the `confirm_risk` field (line 95), and the `risk_prob_table` field (line 96). Keep `confirm_active`, `confirm_min_coeff`, `relic_reroll_threshold`, `relic_prob_table`.

- [ ] **Step 5: Update `GemSimulator`**

In `arkgrid/simulator.py` `__init__`: delete the `early_finish_coeff` param (line 40), the `relic_no_early_finish` param (line 41), and the `confirm_risk` param (line 45). Keep `confirm_min_coeff`. Then:

- Delete `self.early_finish_coeff = early_finish_coeff` (line 104).
- Replace `self.confirm_active = (confirm_risk is not None or confirm_min_coeff is not None)` (lines 56–57) with `self.confirm_active = confirm_min_coeff is not None`.
- Delete `self.confirm_risk = ...` (line 58).
- Delete `self.relic_no_early_finish = relic_no_early_finish` (line 137).
- Delete the `self._risk_prob_table` block (lines 156–165) and the `self._ea_risk_table_cache` dict (line 64).
- In the relic-table condition (line 142), change `if relic_no_early_finish > 0.0 or relic_reroll_threshold > 0.0:` to `if relic_reroll_threshold > 0.0:`.
- In every `GoalProbabilityTable(...)` build that passes `early_finish=early_finish_coeff >= 0` (the `prob_table`, `_reset_prob_table` builds, and `_get_ea_tables`), change it to `early_finish=True` (the `-1`/disable mode is gone — a goal-met state is always a guaranteed success for the goal DP).
- In `_get_ea_tables`: delete the `risk_tbl` build and the `_ea_risk_table_cache` use; the method now builds and returns `(reroll_tbl, reset_tbl)`. Update its docstring and the early-return.
- In `simulate_one`, the effect-aware swap: change `ea_reroll, ea_reset, ea_risk = self._get_ea_tables(...)` to `ea_reroll, ea_reset = self._get_ea_tables(...)` and delete the `if self.confirm_active: self._risk_prob_table = ea_risk` lines.
- In `_decision_context`, delete `early_finish_coeff=...`, `relic_no_early_finish=...`, `confirm_risk=...`, `risk_prob_table=...` from the `DecisionContext(...)` constructor.

Add `relic_coeff` / `ancient_coeff` are already on `GemSimulator` from Task 2 — no change.

- [ ] **Step 6: Update `automation.run_auto`**

In `arkgrid/automation.py` `run_auto`: delete the `early_finish_coeff` param (line 549), the `relic_no_early_finish` param (line 550), and the `confirm_risk` param (line 555). Then:

- Replace `confirm_active = (confirm_risk is not None or confirm_min_coeff is not None)` (line 565) with `confirm_active = confirm_min_coeff is not None`.
- Delete the `confirm_risk = ...` line (566).
- Delete the `risk_table` declaration (617) and the entire risk-table build block (lines 827–837).
- In `_build_prob_table` calls and the `relic_table` / `reset_prob_table` builds, change `early_finish=early_finish_coeff >= 0` to `early_finish=True`.
- In the `relic_table` build condition (line 810–811), change `relic_no_early_finish > 0.0 or relic_reroll_threshold > 0.0` to `relic_reroll_threshold > 0.0`.
- In the `DecisionContext(...)` constructor, delete `early_finish_coeff=...`, `relic_no_early_finish=...`, `confirm_risk=...`, `risk_prob_table=...`.

`relic_coeff` / `ancient_coeff` params are already on `run_auto` from Task 3 — no change.

- [ ] **Step 7: Update the `cli.py` command handlers**

In `arkgrid/cli.py`:

(a) `_compute_dp_prob` and `cmd_stats` — the `early_finish` argument was derived from `args.early_finish_coeff >= 0`. In `cmd_stats`, delete `ef = args.early_finish_coeff >= 0` (line 552) and pass `early_finish=True` to both `_compute_dp_prob` calls (lines 556, 562) and the relic-DP call already passes `early_finish=False` — leave it.

(b) `cmd_stats` `GemSimulator(...)` call (lines 577–598): delete `early_finish_coeff=args.early_finish_coeff,`, `relic_no_early_finish=args.relic_no_early_finish,`, `confirm_risk=args.confirm_risk,`; add `relic_coeff=args.relic_coeff,` and `ancient_coeff=args.ancient_coeff,`.

(c) `cmd_sim` `GemSimulator(...)` call (lines 616–637): same three deletions, same two additions.

(d) `cmd_auto` `run_auto(...)` call (lines 1146–1171): delete `early_finish_coeff=args.early_finish_coeff,`, `relic_no_early_finish=args.relic_no_early_finish,`, `confirm_risk=args.confirm_risk,`; add `relic_coeff=args.relic_coeff,` and `ancient_coeff=args.ancient_coeff,`.

(e) `cmd_live` `GemSimulator(...)` call (lines 1070–1087): delete `early_finish_coeff=early_finish_coeff,`; add `relic_coeff=getattr(args, "relic_coeff", 0),` and `ancient_coeff=getattr(args, "ancient_coeff", 0),`.

(f) `_print_config` (lines 371–372): the `early_finish_coeff` line reads a now-removed flag. Replace those two lines with:

```python
    print(f"Endgame risk:   {getattr(args, 'endgame_risk', 0.0):.0f} "
          f"(side-value finish margin)")
```

- [ ] **Step 8: Rewrite the `cmd_live` inline early-finish hint**

In `arkgrid/cli.py` `cmd_live`, the inline hint block (lines 1014–1051) computes a finish recommendation from the now-removed `early_finish_coeff`. Replace the whole block (from `# --- Early finish check ---` at 1014 through the `should_early_finish` assignment that ends at line 1046) with a side-value-DP-based hint. `cmd_live` already has `state`, `goal`, `turns_left`, `gem_type_domain`, `args` in scope. Replace lines 1014–1051 (the `# --- Early finish check ---` block and the `if should_early_finish:` print) with:

```python
    # --- Early finish check (side-value DP) ---
    should_early_finish = False
    if (turns_left > 0
            and goal.satisfied(state.will, state.chaos,
                               state.first, state.second)
            and gem_type_domain in GEM_TYPES):
        from arkgrid.probability import SideValueTable
        svt = SideValueTable(
            goal, current_turn + turns_left - 1, pool,
            gem_type=gem_type_domain,
            optimize=getattr(args, "optimize", "dps"),
            min_side_coeff=getattr(args, "min_side_coeff", 0),
            max_rerolls=reroll_count,
            relic_coeff=getattr(args, "relic_coeff", 0),
            ancient_coeff=getattr(args, "ancient_coeff", 0),
        )
        finish_val = svt.gem_value(state)
        offer_objs = [opt for opt, _kind, _dv, _p in option_probs]
        process_ev = svt.expected_value_after_click(
            state, offer_objs, turns_left - 1, rerolls=reroll_count)
        reroll_v = (svt.lookup(state, turns_left, rerolls=reroll_count - 1)
                    if (reroll_count > 0 and current_turn != 1) else 0.0)
        continue_val = max(process_ev, reroll_v)
        should_early_finish = finish_val >= continue_val

    if should_early_finish:
        print(f"  >>> Finish (side-value DP: stopping is at least as "
              f"good as continuing)")
```

Note: `option_probs` is the list of `(opt, kind, delta_val, p_after)` tuples already built earlier in `cmd_live`; `current_turn`, `reroll_count`, `pool` are in scope. If `pool` is not a local in `cmd_live`, build one: `from arkgrid.pool import OptionPool` then `pool = OptionPool()` — check the surrounding code and reuse the existing pool variable if present.

- [ ] **Step 9: Add a `P(ancient)` display**

In `arkgrid/cli.py` `cmd_stats`, after the relic-DP block (lines 568–574), add an ancient-DP figure:

```python
            ancient_dp = _compute_dp_prob(
                LastTurnGoal(min_total=19), rarity, astro_gem, args.optimize,
                bis_only=False, min_side_coeff=0,
                early_finish=False,
                max_rerolls=base_rerolls,
            )
            summary["ancient_dp_prob"] = ancient_dp
```

The `pprint_result` display function reads `summary["relic_dp_prob"]`; add an `ancient_dp_prob` line next to it. Locate `pprint_result` (search `def pprint_result` — it is imported into `cli.py`; it lives in `arkgrid/analyzer.py` or a display module). Add a print line mirroring the relic one, e.g. `P(ancient>=19): {summary['ancient_dp_prob']:.1%}`. If `pprint_result` iterates a fixed key list, add `ancient_dp_prob` to it.

- [ ] **Step 10: Clean up `log_analyzer.py` filter references**

Run `grep -rn "early_finish_coeff\|relic_no_early_finish\|confirm_risk" arkgrid/`. For any remaining match in `arkgrid/log_analyzer.py` (a report filter comparing `a.get("early_finish_coeff")` etc.), delete that filter entry — the keys are no longer produced. Leave matches in comments/docstrings for Step 11 of Task 6.

- [ ] **Step 11: Run the tests**

Run: `python -m unittest tests.test_cli.TestTierFlags -v` → PASS (4 tests).
Run: `python -m unittest discover -s tests -v` → PASS. Fix any test still constructing `GemSimulator` / `DecisionContext` / `run_auto` with a removed kwarg (update it to the new signature).

- [ ] **Step 12: Smoke-test the CLI**

```bash
python -m arkgrid stats --min-will 4 --min-chaos 4 --rarity epic --trials 0 --relic-coeff 3000 --ancient-coeff 8000
python -m arkgrid sim --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --ancient-coeff 8000 --endgame-risk 1500 --seed 42
python -m arkgrid sim --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --confirm-min-coeff 2000 --seed 42
```
Expected: all three run without error; `stats` prints `P(ancient>=19)`.

- [ ] **Step 13: Verify and pause for commit.**

---

## Task 6: Monte-Carlo validation and documentation

**Files:**
- Verify: full test suite + MC comparison
- Modify: `CLAUDE.md`

- [ ] **Step 1: Monte-Carlo before/after comparison**

Run a fixed-seed `stats` comparison on an epic gem, default knobs vs tier knobs:

```bash
python -m arkgrid stats --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --rarity epic --trials 20000 --seed 1
python -m arkgrid stats --min-will 4 --min-chaos 4 --first-effect boss_damage --second-effect attack_power --rarity epic --trials 20000 --seed 1 --relic-coeff 3000 --ancient-coeff 8000
```

Confirm: (a) main-goal success rate is within noise between the two runs (tier knobs must not regress goal success); (b) the second run shows a higher relic+/ancient rate and/or average side coefficient — the tier weights are doing their job. Record the figures in the commit message. If main-goal success regresses materially, stop and investigate — the side-value DP must never trade goal success for tier value (a goal-broken state is valued 0).

- [ ] **Step 2: Document the feature in `CLAUDE.md`**

In `CLAUDE.md`:

- In the `probability.py` module description, add a sentence: `SideValueTable` is a parallel effect-aware reroll-aware DP whose value is the expected final gem value (`side_coeff + tier_bonus(total_points)`); it is consulted once the goal is met to decide finish-vs-continue.
- In the `decision.py` description, replace mentions of `_ev_cell` / `_legacy_early_finish_decision` / `_confirm_finish_decision` / `_relic_chase_active` with `_side_value_finish_decision`.
- Replace the **EV-gated finish** key-concept bullet with a **Side-value finish** bullet: the side-value DP decides finish-vs-continue at every goal-met turn; `gem_value = side_coeff + tier_bonus`; gate-off `--endgame-risk` margin; gate-on `--confirm-min-coeff` FINISH-prompt.
- Delete the **Early finish** (`--early-finish-coeff`) bullet and update the **Relic+ tracking** bullet: `--relic-no-early-finish` is retired (folded into `--relic-coeff`); `--relic-reroll-threshold` is unchanged.
- Update the **Confirmation gate** bullet: `--confirm-risk` is retired; `--confirm-min-coeff` is the sole confirm-gate knob — it activates the gate and prompts on every side-value FINISH for a gem above the floor. Gates #2/#3 (infeasibility, reset) unchanged.
- Add `--relic-coeff` / `--ancient-coeff` to the **Effect coefficients** / domain notes.

- [ ] **Step 3: Full regression sweep**

Run: `python -m unittest discover -s tests -v`
Expected: all tests pass.

- [ ] **Step 4: Verify and pause for commit.**

---

## Self-review notes

- **Spec coverage:** `gem_value` additive model + `SideValueTable` (Task 1) · simulator wiring + caching (Task 2) · automation wiring (Task 3) · `_side_value_finish_decision` replacing `_ev_cell` / `_relic_chase_active` / both early-finish call sites, `--endgame-risk` as a float margin, gate-on `--confirm-min-coeff` FINISH-prompt (Task 4) · retire `--early-finish-coeff` / `--relic-no-early-finish` / `--confirm-risk` + the risk table, add `--relic-coeff` / `--ancient-coeff`, `P(ancient)` display (Task 5) · MC validation + docs (Task 6). All spec sections mapped.
- **Spec deviation (intentional):** the spec's Integration sketch says `DecisionContext` gains the `relic_coeff` / `ancient_coeff` knobs. The plan bakes those into `SideValueTable` at build time instead — the decision layer only ever needs `gem_value` / `lookup` outputs, so `DecisionContext` carries just `side_value_table`. Same design, cleaner boundary.
- **Green-suite invariant:** Tasks 1–3 are additive (table built and carried, unused) — suite stays green. Task 4 is the behavior switch; it deletes the obsolete decision tests and re-baselines `test_simulator` / `test_scenarios`, exactly as the prior ev-gated-finish plan handled its goal-met behavior change. Task 5 is mechanical signature surgery.
- **Type consistency:** `SideValueTable(goal, max_turns, pool, *, gem_type, optimize, min_side_coeff, max_rerolls, relic_coeff, ancient_coeff)`; `.gem_value(state)`, `.lookup(state, tl, rerolls)`, `.expected_value_after_click(state, offers, tl_after, rerolls)`, `.enabled`. `DecisionContext.side_value_table: Optional[SideValueTable]`, `DecisionContext.endgame_risk: float`. `GemSimulator(..., relic_coeff, ancient_coeff)`, `run_auto(..., relic_coeff, ancient_coeff)`. `_side_value_finish_decision(ctx, ti, m) -> Optional[Decision]`, branch tag `"side_value_finish"`. Names consistent across all tasks.
- **No-gem-type fallback:** `SideValueTable.enabled is False` when the gem type is unknown; `_side_value_finish_decision` returns `None` (no early finish — the gem plays to the last turn). Tested in Task 4 Step 1.
- **`early_finish` argument:** with `--early-finish-coeff` gone, every `GoalProbabilityTable(early_finish=...)` build that was gated on `early_finish_coeff >= 0` becomes `early_finish=True` (Task 5) — a goal-met state is always a guaranteed goal success for the goal DP; the `-1`/disable mode had no other consumer.
