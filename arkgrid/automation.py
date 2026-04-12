"""Automation engine for astrogem cutting (Windows only).

Captures the game screen, detects state via template matching,
makes reroll/process/reset decisions using DP probability, and
clicks the appropriate buttons.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
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
    FinishDetectionResult,
    OptionDetection,
    detect,
    detect_finish,
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
BTN_CONFIRM_TICKET = (897, 643)
BTN_CONFIRM_GEM_DONE = (957, 766)
BTN_NEXT_GEM = (356, 113)
TICKET_CONFIRM_DELAY = 0.5

# All-mode: pixel at (573, 113) equals 0x5AA9E2 iff a gem is selected
ALL_MODE_CHECK_POS = (573, 113)
ALL_MODE_GEM_SELECTED_RGB = 0x5AA9E2
ALL_MODE_CLICK_DELAY = 1.0
# Park the cursor here after selecting the next gem so the inventory
# tooltip doesn't overlap the detection ROIs.
ALL_MODE_PARK_POS = (1170, 195)

_VK_ESCAPE = 0x1B
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004

MAX_DETECT_RETRIES = 5
DETECT_RETRY_WAIT = 0.5


class _TeeWriter:
    """Duplicate writes to both the original stdout and a log file."""

    def __init__(self, log_path: str):
        self._stdout = sys.stdout
        self._file = open(log_path, "w", encoding="utf-8")

    def write(self, text: str) -> int:
        self._stdout.write(text)
        self._file.write(text)
        self._file.flush()
        return len(text)

    def flush(self) -> None:
        self._stdout.flush()
        self._file.flush()

    def close(self) -> None:
        self._file.close()


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


def _move_cursor(ref_x: int, ref_y: int, monitor: dict) -> None:
    """Move cursor to 1920x1080 reference coordinates, scaled to actual screen."""
    scale_x = monitor["width"] / 1920
    scale_y = monitor["height"] / 1080
    x = monitor["left"] + int(ref_x * scale_x)
    y = monitor["top"] + int(ref_y * scale_y)
    ctypes.windll.user32.SetCursorPos(x, y)


def _click(ref_x: int, ref_y: int, monitor: dict) -> None:
    """Click at 1920x1080 reference coordinates, scaled to actual screen."""
    _move_cursor(ref_x, ref_y, monitor)
    time.sleep(0.05)
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.02)
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _get_pixel_rgb(ref_x: int, ref_y: int, monitor: dict) -> int:
    """Read pixel color at 1920x1080 reference coords. Returns 0xRRGGBB."""
    scale_x = monitor["width"] / 1920
    scale_y = monitor["height"] / 1080
    x = monitor["left"] + int(ref_x * scale_x)
    y = monitor["top"] + int(ref_y * scale_y)
    hdc = ctypes.windll.user32.GetDC(0)
    try:
        colorref = ctypes.windll.gdi32.GetPixel(hdc, x, y)
    finally:
        ctypes.windll.user32.ReleaseDC(0, hdc)
    if colorref == 0xFFFFFFFF:  # CLR_INVALID
        return -1
    r = colorref & 0xFF
    g = (colorref >> 8) & 0xFF
    b = (colorref >> 16) & 0xFF
    return (r << 16) | (g << 8) | b


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


_DP_CACHE: dict = {}


def _goal_cache_key(goal: LastTurnGoal) -> tuple:
    return (goal.min_will, goal.min_chaos, goal.exact_will, goal.exact_chaos,
            goal.min_total_will_chaos, goal.exact_total_will_chaos,
            goal.min_first, goal.min_second, goal.min_total)


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
    max_rerolls: int = 0,
    effect_aware: bool = False,
) -> Tuple[GoalProbabilityTable, frozenset, int, int]:
    """Build the DP probability table.

    Returns (table, target_effects, side_coeff_first, side_coeff_second).
    When effect_aware is True, results are cached by (goal, turns, gem_type,
    optimize, min_side_coeff, exact_draw, max_rerolls, early_finish) — the
    effect-pair is encoded in the DP state, so one table covers all configs
    of the same gem type.
    """
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

    use_effect_aware = effect_aware and gem_type_domain in GEM_TYPES

    cache_key = None
    if use_effect_aware:
        cache_key = (
            "ea",
            _goal_cache_key(goal), turns_total, gem_type_domain, optimize,
            min_side_coeff, exact_draw, max_rerolls, early_finish,
        )
        cached = _DP_CACHE.get(cache_key)
        if cached is not None:
            return cached, target_effects, side_coeff_first, side_coeff_second

    if use_effect_aware:
        print(f"  [dp] Building effect-aware table "
              f"({gem_type_domain}, exact={exact_draw}, "
              f"rerolls={max_rerolls})...", flush=True)
        t0 = time.time()
        table = GoalProbabilityTable(
            goal, turns_total, pool,
            min_side_coeff=min_side_coeff,
            exact_draw=exact_draw,
            early_finish=early_finish,
            max_rerolls=max_rerolls,
            effect_aware=True,
            gem_type=gem_type_domain,
            optimize=optimize,
        )
        print(f"  [dp] Built in {time.time() - t0:.2f}s "
              f"({len(table._dp)} states)", flush=True)
        _DP_CACHE[cache_key] = table
    else:
        table = GoalProbabilityTable(
            goal, turns_total, pool,
            bis_only=bis_only, target_effects=target_effects,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=min_side_coeff,
            exact_draw=exact_draw,
            early_finish=early_finish,
            max_rerolls=max_rerolls,
        )
    return table, target_effects, side_coeff_first, side_coeff_second


def _has_progress_offer(
    offers: List[Option],
    state: GemState,
    goal: LastTurnGoal,
    min_side_coeff: int,
    side_coeff_first: int,
    side_coeff_second: int,
) -> bool:
    """Return True if any offer progresses an unmet goal constraint."""
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


def _parse_view_delta(delta_key: Optional[str]) -> int:
    """Extract the signed integer from a view/reroll delta key (e.g. 'reroll+1' -> 1)."""
    if not delta_key:
        return 0
    m = re.search(r"[+-]?\d+", delta_key)
    return int(m.group(0)) if m else 0


def _analyze_frame(
    det: DetectionResult,
    goal: LastTurnGoal,
    extra_ticket: bool,
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

    max_r = prob_table._max_rerolls
    p_current = prob_table.lookup(state, turns_left, rerolls=reroll_count)

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
            view_delta = _parse_view_delta(opt.delta_key) if kind == "view" else 0
            next_rerolls = (min(max_r, reroll_count + view_delta)
                            if max_r > 0 else reroll_count)
            p_after = prob_table.lookup(next_state, turns_left - 1,
                                        rerolls=next_rerolls)

        option_probs.append((opt, kind, delta_val, p_after))
        option_labels.append(_fmt_option(opt, kind, delta_val,
                                         state.first_effect, state.second_effect))

    best_idx = max(range(len(option_probs)), key=lambda i: option_probs[i][3]) if option_probs else 0
    p_best_option = max((p for _, _, _, p in option_probs), default=0.0)
    p_avg_offers = (sum(p for _, _, _, p in option_probs) / len(option_probs)
                    if option_probs else 0.0)

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
        warnings=warnings,
    )


def _detected_to_options(
    det_options: list,
    option_probs: list,
    state: GemState,
) -> List[Option]:
    """Convert detected options to Option objects for DP reroll decisions."""
    result = []
    for (opt, kind, delta_val, _p), det_opt in zip(option_probs, det_options):
        kind_hint, _ = parse_delta(det_opt.delta_key)
        # Build a key matching the Option format expected by should_reroll_dp
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
        if kind == "view":
            delta = _parse_view_delta(det_opt.delta_key)
        else:
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
    reset_ticket,  # bool | str (rarity threshold: common/rare/epic) | None
    optimize: str,
    bis_only: bool,
    min_side_coeff: int,
    exact_draw: bool,
    prob_reset_threshold: float,
    side_threshold: float,
    animation_delay: float,
    dry_run: bool,
    astro_gem: Optional[AstroGem],
    reset_min_coeff: int,
    reroll_min_coeff: int,
    early_finish_coeff: int = 0,
    relic_no_early_finish: float = 0.0,
    relic_reroll_threshold: float = 0.0,
    force_reroll_no_progress: int = 0,
    all_gems: bool = False,
    effect_aware_dp: bool = False,
) -> None:
    """Run the full automation loop: detect → decide → click → repeat."""

    # Set up logging — tee stdout to a per-run log file
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join("logs", f"auto_{timestamp}.log")
    tee = _TeeWriter(log_path)
    _original_stdout = sys.stdout
    sys.stdout = tee

    # Log run parameters for context
    print(f"[LOG] Run started at {timestamp}")
    print(f"[LOG] Goal: min_will={goal.min_will} min_chaos={goal.min_chaos} "
          f"min_first={goal.min_first} min_second={goal.min_second}")
    print(f"[LOG] Settings: exact_draw={exact_draw} bis_only={bis_only} "
          f"optimize={optimize} early_finish_coeff={early_finish_coeff}")
    print(f"[LOG] Relic+: no_early_finish={relic_no_early_finish} "
          f"reroll_threshold={relic_reroll_threshold}")
    print(f"[LOG] Tickets: extra={extra_ticket} reset={reset_ticket}")
    print(f"[LOG] Force reroll no progress threshold: {force_reroll_no_progress}")
    print(f"[LOG] Effect-aware DP: {effect_aware_dp}")
    print()

    pool = OptionPool()
    monitor = _get_monitor(monitor_index)

    # Safety countdown
    print("=== Astrogem Auto Mode ===")
    print(f"Press Escape to stop.{' (DRY RUN)' if dry_run else ''}"
          f"{' [ALL GEMS]' if all_gems else ''}")
    if not dry_run:
        for i in range(3, 0, -1):
            if _is_stop_pressed():
                print("Aborted.")
                sys.stdout = _original_stdout
                tee.close()
                print(f"Log saved to: {log_path}")
                return
            print(f"  Starting in {i}...")
            time.sleep(1)
    print()

    stop_requested = False
    gem_count = 0
    while True:  # outer: iterate over gems (only repeats when --all is set)
        gem_count += 1
        if all_gems and gem_count > 1:
            print(f"=== Starting gem #{gem_count} ===")

        # Cached probability table (rebuilt if effects change)
        prob_table: Optional[GoalProbabilityTable] = None
        target_effects: frozenset = frozenset()
        side_coeff_first: int = 0
        side_coeff_second: int = 0
        cached_effects: Optional[Tuple[str, str]] = None
        p_fresh: Optional[float] = None

        # Relic+ (>=16 total points) probability table — built on first detection
        relic_table: Optional[GoalProbabilityTable] = None

        # Auto-detected gem (from first screen capture)
        detected_gem: Optional[AstroGem] = astro_gem

        # Internal state tracking
        # Resolved against the gem's rarity once detection succeeds; until
        # then we optimistically enable it (any truthy --reset-ticket value).
        reset_available = bool(reset_ticket)
        extra_ticket_active = bool(extra_ticket)
        force_reroll_active = False  # gated by starting coeff, set on first detection
        reset_used = False
        internal_rerolls: Optional[int] = None
        base_rerolls = 0  # updated on first detection
        prev_analysis: Optional[FrameAnalysis] = None
        prev_action: Optional[str] = None
        prev_action_reason: str = ""
        turn_history: List[dict] = []
        current_turn_rerolls = 0
        consecutive_failures = 0
        # (turn, reroll_key, target_turn). If target_turn is set, wait until
        # det_turn == target_turn (used for reset which always returns to
        # turn 1 — avoids clearing on mid-animation frames where the reroll
        # counter has already decremented but the turn hasn't flipped yet).
        waiting_for_change: Optional[
            Tuple[int, Optional[str], Optional[int]]
        ] = None
        finish_state: Optional[dict] = None  # Set from finish screen detection
        gem_completed = False

        while True:
            # --- Stop key ---
            if _is_stop_pressed():
                print("\n[stopped by Escape]")
                stop_requested = True
                break

            # --- Focus check ---
            if not dry_run and not _is_lostark_focused():
                if not _wait_for_focus():
                    print("\n[stopped by Escape]")
                    stop_requested = True
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
                if (prev_action in ("process", "finish") and prev_analysis
                        and prev_analysis.turns_left <= 1):
                    # Last turn processed or finish clicked — try to detect finish screen
                    finish_det = None
                    for f_attempt in range(MAX_DETECT_RETRIES):
                        f_frame = grab_screen(monitor_index)
                        finish_det = detect_finish(f_frame)
                        if finish_det.found:
                            break
                        if f_attempt < MAX_DETECT_RETRIES - 1:
                            time.sleep(DETECT_RETRY_WAIT)

                    if finish_det and finish_det.found:
                        fw = finish_det.willpower or prev_analysis.state.will
                        fc = finish_det.chaos or prev_analysis.state.chaos
                        f1 = finish_det.first_level or prev_analysis.state.first
                        f2 = finish_det.second_level or prev_analysis.state.second
                        ft = fw + fc + f1 + f2
                        finish_state = {
                            "will": fw, "chaos": fc,
                            "first": f1, "second": f2, "total": ft,
                        }
                        # Show picked for the last turn
                        finish_picked = None
                        if prev_action == "process":
                            finish_gs = GemState(
                                will=fw, chaos=fc, first=f1, second=f2,
                                first_effect=prev_analysis.state.first_effect,
                                second_effect=prev_analysis.state.second_effect,
                            )
                            finish_picked = _infer_picked(
                                prev_analysis.state, finish_gs)
                            print(f"  picked:  {finish_picked}")
                        print()
                        print("--- Gem cutting complete! ---")
                        print(f"  Final: w={fw} c={fc} "
                              f"1st={f1} 2nd={f2}  (total={ft})")
                        turn_history.append({
                            "turn": prev_analysis.current_turn,
                            "rerolls_used": current_turn_rerolls,
                            "picked": finish_picked,
                            "action": prev_action,
                            "action_reason": prev_action_reason,
                            "state_after": {
                                "will": fw, "chaos": fc,
                                "first": f1, "second": f2,
                                "total": ft,
                                "effects": (f"{prev_analysis.state.first_effect}/"
                                            f"{prev_analysis.state.second_effect}"),
                            },
                            "p_goal": 0.0,
                        })
                    elif prev_analysis:
                        s = prev_analysis.state
                        print(f"  Last known state before final click: "
                              f"w={s.will} c={s.chaos} "
                              f"1st={s.first} 2nd={s.second}  "
                              f"(total={s.total_points()})")
                    if finish_det and finish_det.found:
                        gem_completed = True
                    else:
                        stop_requested = True
                    break
                if consecutive_failures > 10:
                    print("\n[error] Too many detection failures. Exiting.")
                    stop_requested = True
                    break
                time.sleep(DETECT_RETRY_WAIT)
                continue

            consecutive_failures = 0

            # --- Validate critical fields ---
            if (det.gem_type is None or det.willpower is None or det.chaos is None
                    or det.first_effect is None or det.second_effect is None
                    or det.current_step is None or det.total_steps is None):
                if waiting_for_change is None:
                    print("  [error] Critical detection failure. Retrying...")
                # Silent retry when waiting — expected during animations
                time.sleep(DETECT_RETRY_WAIT)
                continue

            # --- Wait for state change (turn or reroll count) ---
            if waiting_for_change is not None:
                det_turn = det.total_steps - det.current_step + 1
                wait_turn, wait_rerolls, target_turn = waiting_for_change
                if target_turn is not None:
                    # Reset flow: hold until the turn indicator flips to
                    # target_turn (reset always returns to turn 1). The
                    # reroll counter decrements before the reset animation
                    # finishes, so relying on a generic "anything changed"
                    # check would release too early on a mid-animation frame.
                    if det_turn != target_turn:
                        time.sleep(animation_delay)
                        continue
                elif det_turn == wait_turn and det.rerolls == wait_rerolls:
                    time.sleep(animation_delay)
                    continue
                waiting_for_change = None
                internal_rerolls = None  # state changed: trust OCR
                # Let UI fully settle before recapturing
                time.sleep(0.5)
                continue

            # --- Build/reuse probability table ---
            gem_type_domain = GEM_TYPE_TEMPLATE_TO_DOMAIN.get(det.gem_type, det.gem_type)
            current_effects = (det.first_effect, det.second_effect)

            if prob_table is None or (
                not effect_aware_dp
                and (bis_only or min_side_coeff > 0)
                and cached_effects != current_effects
            ):
                temp_state = GemState(
                    first_effect=det.first_effect,
                    second_effect=det.second_effect,
                )
                rarity_name = RARITY_FROM_TOTAL_STEPS.get(det.total_steps, "rare")
                base_rerolls = GemSimulator.RARITY_REROLLS.get(rarity_name, 0)
                total_rerolls = base_rerolls + (1 if extra_ticket_active else 0)
                prob_table, target_effects, side_coeff_first, side_coeff_second = (
                    _build_prob_table(
                        goal, det.total_steps, pool, temp_state,
                        bis_only, optimize, min_side_coeff, exact_draw,
                        gem_type_domain, early_finish=early_finish_coeff >= 0,
                        max_rerolls=total_rerolls,
                        effect_aware=effect_aware_dp,
                    ))
                # Build relic+ table once (doesn't depend on effects)
                if relic_table is None and (
                        relic_no_early_finish > 0.0 or relic_reroll_threshold > 0.0):
                    relic_table = GoalProbabilityTable(
                        LastTurnGoal(min_total=16), det.total_steps, pool,
                        exact_draw=exact_draw, early_finish=False,
                    )
                # Use standard (non-reroll) DP for p_fresh — the reroll-aware
                # DP overestimates fresh start probability.
                _reset_table = GoalProbabilityTable(
                    goal, det.total_steps, pool,
                    exact_draw=exact_draw,
                    early_finish=early_finish_coeff >= 0,
                )
                p_fresh = _reset_table.lookup(
                    GemState(will=1, chaos=1, first=1, second=1),
                    det.total_steps,
                )

            # Re-detect gem and re-evaluate tickets when effects change
            if detected_gem is None or cached_effects != current_effects:
                detected_gem = AstroGem(
                    gem_type_domain, det.first_effect,
                    det.second_effect, optimize,
                )
                # Gate tickets by coefficient thresholds (same as simulator)
                # Reset only checked on first detection (reset restores
                # original effects). Reroll re-evaluated on effect changes.
                if (reset_min_coeff > 0 or reroll_min_coeff > 0
                        or force_reroll_no_progress > 0):
                    coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
                    t_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
                    total_coeff = sum(
                        coeff_map.get(e, 0)
                        for e in (det.first_effect, det.second_effect)
                        if e in t_set
                    )
                    if cached_effects is None:
                        # First detection: gate reset ticket on starting effects
                        if reset_min_coeff > 0 and total_coeff < reset_min_coeff:
                            reset_available = False
                            print(f"  [info] Reset ticket disabled "
                                  f"(coeff {total_coeff} < {reset_min_coeff})")
                    if reroll_min_coeff > 0 and total_coeff < reroll_min_coeff:
                        extra_ticket_active = False
                        print(f"  [info] Extra reroll ticket disabled "
                              f"(coeff {total_coeff} < {reroll_min_coeff})")
                    force_reroll_active = (
                        force_reroll_no_progress > 0
                        and total_coeff >= force_reroll_no_progress)
                    if cached_effects is None and force_reroll_no_progress > 0:
                        status = "enabled" if force_reroll_active else "disabled"
                        print(f"  [info] Force-reroll-no-progress {status} "
                              f"(coeff {total_coeff} vs {force_reroll_no_progress})")
                else:
                    force_reroll_active = False

                # Rarity threshold on --reset-ticket (common/rare/epic). If
                # the gem's rarity is below the threshold, disable reset for
                # this run. Evaluated once on first detection — the rarity
                # can't change mid-run.
                if (cached_effects is None and reset_available
                        and isinstance(reset_ticket, str)):
                    rarity_name = RARITY_FROM_TOTAL_STEPS.get(
                        det.total_steps, "rare")
                    rarity_level = {"common": 1, "rare": 2, "epic": 3}
                    if (rarity_level.get(rarity_name, 0)
                            < rarity_level[reset_ticket]):
                        reset_available = False
                        print(f"  [info] Reset ticket disabled "
                              f"(rarity {rarity_name} below "
                              f"--reset-ticket {reset_ticket})")

                # Relic+ override is checked per-turn below (not here)

                cached_effects = current_effects

            # --- Analyze ---
            # Use OCR for rerolls only when a new turn is detected (turn
            # changed since last action).  Within the same turn keep internal
            # tracking — in dry-run the screen doesn't update after our
            # "clicks", so OCR would return stale values.
            reroll_override = internal_rerolls
            if prev_action in ("process", "reset"):
                det_current_turn = det.total_steps - det.current_step + 1
                if (prev_analysis is None
                        or det_current_turn != prev_analysis.current_turn):
                    reroll_override = None

            analysis = _analyze_frame(
                det, goal, extra_ticket_active,
                prob_table, target_effects, bis_only,
                override_reroll_count=reroll_override,
            )

            # --- Print previous turn's result (after process) ---
            if (prev_action == "process" and prev_analysis
                    and analysis.current_turn > prev_analysis.current_turn):
                picked = _infer_picked(prev_analysis.state, analysis.state)
                print(f"  picked:  {picked}")
                s = analysis.state
                state_line = (f"  state:   w={s.will} c={s.chaos} "
                              f"1st={s.first} 2nd={s.second}  "
                              f"(total={s.total_points()})  "
                              f"effects={s.first_effect}/{s.second_effect}  "
                              f"P(goal)={analysis.p_current:.1%}")
                if relic_table is not None:
                    p_r = relic_table.lookup(s, analysis.turns_left)
                    state_line += f"  P(r+)={p_r:.1%}"
                print(state_line)
                print()

                # Update internal reroll tracking from detected state
                internal_rerolls = analysis.reroll_count

                turn_history.append({
                    "turn": prev_analysis.current_turn,
                    "rerolls_used": current_turn_rerolls,
                    "picked": picked,
                    "action": prev_action,
                    "action_reason": prev_action_reason,
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

            # --- Relic+ reroll ticket override (per-turn check) ---
            if (not extra_ticket_active and extra_ticket
                    and relic_reroll_threshold > 0.0 and relic_table is not None):
                p_relic_cur = relic_table.lookup(
                    analysis.state, analysis.turns_left)
                if p_relic_cur >= relic_reroll_threshold:
                    extra_ticket_active = True
                    # Grant +1 reroll to internal tracking
                    if internal_rerolls is not None:
                        internal_rerolls += 1
                    print(f"  [info] Extra reroll ticket re-enabled "
                          f"(P(relic+)={p_relic_cur:.1%} >= "
                          f"{relic_reroll_threshold:.1%})")

            # --- Print turn header ---
            note = ""
            if (prev_action == "reroll" and prev_analysis
                    and analysis.current_turn == prev_analysis.current_turn):
                note = "  [after reroll]"
            relic_info = ""
            if relic_table is not None:
                p_r = relic_table.lookup(analysis.state, analysis.turns_left)
                relic_info = f"  P(r+)={p_r:.1%}"
            print(f"Turn {analysis.current_turn}/{analysis.turns_total} "
                  f"(left={analysis.turns_left})  "
                  f"P(goal)={analysis.p_current:.1%}{relic_info}  "
                  f"rerolls={analysis.reroll_count}{note}")
            opts_with_prob = [
                f"{lbl} ({p:.1%})"
                for lbl, (_, _, _, p) in zip(analysis.option_labels,
                                             analysis.option_probs)
            ]
            print(f"  options: [{', '.join(opts_with_prob)}]")

            if analysis.warnings:
                for w in analysis.warnings:
                    print(f"  [warn] {w}")

            # --- Decision logic ---
            action: Optional[str] = None
            action_reason = ""

            # 0. Early finish / coefficient-aware reroll: goal already satisfied
            if (early_finish_coeff >= 0 and analysis.turns_left > 0
                    and goal.satisfied(analysis.state.will, analysis.state.chaos,
                                       analysis.state.first, analysis.state.second)):
                miss_count = 0
                coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
                t_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
                total_coeff = 0
                for opt, kind, dv, p_after in analysis.option_probs:
                    ns = analysis.state.clone()
                    if dv is not None and kind in ("will", "chaos", "first", "second"):
                        cur = getattr(ns, kind)
                        setattr(ns, kind, min(5, max(1, cur + dv)))
                    if not goal.satisfied(ns.will, ns.chaos, ns.first, ns.second):
                        miss_count += 1
                    # Coefficient impact: side stat changes
                    if kind in ("first", "second") and dv is not None:
                        eff = getattr(analysis.state, f"{kind}_effect")
                        if eff in t_set:
                            total_coeff += dv * coeff_map[eff]
                    else:
                        # Effect change: losing current effect's coefficient
                        kind_hint, _ = parse_delta(opt.delta_key)
                        if kind_hint == "effect_changed":
                            if opt.name_key == analysis.state.first_effect:
                                eff = analysis.state.first_effect
                                lvl = analysis.state.first
                            elif opt.name_key == analysis.state.second_effect:
                                eff = analysis.state.second_effect
                                lvl = analysis.state.second
                            else:
                                eff, lvl = None, 0
                            if eff and eff in t_set:
                                total_coeff -= lvl * coeff_map[eff]

                avg_coeff = total_coeff / len(analysis.option_probs) if analysis.option_probs else 0
                expected_total = avg_coeff * analysis.turns_left
                p_miss = miss_count / len(analysis.option_probs) if analysis.option_probs else 0.0

                # Determine if options are bad enough to stop/reroll
                should_stop = False
                if p_miss > 0:
                    should_stop = (early_finish_coeff == 0
                                   or expected_total <= early_finish_coeff)
                elif early_finish_coeff > 0 and avg_coeff < 0:
                    # No goal risk but net negative coefficient
                    # Only when user set a positive threshold (not safe-mode 0)
                    should_stop = True

                # Relic+ override: don't early-finish if relic+ is achievable
                if (should_stop and relic_no_early_finish > 0.0
                        and relic_table is not None):
                    p_r = relic_table.lookup(analysis.state, analysis.turns_left)
                    if p_r > relic_no_early_finish:
                        should_stop = False
                        print(f"  [info] Relic+ override: not finishing early "
                              f"(P(r+)={p_r:.1%} > {relic_no_early_finish:.1%})")

                if should_stop:
                    if analysis.reroll_count > 0:
                        action = "reroll"
                        action_reason = (
                            f"goal satisfied, bad options: "
                            f"risk={p_miss:.0%}, avg_coeff={avg_coeff:.0f}")
                        print(f"  action:  reroll  "
                              f"({action_reason}, "
                              f"{analysis.reroll_count} rerolls left)")
                    else:
                        action = "finish"
                        action_reason = (
                            f"goal satisfied, risk={p_miss:.0%}, "
                            f"avg_coeff={avg_coeff:.0f}, "
                            f"expected={expected_total:.0f}, "
                            f"threshold={early_finish_coeff}")
                        print(f"  action:  FINISH EARLY ({action_reason})")

            # 1. Goal infeasibility → reset or finish
            if not goal.feasible(analysis.state.will, analysis.state.chaos,
                                 analysis.turns_left,
                                 first=analysis.state.first,
                                 second=analysis.state.second):
                if reset_available and not reset_used:
                    action = "reset"
                    action_reason = "goal infeasible"
                    print(f"  action:  RESET ({action_reason})")
                else:
                    action = "finish"
                    action_reason = "goal infeasible, no reset available"
                    print(f"  action:  FINISH ({action_reason})")

            # 2. Probability threshold → reset
            if (action is None and prob_reset_threshold > 0
                    and reset_available and not reset_used):
                if analysis.p_current < prob_reset_threshold:
                    action = "reset"
                    action_reason = (
                        f"P(goal)={analysis.p_current:.1%} "
                        f"< threshold {prob_reset_threshold:.1%}")
                    print(f"  action:  RESET ({action_reason})")

            # 3. No offer keeps goal feasible → reset or finish
            if action is None:
                feasible_count = sum(1 for _, _, _, p in analysis.option_probs if p > 0)
                if feasible_count == 0:
                    if reset_available and not reset_used:
                        action = "reset"
                        action_reason = "no offer keeps goal feasible"
                        print(f"  action:  RESET ({action_reason})")
                    elif analysis.reroll_count <= 0:
                        action = "finish"
                        action_reason = "no option can reach goal"
                        print(f"  action:  FINISH ({action_reason})")

            # 4. Last turn: fresh start comparison → reset
            if (action is None and analysis.turns_left == 1
                    and reset_available and not reset_used and p_fresh is not None):
                if analysis.p_avg_offers < p_fresh:
                    action = "reset"
                    action_reason = (
                        f"last turn avg {analysis.p_avg_offers:.1%} "
                        f"< fresh start {p_fresh:.1%}")
                    print(f"  action:  RESET ({action_reason})")

            # 5. Reroll (DP-optimal decision, with optional forced override)
            if action is None and analysis.reroll_count > 0 and analysis.current_turn != 1:
                should_reroll = False
                reroll_reasons: List[str] = []

                if prob_table:
                    pool_opts = _detected_to_options(
                        det.options, analysis.option_probs, analysis.state)
                    if force_reroll_active and not _has_progress_offer(
                            pool_opts, analysis.state, goal,
                            min_side_coeff, side_coeff_first, side_coeff_second):
                        should_reroll = True
                        reroll_reasons = ["forced_no_progress"]
                    else:
                        should_reroll = prob_table.should_reroll_dp(
                            analysis.state, pool_opts,
                            analysis.turns_left, analysis.reroll_count)
                        if should_reroll:
                            reroll_reasons = ["dp_reroll_optimal"]

                if should_reroll:
                    action = "reroll"
                    reason_str = ", ".join(reroll_reasons) if reroll_reasons else "policy"
                    action_reason = (
                        f"reasons=[{reason_str}], "
                        f"avg={analysis.p_avg_offers:.1%}, "
                        f"baseline={analysis.p_current:.1%}")
                    print(f"  action:  reroll  "
                          f"({action_reason}, "
                          f"{analysis.reroll_count} rerolls left)")

            # 6. Process (default)
            if action is None:
                action = "process"
                action_reason = (
                    f"P(click)={analysis.p_avg_offers:.1%}, "
                    f"Best={analysis.p_best_option:.1%}, "
                    f"Baseline={analysis.p_current:.1%}")
                print(f"  action:  process  {action_reason}")

            # --- Execute ---
            if dry_run:
                btn_name = {"process": "Process", "reroll": "Reroll",
                            "reset": "Reset", "finish": "Finish"}[action]
                print(f"  >>> [dry-run] Would click {btn_name}")
                print()
                # Post-action tracking (must mirror non-dry-run path)
                if action == "reset":
                    reset_used = True
                    reset_available = False
                    internal_rerolls = None
                    turn_history.append({
                        "turn": analysis.current_turn,
                        "rerolls_used": current_turn_rerolls,
                        "action": "reset",
                        "action_reason": action_reason,
                    })
                    current_turn_rerolls = 0
                # In dry-run no click happens, so wait for the game state
                # to change (turn or reroll count) before re-evaluating.
                target = 1 if action == "reset" else None
                waiting_for_change = (analysis.current_turn, det.rerolls, target)
                prev_analysis = analysis
                prev_action = action
                prev_action_reason = action_reason
                time.sleep(animation_delay)
                continue

            # Verify focus
            if not _is_lostark_focused():
                if not _wait_for_focus():
                    print("\n[stopped by Escape]")
                    stop_requested = True
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
                    "action_reason": action_reason,
                })
                prev_analysis = analysis
                prev_action = action
                prev_action_reason = action_reason
                time.sleep(animation_delay)
                print()
                print("--- Gem cutting complete (early finish)! ---")
                print(f"  Final: w={s.will} c={s.chaos} "
                      f"1st={s.first} 2nd={s.second}  "
                      f"(total={s.total_points()})  "
                      f"effects={s.first_effect}/{s.second_effect}")
                gem_completed = True
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
                    "action_reason": action_reason,
                })
                current_turn_rerolls = 0

            if action in ("process", "reset"):
                target = 1 if action == "reset" else None
                waiting_for_change = (analysis.current_turn, det.rerolls, target)

            prev_analysis = analysis
            prev_action = action
            prev_action_reason = action_reason

            # Wait for animation
            time.sleep(animation_delay)

        # --- Per-gem summary ---
        print()
        if turn_history:
            print("--- Run Summary ---")
            for entry in turn_history:
                reason = entry.get("action_reason", "")
                reason_part = f" ({reason})" if reason else ""
                if entry.get("action") == "reset":
                    print(f"  Turn {entry['turn']}: RESET{reason_part} "
                          f"(used {entry['rerolls_used']} rerolls)")
                elif entry.get("action") == "early_finish":
                    sa = entry["state_after"]
                    line = (f"  Turn {entry['turn']}: "
                            f"w={sa['will']} c={sa['chaos']} "
                            f"1st={sa['first']} 2nd={sa['second']}  "
                            f"(total={sa['total']})  "
                            f"P(goal)={entry['p_goal']:.1%}  "
                            f"EARLY FINISH{reason_part}")
                    print(line)
                else:
                    sa = entry["state_after"]
                    act = entry.get("action", "process")
                    line = (f"  Turn {entry['turn']}: "
                            f"w={sa['will']} c={sa['chaos']} "
                            f"1st={sa['first']} 2nd={sa['second']}  "
                            f"(total={sa['total']})  "
                            f"P(goal)={entry['p_goal']:.1%}")
                    if entry["rerolls_used"] > 0:
                        line += f"  ({entry['rerolls_used']} rerolls used)"
                    picked = entry.get("picked")
                    if picked:
                        line += f"  [{picked}]"
                    line += f"  {act}{reason_part}"
                    print(line)
            print()

        if finish_state:
            effects = (f"{prev_analysis.state.first_effect}/"
                       f"{prev_analysis.state.second_effect}" if prev_analysis else "")
            print(f"Final: w={finish_state['will']} c={finish_state['chaos']} "
                  f"1st={finish_state['first']} 2nd={finish_state['second']}  "
                  f"(total={finish_state['total']})  "
                  f"effects={effects}")
        elif prev_analysis:
            s = prev_analysis.state
            print(f"Final: w={s.will} c={s.chaos} "
                  f"1st={s.first} 2nd={s.second}  "
                  f"(total={s.total_points()})  "
                  f"effects={s.first_effect}/{s.second_effect}")
        print(f"Reset used: {reset_used}")

        # --- Decide whether to continue to next gem (--all mode) ---
        if stop_requested or not all_gems or not gem_completed or dry_run:
            break

        print()
        print(f"[all mode] Confirming processed gem...")
        _click(*BTN_CONFIRM_GEM_DONE, monitor)
        time.sleep(ALL_MODE_CLICK_DELAY)

        if _is_stop_pressed():
            print("\n[stopped by Escape]")
            break

        print(f"[all mode] Selecting next gem...")
        _click(*BTN_NEXT_GEM, monitor)
        # Park cursor away from the gem slot so the tooltip doesn't
        # cover the detection ROIs on the next capture.
        _move_cursor(*ALL_MODE_PARK_POS, monitor)
        time.sleep(ALL_MODE_CLICK_DELAY)

        pixel = _get_pixel_rgb(*ALL_MODE_CHECK_POS, monitor)
        if pixel != ALL_MODE_GEM_SELECTED_RGB:
            print(f"[all mode] No new gem selected "
                  f"(pixel={pixel:#08x} at {ALL_MODE_CHECK_POS}, "
                  f"expected {ALL_MODE_GEM_SELECTED_RGB:#08x}). Stopping.")
            break

        print(f"[all mode] New gem detected (pixel={pixel:#08x}). Continuing.")
        print()
        # Give the UI a moment to render the new gem before re-detection
        time.sleep(ALL_MODE_CLICK_DELAY)

    # Close log file and restore stdout
    sys.stdout = _original_stdout
    tee.close()
    print(f"Log saved to: {log_path}")
