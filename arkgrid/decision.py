"""Shared per-turn decision logic for both the simulator and the
automation loop.

Both `arkgrid.simulator.GemSimulator.simulate_one` and
`arkgrid.automation.run_auto` need to make the same kind of per-turn
choice given (state, visible offers, turns_left, rerolls, available
tickets, DP tables, knobs): process / reroll / reset / finish.

Keeping that logic in one place means a bug in the decision tree
shows up in MC simulations as well as live runs, instead of only being
caught after a real Lost Ark gem is wasted.

The module is split into:

* `DecisionContext` / `TurnInput` / `TurnMetrics` — pure data containers.
* `compute_post_roll_metrics` — the one expensive computation, run
  once per turn so branch helpers don't redo the offer loop.
* Branch helpers (`early_finish_decision`, `infeasibility_decision`, ...)
  — each returns a `Decision` if it applies, or `None` to defer.
* `decide_post_roll` — the full Branch 0–6 tree, used by automation
  every frame and by the simulator after the reroll loop.
* `decide_reroll_only` — the narrow tree used inside the simulator's
  reroll loop. Returns REROLL or PROCESS only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, SUPPORT_COEFF, SUPPORT_EFFECTS,
    change_dest_max_coeff,
)
from arkgrid.models import GemState, LastTurnGoal, Option
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable, SideValueTable


# ---------------------------------------------------------------------------
# Action / decision types
# ---------------------------------------------------------------------------


class ActionKind(str, Enum):
    PROCESS = "process"   # apply one of the visible offers
    REROLL = "reroll"     # spend a reroll, redraw offers
    RESET = "reset"       # spend the reset ticket, restart from turn 1
    FINISH = "finish"     # stop early — either goal+relic+ unreachable, or early-finish
    FAIL = "fail"         # simulator-only: no path to goal, no reset; auto maps to FINISH


@dataclass(frozen=True)
class Decision:
    action: ActionKind
    branch: str
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    needs_confirmation: bool = False
    confirm_choices: tuple = ()


# ---------------------------------------------------------------------------
# Context built once per run / per turn
# ---------------------------------------------------------------------------


@dataclass
class DecisionContext:
    """Per-run context. Built once when DP tables are ready and rebuilt
    only when something the tables depend on changes (e.g. effect-aware
    table swap mid-run).
    """
    goal: LastTurnGoal
    pool: OptionPool
    optimize: str                                  # "dps" | "support"
    bis_only: bool
    min_side_coeff: int
    prob_reset_threshold: float
    relic_reroll_threshold: float
    force_reroll_no_progress: int
    turns_total: int
    base_rerolls: int
    p_fresh: float
    prob_table: GoalProbabilityTable               # reroll-aware goal table
    reset_prob_table: GoalProbabilityTable         # standard goal table for reset
    relic_prob_table: Optional[GoalProbabilityTable]
    gem_type: str
    force_reroll_active: bool                      # gated by starting coeff
    confirm_active: bool = False
    confirm_min_coeff: int = 0
    # None => auto-gate (grade-protect a below-benchmark relic/ancient gem);
    # a float is an explicit player-set finish margin.
    endgame_risk: Optional[float] = None
    side_value_table: Optional[SideValueTable] = None
    # Goal-independent value table (`side_coeff + grade tier bonus`, built
    # with a trivial always-satisfied goal). Consulted only on dead-goal
    # turns, where the goal-conditioned `side_value_table` would zero every
    # state. None unless relic/ancient grade is assigned a coefficient.
    grade_value_table: Optional[SideValueTable] = None
    # Side-mode value oracle (`side_coeff + tier_bonus`) consulted only at
    # the will/chaos cap under --ignore-side-node-values, where the
    # `will_chaos` `side_value_table` is degenerate (every state scores 10).
    # Its presence is the flag signal — None unless the flag is set.
    maxed_value_table: Optional[SideValueTable] = None
    # --- Reroll-ticket per-turn enable gate (see `ticket_enabled`) ---
    # The reroll ticket is re-evaluated every turn (never
    # banked): it is usable this turn if ANY enabler clears its bar. These
    # carry the enablers' tables/thresholds so the gate is a pure function of
    # the context. `extra_ticket_force_on` is `--extra-ticket` (always on).
    extra_ticket_force_on: bool = False
    reroll_goal_prob_table: Optional[GoalProbabilityTable] = None
    reroll_goal_threshold: float = 0.0
    reroll_min_coeff: int = 0
    # Goal-conditioned expected side-coefficient table (relic/ancient coeff 0,
    # so value == E[side_coeff]); ~0 when the goal is unreachable, which is why
    # the coeff enabler "requires the goal" for free.
    expected_coeff_table: Optional[SideValueTable] = None


@dataclass
class TurnInput:
    """Per-turn inputs. Built fresh at the call site each turn."""
    state: GemState
    offers: List[Option]
    turn: int                                      # 1-indexed
    turns_left: int
    rerolls: int                                   # caller-managed count
    reset_available: bool


# ---------------------------------------------------------------------------
# has_progress_offer (used by force-reroll-no-progress)
# ---------------------------------------------------------------------------


def has_progress_offer(
    offers: List[Option],
    state: GemState,
    goal: LastTurnGoal,
    min_side_coeff: int,
    side_coeff_first: int,
    side_coeff_second: int,
) -> bool:
    """Return True if any offer progresses an unmet goal constraint.

    Used by the `--force-reroll-no-progress` heuristic to override the
    DP's marginal keep-vs-reroll decision when a turn has no offer that
    moves the goal forward at all.
    """
    need_total = goal.min_total is not None and (
        state.will + state.chaos + state.first + state.second) < goal.min_total
    need_wc_total = goal.min_total_will_chaos is not None and (
        state.will + state.chaos) < goal.min_total_will_chaos
    need_will = goal.min_will is not None and state.will < goal.min_will
    need_chaos = goal.min_chaos is not None and state.chaos < goal.min_chaos
    need_first = goal.min_first is not None and state.first < goal.min_first
    need_second = goal.min_second is not None and state.second < goal.min_second
    need_coeff_first = (min_side_coeff > 0 and side_coeff_first > 0
                        and state.first < 5)
    need_coeff_second = (min_side_coeff > 0 and side_coeff_second > 0
                         and state.second < 5)

    for o in offers:
        # change_first/second_effect has delta == 0 and must be checked before
        # the delta guard below.  When min_side_coeff is active and the current
        # effect for a slot contributes nothing (side_coeff_* == 0), any change
        # to that effect is potentially positive for the side-coeff goal — it is
        # the rescue move and should count as progress.
        if o.key == "change_first_effect" and min_side_coeff > 0 and side_coeff_first == 0:
            return True
        if o.key == "change_second_effect" and min_side_coeff > 0 and side_coeff_second == 0:
            return True
        if o.delta <= 0:
            continue
        if o.kind == "will" and (need_will or need_wc_total or need_total):
            return True
        if o.kind == "chaos" and (need_chaos or need_wc_total or need_total):
            return True
        if o.kind == "first" and (need_first or need_coeff_first or need_total):
            return True
        if o.kind == "second" and (need_second or need_coeff_second or need_total):
            return True
    return False


# ---------------------------------------------------------------------------
# Reroll-ticket per-turn enable gate
# ---------------------------------------------------------------------------


def ticket_enabled(
    ctx: DecisionContext, state: GemState, turns_left: int, free_rerolls: int,
) -> bool:
    """Whether the reroll ticket may be used THIS turn.

    Re-evaluated every turn (the ticket is never banked). Usable if ANY enabler
    clears its bar — OR'd together — each looking ahead as if the ticket were in
    hand (`free_rerolls + 1`), except the coefficient enabler, whose table is
    reroll-independent:

    * ``--extra-ticket``           → always (force-on, unconditional +1).
    * ``--reroll-min-coeff N``     → expected side-coefficient ≥ N. The table is
      goal-conditioned, so it reads ~0 once the goal is unreachable — a dead
      gem's side coefficient is worthless, so the ticket disables itself.
    * ``--relic-reroll-threshold F`` → P(relic+) with the ticket ≥ F. Grade is
      valuable regardless of the goal, so this is goal-independent.
    * ``--reroll-goal N``/``--reroll-goal-threshold F`` → P(will+chaos ≥ N) with
      the ticket ≥ F.

    Free rerolls are unaffected by this gate — they are always free to spend; it
    governs only the reroll ticket.
    """
    if ctx.extra_ticket_force_on:
        return True
    if (ctx.reroll_min_coeff > 0 and ctx.expected_coeff_table is not None
            and ctx.expected_coeff_table.lookup(state, turns_left)
            >= ctx.reroll_min_coeff):
        return True
    look_ahead = free_rerolls + 1  # P "as if the ticket were used"
    if (ctx.relic_reroll_threshold > 0 and ctx.relic_prob_table is not None
            and ctx.relic_prob_table.lookup(state, turns_left, rerolls=look_ahead)
            >= ctx.relic_reroll_threshold):
        return True
    if (ctx.reroll_goal_threshold > 0 and ctx.reroll_goal_prob_table is not None
            and ctx.reroll_goal_prob_table.lookup(
                state, turns_left, rerolls=look_ahead)
            >= ctx.reroll_goal_threshold):
        return True
    return False


# ---------------------------------------------------------------------------
# Metrics: computed once per turn, fed to all branch helpers
# ---------------------------------------------------------------------------


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


def _apply_option_for_metrics(state: GemState, opt: Option) -> GemState:
    """Apply an option to a cloned state for metrics purposes.

    Mirrors `GemSimulator.apply_option` but doesn't take an RNG:
    `change_*_effect` options use `opt.resolved_effect` if the caller
    pre-resolved them (simulator), otherwise leave the effect unchanged
    (automation, where the destination is only known after clicking).
    """
    s = state.clone()
    if opt.kind == "will":
        s.will = min(5, max(1, s.will + opt.delta))
    elif opt.kind == "chaos":
        s.chaos = min(5, max(1, s.chaos + opt.delta))
    elif opt.kind == "first":
        s.first = min(5, max(1, s.first + opt.delta))
    elif opt.kind == "second":
        s.second = min(5, max(1, s.second + opt.delta))
    elif opt.kind == "view":
        s.rerolls = max(0, s.rerolls + opt.delta)
    elif opt.kind == "cost":
        if opt.key == "cost+100":
            s.cost_ratio = min(100, s.cost_ratio + 100)
        elif opt.key == "cost-100":
            s.cost_ratio = max(-100, s.cost_ratio - 100)
    elif opt.key == "change_first_effect" and opt.resolved_effect:
        s.first_effect = opt.resolved_effect
    elif opt.key == "change_second_effect" and opt.resolved_effect:
        s.second_effect = opt.resolved_effect
    return s


def _goal_fully_satisfied(ctx: DecisionContext, state: GemState) -> bool:
    """Check goal + bis_only + min_side_coeff all together.

    Mirrors `GemSimulator._goal_fully_satisfied`. Used for early-finish
    `miss_count` so the simulator's tighter check carries over to
    automation as well (latent divergence #3 — automation Branch 0
    previously checked only `goal.satisfied`).
    """
    if not ctx.goal.satisfied(state.will, state.chaos,
                              state.first, state.second):
        return False
    if ctx.bis_only:
        target = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
        if (state.first_effect not in target
                or state.second_effect not in target):
            return False
    if ctx.min_side_coeff > 0:
        coeff = DPS_COEFF if ctx.optimize == "dps" else SUPPORT_COEFF
        target = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
        coeff_total = 0
        if state.first_effect in target:
            coeff_total += state.first * coeff[state.first_effect]
        if state.second_effect in target:
            coeff_total += state.second * coeff[state.second_effect]
        if coeff_total < ctx.min_side_coeff:
            return False
    return True


def _side_coeff(ctx: DecisionContext, state: GemState) -> int:
    """Coefficient-weighted total of the gem's two side nodes.

    Mirrors the `--min-side-coeff` measure: sum of level * effect
    coefficient for side effects in the optimize target set. Effects
    outside the target set contribute 0.
    """
    coeff_map = DPS_COEFF if ctx.optimize == "dps" else SUPPORT_COEFF
    target = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
    total = 0
    if state.first_effect in target:
        total += state.first * coeff_map.get(state.first_effect, 0)
    if state.second_effect in target:
        total += state.second * coeff_map.get(state.second_effect, 0)
    return total


def _hand_is_wc_safe(offers: List[Option]) -> bool:
    """True when no offer can reduce will or chaos.

    `Process` applies a uniformly random one of the 4 offers, so a hand
    that contains any `will-`/`chaos-` offer carries a real risk of
    dropping off the will/chaos cap. `_maxed_hold_decision` never processes
    such a hand.
    """
    return not any(o.kind in ("will", "chaos") and o.delta < 0
                   for o in offers)


def _legal_actions(ti: TurnInput) -> tuple:
    """Actions the player may legally take this turn — the confirmation
    menu. Fixed order: finish, process, reroll, reset.
    """
    choices = [ActionKind.FINISH, ActionKind.PROCESS]
    if ti.rerolls > 0:
        choices.append(ActionKind.REROLL)
    if ti.reset_available:
        choices.append(ActionKind.RESET)
    return tuple(choices)


def _maybe_confirm(ctx: DecisionContext, ti: TurnInput,
                   decision: Decision) -> Decision:
    """Stamp `needs_confirmation` on a reset / infeasibility decision
    when `--confirm-risk` is active and the gem's side coefficient meets
    the floor. Returns the decision unchanged otherwise.
    """
    if not ctx.confirm_active:
        return decision
    if _side_coeff(ctx, ti.state) < ctx.confirm_min_coeff:
        return decision
    return replace(decision, needs_confirmation=True,
                   confirm_choices=_legal_actions(ti))


def compute_post_roll_metrics(ctx: DecisionContext, ti: TurnInput) -> TurnMetrics:
    """Compute every probability and aggregate a branch helper might need.

    Costs ~4-8 DP lookups + a small per-offer loop — negligible vs the
    DP table build itself. Done once per turn so helpers don't repeat
    the work.
    """
    if not ti.offers:
        return TurnMetrics(0.0, 0.0, 0.0, 0.0, 0)

    tla = ti.turns_left - 1   # turns_left after this click

    p_keep_goal = ctx.prob_table.expected_prob_after_click(
        ti.state, ti.offers, tla, rerolls=ti.rerolls)
    p_keep_goal_reset = ctx.reset_prob_table.expected_prob_after_click(
        ti.state, ti.offers, tla)

    if ctx.relic_prob_table is not None:
        p_keep_relic = ctx.relic_prob_table.expected_prob_after_click(
            ti.state, ti.offers, tla, rerolls=ti.rerolls)
        can_reroll = ti.rerolls > 0 and ti.turn != 1
        p_reroll_relic = (ctx.relic_prob_table.lookup(
            ti.state, ti.turns_left, rerolls=ti.rerolls - 1)
            if can_reroll else 0.0)
    else:
        p_keep_relic = 0.0
        p_reroll_relic = 0.0

    # Per-offer post-click feasibility under the goal DP.
    max_r = ctx.prob_table._max_rerolls

    feasible_count = 0

    for o in ti.offers:
        ns = _apply_option_for_metrics(ti.state, o)
        view_delta = o.delta if o.kind == "view" else 0
        nr = (min(max_r, ti.rerolls + view_delta)
              if max_r > 0 else ti.rerolls)
        if ctx.prob_table.lookup(ns, tla, rerolls=nr) > 0:
            feasible_count += 1

    return TurnMetrics(
        p_keep_goal=p_keep_goal,
        p_keep_goal_reset=p_keep_goal_reset,
        p_keep_relic=p_keep_relic,
        p_reroll_relic=p_reroll_relic,
        feasible_count=feasible_count,
    )


# ---------------------------------------------------------------------------
# Branch 0: early-finish (goal already satisfied)
# ---------------------------------------------------------------------------


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
        ti.state, ti.offers, ti.turns_left - 1, rerolls=ti.rerolls)
    hand_safe = _hand_is_wc_safe(ti.offers)
    can_reroll = ti.rerolls > 0 and ti.turn != 1
    metrics = {"finish_val": finish_val, "process_ev": process_ev,
               "hand_safe": hand_safe}

    if can_reroll:
        reroll_val = oracle.lookup(ti.state, ti.turns_left, rerolls=ti.rerolls - 1)
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


def _side_value_finish_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Turns-aware finish-vs-continue using the side-value DP.

    `finish_val` is the value of stopping now; `process_ev` is the value
    of taking the 4 offers in hand; `reroll_val` is the value of redrawing
    (the side-value table's optimal-play value, always >= `finish_val`).

    Rerolls are free and gem supply — not gold — is the bottleneck, so the
    decision **never finishes while a reroll remains**: it spends every
    leftover reroll fishing for better offers, and processes the hand only
    when those offers already beat a redraw. Finishing happens only once
    rerolls are exhausted (or on turn 1, where rerolling is disallowed),
    when `finish_val` beats `process_ev` by the `--endgame-risk` margin.

    Exception: when `--endgame-risk` is omitted (auto-gate), a relic or
    ancient gem whose side coefficient is below the grade benchmark
    (`svt.relic_coeff` / `svt.ancient_coeff` — the fusion-derived average
    coefficient for that grade) is always finished regardless of EV, to
    protect the grade.

    Gate on (`--confirm-min-coeff` set): a finish on a gem above the
    side-coefficient floor is surfaced as an F1-F4 prompt.
    """
    # At the will/chaos cap under --ignore-side-node-values the will_chaos
    # side-value table is degenerate (every state scores 10). Delegate to the
    # side-mode maxed oracle, which chases side+grade while holding the cap.
    if (ctx.maxed_value_table is not None
            and ti.state.will == 5 and ti.state.chaos == 5):
        return _maxed_hold_decision(ctx, ti)

    svt = ctx.side_value_table
    if svt is None or not svt.enabled:
        return None

    finish_val = svt.gem_value(ti.state)
    process_ev = svt.expected_value_after_click(
        ti.state, ti.offers, ti.turns_left - 1, rerolls=ti.rerolls)
    can_reroll = ti.rerolls > 0 and ti.turn != 1

    if can_reroll:
        # Never finish with a free reroll in hand: `lookup()` (optimal-play
        # value) is always >= `finish_val`, so a redraw is never worse than
        # stopping. Reroll unless the offers in hand already beat a redraw.
        reroll_val = svt.lookup(ti.state, ti.turns_left, rerolls=ti.rerolls - 1)
        metrics = {"finish_val": finish_val, "process_ev": process_ev,
                   "reroll_val": reroll_val}
        if reroll_val >= process_ev:
            return Decision(
                action=ActionKind.REROLL, branch="side_value_finish",
                reason=(f"goal met, spending a free reroll: "
                        f"reroll_val={reroll_val:.0f} >= "
                        f"process_ev={process_ev:.0f}"),
                metrics=metrics,
            )
        return None  # PROCESS — the offers in hand beat a redraw

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


# ---------------------------------------------------------------------------
# Branch 1 / 3 helpers: goal infeasibility + no feasible offer
# ---------------------------------------------------------------------------


def _feasibility_args(ctx: DecisionContext, state: GemState) -> Dict[str, Any]:
    """Build kwargs for `LastTurnGoal.feasible()` reflecting the current
    state's effects (which may differ from the gem's starting effects).
    """
    if ctx.min_side_coeff <= 0:
        return {}
    coeff_map = DPS_COEFF if ctx.optimize == "dps" else SUPPORT_COEFF
    return {
        "min_side_coeff": ctx.min_side_coeff,
        "side_coeff_first": coeff_map.get(state.first_effect, 0),
        "side_coeff_second": coeff_map.get(state.second_effect, 0),
        "change_dest_max_coeff": change_dest_max_coeff(
            ctx.gem_type, state.first_effect,
            state.second_effect, ctx.optimize),
    }


# Float slack for "the optimal continuation can't beat finishing" — the DP
# value floors at `finish_val`, so a near-equal value means no upside.
_GRADE_VALUE_EPS = 1e-9


def _grade_value_decision(
    ctx: DecisionContext, ti: TurnInput, gvt: SideValueTable,
    branch: str, reason: str,
) -> Decision:
    """Goal is permanently out of reach — maximise expected gem *value*
    (`side_coeff + grade tier bonus`) via the goal-independent grade-value
    table, instead of the binary `P(relic+ >= 16)` the relic table exposes.

    The binary metric scores totals 16/17/18/19 identically; this prices
    ancient (>=19) upside and point magnitude correctly.

    Mirrors `_side_value_finish_decision`, with two differences:

    * It uses `ctx.grade_value_table` (built with a trivial, always-satisfied
      goal), so a broken main goal doesn't zero every state.
    * It always returns a concrete Decision — the infeasibility branches are
      terminal and never defer back to the tree.

    Finish-early guard (the "no chance left" case): `gvt.lookup` is backward-
    induced as `max(finish_now, process)`, so it is always >= `finish_val`.
    When neither a redraw (`reroll_val`) nor the offers in hand (`process_ev`)
    can beat stopping now, there is provably no value upside left and the
    decision FINISHES — even with rerolls in hand. This is the one exception
    to "never finish with a free reroll": fishing cannot help here.
    """
    finish_val = gvt.gem_value(ti.state)
    process_ev = gvt.expected_value_after_click(
        ti.state, ti.offers, ti.turns_left - 1, rerolls=ti.rerolls)
    can_reroll = ti.rerolls > 0 and ti.turn != 1
    metrics = {"finish_val": finish_val, "process_ev": process_ev}

    if can_reroll:
        reroll_val = gvt.lookup(ti.state, ti.turns_left, rerolls=ti.rerolls - 1)
        metrics["reroll_val"] = reroll_val
        best_continue = max(reroll_val, process_ev)
        if best_continue <= finish_val + _GRADE_VALUE_EPS:
            return Decision(
                action=ActionKind.FINISH, branch=branch,
                reason=(f"{reason}, no grade upside left "
                        f"(finish_val={finish_val:.0f} >= "
                        f"continue={best_continue:.0f})"),
                metrics=metrics,
            )
        if reroll_val >= process_ev:
            return Decision(
                action=ActionKind.REROLL, branch=branch,
                reason=(f"{reason}, chasing gem value "
                        f"(reroll_val={reroll_val:.0f} >= "
                        f"process_ev={process_ev:.0f})"),
                metrics=metrics,
            )
        return Decision(
            action=ActionKind.PROCESS, branch=branch,
            reason=(f"{reason}, processing for gem value "
                    f"(process_ev={process_ev:.0f} > "
                    f"reroll_val={reroll_val:.0f})"),
            metrics=metrics,
        )

    # No reroll (exhausted, or turn 1): finish vs process by value. A
    # below-grade-band offer already tanks process_ev via the lost
    # tier_bonus, so the value comparison protects the grade implicitly —
    # no separate benchmark gate is needed here.
    margin = (0.0 if (ctx.confirm_active or ctx.endgame_risk is None)
              else ctx.endgame_risk)
    metrics["margin"] = margin
    if finish_val >= process_ev + margin:
        return Decision(
            action=ActionKind.FINISH, branch=branch,
            reason=(f"{reason}, finishing for gem value "
                    f"(finish_val={finish_val:.0f} >= "
                    f"process_ev={process_ev:.0f}+margin={margin:.0f})"),
            metrics=metrics,
        )
    return Decision(
        action=ActionKind.PROCESS, branch=branch,
        reason=(f"{reason}, processing for gem value "
                f"(process_ev={process_ev:.0f} > "
                f"finish_val={finish_val:.0f})"),
        metrics=metrics,
    )


def _reset_or_chase_relic(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
    branch: str, reason: str,
) -> Decision:
    """Common tail used by both infeasibility branches.

    Tries reset → relic+ chase (process or reroll, whichever has higher
    offer-conditional P(r+)) → goal-reroll fallback → finish/fail. FAIL
    is returned only when no reset is available *and* relic+ tracking is
    disabled *and* a reroll can't reach the goal either — the simulator
    translates that to RunResult(success=False); automation treats it
    the same as FINISH.

    The goal-reroll fallback fires when relic+ has no chance (e.g. last
    turn with too few points) but a reroll could still draw a
    goal-reaching offer — without it, `no_feasible_offer` would FINISH
    even though `should_reroll_dp` would say keep_val=0 < reroll_val>0.
    """
    base_metrics = {
        "p_keep_relic": m.p_keep_relic,
        "p_reroll_relic": m.p_reroll_relic,
    }

    if ti.reset_available:
        return Decision(
            action=ActionKind.RESET,
            branch=branch,
            reason=reason,
            metrics=base_metrics,
        )

    can_reroll = ti.rerolls > 0 and ti.turn != 1
    p_reroll_goal = (ctx.prob_table.lookup(
        ti.state, ti.turns_left, rerolls=ti.rerolls - 1)
        if can_reroll else 0.0)

    # Note: `--relic-reroll-threshold` does NOT force-finish a dead gem here.
    # Rerolls are free, so while a free reroll (or the current offers) can still
    # reach relic+, the grade-value chase below keeps working them. The
    # threshold's sole job is gating the reroll ticket — handled at
    # *arming* time in the simulator / `run_auto`, which only add the ticket to
    # the reroll budget when P(relic+) clears the threshold. (User directive:
    # use free rerolls to chase a reachable relic+; the threshold limits only
    # the reroll ticket's gold cost.)

    # Preferred path: value-aware grade chase via the goal-independent
    # grade-value table (present only when relic/ancient grade has a
    # coefficient). Prices ancient upside + point magnitude correctly,
    # which the binary relic+ probability below cannot.
    gvt = ctx.grade_value_table
    if gvt is not None and gvt.enabled:
        # A reroll that can still reach the *goal* (Branch 3: this draw
        # can't, a fresh one might) dominates grade chasing — the goal is
        # the primary objective. Structural infeasibility => p == 0, so
        # this never fires from Branch 1.
        if p_reroll_goal > 0:
            return Decision(
                action=ActionKind.REROLL,
                branch=branch,
                reason=(f"{reason}, rerolling for goal "
                        f"(P(goal|reroll)={p_reroll_goal:.1%})"),
                metrics={**base_metrics, "p_reroll_goal": p_reroll_goal},
            )
        return _grade_value_decision(ctx, ti, gvt, branch, reason)

    # Binary relic+ fallback — no grade coefficient set, or gem type unknown
    # (grade table disabled). Preserves the prior behaviour exactly.
    if ctx.relic_prob_table is not None:
        has_chance = m.p_keep_relic > 0 or (can_reroll and m.p_reroll_relic > 0)
        if has_chance:
            if can_reroll and m.p_reroll_relic > m.p_keep_relic:
                return Decision(
                    action=ActionKind.REROLL,
                    branch=branch,
                    reason=(f"{reason}, chasing relic+ "
                            f"(P(r+|reroll)={m.p_reroll_relic:.1%} > "
                            f"P(r+|process)={m.p_keep_relic:.1%})"),
                    metrics=base_metrics,
                )
            return Decision(
                action=ActionKind.PROCESS,
                branch=branch,
                reason=(f"{reason}, chasing relic+ "
                        f"(P(r+|process)={m.p_keep_relic:.1%})"),
                metrics=base_metrics,
            )
        # Relic+ unreachable. A reroll might still find a goal-reaching
        # offer (current offers all have post-click P(goal)=0, but the
        # DP says fresh draws can hit it).
        if p_reroll_goal > 0:
            return Decision(
                action=ActionKind.REROLL,
                branch=branch,
                reason=(f"{reason}, rerolling for goal "
                        f"(P(goal|reroll)={p_reroll_goal:.1%})"),
                metrics={**base_metrics, "p_reroll_goal": p_reroll_goal},
            )
        # Goal AND relic+ both unreachable
        return Decision(
            action=ActionKind.FINISH,
            branch=branch,
            reason="goal & relic+ both unreachable",
            metrics=base_metrics,
        )

    # No relic table — try the goal-reroll fallback before failing.
    if p_reroll_goal > 0:
        return Decision(
            action=ActionKind.REROLL,
            branch=branch,
            reason=(f"{reason}, rerolling for goal "
                    f"(P(goal|reroll)={p_reroll_goal:.1%})"),
            metrics={**base_metrics, "p_reroll_goal": p_reroll_goal},
        )
    return Decision(
        action=ActionKind.FAIL,
        branch=branch,
        reason=f"{reason}, no reset available",
        metrics=base_metrics,
    )


def infeasibility_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Branch 1: current state can't structurally reach the goal.

    Uses `LastTurnGoal.feasible()` — the loose +4-per-turn upper bound.
    Catches the obvious cases (e.g. need will=5 but turns_left=0).
    Branch 3 (DP-based) catches the cases this misses.
    """
    if ctx.goal.feasible(
        ti.state.will, ti.state.chaos, ti.turns_left,
        first=ti.state.first, second=ti.state.second,
        **_feasibility_args(ctx, ti.state),
    ):
        return None
    decision = _reset_or_chase_relic(
        ctx, ti, m, branch="infeasible", reason="goal infeasible",
    )
    return _maybe_confirm(ctx, ti, decision)


def no_feasible_offer_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Branch 3: every visible offer has DP P(goal) == 0.

    Catches cases the loose `goal.feasible` upper bound misses — e.g.
    `min_side_coeff` says feasible because +4 per turn could reach it,
    but the actual offer pool tops out at +2.
    """
    if not ti.offers or m.feasible_count > 0:
        return None
    decision = _reset_or_chase_relic(
        ctx, ti, m, branch="no_feasible_offer",
        reason="no offer reaches goal",
    )
    return _maybe_confirm(ctx, ti, decision)


# ---------------------------------------------------------------------------
# Branch 2: prob_reset_threshold (post-click posterior)
# ---------------------------------------------------------------------------


def prob_reset_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Branch 2: post-click P(goal) below user-set reset threshold."""
    if ctx.prob_reset_threshold <= 0 or not ti.reset_available:
        return None
    # Never reset a gem that already satisfies the goal — it is a guaranteed
    # success, so discarding it for a fresh start is strictly worse. The
    # threshold is a "draw toward an unmet goal" knob; a met goal means
    # early_finish has already chosen finish/process/reroll for it.
    if _goal_fully_satisfied(ctx, ti.state):
        return None
    if m.p_keep_goal_reset >= ctx.prob_reset_threshold:
        return None
    return _maybe_confirm(ctx, ti, Decision(
        action=ActionKind.RESET,
        branch="prob_reset",
        reason=(f"post-click P(goal)={m.p_keep_goal_reset:.1%} < "
                f"threshold {ctx.prob_reset_threshold:.1%}"),
        metrics={"p_keep_goal_reset": m.p_keep_goal_reset},
    ))


# ---------------------------------------------------------------------------
# Branch 4: last-turn fresh-start comparison
# ---------------------------------------------------------------------------


def last_turn_reset_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Branch 4: last turn — reset if a fresh start has better odds.

    Both sides of the comparison use the non-reroll-aware reset table:
    `m.p_keep_goal_reset` (offer-conditional, this turn) vs
    `ctx.p_fresh` (prior at fresh start). The reroll-aware DP would
    overestimate fresh-start value.
    """
    if (ti.turns_left != 1
            or not ti.reset_available
            or ctx.p_fresh <= 0):
        return None
    # Never reset a gem that already satisfies the goal (see prob_reset_decision)
    # — a fresh start can only lose the success already in hand.
    if _goal_fully_satisfied(ctx, ti.state):
        return None
    if m.p_keep_goal_reset >= ctx.p_fresh:
        return None
    return _maybe_confirm(ctx, ti, Decision(
        action=ActionKind.RESET,
        branch="last_turn_fresh",
        reason=(f"last turn post-click {m.p_keep_goal_reset:.1%} < "
                f"fresh start {ctx.p_fresh:.1%}"),
        metrics={"p_keep_goal_reset": m.p_keep_goal_reset,
                 "p_fresh": ctx.p_fresh},
    ))


# ---------------------------------------------------------------------------
# Branch 5: DP-optimal reroll (with force-no-progress override)
# ---------------------------------------------------------------------------


def dp_reroll_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Branch 5: spend a reroll when DP says it's optimal, or force a
    reroll when the gem's coefficient is high enough and no offer
    progresses the goal at all.
    """
    if ti.rerolls <= 0 or ti.turn == 1:
        return None

    coeff_map = DPS_COEFF if ctx.optimize == "dps" else SUPPORT_COEFF
    target_set = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
    side_coeff_first = (coeff_map.get(ti.state.first_effect, 0)
                        if ti.state.first_effect in target_set else 0)
    side_coeff_second = (coeff_map.get(ti.state.second_effect, 0)
                         if ti.state.second_effect in target_set else 0)

    if (ctx.force_reroll_active
            and not has_progress_offer(
                ti.offers, ti.state, ctx.goal,
                ctx.min_side_coeff, side_coeff_first, side_coeff_second)):
        return Decision(
            action=ActionKind.REROLL,
            branch="dp_reroll",
            reason=(f"forced_no_progress, "
                    f"avg_keep={m.p_keep_goal:.1%}"),
            metrics={"reasons": ["forced_no_progress"]},
        )

    if ctx.prob_table.should_reroll_dp(
            ti.state, ti.offers, ti.turns_left, ti.rerolls):
        return Decision(
            action=ActionKind.REROLL,
            branch="dp_reroll",
            reason=(f"dp_reroll_optimal, "
                    f"avg_keep={m.p_keep_goal:.1%}"),
            metrics={"reasons": ["dp_reroll_optimal"]},
        )
    return None


# ---------------------------------------------------------------------------
# Decision-tree assembly
# ---------------------------------------------------------------------------


_POST_ROLL_BRANCHES = (
    early_finish_decision,
    infeasibility_decision,
    prob_reset_decision,
    no_feasible_offer_decision,
    last_turn_reset_decision,
    dp_reroll_decision,
)


def decide_post_roll(ctx: DecisionContext, ti: TurnInput) -> Decision:
    """Full Branch 0–6 tree. Used by automation each frame and by the
    simulator after the per-turn reroll loop completes.
    """
    m = compute_post_roll_metrics(ctx, ti)
    for fn in _POST_ROLL_BRANCHES:
        d = fn(ctx, ti, m)
        if d is not None:
            return d
    return Decision(
        action=ActionKind.PROCESS,
        branch="default_process",
        reason=(f"P(click)={m.p_keep_goal:.1%}"),
        metrics={"p_keep_goal": m.p_keep_goal},
    )


def decide_reroll_only(ctx: DecisionContext, ti: TurnInput) -> Decision:
    """Narrow tree used inside the simulator's reroll loop.

    Only the reroll-relevant branches fire here: the loop spends
    rerolls before the main decision tree runs, so reset/finish are
    handled later. We do still consult `early_finish_decision` because
    it can return REROLL when the goal is satisfied but offers are
    bad — losing that signal would mean the reroll loop exits with
    risky offers in hand.
    """
    m = compute_post_roll_metrics(ctx, ti)
    d = early_finish_decision(ctx, ti, m)
    if d is not None and d.action == ActionKind.REROLL:
        return d
    d = dp_reroll_decision(ctx, ti, m)
    if d is not None:
        return d
    return Decision(
        action=ActionKind.PROCESS,
        branch="default_process",
        reason=(f"P(click)={m.p_keep_goal:.1%}"),
        metrics={"p_keep_goal": m.p_keep_goal},
    )
