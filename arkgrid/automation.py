"""Automation engine for astrogem cutting (Windows only).

Captures the game screen, detects state via template matching,
makes reroll/process/reset decisions using DP probability, and
clicks the appropriate buttons.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

if sys.platform != "win32":
    raise RuntimeError("The 'auto' command requires Windows.")

import ctypes

# Make the process DPI-aware so SetCursorPos uses physical pixels,
# matching the physical pixel coordinates from mss screen capture.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS,
)
from arkgrid.models import AstroGem, GemState, LastTurnGoal, Option
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable
from arkgrid.simulator import GemSimulator
from arkgrid.vision.capture import grab_screen
from arkgrid.vision.template_recognizer import (
    DetectionResult,
    OptionDetection,
    detect,
    determine_option_kind,
    parse_delta,
    parse_rerolls,
)
from arkgrid.vision.constants import (
    GEM_TYPE_TEMPLATE_TO_DOMAIN,
    RARITY_FROM_TOTAL_STEPS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Button positions at 1920x1080 reference resolution
BTN_RESET = (962, 255)
BTN_PROCESS = (1068, 765)
BTN_REROLL = (1254, 595)
BTN_FINISH = (831, 764)
BTN_CONFIRM_TICKET = (906, 666)
TICKET_CONFIRM_DELAY = 0.5

_VK_ESCAPE = 0x1B
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004

MAX_DETECT_RETRIES = 5
DETECT_RETRY_WAIT = 0.5


# ---------------------------------------------------------------------------
# Windows helpers
# ---------------------------------------------------------------------------

def _is_lostark_focused() -> bool:
    """Check if Lost Ark is the foreground window."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length)
    title = buf.value.upper()
    return "LOST ARK" in title or "LOSTARK" in title


def _is_stop_pressed() -> bool:
    """Check if Escape is currently pressed."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(_VK_ESCAPE) & 0x8000)


def _get_monitor(monitor_index: int) -> dict:
    """Get monitor geometry from mss."""
    import mss as mss_lib
    with mss_lib.mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 1
        return dict(monitors[monitor_index])


def _click(ref_x: int, ref_y: int, monitor: dict) -> None:
    """Click at 1920x1080 reference coordinates, scaled to actual screen."""
    scale_x = monitor["width"] / 1920
    scale_y = monitor["height"] / 1080
    x = monitor["left"] + int(ref_x * scale_x)
    y = monitor["top"] + int(ref_y * scale_y)
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _wait_for_focus() -> bool:
    """Block until Lost Ark is focused. Returns False if Escape pressed."""
    print("  [paused] Lost Ark not focused. Waiting...")
    while not _is_lostark_focused():
        if _is_stop_pressed():
            return False
        time.sleep(0.5)
    print("  [resumed]")
    return True


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

@dataclass
class FrameAnalysis:
    """Result of analyzing one game screenshot."""
    gem_type_domain: str
    rarity: str
    turns_total: int
    turns_left: int
    current_turn: int
    reroll_count: int
    state: GemState

    option_probs: list   # [(OptionDetection, kind, delta_val, p_after), ...]
    option_labels: List[str]
    best_idx: int

    p_current: float
    p_avg_offers: float
    p_best_option: float
    should_reroll: bool

    warnings: List[str]


def _fmt_option(opt: OptionDetection, kind: str, delta_val: Optional[int],
                first_effect: str, second_effect: str) -> str:
    """Format an option for display."""
    kind_hint, _ = parse_delta(opt.delta_key)
    if kind_hint == "effect_changed":
        return f"{opt.name_key} EC"
    if kind_hint == "maintained":
        return "maintain"
    if kind_hint == "cost":
        return opt.delta_key or "cost"
    if kind_hint == "reroll":
        return opt.delta_key or "reroll"
    if opt.name_key and delta_val is not None:
        sign = "+" if delta_val > 0 else ""
        return f"{opt.name_key} {sign}{delta_val}"
    return opt.name_key or "???"


def _build_prob_table(
    goal: LastTurnGoal,
    turns_total: int,
    pool: OptionPool,
    state: GemState,
    bis_only: bool,
    optimize: str,
    min_side_coeff: int,
    exact_draw: bool,
    gem_type_domain: str,
    early_finish: bool = False,
) -> Tuple[GoalProbabilityTable, frozenset]:
    """Build the DP probability table."""
    target_effects: frozenset = frozenset()
    if bis_only and gem_type_domain in GEM_TYPES:
        opt_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        gem_pool = set(GEM_TYPES[gem_type_domain])
        target_effects = frozenset(gem_pool & opt_set)

    side_coeff_first, side_coeff_second = 0, 0
    if min_side_coeff > 0 and gem_type_domain in GEM_TYPES:
        coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        opt_set_coeff = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        if state.first_effect in opt_set_coeff:
            side_coeff_first = coeff_map[state.first_effect]
        if state.second_effect in opt_set_coeff:
            side_coeff_second = coeff_map[state.second_effect]

    table = GoalProbabilityTable(
        goal, turns_total, pool,
        bis_only=bis_only, target_effects=target_effects,
        side_coeff_first=side_coeff_first,
        side_coeff_second=side_coeff_second,
        min_side_coeff=min_side_coeff,
        exact_draw=exact_draw,
        early_finish=early_finish,
    )
    return table, target_effects


def _analyze_frame(
    det: DetectionResult,
    goal: LastTurnGoal,
    extra_ticket: bool,
    dp_reroll_margin: float,
    prob_table: GoalProbabilityTable,
    target_effects: frozenset,
    bis_only: bool,
    override_reroll_count: Optional[int] = None,
) -> FrameAnalysis:
    """Analyze a detection result into structured decision data."""
    gem_type_domain = GEM_TYPE_TEMPLATE_TO_DOMAIN.get(det.gem_type, det.gem_type)
    rarity = RARITY_FROM_TOTAL_STEPS.get(det.total_steps, "rare")
    turns_total = det.total_steps
    turns_left = det.current_step
    current_turn = turns_total - turns_left + 1

    if override_reroll_count is not None:
        reroll_count = override_reroll_count
    else:
        reroll_count = parse_rerolls(det.rerolls, extra_ticket=extra_ticket)

    state = GemState(
        will=det.willpower,
        chaos=det.chaos,
        first=det.first_level or 1,
        second=det.second_level or 1,
        cost_ratio=0,
        rerolls=reroll_count,
        first_effect=det.first_effect,
        second_effect=det.second_effect,
    )

    warnings = []
    for score, label in [
        (det.gem_type_score, "gem_type"),
        (det.willpower_score, "willpower"),
        (det.chaos_score, "chaos"),
        (det.first_effect_score, "side_1 name"),
        (det.first_level_score, "side_1 level"),
        (det.second_effect_score, "side_2 name"),
        (det.second_level_score, "side_2 level"),
        (det.rerolls_score, "rerolls"),
        (det.step_score, "step"),
        (det.rarity_score, "rarity"),
    ]:
        if score < 0.9:
            warnings.append(f"LOW: {label} = {score:.2f}")

    p_current = prob_table.lookup(state, turns_left)

    option_probs = []
    option_labels = []
    for opt in det.options:
        kind, delta_val = determine_option_kind(
            opt.name_key, opt.delta_key,
            state.first_effect, state.second_effect,
        )
        kind_hint, _ = parse_delta(opt.delta_key)

        if kind_hint == "effect_changed" and bis_only:
            slot = "first" if opt.name_key == state.first_effect else "second"
            p_after = prob_table.lookup_after_effect_change(
                state, slot, turns_left - 1)
        else:
            next_state = state.clone()
            if delta_val is not None and kind in ("will", "chaos", "first", "second"):
                cur = getattr(next_state, kind)
                setattr(next_state, kind, min(5, max(1, cur + delta_val)))
            p_after = prob_table.lookup(next_state, turns_left - 1)

        option_probs.append((opt, kind, delta_val, p_after))
        option_labels.append(_fmt_option(opt, kind, delta_val,
                                         state.first_effect, state.second_effect))

    best_idx = max(range(len(option_probs)), key=lambda i: option_probs[i][3]) if option_probs else 0
    p_best_option = max((p for _, _, _, p in option_probs), default=0.0)
    p_avg_offers = (sum(p for _, _, _, p in option_probs) / len(option_probs)
                    if option_probs else 0.0)

    should_reroll = (reroll_count > 0
                     and current_turn != 1
                     and turns_left != 1
                     and p_current > 0
                     and p_avg_offers < p_current * (1 - dp_reroll_margin))

    return FrameAnalysis(
        gem_type_domain=gem_type_domain,
        rarity=rarity,
        turns_total=turns_total,
        turns_left=turns_left,
        current_turn=current_turn,
        reroll_count=reroll_count,
        state=state,
        option_probs=option_probs,
        option_labels=option_labels,
        best_idx=best_idx,
        p_current=p_current,
        p_avg_offers=p_avg_offers,
        p_best_option=p_best_option,
        should_reroll=should_reroll,
        warnings=warnings,
    )


def _detected_to_options(
    det_options: list,
    option_probs: list,
    state: GemState,
) -> List[Option]:
    """Convert detected options to Option objects for RerollPolicy."""
    result = []
    for (opt, kind, delta_val, _p), det_opt in zip(option_probs, det_options):
        kind_hint, _ = parse_delta(det_opt.delta_key)
        # Build a key matching RerollPolicy's expected format
        if kind in ("will", "chaos", "first", "second") and delta_val is not None:
            key = f"{kind}{delta_val:+d}"
        elif kind_hint == "cost":
            key = det_opt.delta_key or "cost+100"
        elif kind_hint == "reroll":
            key = det_opt.delta_key or "reroll+1"
        elif kind_hint == "effect_changed":
            slot = "first" if det_opt.name_key == state.first_effect else "second"
            key = f"change_{slot}_effect"
        elif kind_hint == "maintained":
            key = "maintain"
        else:
            key = det_opt.name_key or "other"
        delta = delta_val if delta_val is not None else 0
        result.append(Option(key=key, weight=1.0, kind=kind, delta=delta))
    return result


def _infer_picked(old: GemState, new: GemState) -> str:
    """Describe state changes to infer which option was picked."""
    parts = []
    if new.will != old.will:
        parts.append(f"will {new.will - old.will:+d}")
    if new.chaos != old.chaos:
        parts.append(f"chaos {new.chaos - old.chaos:+d}")
    if new.first != old.first:
        parts.append(f"first {new.first - old.first:+d}")
    if new.second != old.second:
        parts.append(f"second {new.second - old.second:+d}")
    if new.first_effect != old.first_effect:
        parts.append(f"first_effect -> {new.first_effect}")
    if new.second_effect != old.second_effect:
        parts.append(f"second_effect -> {new.second_effect}")
    if new.rerolls > old.rerolls:
        parts.append(f"rerolls +{new.rerolls - old.rerolls}")
    return ", ".join(parts) if parts else "maintain / cost"


# ---------------------------------------------------------------------------
# Main automation loop
# ---------------------------------------------------------------------------

def run_auto(
    monitor_index: int,
    goal: LastTurnGoal,
    extra_ticket: bool,
    reset_ticket: Optional[bool],
    dp_reroll_margin: float,
    optimize: str,
    bis_only: bool,
    min_side_coeff: int,
    exact_draw: bool,
    prob_reset_threshold: float,
    side_quality_weight: float,
    side_threshold: float,
    animation_delay: float,
    dry_run: bool,
    astro_gem: Optional[AstroGem],
    reset_min_coeff: int,
    reroll_min_coeff: int,
    early_finish_coeff: int = 0,
) -> None:
    """Run the full automation loop: detect → decide → click → repeat."""
    from arkgrid.policy import RerollPolicy

    pool = OptionPool()
    monitor = _get_monitor(monitor_index)

    # Cached probability table (rebuilt if effects change)
    prob_table: Optional[GoalProbabilityTable] = None
    target_effects: frozenset = frozenset()
    cached_effects: Optional[Tuple[str, str]] = None
    p_fresh: Optional[float] = None

    # Auto-detected gem (from first screen capture)
    detected_gem: Optional[AstroGem] = astro_gem
    reroll_policy: Optional[RerollPolicy] = None

    # Internal state tracking
    reset_available = bool(reset_ticket)
    extra_ticket_active = bool(extra_ticket)
    reset_used = False
    internal_rerolls: Optional[int] = None
    base_rerolls = 0  # updated on first detection
    prev_analysis: Optional[FrameAnalysis] = None
    prev_action: Optional[str] = None
    turn_history: List[dict] = []
    current_turn_rerolls = 0
    consecutive_failures = 0

    # Safety countdown
    print("=== Astrogem Auto Mode ===")
    print(f"Press Escape to stop.{' (DRY RUN)' if dry_run else ''}")
    if not dry_run:
        for i in range(3, 0, -1):
            if _is_stop_pressed():
                print("Aborted.")
                return
            print(f"  Starting in {i}...")
            time.sleep(1)
    print()

    while True:
        # --- Stop key ---
        if _is_stop_pressed():
            print("\n[stopped by Escape]")
            break

        # --- Focus check ---
        if not dry_run and not _is_lostark_focused():
            if not _wait_for_focus():
                print("\n[stopped by Escape]")
                break

        # --- Capture & detect ---
        det: Optional[DetectionResult] = None
        for attempt in range(MAX_DETECT_RETRIES):
            frame = grab_screen(monitor_index)
            det = detect(frame)
            if det.found:
                break
            if attempt < MAX_DETECT_RETRIES - 1:
                time.sleep(DETECT_RETRY_WAIT)

        if det is None or not det.found:
            consecutive_failures += 1
            if (prev_action == "process" and prev_analysis
                    and prev_analysis.turns_left == 1):
                # Last turn processed — gem cutting complete
                print()
                print("--- Gem cutting complete! ---")
                if prev_analysis:
                    s = prev_analysis.state
                    print(f"  Last known state before final click: "
                          f"w={s.will} c={s.chaos} "
                          f"1st={s.first} 2nd={s.second}  "
                          f"(total={s.total_points()})")
                break
            if consecutive_failures > 10:
                print("\n[error] Too many detection failures. Exiting.")
                break
            time.sleep(DETECT_RETRY_WAIT)
            continue

        consecutive_failures = 0

        # --- Validate critical fields ---
        if (det.gem_type is None or det.willpower is None or det.chaos is None
                or det.first_effect is None or det.second_effect is None
                or det.current_step is None or det.total_steps is None):
            print("  [error] Critical detection failure. Retrying...")
            time.sleep(1.0)
            continue

        # --- Build/reuse probability table ---
        gem_type_domain = GEM_TYPE_TEMPLATE_TO_DOMAIN.get(det.gem_type, det.gem_type)
        current_effects = (det.first_effect, det.second_effect)

        if prob_table is None or (
            (bis_only or min_side_coeff > 0) and cached_effects != current_effects
        ):
            temp_state = GemState(
                first_effect=det.first_effect,
                second_effect=det.second_effect,
            )
            prob_table, target_effects = _build_prob_table(
                goal, det.total_steps, pool, temp_state,
                bis_only, optimize, min_side_coeff, exact_draw,
                gem_type_domain, early_finish=early_finish_coeff >= 0,
            )
            rarity_name = RARITY_FROM_TOTAL_STEPS.get(det.total_steps, "rare")
            base_rerolls = GemSimulator.RARITY_REROLLS.get(rarity_name, 0)

            # Auto-detect gem on first detection (or when effects change)
            if detected_gem is None or cached_effects != current_effects:
                detected_gem = AstroGem(
                    gem_type_domain, det.first_effect,
                    det.second_effect, optimize,
                )
                # Gate tickets by coefficient thresholds (same as simulator)
                if reset_min_coeff > 0 or reroll_min_coeff > 0:
                    coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
                    t_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
                    total_coeff = sum(
                        coeff_map.get(e, 0)
                        for e in (det.first_effect, det.second_effect)
                        if e in t_set
                    )
                    if reset_min_coeff > 0 and total_coeff < reset_min_coeff:
                        reset_available = False
                        print(f"  [info] Reset ticket disabled "
                              f"(coeff {total_coeff} < {reset_min_coeff})")
                    if reroll_min_coeff > 0 and total_coeff < reroll_min_coeff:
                        extra_ticket_active = False
                        print(f"  [info] Extra reroll ticket disabled "
                              f"(coeff {total_coeff} < {reroll_min_coeff})")

                # Build reroll policy with all parameters
                reroll_policy = RerollPolicy(
                    goal, side_threshold, detected_gem, bis_only,
                    dp_reroll_margin=dp_reroll_margin,
                    side_quality_weight=side_quality_weight,
                )

            cached_effects = current_effects
            p_fresh = prob_table.lookup(
                GemState(will=1, chaos=1, first=1, second=1),
                det.total_steps,
            )

        # --- Analyze ---
        # After process/reset, use OCR for rerolls (new turn, state unknown).
        # After reroll, use internal tracking (more reliable mid-turn).
        reroll_override = internal_rerolls
        if prev_action in ("process", "reset"):
            reroll_override = None

        analysis = _analyze_frame(
            det, goal, extra_ticket_active, dp_reroll_margin,
            prob_table, target_effects, bis_only,
            override_reroll_count=reroll_override,
        )

        # --- Print previous turn's result (after process) ---
        if (prev_action == "process" and prev_analysis
                and analysis.current_turn > prev_analysis.current_turn):
            picked = _infer_picked(prev_analysis.state, analysis.state)
            print(f"  picked:  {picked}")
            s = analysis.state
            print(f"  state:   w={s.will} c={s.chaos} "
                  f"1st={s.first} 2nd={s.second}  "
                  f"(total={s.total_points()})  "
                  f"effects={s.first_effect}/{s.second_effect}  "
                  f"P(goal)={analysis.p_current:.1%}")
            print()

            # Update internal reroll tracking from detected state
            internal_rerolls = analysis.reroll_count

            turn_history.append({
                "turn": prev_analysis.current_turn,
                "rerolls_used": current_turn_rerolls,
                "state_after": {
                    "will": s.will, "chaos": s.chaos,
                    "first": s.first, "second": s.second,
                    "total": s.total_points(),
                    "effects": f"{s.first_effect}/{s.second_effect}",
                },
                "p_goal": analysis.p_current,
            })
            current_turn_rerolls = 0

        elif prev_action == "reset" and prev_analysis:
            print("  [reset complete]")
            print()
            internal_rerolls = None
            current_turn_rerolls = 0

        # --- Print turn header ---
        note = ""
        if (prev_action == "reroll" and prev_analysis
                and analysis.current_turn == prev_analysis.current_turn):
            note = "  [after reroll]"
        print(f"Turn {analysis.current_turn}/{analysis.turns_total} "
              f"(left={analysis.turns_left})  "
              f"P(goal)={analysis.p_current:.1%}  "
              f"rerolls={analysis.reroll_count}{note}")
        print(f"  options: [{', '.join(analysis.option_labels)}]")

        if analysis.warnings:
            for w in analysis.warnings:
                print(f"  [warn] {w}")

        # --- Decision logic ---
        action: Optional[str] = None

        # 0. Early finish: goal already satisfied, risk not worth it
        if (early_finish_coeff >= 0 and analysis.turns_left > 0
                and goal.satisfied(analysis.state.will, analysis.state.chaos,
                                   analysis.state.first, analysis.state.second)):
            miss_count = 0
            best_coeff_gain = 0
            coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
            t_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
            for opt, kind, dv, p_after in analysis.option_probs:
                ns = analysis.state.clone()
                if dv is not None and kind in ("will", "chaos", "first", "second"):
                    cur = getattr(ns, kind)
                    setattr(ns, kind, min(5, max(1, cur + dv)))
                if not goal.satisfied(ns.will, ns.chaos, ns.first, ns.second):
                    miss_count += 1
                if kind in ("first", "second") and dv is not None and dv > 0:
                    eff = getattr(analysis.state, f"{kind}_effect")
                    if eff in t_set:
                        gain = dv * coeff_map[eff]
                        best_coeff_gain = max(best_coeff_gain, gain)

            p_miss = miss_count / len(analysis.option_probs) if analysis.option_probs else 0.0
            if p_miss > 0:
                if best_coeff_gain == 0 or best_coeff_gain * p_miss > early_finish_coeff:
                    action = "finish"
                    risk_score = best_coeff_gain * p_miss
                    print(f"  action:  FINISH EARLY (goal satisfied, "
                          f"risk={p_miss:.0%}, best_gain={best_coeff_gain}, "
                          f"score={risk_score:.0f} > {early_finish_coeff})")

        # 1. Goal infeasibility → reset
        if not goal.feasible(analysis.state.will, analysis.state.chaos,
                             analysis.turns_left,
                             first=analysis.state.first,
                             second=analysis.state.second):
            if reset_available and not reset_used:
                action = "reset"
                print(f"  action:  RESET (goal infeasible)")
            else:
                print(f"  [warn] Goal infeasible, no reset available")

        # 2. Probability threshold → reset
        if (action is None and prob_reset_threshold > 0
                and reset_available and not reset_used):
            if analysis.p_current < prob_reset_threshold:
                action = "reset"
                print(f"  action:  RESET (P(goal)={analysis.p_current:.1%} "
                      f"< threshold {prob_reset_threshold:.1%})")

        # 3. No offer keeps goal feasible → reset
        if action is None:
            feasible_count = sum(1 for _, _, _, p in analysis.option_probs if p > 0)
            if feasible_count == 0 and reset_available and not reset_used:
                action = "reset"
                print(f"  action:  RESET (no offer keeps goal feasible)")

        # 4. Last turn: fresh start comparison → reset
        if (action is None and analysis.turns_left == 1
                and reset_available and not reset_used and p_fresh is not None):
            if analysis.p_avg_offers < p_fresh:
                action = "reset"
                print(f"  action:  RESET (last turn avg {analysis.p_avg_offers:.1%} "
                      f"< fresh start {p_fresh:.1%})")

        # 5. Reroll (use full RerollPolicy when available)
        if action is None and analysis.reroll_count > 0 and analysis.current_turn != 1:
            should_reroll = False
            reroll_reasons: List[str] = []

            if reroll_policy and prob_table:
                pool_opts = _detected_to_options(
                    det.options, analysis.option_probs, analysis.state)
                goal_feasible = sum(
                    1 for _, _, _, p in analysis.option_probs if p > 0
                ) / len(analysis.option_probs) if analysis.option_probs else 0.0
                should_reroll, reroll_reasons = reroll_policy.should_reroll(
                    pool_opts, analysis.state, analysis.turns_left,
                    goal_feasible,
                    goal_success_prob=analysis.p_avg_offers,
                    dp_baseline=analysis.p_current,
                    rerolls_remaining=analysis.reroll_count,
                )
            else:
                # Fallback: simple DP-margin check
                should_reroll = analysis.should_reroll
                if should_reroll:
                    reroll_reasons = ["dp_margin"]

            if should_reroll:
                action = "reroll"
                reason_str = ", ".join(reroll_reasons) if reroll_reasons else "policy"
                print(f"  action:  reroll  "
                      f"(reasons=[{reason_str}], "
                      f"avg={analysis.p_avg_offers:.1%}, "
                      f"baseline={analysis.p_current:.1%}, "
                      f"{analysis.reroll_count} rerolls left)")

        # 6. Process (default)
        if action is None:
            action = "process"
            print(f"  action:  process  "
                  f"P(click)={analysis.p_avg_offers:.1%}  "
                  f"Best={analysis.p_best_option:.1%}  "
                  f"Baseline={analysis.p_current:.1%}")

        # --- Execute ---
        if dry_run:
            btn_name = {"process": "Process", "reroll": "Reroll",
                        "reset": "Reset", "finish": "Finish"}[action]
            print(f"  >>> [dry-run] Would click {btn_name}")
            print()
            prev_analysis = analysis
            prev_action = action
            time.sleep(animation_delay)
            if action == "finish":
                print("--- Gem cutting complete (early finish)! ---")
                break
            continue

        # Verify focus
        if not _is_lostark_focused():
            if not _wait_for_focus():
                print("\n[stopped by Escape]")
                break

        btn_map = {
            "process": ("Process", BTN_PROCESS),
            "reroll": ("Reroll", BTN_REROLL),
            "reset": ("Reset", BTN_RESET),
            "finish": ("Finish", BTN_FINISH),
        }
        btn_name, btn_pos = btn_map[action]
        print(f"  >>> Clicking {btn_name}...", end="", flush=True)
        _click(*btn_pos, monitor)
        print(" done")

        # Ticket confirmation for reset and ticket-based rerolls
        needs_confirm = False
        if action == "reset" and reset_available:
            needs_confirm = True
        elif action == "reroll" and extra_ticket_active:
            # The ticket-provided reroll needs confirmation when
            # we've used all base rerolls
            rerolls_used_this_run = (
                (base_rerolls + 1)  # total with ticket
                - analysis.reroll_count
            )
            if rerolls_used_this_run >= base_rerolls:
                needs_confirm = True

        if needs_confirm:
            time.sleep(TICKET_CONFIRM_DELAY)
            print(f"  >>> Confirming ticket...", end="", flush=True)
            _click(*BTN_CONFIRM_TICKET, monitor)
            print(" done")

        # Post-action tracking
        if action == "finish":
            s = analysis.state
            turn_history.append({
                "turn": analysis.current_turn,
                "rerolls_used": current_turn_rerolls,
                "state_after": {
                    "will": s.will, "chaos": s.chaos,
                    "first": s.first, "second": s.second,
                    "total": s.total_points(),
                    "effects": f"{s.first_effect}/{s.second_effect}",
                },
                "p_goal": 1.0,
                "action": "early_finish",
            })
            prev_analysis = analysis
            prev_action = action
            time.sleep(animation_delay)
            print()
            print("--- Gem cutting complete (early finish)! ---")
            print(f"  Final: w={s.will} c={s.chaos} "
                  f"1st={s.first} 2nd={s.second}  "
                  f"(total={s.total_points()})  "
                  f"effects={s.first_effect}/{s.second_effect}")
            break
        elif action == "reroll":
            current_turn_rerolls += 1
            if internal_rerolls is not None:
                internal_rerolls = max(0, internal_rerolls - 1)
            else:
                internal_rerolls = max(0, analysis.reroll_count - 1)
        elif action == "reset":
            reset_used = True
            reset_available = False
            internal_rerolls = None
            turn_history.append({
                "turn": analysis.current_turn,
                "rerolls_used": current_turn_rerolls,
                "action": "reset",
            })
            current_turn_rerolls = 0

        prev_analysis = analysis
        prev_action = action

        # Wait for animation
        time.sleep(animation_delay)

    # --- Summary ---
    print()
    if turn_history:
        print("--- Run Summary ---")
        for entry in turn_history:
            if entry.get("action") == "reset":
                print(f"  Turn {entry['turn']}: RESET "
                      f"(used {entry['rerolls_used']} rerolls)")
            else:
                sa = entry["state_after"]
                line = (f"  Turn {entry['turn']}: "
                        f"w={sa['will']} c={sa['chaos']} "
                        f"1st={sa['first']} 2nd={sa['second']}  "
                        f"(total={sa['total']})  "
                        f"P(goal)={entry['p_goal']:.1%}")
                if entry["rerolls_used"] > 0:
                    line += f"  ({entry['rerolls_used']} rerolls used)"
                print(line)
        print()

    if prev_analysis:
        s = prev_analysis.state
        print(f"Final: w={s.will} c={s.chaos} "
              f"1st={s.first} 2nd={s.second}  "
              f"(total={s.total_points()})  "
              f"effects={s.first_effect}/{s.second_effect}")
    print(f"Reset used: {reset_used}")
