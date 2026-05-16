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
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES, SUPPORT_COEFF, SUPPORT_EFFECTS,
    change_dest_max_coeff,
)
from arkgrid.models import GemState, LastTurnGoal, Option
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable


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
    early_finish_coeff: int                        # -1 = disabled
    prob_reset_threshold: float
    relic_no_early_finish: float
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
    confirm_risk: float = 0.0
    confirm_min_coeff: int = 0
    risk_prob_table: Optional[GoalProbabilityTable] = None


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
    miss_count: int               # # offers that break goal_fully_satisfied
    avg_coeff_change: float       # avg side-coeff EV (clamped, change_effect-aware)
    ev_points: float              # avg total-points EV
    improving_count: int          # # offers that strictly improve the gem
    degrading_count: int          # # offers that strictly degrade the gem


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


def _continue_has_upside(ctx: DecisionContext, state: GemState,
                         turns_left: int) -> bool:
    """True when continuing to cut can still improve the gem.

    Upside exists when turns remain and either a target-set side node
    is below level 5 (side coefficient can still grow) or total points
    are below 19 (a higher relic+/ancient tier is still reachable).
    """
    if turns_left <= 0:
        return False
    target = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
    if state.first_effect in target and state.first < 5:
        return True
    if state.second_effect in target and state.second < 5:
        return True
    if state.total_points() < 19:
        return True
    return False


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


def _change_effect_ev(ctx: DecisionContext, state: GemState,
                      slot: str) -> float:
    """Expected side-coefficient delta from a change_{slot}_effect option.

    The new effect is drawn uniformly from the gem-pool effects not
    currently equipped, so the expected delta is
    `level * (mean destination coeff - current coeff)`.

    Replaces the old `-= full contribution` model, which over-counted
    the loss whenever a destination was itself a target effect (the
    inaccuracy F10 flagged). Returns 0.0 when the gem type is unknown.
    """
    coeff_map = DPS_COEFF if ctx.optimize == "dps" else SUPPORT_COEFF
    target = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
    cur_eff = getattr(state, f"{slot}_effect")
    cur = coeff_map.get(cur_eff, 0) if cur_eff in target else 0
    lvl = getattr(state, slot)
    dests = [e for e in GEM_TYPES.get(ctx.gem_type, ())
             if e not in (state.first_effect, state.second_effect)]
    if not dests:
        return 0.0
    mean_dest = sum((coeff_map.get(e, 0) if e in target else 0)
                    for e in dests) / len(dests)
    return lvl * (mean_dest - cur)


def compute_post_roll_metrics(ctx: DecisionContext, ti: TurnInput) -> TurnMetrics:
    """Compute every probability and aggregate a branch helper might need.

    Costs ~4-8 DP lookups + a small per-offer loop — negligible vs the
    DP table build itself. Done once per turn so helpers don't repeat
    the work.
    """
    if not ti.offers:
        return TurnMetrics(0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0, 0, 0)

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

    # Per-offer post-click feasibility under the goal DP, plus
    # early-finish miss/coeff aggregates.
    coeff_map = DPS_COEFF if ctx.optimize == "dps" else SUPPORT_COEFF
    target_set = DPS_EFFECTS if ctx.optimize == "dps" else SUPPORT_EFFECTS
    max_r = ctx.prob_table._max_rerolls

    feasible_count = 0
    miss_count = 0
    coeff_total = 0.0
    point_total = 0
    improving_count = 0
    degrading_count = 0

    for o in ti.offers:
        ns = _apply_option_for_metrics(ti.state, o)
        view_delta = o.delta if o.kind == "view" else 0
        nr = (min(max_r, ti.rerolls + view_delta)
              if max_r > 0 else ti.rerolls)
        if ctx.prob_table.lookup(ns, tla, rerolls=nr) > 0:
            feasible_count += 1
        if not _goal_fully_satisfied(ctx, ns):
            miss_count += 1
        # Per-offer EV on two axes. Total-points: clamped delta straight
        # off the applied state. Side-coeff: clamped level delta, or the
        # expected destination coefficient for change_effect offers.
        dp = ns.total_points() - ti.state.total_points()
        dc = 0.0
        if o.kind in ("first", "second"):
            eff = getattr(ti.state, f"{o.kind}_effect")
            if eff in target_set:
                actual = getattr(ns, o.kind) - getattr(ti.state, o.kind)
                dc = actual * coeff_map.get(eff, 0)
        elif o.key in ("change_first_effect", "change_second_effect"):
            slot = "first" if o.key == "change_first_effect" else "second"
            dc = _change_effect_ev(ctx, ti.state, slot)
        coeff_total += dc
        point_total += dp
        if dp > 0 or dc > 1e-9:
            improving_count += 1
        elif dp < 0 or dc < -1e-9:
            degrading_count += 1
        # else: neutral (maintain / capped / cost / view)

    avg_coeff_change = coeff_total / len(ti.offers)
    ev_points = point_total / len(ti.offers)

    return TurnMetrics(
        p_keep_goal=p_keep_goal,
        p_keep_goal_reset=p_keep_goal_reset,
        p_keep_relic=p_keep_relic,
        p_reroll_relic=p_reroll_relic,
        feasible_count=feasible_count,
        miss_count=miss_count,
        avg_coeff_change=avg_coeff_change,
        ev_points=ev_points,
        improving_count=improving_count,
        degrading_count=degrading_count,
    )


# ---------------------------------------------------------------------------
# Branch 0: early-finish (goal already satisfied)
# ---------------------------------------------------------------------------


def early_finish_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Goal already met — stop, continue, or hand the call to the player.

    With `--confirm-risk` active, uses the goal-loss-probability gate
    (`_confirm_finish_decision`); otherwise the legacy
    `--early-finish-coeff` heuristic (`_legacy_early_finish_decision`).
    The legacy path may also return REROLL when the goal is satisfied
    but all visible offers are risky and rerolls remain.
    """
    if not _goal_fully_satisfied(ctx, ti.state):
        return None
    if not ti.offers:
        return None
    if ctx.confirm_active:
        return _confirm_finish_decision(ctx, ti, m)
    return _legacy_early_finish_decision(ctx, ti, m)


def _confirm_finish_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Gate #1 — finish-vs-continue under `--confirm-risk`.

    Returns FINISH (silent) when there is no upside or the gem is too
    cheap to bother the player with, None to continue silently when the
    risk is acceptable, or FINISH+needs_confirmation when continuing is
    a real gamble on a valuable gem.
    """
    if not _continue_has_upside(ctx, ti.state, ti.turns_left):
        return Decision(
            action=ActionKind.FINISH, branch="confirm_finish",
            reason="goal met, no side upside — finishing",
            metrics={"side_coeff": _side_coeff(ctx, ti.state)},
        )

    # Relic+ override: keep cutting silently when relic+ is likely.
    if (ctx.relic_no_early_finish > 0.0
            and ctx.relic_prob_table is not None
            and m.p_keep_relic > ctx.relic_no_early_finish):
        return None

    coeff = _side_coeff(ctx, ti.state)
    risk = 1.0
    if ctx.risk_prob_table is not None:
        risk = 1.0 - ctx.risk_prob_table.lookup(
            ti.state, ti.turns_left, rerolls=ti.rerolls)
    # risk <= 0.0 is a defensive zero-guard: not normally reachable once
    # upside exists (the risk_prob_table lookup should be < 1.0), but
    # protects against FP underflow or a tightly-bounded table rounding to 1.
    if risk <= 0.0 or risk < ctx.confirm_risk:
        # Free or acceptable-risk upgrade — continue silently.
        return None

    metrics = {"risk": risk, "side_coeff": coeff,
               "p_keep_relic": m.p_keep_relic}
    if coeff < ctx.confirm_min_coeff:
        return Decision(
            action=ActionKind.FINISH, branch="confirm_finish",
            reason=(f"goal met, risk={risk:.0%} but side_coeff {coeff} "
                    f"< floor {ctx.confirm_min_coeff} — finishing"),
            metrics=metrics,
        )
    return Decision(
        action=ActionKind.FINISH, branch="confirm_finish",
        reason=(f"goal met, risk={risk:.0%}, side_coeff={coeff} — "
                f"player confirmation required"),
        metrics=metrics,
        needs_confirmation=True,
        confirm_choices=_legal_actions(ti),
    )


def _legacy_early_finish_decision(
    ctx: DecisionContext, ti: TurnInput, m: TurnMetrics,
) -> Optional[Decision]:
    """Legacy `--early-finish-coeff` heuristic (used when `--confirm-risk`
    is not set).

    F10 removed the ``elif avg_coeff_change < 0`` branch that previously
    triggered early finish on zero-risk turns (see inline comment below).
    Behavior is therefore *not* identical to pre-confirm-gate code.
    """
    if ctx.early_finish_coeff < 0:
        return None

    p_miss = m.miss_count / len(ti.offers)
    expected_total = m.avg_coeff_change * ti.turns_left

    should_stop = False
    if p_miss > 0:
        should_stop = (ctx.early_finish_coeff == 0
                       or expected_total <= ctx.early_finish_coeff)
    # When p_miss == 0 the goal is in no danger: finishing early on a negative
    # coefficient *average* (a 25%-random outcome, not a chosen one) would only
    # abandon free points — F10.  The elif that did this is intentionally absent.

    if not should_stop:
        return None

    if (ctx.relic_no_early_finish > 0.0
            and ctx.relic_prob_table is not None
            and m.p_keep_relic > ctx.relic_no_early_finish):
        return None

    metrics = {
        "p_miss": p_miss,
        "avg_coeff": m.avg_coeff_change,
        "expected_total": expected_total,
        "p_keep_relic": m.p_keep_relic,
        "early_finish_coeff": ctx.early_finish_coeff,
    }

    if ti.rerolls > 0 and ti.turn != 1:
        return Decision(
            action=ActionKind.REROLL,
            branch="early_finish",
            reason=(f"goal satisfied, bad options: "
                    f"risk={p_miss:.0%}, "
                    f"avg_coeff={m.avg_coeff_change:.0f}"),
            metrics=metrics,
        )
    return Decision(
        action=ActionKind.FINISH,
        branch="early_finish",
        reason=(f"goal satisfied, risk={p_miss:.0%}, "
                f"avg_coeff={m.avg_coeff_change:.0f}, "
                f"expected={expected_total:.0f}, "
                f"threshold={ctx.early_finish_coeff}"),
        metrics=metrics,
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
