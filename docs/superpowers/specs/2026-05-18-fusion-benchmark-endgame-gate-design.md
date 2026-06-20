# Fusion-derived tier value + endgame-risk grade gate (design)

> **Status:** design doc — resolved. `tier_bonus` is kept; its value is now
> auto-derived from the fusion mechanic instead of a manual knob. Ready to
> turn into an implementation plan.

## Problem

`--relic-coeff` / `--ancient-coeff` feed an additive `tier_bonus` in the
side-value DP's `gem_value` (`gem_value = side_coeff + tier_bonus`). Their
values were arbitrary player guesses defaulting to `0`, so out of the box the
DP gave grade no weight at all.

Investigation of `documentation/official_probability_info_en.md` (Gem Fusion:
Processed Gems) showed the fusion mechanic lets us compute an *average gem of
each grade* exactly — so the tier value need not be guessed; it can be
derived from the gem type.

## What the fusion doc gives us

**Gem Points (Processed Fusion)** — points distribution conditioned on the
*result grade* (recipe-independent; the doc states points are determined by
grade, not recipe):

- Legendary: 4–15 pts, `E[points] = 9.62`
- Relic: 16 (80%), 17 (15%), 18 (5%) → `E[points] = 16.25`
- Ancient: 19 (95%), 20 (5%) → `E[points] = 19.05`

**Gem Point Distribution** — 1 point to each of the 4 options, the rest spread
uniformly; by exchangeability each option averages `E[points]/4` regardless of
the cap-at-5 rule.

**Gem Effect Determination** — 2 effects drawn uniformly from the gem type's
4-effect pool; each pool member is "the first effect" with probability 1/4.

Closed form for the average gem's side coefficient:

```
fusion_avg_coeff(gem_type, optimize, grade)
    = (sum of optimize-side coeffs in the 4-effect pool) * E[points|grade] / 8
```

This is **per gem-type-pair** (order/chaos pairs share an effect pool) and per
optimize side:

| Pool (DPS) | relic | ancient | Pool (Support) | relic | ancient |
|---|---|---|---|---|---|
| stability·erosion (1100) | 2234 | 2619 | (1650) | 3352 | 3929 |
| fortitude·distortion (1400) | 2844 | 3334 | (2100) | 4266 | 5001 |
| immutability·collapse (1700) | 3453 | 4048 | (2550) | 5180 | 6072 |

**Recipe note (context only, not wired in):** points are conditioned on
result grade, so the fusion *recipe* does not change these numbers. The
relic→ancient conversion is a fixed **37.5 relics per ancient** independent of
free-legendary filler — "3 relic" and "3×(2 legendary + 1 relic)" are
economically identical. No recipe assumption enters this design.

## Design

### 1. `tier_bonus` is kept; its value is auto-derived

`gem_value = side_coeff + tier_bonus(total_points)` is unchanged.
`tier_bonus` is still `ancient_coeff` at ≥19 points, `relic_coeff` at 16–18,
`0` below. What changes is where `relic_coeff` / `ancient_coeff` come from:

- **Default**: `fusion_avg_coeff(gem_type, optimize, grade)` — resolved from
  the run's gem type + optimize side (the table above; *computed* from
  `pool_sum * E[points|grade] / 8`, not hard-coded).
- **Override**: `--relic-coeff N` / `--ancient-coeff N` are kept — a player
  who no longer values, say, relic-grade gems can still set them by hand.
  Passing the flag overrides the fusion default.

A fusion-magnitude `tier_bonus` (≈ the gem's own `side_coeff` scale) is a
deliberately *strong* grade pull: both `finish_val` and `process_ev` include
it, so an offer that risks dropping a grade tank `process_ev` and the DP
avoids it. That strong grade protection is what makes the gate in §3 behave
as intended. There is no double-count — `tier_bonus` is a grade-band constant;
it shifts cross-grade and cliff comparisons, never within-grade ones.

### 2. Resolution per gem type

`relic_coeff` / `ancient_coeff` resolve per gem type, exactly where
`SideValueTable` is already built and cached per gem type (`--all` and
random-gem runs amortise it). When no gem type is known the side-value table
self-disables already, so no fusion default is needed there. An explicit
`--relic-coeff` / `--ancient-coeff` is a flat override across all gem types.

### 3. Endgame-risk grade gate

`decision._side_value_finish_decision`'s no-reroll branch (the "never finish
while a free reroll remains" rule is unchanged — this only affects play once
rerolls are exhausted) gains a benchmark gate:

- **`--endgame-risk` passed by the player** → today's behaviour exactly:
  `finish iff finish_val >= process_ev + endgame_risk`. No gating — the
  player has taken manual control of the risk margin.
- **`--endgame-risk` omitted** → gate by the gem's grade
  (`state.total_points()` → relic 16–18, ancient ≥19) and its current side
  coefficient (`_side_coeff(ctx, state)`):
  - grade ∈ {relic, ancient} and **`side_coeff < relic_coeff`/`ancient_coeff`
    for that grade** → **FINISH**. A below-average gem protects its grade
    instead of chasing more coefficient — declining even a +EV offer is
    intended; that is the point of the gate.
  - otherwise (at/above the benchmark, or legendary grade — no grade to
    protect) → margin `0`, EV-optimal (`finish iff finish_val >= process_ev`),
    i.e. continue chasing coefficient/grade upside as today.

The benchmark and the `tier_bonus` value are the **same numbers**
(`relic_coeff` / `ancient_coeff`) — "the average coefficient of a relic /
ancient gem of this type" serves both roles.

The confirmation gate (`--confirm-min-coeff`) is unchanged: it still forces
margin `0`, and a gate-driven FINISH on a gem above the side-coeff floor still
surfaces the F1–F4 prompt.

## Integration points

- `arkgrid/constants.py` — fusion point-distribution constants
  (`E[points|grade]`) and a `fusion_avg_coeff(gem_type, optimize, grade)`
  helper.
- `arkgrid/probability.py` — `SideValueTable` keeps `relic_coeff` /
  `ancient_coeff` and `_tier_bonus` unchanged; only the *values* passed in
  change (callers resolve the fusion default).
- `arkgrid/decision.py` — `DecisionContext` gains the resolved
  `relic_coeff` / `ancient_coeff` (for the gate) and an
  `endgame_risk_user_set` flag (or `endgame_risk: Optional[float]`);
  `_side_value_finish_decision`'s no-reroll branch implements §3.
- `arkgrid/cli.py` — `--relic-coeff` / `--ancient-coeff` default to a `None`
  sentinel ("use fusion default"); `--endgame-risk` defaults to `None`
  ("auto-gate"); `--help` rewritten; resolution wired in once the gem type is
  known. `stats` config display updated to show the resolved values.
- `arkgrid/simulator.py`, `arkgrid/automation.py` — resolve the fusion
  defaults per gem type, thread the resolved values + `endgame_risk_user_set`.
- `arkgrid/log_analyzer.py` — config fields unchanged; semantics note updated.

## Validation

`tier_bonus` defaulting to a non-zero fusion value changes finish-vs-continue
on every goal-met turn, so a Monte-Carlo before/after (`stats` runs) is needed
to confirm average side coefficient and relic+/ancient rates move as intended
and main-goal success does not regress.

## Out of scope

- Gold-cost modelling stays out (see the `value-model-no-gold` note).
- `--relic-reroll-threshold` (ticket-spend policy) and the relic/ancient
  `P(>=N)` display DPs are unchanged.
- The 37.5:1 relic→ancient scarcity ratio is documented above as context only.
