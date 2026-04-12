# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Lost Ark Astrogem cutting/fusion Monte Carlo simulator. Estimates success probabilities for achieving specific gem stat goals (e.g., min willpower 4 + min chaos 5 + boss_damage at level 5) across gem rarities, using the official in-game probability weights from Smilegate's published data.

## Running

Always activate the virtual environment before running Python:

```bash
source .venv/Scripts/activate
python -m arkgrid
```

No external dependencies for the simulator — stdlib only (`dataclasses`, `random`, `math`, `typing`). Vision features (`live`, `read`) require `opencv-python`, `numpy`, and `mss`. Automation (`auto`) additionally requires Windows (`ctypes` user32.dll). No build step, no linter configured.

## Testing

```bash
source .venv/Scripts/activate
python -m unittest discover -s tests -v

# Run a single test file
python -m unittest tests.test_models -v

# Run a single test case
python -m unittest tests.test_models.TestLastTurnGoal.test_satisfied_min -v
```

## Architecture

The `arkgrid/` package is split into modules:

- **`constants.py`** — Gem effect definitions, coefficients, priorities, gem type mappings
- **`models.py`** — `Option`, `LastTurnGoal`, `AstroGem`, `GemState`, `RunResult` (frozen/mutable dataclasses)
- **`pool.py`** — `OptionPool` — Builds the 27-entry weighted probability pool matching official rates; filters eligible options per turn based on current state and turn constraints (view excluded on turn 1 & last turn, cost excluded on last turn); draws 4 unique offers via weighted sampling without replacement
- **`probability.py`** — `GoalProbabilityTable` — Precomputed DP table with four modes: standard (state = will, chaos, first, second, turns_left), reroll-aware (state adds reroll count), BIS-aware (state adds first_is_target/second_is_target booleans), and effect-aware (state adds first_idx/second_idx indices into `GEM_TYPES[gem_type]`). Two transition modes: single-draw approximation (option prob = weight/total, ~20ms build) and exact 4-draw-pick-1 via PPSWOR inclusion probabilities (`exact_draw=True`, ~1-4s build). The reroll-aware mode (`max_rerolls > 0`) extends the DP with a per-option keep-vs-reroll decision at each state, using backward induction to find the optimal reroll timing (~50ms single-draw, ~1s exact-draw). O(1) lookup. Supports side-node goals (min_first/min_second/min_side_coeff) via extended terminal success conditions. BIS-aware mode (`bis_only=True`) extends state with (first_is_target, second_is_target); `lookup_bis_averaged()` averages over random starting effect combinations. Effect-aware mode (`effect_aware=True`, `gem_type`, `optimize`) tracks effect identity and models change_first/second_effect as probabilistic transitions to the 2 non-equipped pool members — correctly prices min_side_coeff goals when starting effects don't contribute to the target side. Early finish mode (`early_finish=True`) sets P=1.0 for any state where the goal is already satisfied (reflecting that the player can stop). `should_reroll_dp()` compares the expected value of keeping current offers against the value of rerolling (one fewer reroll, same state).
- **`policy.py`** — `RerollPolicy` — Fallback heuristic reroll policy used in automation when the reroll-aware DP is not available. Three-mode heuristic (goal-met / comfortable / desperate) with target-aware side-node filtering (DPS vs support). Uses DP probability when available, binary feasibility fraction otherwise. The simulator's primary reroll path uses `GoalProbabilityTable.should_reroll_dp()` instead.
- **`simulator.py`** — `GemSimulator` — Turn-by-turn simulation engine. Manages rarity config (common=5 turns, rare=7, epic=9), reroll budgets (0/1/2 base + extra ticket), reset ticket (one full restart if goal becomes infeasible or probability drops below threshold), early finish (stop when goal is met if risk outweighs side gains), and feasibility guards before each click. Builds two DP tables: a reroll-aware table (for optimal reroll timing) and a standard table (for accurate reset decisions — the reroll-aware DP overestimates fresh-start probability due to the per-option max approximation). Optionally builds a relic+ DP table (`LastTurnGoal(min_total=16)`) for relic+ probability tracking and decision overrides (`--relic-no-early-finish`, `--relic-reroll-threshold`). When `effect_aware=True`, builds per-gem-type effect-aware DP tables lazily (cached in `_ea_table_cache` / `_ea_reset_table_cache`) and swaps them in at `simulate_one` start — one table per gem type covers all effect configs, so `--all` and random-gem stats amortize the build across trials.
- **`automation.py`** — `run_auto()` — Full automation loop for the `auto` command: capture screen → detect state → decide (reroll/process/reset/finish) → click button → wait for animation → repeat. Windows-only (`ctypes` user32.dll for mouse clicks, focus check, Escape stop key). Uses DP-optimal reroll decisions via `GoalProbabilityTable.should_reroll_dp()`. Auto-detects gem type/effects from screen. Handles ticket confirmation dialogs and coordinate scaling for non-1080p monitors. `_build_prob_table()` maintains a module-level `_DP_CACHE` keyed on (goal, turns, gem_type, optimize, min_side_coeff, exact_draw, max_rerolls, early_finish) — in effect-aware mode a single cached table per gem type covers all effect configs, so `--all` mode rebuilds are eliminated for repeated gem types.
- **`analyzer.py`** — `GemAnalyzer` — Runs N trials (default 200k), aggregates success rate with Wilson confidence intervals, tracks relic+ (>=16 pts) and ancient (>=19 pts) thresholds, average side coefficient
- **`cli.py`** — CLI argument parsing and command handlers (`stats`, `sim`, `effects`, `live`, `read`, `auto`). Gem type auto-resolution from effect pairs in `_resolve_args()`.

Tests live in `tests/`, split by module (e.g. `test_pool.py`, `test_simulator.py`).

### Vision subpackage (`arkgrid/vision/`)

Requires `opencv-python`, `numpy`. Template-matching pipeline for recognizing the in-game astrogem cutting screen:

- **`recognizer.py`** — `ScreenRecognizer`: anchor-relative detection pipeline using template matching for gem type, stats, effects, options, turn/step info
- **`templates.py`** — `TemplateStore`: lazy-loading template manager with resolution scaling
- **`constants.py`** — ROI offsets relative to anchor, match thresholds, domain mappings
- **`matcher.py`** — `find_template`, `find_best_match` wrappers around `cv2.matchTemplate`
- **`capture.py`** — `grab_screen`, `load_screenshot`, `normalize_to_fhd`
- **`template_recognizer.py`** — Template-based recognizer used by `live` and `auto` commands. `detect()` returns `DetectionResult` with gem type, stats, effects, rerolls, turn/step, and 4 option cards with confidence scores. Helper functions `parse_rerolls()`, `determine_option_kind()`, `parse_delta()` for interpreting detection results.

## Key Domain Concepts

- **Gem options**: willpower, chaos, first effect, second effect — each starts at 1, caps at 5
- **Side node goals**: `--min-first`/`--min-second` (level-based) and `--min-side-coeff` (coefficient-weighted total) add side node constraints to the success condition
- **Effect coefficients**: DPS: attack_power=400, additional_damage=700, boss_damage=1000. Support: ally_damage=600, brand_power=1050, ally_attack=1500
- **Cost ratio**: -100% to +100%, only changes via cost modifier possibilities
- **Rerolls** ("View Other Options"): re-draw all 4 offers; earned from pool or extra ticket
- **Reset ticket**: one-time full state reset to initial values when goal becomes impossible mid-run
- Each turn, one of 4 randomly presented possibilities is chosen uniformly (25% each)
- **Gem type auto-resolution**: `--first-effect` + `--second-effect` auto-resolves gem type. Same-type pairs (both DPS or both support) are always unambiguous. Three cross-type pairs need `--gem-type`: attack_power+ally_damage, additional_damage+brand_power, boss_damage+ally_attack
- **DP probability**: Analytical success probability from backward induction, shown alongside MC in `stats`. The DP has two layers: a reroll-aware table (state includes reroll count, used for optimal reroll timing via `should_reroll_dp()`) and a standard table (used for reset decisions and display). Single-draw approximation (default) treats each option as drawn independently with probability proportional to weight. Exact draw (`--exact-dp`) computes true PPSWOR(4) inclusion probabilities for the 4-draw-pick-1 mechanic. The reroll-aware DP uses a per-option keep-vs-reroll max in backward induction, which slightly overestimates reroll value (treats draws as independent accept/reject rather than 4-draw-pick-1), so the standard DP is used for reset decisions to avoid inflating the fresh-start probability.
- **`--exact-dp`**: Available on `stats`, `sim`, `live`, and `auto`. On `stats` it shows both single-draw and exact-draw DP probabilities and uses exact-draw for the MC simulator's reroll/reset decisions. On `sim`, `live`, and `auto` it uses exact-draw DP for all probability displays and policy decisions.
- **`--effect-aware-dp`**: Available on `stats` and `auto`. Extends the DP state to include first/second effect indices (into `GEM_TYPES[gem_type]`) and models `change_first_effect` / `change_second_effect` as probabilistic transitions across the 2 non-equipped pool members. Correctly prices `--min-side-coeff` goals when starting effects don't contribute to the target side — standard DP reports 0% and triggers false resets; effect-aware DP prices in the change-effect rescue. On `stats` with random gems the MC simulator uses per-gem-type EA tables for its reroll/reset decisions (example lift at 20k trials, epic, `--min-side-coeff 5000`: success rate 3.12% → 5.69%, reset usage 60% → 92%). Build cost ~160ms non-reroll / ~1.3s reroll single-draw / ~2.5s reroll+exact-draw per gem type, cached thereafter. Effect-aware mode takes precedence over `--bis-only`.
- **`--trials 0`**: On `stats`, skips Monte Carlo and shows only the DP probability (instant for single-draw, ~1-4s with `--exact-dp`).
- **Early finish** (`--early-finish-coeff N`): When the goal is already satisfied, decides whether to finish early (safe) or continue for side upgrades (risky). Formula: `risk_score = best_coeff_gain * P(miss_goal)`. Finish early if `P(miss) > 0` and either no side gain or `risk_score > N`. Default 0 = always finish when goal met and any risk exists (safe). E.g. `--early-finish-coeff 750` continues for boss_damage+3 at 25% miss (3000*0.25=750 <= 750). Use -1 to disable. Integrated into DP table (P=1.0 when goal satisfied), simulator (EARLY_FINISH action), and all commands.
- **Relic+ tracking** (`--relic-no-early-finish F`, `--relic-reroll-threshold F`): A separate DP table computes P(total_points >= 16) from the current state each turn. `--relic-no-early-finish F` suppresses early finish when P(relic+) exceeds the threshold (keep playing for 16+ points even when the primary goal is met). `--relic-reroll-threshold F` re-enables the extra reroll ticket mid-run when P(relic+) from the current state crosses the threshold, overriding `--reroll-min-coeff` gating. Both default to 0.0 (disabled). P(relic+) is displayed in `sim` turn logs, `live` analysis, `auto` turn headers, and `stats` output.
- **Forced reroll on no-progress turns** (`--force-reroll-no-progress N`): Coefficient-gated heuristic override to the DP reroll decision. When the gem's starting target-effect coefficient is ≥ N, force a reroll on any turn where no offer progresses the goal (no positive will/chaos delta, no positive side level when that side is needed, no side-coeff gain). Bypasses the DP's marginal keep-vs-reroll calculation, which would otherwise sometimes keep no-progress offers because of pool-dilution effects on future draws. MC shows +1-2.6pp on main-goal success at a cost of 1-5pp relic+ rate. 0 = disabled. Implemented in both `GemSimulator._has_progress_offer()` (wired into `roll_offers_with_rerolls`) and `automation._has_progress_offer()` (wired into the auto reroll block); per-run active flag is set based on the detected/configured gem's coefficient sum.
- **Automation** (`auto` command): Full automation loop — captures screen via `mss`, detects state via template matching, makes decisions using DP-optimal reroll timing + heuristic fallbacks, clicks buttons via `ctypes` user32.dll. Windows-only. Button positions at 1920x1080: Reset(962,255), Process(1068,765), Reroll(1254,595), Finish(831,764), Ticket confirm(906,666). Auto-detects gem type and effects from screen. `--dry-run` for testing without clicks. `--animation-delay` controls wait between actions (default 1.0s). Escape key stops automation. Pauses when Lost Ark loses focus. Tracks rerolls internally (OCR on new turns, decremented on rerolls) to handle view+N option picks.
- **Ticket confirmation**: Using reset or extra reroll tickets triggers a confirmation dialog in-game. The automation clicks the confirm button at (906,666) after a 0.5s delay. Tickets are gated by `--reset-min-coeff` and `--reroll-min-coeff` — disabled if starting effect coefficients are below threshold. The relic+ reroll override (`--relic-reroll-threshold`) can re-enable the extra reroll ticket mid-run when P(relic+ >=16) from the current state exceeds the threshold.

## Reference

`documentation/official_probability_info_en.md` contains the full English translation of Smilegate's official probability disclosure for gem cutting and fusion mechanics.
