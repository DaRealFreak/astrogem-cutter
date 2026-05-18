# Side-Value DP — turns-aware finish (design)

> **Status:** design doc — `gem_value` and the finish-flag migration resolved
> (additive tier model; `--early-finish-coeff` / `--relic-no-early-finish` /
> `--confirm-risk` retired, 2026-05-17). Ready to turn into a task-by-task
> implementation plan via `superpowers:writing-plans`.

## Problem

The EV-gated finish just shipped (`decision._ev_cell`) is a **single-turn heuristic**. It judges only the current offer set (EV + odds). That is a *valid* finish signal only on the **last turn**, where this turn's EV is the whole remaining EV. Mid-run it cannot see **recovery potential** — with turns left you can re-roll a wrecked `boss_damage` back, or level other nodes — so the current design deliberately **never finishes mid-run**: an EV-stop mid-run only rerolls or defers (continue/process).

Consequence: finish-vs-continue is decided correctly only on the last turn. Mid-run, a goal-met gem always plays on. That is safe (it never wrongly finishes a recoverable gem) but it is not *optimal* — near the end (2–3 turns left) it taps offer sets it arguably should not, and it can never finish a genuinely played-out gem early.

## Goal

Decide finish-vs-continue **correctly at every turn**, scaling with how many turns of recovery remain — without the single-turn blind spot.

## Approach — a side-value DP

A new DP table `V` whose value is the **expected final gem value under optimal keep / reroll / finish play**.

- **State:** `(w, c, f, s, fi, si, rerolls, turns_left)` — the same effect-aware, reroll-aware state space as the existing default `GoalProbabilityTable` (effect-aware + reroll-aware mode, ~300k states). Effect identity (`fi`, `si`) is required because `change_effect` matters and `gem_value` depends on which effects are equipped.
- **Terminal:** `V[·, tl=0] = gem_value(state)`.
- **Backward induction**, each turn — a max over the three real actions:

  ```
  V[s, r, tl] = max(
      gem_value(s),                                  # finish now
      Σ_offers p_o · V[apply(s, o), r', tl-1],        # process (single-draw approx — same model as the existing DP)
      V[s, r-1, tl]            (if r > 0 and turn > 1) # reroll
  )
  ```

  `change_effect` offers route probabilistically across the two non-equipped pool members, exactly as the existing effect-aware DP already does.

- **Decision** at a goal-met turn: rerolls are free and gem supply is the bottleneck, so the decision **never finishes while a reroll remains** — it rerolls (or processes offers that already beat a redraw) until rerolls run out, then finishes iff `gem_value(current) >= process EV + endgame_risk`. `process EV` averages the table's `V` over the 4 *actual* visible offers (mirroring how `GoalProbabilityTable.expected_prob_after_click` values a click); the redraw value is `V[state, turns_left]`. See the Integration sketch.

This scales with `turns_left` for free: many turns left → `V` is high (lots of recovery) → continue; one turn left → `V` collapses to this turn's EV → it reproduces today's last-turn logic exactly. **It subsumes and generalizes `_ev_cell`** — the single-turn classifier and its last-turn-only gate are replaced by the `V`-comparison at every turn.

## `gem_value(state)` — additive side coefficient + tier weight

```
gem_value(state) =
    side_coeff(state)                      # Σ level × effect coeff over target effects
  + tier_bonus(state.total_points())

tier_bonus(pts) = ANCIENT_COEFF  if pts >= 19   (ancient)
                  RELIC_COEFF    if pts >= 16   (relic+)
                  0              otherwise
```

`side_coeff` is the existing `--min-side-coeff` measure (Σ level × effect coefficient over the `--optimize` target effects). `tier_bonus` is a step function of total points keyed on the two grade cliffs.

Two CLI knobs set the tier weights:

- `--relic-coeff N` — the coefficient-equivalent worth of holding the relic+ grade (total points ≥ 16).
- `--ancient-coeff N` — the coefficient-equivalent worth of holding the ancient grade (total points ≥ 19).

Both default to `0`. At the defaults `gem_value` collapses to `side_coeff`, so the side-value DP behaves identically to a coefficient-only finish — the same as today's default (no tier chasing). The knobs are opt-in. Expectation: `--ancient-coeff >= --relic-coeff` (ancient is the higher grade); the build documents this and may clamp.

### Why additive, not a floor / `max`

A `max(side_coeff, tier_floor)` model — "an ancient gem is worth *at least* X" — was considered and rejected. Once a gem is already ancient with sub-floor coefficient, every coefficient gain below the floor becomes invisible to the DP, so it would treat a low-coefficient ancient gem as finished even with safe coefficient offers on the table.

The additive model keeps `side_coeff` in `gem_value` everywhere, so:

- coefficient gains always count, including on an already-ancient gem;
- the grade is a value the gem can **lose** — dropping 19 → 18 costs `ANCIENT_COEFF − RELIC_COEFF`, which the DP prices and avoids;
- the finish/process/reroll choice is a single expected-value comparison: a coefficient-chasing turn is taken iff `E[coeff gain] > P(lose tier) × tier weight`. "Pursue safe gains, decline risky ones" is not coded — it emerges from the DP's backward induction.

The knob is a **weight**, not a literal coefficient crossover. The point where behaviour flips between tier-chasing and coefficient-chasing emerges from the DP and depends on both the weight and the gem's offer structure — correctly distinguishing "one point from ancient with strong offers" from "four points away with weak offers."

Worked check — early ancient, `side_coeff 3600`, `--ancient-coeff 8000`, `--relic-coeff 3000` → `gem_value = 11600`:

- a `second+1` (+400 coeff, → 20 pts, stays ancient): process → 12000 > 11600 → **continue**;
- a forced set with a 25% `will-1` (→ 18 pts, loses ancient): `E ≈ 0.75·11600 + 0.25·(3600+3000) = 10350 < 11600` → **finish to lock the grade**.

## Relationship to the existing DPs and the relic machinery

`GoalProbabilityTable` computes `P(goal)` and stays the driver for reroll-for-goal, reset, and infeasibility. The side-value DP is a parallel table consulted only once the goal is met (the same `_goal_fully_satisfied` gate as `_ev_cell` today). It does not change any not-yet-met-goal behaviour.

`--relic-coeff` folds relic+ value into that one DP, so **`--relic-no-early-finish` is retired** — its job (keep cutting for 16+ points when the primary goal is met) is now done value-consistently inside the DP rather than by a binary finish veto. `_relic_chase_active` (the EV-gated-finish helper that narrowed that veto below 16 points) is removed with it.

Kept:

- `--relic-reroll-threshold` — re-enables the extra reroll **ticket** mid-run; that is a ticket-spend policy, orthogonal to the finish value, and stays unchanged.
- The relic DP table (`LastTurnGoal(min_total=16)`) — kept for *display* of `P(relic+)` in `sim` / `live` / `auto` / `stats`. A companion `P(ancient)` (`min_total=19`) display is added.

## Integration sketch

- `DecisionContext` gains a `side_value_table` (effect-aware, per gem type — cached like the existing `_ea_table_cache`), the `relic_coeff` / `ancient_coeff` knobs, and a float `endgame_risk`.
- `_ev_cell`, `_relic_chase_active`, and both early-finish call sites (`_legacy_early_finish_decision`, `_confirm_finish_decision`) are replaced by one `_side_value_finish_decision`. It computes `finish_val` and `continue_val` (above) from the side-value table and the visible offers.
- **Gate off** (`--confirm-min-coeff` unset): rerolls are free and gem supply — not gold — is the bottleneck, so the decision **never finishes while a reroll remains** (`rerolls > 0`, not turn 1). It spends every leftover reroll fishing for better offers, processing the offers in hand only when they already beat a redraw. Once rerolls are exhausted it finishes iff `finish_val >= process_ev + endgame_risk`. `--endgame-risk N` (float, default `0`) is the unattended risk margin on that final comparison — `0` finishes as soon as processing cannot beat stopping; a large `N` keeps processing to the last turn.
- **Gate on** (`--confirm-min-coeff` set): `--confirm-min-coeff N` both activates the confirmation gate and is its only knob. On a goal-met gem whose side coefficient ≥ `N`, every turn `_side_value_finish_decision` would FINISH is surfaced as an F1–F4 prompt (finish / keep cutting / reroll / reset) instead of finishing silently; the player accepts or overrides to gamble. Below the floor the DP decision runs silently. `--endgame-risk` has no effect when the gate is on.
- **Retired:** `--early-finish-coeff`, `--relic-no-early-finish`, `--confirm-risk` — removed from the CLI, `DecisionContext`, simulator, and automation. Their roles are covered by the side-value DP, by `--relic-coeff`, and by `--confirm-min-coeff` as sole gate knob, respectively. The `early_finish=False` "risk" DP table built only for `--confirm-risk` is removed with it; gates #2/#3 (infeasibility / reset confirmation) are unaffected — they only ever used `--confirm-min-coeff`.
- `--relic-coeff` / `--ancient-coeff` are added and threaded the same way the retired flags were (`stats` / `sim` / `auto` / `live`).

## Cost / risk

- A new DP build per gem type, same state space as the existing effect-aware reroll table (~1.3 s per build per the user's log). Roughly doubles per-gem-type DP build time; cache it the same way (`--all` runs amortize it).
- Retiring `_ev_cell`, `--early-finish-coeff`, `--relic-no-early-finish`, and `--confirm-risk` changes finish-vs-continue on **every** goal-met turn, not just the last — this needs a Monte-Carlo before/after comparison (`stats` runs) to confirm it improves average gem value, moves relic+/ancient rates as intended, and does not regress main-goal success.

## Rough task outline (for the implementation plan)

1. `gem_value(state)` helper — additive `side_coeff + tier_bonus`, plus the `relic_coeff` / `ancient_coeff` plumbing.
2. The side-value DP table — terminal value `gem_value`, transitions (reuse the existing effect-aware transition machinery), backward induction with the keep/reroll/finish `max`.
3. Decision integration — one `_side_value_finish_decision` replacing `_ev_cell`, `_relic_chase_active`, `_legacy_early_finish_decision`, and `_confirm_finish_decision`; gate-off `--endgame-risk` margin; gate-on `--confirm-min-coeff` FINISH-prompt.
4. Retire `--early-finish-coeff`, `--relic-no-early-finish`, `--confirm-risk` (and the `early_finish=False` risk table); make `--endgame-risk` a float; add `--relic-coeff` / `--ancient-coeff` CLI flags; add the `P(ancient)` display.
5. `DecisionContext` + simulator + automation wiring + per-gem-type caching.
6. Monte-Carlo validation: `stats` before/after — confirm average side coefficient and relic+/ancient rates move as intended and main-goal success is not regressed.
7. Tests + docs (`CLAUDE.md`).

## Out of scope

Gold-cost modelling stays out — the simulator still does not assign a numeric gold cost to a tap (see the `gold-cost-per-tap` note). The side-value DP makes finish-vs-continue *value-optimal*; "is the marginal value worth the gold" remains a heuristic judgment, the same as today. `--relic-reroll-threshold` (ticket-spend policy) is unchanged.
