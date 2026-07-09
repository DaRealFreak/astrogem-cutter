"""Automation engine for astrogem cutting (Windows only).

Captures the game screen, detects state via template matching,
makes reroll/process/reset decisions using DP probability, and
clicks the appropriate buttons.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, replace
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

from arkgrid.analyzer import GemAnalyzer
from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS, change_dest_max_coeff,
)
from arkgrid.decision import (
    ActionKind, DecisionContext, TurnInput, decide_post_roll, ticket_enabled,
    has_progress_offer,
)
from arkgrid.models import AstroGem, GemState, LastTurnGoal, Option
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable, SideValueTable
from arkgrid.table_cache import (
    goal_table as cached_goal_table,
    side_value_table as cached_side_value_table,
)
from arkgrid.run_logger import RunLogger
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
# Alternate confirm position shown when a ticket item is available
# (reset or reroll) and the dialog offers to consume it instead of
# paying directly. Detected via the teal pill color at TICKET_ITEM_CHECK_POS.
BTN_CONFIRM_TICKET_WITH_ITEM = (917, 668)
TICKET_ITEM_CHECK_POS = (960, 493)
TICKET_ITEM_CHECK_RGB = 0x0B92A9
# F6: The teal pixel above is a POSITIVE signal that the item-ticket dialog is
# present.  The standard (no-item) confirm dialog renders an opaque dark panel
# at the same coordinate instead of the teal pill.  The panel is near-black and
# its exact sample drifts by a channel step between captures (e.g. 0x111211 and
# 0x121211 both observed on live resets), so we accept a small set of known
# values rather than a single one.  These reads are still deterministic per-pixel
# samples of a static modal, so matching any known value is a reliable positive
# signal.  Together with the teal pill they let run_auto verify *which* dialog is
# up — and skip the confirm click when neither matches (the dialog never appeared
# and the cutting screen is still showing).
TICKET_STANDARD_CHECK_RGBS = frozenset({0x111211, 0x121211})
BTN_CONFIRM_GEM_DONE = (957, 766)
BTN_NEXT_GEM = (356, 113)
TICKET_CONFIRM_DELAY = 0.5
# Extra settle time after TICKET_CONFIRM_DELAY before sampling the verification
# pixel.  The confirm dialog fades in, so sampling too early can catch the panel
# mid-animation, a step off its settled color, and trip the "unrecognized pixel"
# guard that wrongly skips the confirm click.  Wait this much more before
# sampling.  (Known settled values are enumerated in TICKET_STANDARD_CHECK_RGBS.)
TICKET_VERIFY_SETTLE_DELAY = 0.5

# All-mode: pixel at (573, 113) equals 0x5AA9E2 iff a gem is selected
ALL_MODE_CHECK_POS = (573, 113)
ALL_MODE_GEM_SELECTED_RGB = 0x5AA9E2
ALL_MODE_CLICK_DELAY = 1.0
# Park the cursor here after selecting the next gem so the inventory
# tooltip doesn't overlap the detection ROIs.
ALL_MODE_PARK_POS = (1170, 195)

_VK_ESCAPE = 0x1B
_VK_F1 = 0x70
_VK_F2 = 0x71
_VK_F3 = 0x72
_VK_F4 = 0x73
_CONFIRM_VKS = (_VK_F1, _VK_F2, _VK_F3, _VK_F4)
_CONFIRM_LABELS = {
    ActionKind.FINISH: "finish & keep gem",
    ActionKind.PROCESS: "keep cutting",
    ActionKind.REROLL: "reroll offers",
    ActionKind.RESET: "reset gem",
}
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


def _wait_for_confirm_key(n_choices: int) -> int:
    """Block until one of F1..F<n_choices> is pressed, or Escape.

    Returns the 0-based choice index, or -1 if Escape was pressed.
    Waits for a key-down edge then for release, so one press = one result.

    Precondition: ``n_choices`` must be between 0 and ``len(_CONFIRM_VKS)``
    (4) inclusive — callers must not exceed 4.
    """
    while True:
        if _is_stop_pressed():
            return -1
        for idx in range(n_choices):
            vk = _CONFIRM_VKS[idx]
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                while ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                    time.sleep(0.02)
                return idx
        time.sleep(0.03)


def _get_monitor(monitor_index: int) -> dict:
    """Get monitor geometry from mss."""
    import mss as mss_lib
    with mss_lib.mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 1
        return dict(monitors[monitor_index])


def scale_to_screen(ref_x: int, ref_y: int, width: int, height: int) -> tuple[int, int]:
    """Convert 1920x1080 reference coordinates to physical screen coordinates.

    Uses uniform (letterbox/pillar-box) scaling so the game UI is treated as
    a fixed-aspect-ratio viewport centred inside the actual monitor, matching
    how Lost Ark renders on non-16:9 displays.

    Formula::

        s        = min(width / 1920, height / 1080)
        offset_x = (width  - 1920 * s) / 2
        offset_y = (height - 1080 * s) / 2
        screen_x = int(round(ref_x * s + offset_x))
        screen_y = int(round(ref_y * s + offset_y))

    On a native 1920x1080 monitor s == 1.0, both offsets are 0, and the
    mapping is the identity.  Rounding is ``int(round(...))`` (nearest
    integer) rather than bare ``int(...)`` (truncation); the old truncation
    was an unintended artifact of earlier code, not a deliberate choice, and
    nearest-integer rounding gives smaller maximum error across all scales.
    """
    s = min(width / 1920, height / 1080)
    offset_x = (width - 1920 * s) / 2
    offset_y = (height - 1080 * s) / 2
    return int(round(ref_x * s + offset_x)), int(round(ref_y * s + offset_y))


def _move_cursor(ref_x: int, ref_y: int, monitor: dict) -> None:
    """Move cursor to 1920x1080 reference coordinates, scaled to actual screen."""
    sx, sy = scale_to_screen(ref_x, ref_y, monitor["width"], monitor["height"])
    x = monitor["left"] + sx
    y = monitor["top"] + sy
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
    sx, sy = scale_to_screen(ref_x, ref_y, monitor["width"], monitor["height"])
    x = monitor["left"] + sx
    y = monitor["top"] + sy
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
    gem_type_domain: str,
    early_finish: bool = False,
    max_rerolls: int = 0,
    effect_aware: bool = True,
) -> Tuple[GoalProbabilityTable, frozenset, int, int]:
    """Build the DP probability table.

    Returns (table, target_effects, side_coeff_first, side_coeff_second).
    When effect_aware is True, results are cached by (goal, turns, gem_type,
    optimize, min_side_coeff, max_rerolls, early_finish) — the
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
            min_side_coeff, max_rerolls, early_finish,
        )
        cached = _DP_CACHE.get(cache_key)
        if cached is not None:
            return cached, target_effects, side_coeff_first, side_coeff_second

    if use_effect_aware:
        print(f"  [dp] Building effect-aware table "
              f"({gem_type_domain}, rerolls={max_rerolls})...", flush=True)
        t0 = time.time()
        table = cached_goal_table(
            goal, turns_total, pool,
            min_side_coeff=min_side_coeff,
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
        table = cached_goal_table(
            goal, turns_total, pool,
            bis_only=bis_only, target_effects=target_effects,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=min_side_coeff,
            early_finish=early_finish,
            max_rerolls=max_rerolls,
        )
    return table, target_effects, side_coeff_first, side_coeff_second




def _timed_table(label: str, build):
    """Build (or disk-load) a DP table with visible progress.

    Cold builds take seconds each and several run back-to-back per gem
    type — without output the auto loop looks hung before turn 1.
    """
    print(f"  [dp] {label}...", end="", flush=True)
    t0 = time.time()
    obj = build()
    print(f" ready in {time.time() - t0:.2f}s", flush=True)
    return obj


def _build_reset_table(
    goal: LastTurnGoal,
    turns_total: int,
    pool: OptionPool,
    *,
    gem_type_domain: str,
    optimize: str,
    min_side_coeff: int,
    effect_aware: bool = True,
) -> GoalProbabilityTable:
    """Build the standard (non-reroll) reset / p_fresh DP table.

    Mirrors ``GemSimulator._get_ea_tables``' reset table: effect-aware with the
    ``min_side_coeff`` floor when the gem type is known, so ``p_fresh`` and the
    offer-conditional ``p_keep_goal_reset`` price a ``--min-side-coeff`` goal
    exactly as the simulator does. A plain (non-effect-aware) table would drop
    the side-coeff requirement entirely and report over-optimistic fresh-start
    odds, diverging from the simulator's reset decisions. Falls back to the
    plain table only when the gem type is unknown (no effect/coeff info), which
    matches the goal prob_table's own fallback in ``_build_prob_table``.
    """
    if effect_aware and gem_type_domain in GEM_TYPES:
        return cached_goal_table(
            goal, turns_total, pool,
            min_side_coeff=min_side_coeff,
            early_finish=True,
            effect_aware=True, gem_type=gem_type_domain, optimize=optimize,
        )
    return cached_goal_table(goal, turns_total, pool, early_finish=True)


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


def _offer_signature(det) -> Optional[tuple]:
    """Signature of the 4 detected option cards, or None when the hand is
    not fully detected (mid-animation frames must not release the settle
    gate below on a garbled read)."""
    if len(det.options) != 4:
        return None
    sig = tuple((o.name_key, o.delta_key) for o in det.options)
    if any(not name for name, _ in sig):
        return None
    return sig


def _still_waiting(det_turn, det_rerolls, det_sig, waiting) -> bool:
    """Release predicate for the post-action settle gate.

    `waiting` is (turn, reroll_key, target_turn, offer_signature). Reset
    flows hold until the turn flips to `target_turn`; everything else
    releases when the turn or reroll counter changes. A Charge (ticket)
    reroll changes NEITHER — the free counter is already 0 and stays 0 —
    so for rerolls the pre-action offer signature is carried along and a
    fully-detected different hand releases the gate (regression: the gate
    used to wait forever after a Charge reroll).
    """
    wait_turn, wait_rerolls, target_turn, wait_offers = waiting
    if target_turn is not None:
        return det_turn != target_turn
    if det_turn != wait_turn or det_rerolls != wait_rerolls:
        return False
    if (wait_offers is not None and det_sig is not None
            and det_sig != wait_offers):
        return False
    return True


def _run_success(goal: LastTurnGoal, state: GemState, optimize: str,
                 bis_only: bool, min_side_coeff: int) -> bool:
    """End-of-gem success — mirrors `GemSimulator`'s check (goal +
    `bis_only` target effects + `min_side_coeff` floor) so the auto JSONL
    agrees with `sim` batches."""
    if not goal.satisfied(state.will, state.chaos, state.first, state.second):
        return False
    if bis_only:
        target = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        if (state.first_effect not in target
                or state.second_effect not in target):
            return False
    if min_side_coeff > 0:
        if GemAnalyzer._side_coeff(state, optimize) < min_side_coeff:
            return False
    return True


# ---------------------------------------------------------------------------
# Main automation loop
# ---------------------------------------------------------------------------

def run_auto(
    monitor_index: int,
    goal: LastTurnGoal,
    extra_ticket: Optional[bool],
    reset_ticket,  # bool | str (rarity threshold: common/rare/epic) | None
    optimize: str,
    bis_only: bool,
    min_side_coeff: int,
    prob_reset_threshold: float,
    side_threshold: float,
    animation_delay: float,
    dry_run: bool,
    astro_gem: Optional[AstroGem],
    reset_min_coeff: int,
    reroll_min_coeff: int,
    relic_reroll_threshold: float = 0.0,
    force_reroll_no_progress: int = 0,
    all_gems: bool = False,
    effect_aware_dp: bool = True,
    confirm_min_coeff: Optional[int] = None,
    endgame_risk: Optional[float] = None,
    relic_coeff: Optional[int] = None,
    ancient_coeff: Optional[int] = None,
    ignore_side_node_values: bool = False,
    reroll_goal: Optional[int] = None,
    reroll_goal_threshold: float = 0.0,
    args=None,
) -> None:
    """Run the full automation loop: detect → decide → click → repeat."""

    logger = RunLogger()
    logger.log_run_start(args, goal, astro_gem)

    confirm_active = confirm_min_coeff is not None
    confirm_min_coeff = confirm_min_coeff if confirm_min_coeff is not None else 0

    pool = OptionPool()
    monitor = _get_monitor(monitor_index)

    # Safety countdown
    print("=== Astrogem Auto Mode ===")
    print(f"Press Escape to stop.{' (DRY RUN)' if dry_run else ''}"
          f"{' [ALL GEMS]' if all_gems else ''}")
    print("(P(goal)~ is an optimistic estimate — reroll-aware DP)")
    if not dry_run:
        for i in range(3, 0, -1):
            if _is_stop_pressed():
                print("Aborted.")
                logger.log_run_end()
                logger.close()
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
        logger.log_gem_start(gem_count)
        gem_logged_detected = False
        # Buffer for a "process" action whose ``picked`` / ``state_after``
        # fields are only known once the next iteration's screen capture
        # reveals the new state. Reroll/reset/finish records are emitted
        # immediately and never use this buffer.
        pending_turn_record: Optional[dict] = None

        # Cached probability table (rebuilt if effects change)
        prob_table: Optional[GoalProbabilityTable] = None
        target_effects: frozenset = frozenset()
        side_coeff_first: int = 0
        side_coeff_second: int = 0
        cached_effects: Optional[Tuple[str, str]] = None
        p_fresh: Optional[float] = None
        decision_ctx: Optional[DecisionContext] = None
        reset_prob_table: Optional[GoalProbabilityTable] = None

        # Relic+ (>=16 total points) probability table — built on first detection
        relic_table: Optional[GoalProbabilityTable] = None

        # Will/chaos-total reroll-ticket override table — built once.
        reroll_goal_table: Optional[GoalProbabilityTable] = None

        # Side-value DP table — built on first detection.
        side_value_table: Optional[SideValueTable] = None

        # Goal-independent grade-value table for dead-goal turns — built on
        # first detection, only when relic/ancient grade has a coefficient.
        grade_value_table: Optional[SideValueTable] = None

        # Side-mode oracle for the will/chaos cap under
        # --ignore-side-node-values — built on first detection, flag-gated.
        maxed_value_table: Optional[SideValueTable] = None

        # Goal-conditioned expected side-coefficient table (no tier bonus) for
        # the per-turn --reroll-min-coeff ticket enabler — built on first
        # detection when the flag is set.
        expected_coeff_table: Optional[SideValueTable] = None

        # Auto-detected gem (from first screen capture)
        detected_gem: Optional[AstroGem] = astro_gem

        # Internal state tracking
        # Resolved against the gem's rarity once detection succeeds; until
        # then we optimistically enable it (any truthy --reset-ticket value).
        reset_available = bool(reset_ticket)
        # The reroll ticket is re-evaluated per turn (see
        # decision.ticket_enabled) — never banked. `ownable` = the player has
        # it; `extra_ticket_force_on` = --extra-ticket (always lent).
        # `extra_ticket_available` is the per-cutting-process lend gate: it
        # flips False once the ticket is actually spent (the in-game Charge
        # confirm) and RENEWS on a reset (a reset starts a fresh cutting
        # process). `extra_ticket_consumed` is the cumulative "was the reroll
        # ticket ever spent this run" report (never reset). A NEW gem (--all)
        # re-inits both via the outer loop.
        extra_ticket_force_on = (extra_ticket is True)
        ownable = (extra_ticket is not False)
        extra_ticket_available = ownable
        extra_ticket_consumed = False
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
        # (turn, reroll_key, target_turn, offer_signature). If target_turn is
        # set, wait until det_turn == target_turn (used for reset which always
        # returns to turn 1 — avoids clearing on mid-animation frames where
        # the reroll counter has already decremented but the turn hasn't
        # flipped yet). offer_signature is set for rerolls so a Charge
        # (ticket) reroll — which changes neither turn nor counter — releases
        # on the new hand (see _still_waiting).
        waiting_for_change: Optional[
            Tuple[int, Optional[str], Optional[int], Optional[tuple]]
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

            # --- Wait for state change (turn, reroll count, or — for a
            # Charge reroll, which changes neither — the offer cards) ---
            if waiting_for_change is not None:
                det_turn = det.total_steps - det.current_step + 1
                if _still_waiting(det_turn, det.rerolls,
                                  _offer_signature(det), waiting_for_change):
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

            if prob_table is None:
                temp_state = GemState(
                    first_effect=det.first_effect,
                    second_effect=det.second_effect,
                )
                rarity_name = RARITY_FROM_TOTAL_STEPS.get(det.total_steps, "rare")
                base_rerolls = GemSimulator.RARITY_REROLLS.get(rarity_name, 0)
                # The reroll ticket is lent per turn (at most +1). Size the
                # reroll-aware tables to cover free rerolls + the ticket whenever
                # the player owns it, so GoalProbabilityTable.lookup never clamps
                # the lent reroll (or the free+1 look-ahead in ticket_enabled).
                # Mirror the simulator's sizing exactly: +1 headroom when the
                # relic/goal ticket enablers do a "with the ticket" look-ahead,
                # so `sim` and `auto` gate the ticket identically.
                goal_reroll_lookahead = (reroll_goal is not None
                                         and reroll_goal_threshold > 0.0)
                dp_max_rerolls = base_rerolls + (1 if ownable else 0) + (
                    1 if (relic_reroll_threshold > 0.0
                          or goal_reroll_lookahead) else 0)
                prob_table, target_effects, side_coeff_first, side_coeff_second = (
                    _build_prob_table(
                        goal, det.total_steps, pool, temp_state,
                        bis_only, optimize, min_side_coeff,
                        gem_type_domain, early_finish=True,
                        max_rerolls=dp_max_rerolls,
                        effect_aware=effect_aware_dp,
                    ))
                # Relic+ table: built once. Always built — grade is part of
                # the side-value gem_value, so P(relic+)/P(ancient) always show.
                # Reroll-aware so should_reroll_dp() and reroll-aware lookups
                # in the goal-unreachable pivot give honest probabilities.
                if relic_table is None:
                    relic_table = _timed_table("relic+ table", lambda: cached_goal_table(
                        LastTurnGoal(min_total=16), det.total_steps, pool,
                        early_finish=False,
                        max_rerolls=dp_max_rerolls,
                    ))
                if (reroll_goal is not None and reroll_goal_threshold > 0.0
                        and reroll_goal_table is None):
                    reroll_goal_table = _timed_table("reroll-goal table", lambda: cached_goal_table(
                        LastTurnGoal(min_total_will_chaos=reroll_goal),
                        det.total_steps, pool,
                        early_finish=False,
                        max_rerolls=dp_max_rerolls,
                    ))
                # Use standard (non-reroll) DP for p_fresh — the reroll-aware
                # DP overestimates fresh start probability. Effect-aware with
                # the side-coeff floor (mirrors GemSimulator) so --min-side-coeff
                # goals are priced the same here as in simulation.
                reset_prob_table = _timed_table("reset table", lambda: _build_reset_table(
                    goal, det.total_steps, pool,
                    gem_type_domain=gem_type_domain, optimize=optimize,
                    min_side_coeff=min_side_coeff, effect_aware=effect_aware_dp,
                ))
                # p_fresh state carries the detected effects so the effect-aware
                # table resolves indices (a reset reverts to the gem's original
                # effects, matching this fresh-start state).
                p_fresh = reset_prob_table.lookup(
                    GemState(will=1, chaos=1, first=1, second=1,
                             first_effect=det.first_effect,
                             second_effect=det.second_effect),
                    det.total_steps,
                )
                # Side-value DP table: built once per gem type detected.
                if side_value_table is None:
                    side_value_table = _timed_table("side-value table", lambda: cached_side_value_table(
                        goal, det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=min_side_coeff,
                        relic_coeff=relic_coeff,
                        ancient_coeff=ancient_coeff,
                        value_mode=("will_chaos" if ignore_side_node_values
                                    else "side"),
                        max_rerolls=dp_max_rerolls,
                    ))
                # Goal-independent grade-value table (trivial goal, no
                # side-coeff floor) for dead-goal turns — built per gem type
                # like the side-value table; coeffs resolve to the fusion
                # default when unset. Always `grade_only`: a gem that missed
                # its goal won't be equipped, so only its fusion grade matters
                # and the dead-goal decision finishes once no higher grade is
                # reachable rather than chasing a worthless side coefficient.
                if grade_value_table is None:
                    grade_value_table = _timed_table("grade-value table", lambda: cached_side_value_table(
                        LastTurnGoal(), det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=0,
                        relic_coeff=relic_coeff,
                        ancient_coeff=ancient_coeff,
                        value_mode="grade_only",
                        max_rerolls=dp_max_rerolls,
                    ))
                # Side-mode oracle for the will/chaos cap under
                # --ignore-side-node-values (see decision._maxed_hold_decision).
                # Built only under the flag; the maxed branch never fires
                # otherwise, so it stays None for the default value model.
                if maxed_value_table is None and ignore_side_node_values:
                    maxed_value_table = _timed_table("maxed-oracle table", lambda: cached_side_value_table(
                        goal, det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=min_side_coeff,
                        relic_coeff=relic_coeff,
                        ancient_coeff=ancient_coeff,
                        value_mode="side",
                        max_rerolls=dp_max_rerolls,
                    ))
                # Goal-conditioned expected side-coefficient table (grade coeffs
                # forced to 0 -> value == E[side_coeff]) for the per-turn
                # --reroll-min-coeff ticket enabler. ~0 when the goal is dead.
                if expected_coeff_table is None and reroll_min_coeff > 0:
                    expected_coeff_table = _timed_table("expected-coeff table", lambda: cached_side_value_table(
                        goal, det.total_steps, pool,
                        gem_type=gem_type_domain, optimize=optimize,
                        min_side_coeff=min_side_coeff,
                        relic_coeff=0, ancient_coeff=0,
                        value_mode="side",
                    ))
                # DecisionContext is rebuilt here too — prob_table /
                # reset_prob_table / relic_table references may have just
                # changed, and force_reroll_active is resolved below.
                decision_ctx = None  # rebuilt after force_reroll_active is set

            # Re-detect gem and re-evaluate tickets when effects change
            if detected_gem is None or cached_effects != current_effects:
                detected_gem = AstroGem(
                    gem_type_domain, det.first_effect,
                    det.second_effect, optimize,
                )
                if not gem_logged_detected:
                    rarity_for_log = RARITY_FROM_TOTAL_STEPS.get(
                        det.total_steps, "rare")
                    logger.log_gem_detected(
                        gem_type=gem_type_domain,
                        rarity=rarity_for_log,
                        first_effect=det.first_effect,
                        second_effect=det.second_effect,
                        total_steps=det.total_steps,
                    )
                    gem_logged_detected = True
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
                    # NOTE: --reroll-min-coeff no longer arms the ticket here. It
                    # is one of the per-turn enablers in decision.ticket_enabled
                    # (expected side-coeff vs the bar), evaluated each turn below.
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
                decision_ctx = None  # rebuilt below now that gating is set

            # Rebuild DecisionContext if anything it depends on changed.
            if decision_ctx is None and prob_table is not None:
                rarity_name = RARITY_FROM_TOTAL_STEPS.get(det.total_steps, "rare")
                # Mirror the simulator's ctx.base_rerolls: rarity free rerolls
                # + the owned reroll ticket (GemSimulator.__init__ line 94).
                _base = GemSimulator.RARITY_REROLLS.get(rarity_name, 0) + (
                    1 if ownable else 0)
                decision_ctx = DecisionContext(
                    goal=goal,
                    pool=pool,
                    optimize=optimize,
                    bis_only=bis_only,
                    min_side_coeff=min_side_coeff,
                    prob_reset_threshold=prob_reset_threshold,
                    relic_reroll_threshold=relic_reroll_threshold,
                    force_reroll_no_progress=force_reroll_no_progress,
                    turns_total=det.total_steps,
                    base_rerolls=_base,
                    p_fresh=p_fresh or 0.0,
                    prob_table=prob_table,
                    reset_prob_table=reset_prob_table,
                    relic_prob_table=relic_table,
                    gem_type=gem_type_domain,
                    force_reroll_active=force_reroll_active,
                    confirm_active=confirm_active,
                    confirm_min_coeff=confirm_min_coeff,
                    endgame_risk=endgame_risk,
                    side_value_table=side_value_table,
                    grade_value_table=grade_value_table,
                    maxed_value_table=maxed_value_table,
                    extra_ticket_force_on=extra_ticket_force_on,
                    reroll_goal_prob_table=reroll_goal_table,
                    reroll_goal_threshold=reroll_goal_threshold,
                    reroll_min_coeff=reroll_min_coeff,
                    expected_coeff_table=expected_coeff_table,
                )

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

            # extra_ticket=False: analysis.reroll_count is now the FREE reroll
            # count (the on-screen number). The reroll ticket is lent per turn
            # below via decision.ticket_enabled — never folded into this count.
            analysis = _analyze_frame(
                det, goal, False,
                prob_table, target_effects, bis_only,
                override_reroll_count=reroll_override,
            )

            # --- Reroll-ticket per-turn lend ---
            # Re-evaluate the ticket every turn (never banked): lend +1 reroll to
            # the decision budget only when the ticket is still available and an
            # enabler clears its bar this turn. On a dead gem the enablers all go
            # false, so the ticket is not lent (and not spent).
            free_rerolls = analysis.reroll_count
            ticket_lent = (
                extra_ticket_available
                and decision_ctx is not None
                and ticket_enabled(decision_ctx, analysis.state,
                                   analysis.turns_left, free_rerolls))
            effective_rerolls = free_rerolls + (1 if ticket_lent else 0)

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
                              f"P(goal)~={analysis.p_current:.1%}")
                if relic_table is not None:
                    p_r = relic_table.lookup(s, analysis.turns_left,
                                             rerolls=analysis.reroll_count)
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

                if pending_turn_record is not None:
                    pending_turn_record["picked"] = picked
                    pending_turn_record["state_after"] = s.clone()
                    logger.log_turn(**pending_turn_record)
                    pending_turn_record = None

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
            relic_info = ""
            if relic_table is not None:
                p_r = relic_table.lookup(analysis.state, analysis.turns_left,
                                         rerolls=analysis.reroll_count)
                relic_info = f"  P(r+)={p_r:.1%}"
            print(f"Turn {analysis.current_turn}/{analysis.turns_total} "
                  f"(left={analysis.turns_left})  "
                  f"P(goal)~={analysis.p_current:.1%}{relic_info}  "
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
            # Single shared decision point with the simulator. All the
            # logic lives in arkgrid.decision.decide_post_roll so future
            # bugs surface in MC tests as well as live runs.
            pool_opts = _detected_to_options(
                det.options, analysis.option_probs, analysis.state)
            ti = TurnInput(
                state=analysis.state,
                offers=pool_opts,
                turn=analysis.current_turn,
                turns_left=analysis.turns_left,
                rerolls=effective_rerolls,  # free + lent ticket (per-turn)
                reset_available=(reset_available and not reset_used),
            )
            decision = decide_post_roll(decision_ctx, ti)

            if decision.needs_confirmation:
                print("  " + "=" * 50)
                print(f"  [CONFIRM] turn {analysis.current_turn}"
                      f"/{det.total_steps}  branch={decision.branch}")
                print(f"  {decision.reason}")
                _m = decision.metrics
                if "risk" in _m:
                    print(f"  P(lose goal if you continue): "
                          f"{_m['risk']:.0%}")
                if "side_coeff" in _m:
                    print(f"  side coefficient: {_m['side_coeff']}")
                if "p_keep_relic" in _m and _m["p_keep_relic"] > 0:
                    print(f"  P(relic+): {_m['p_keep_relic']:.0%}")
                print(f"  auto would: {decision.action.value}")
                for i, choice in enumerate(decision.confirm_choices):
                    print(f"    [F{i + 1}] {_CONFIRM_LABELS[choice]}")
                print("  (Escape aborts the run)")
                print("  " + "=" * 50, flush=True)
                _idx = _wait_for_confirm_key(len(decision.confirm_choices))
                if _idx < 0:
                    print("  [confirm] aborted")
                    stop_requested = True
                    break
                _chosen = decision.confirm_choices[_idx]
                logger.log_confirm(
                    turn=analysis.current_turn, branch=decision.branch,
                    auto_action=decision.action.value,
                    user_choice=_chosen.value,
                    metrics=dict(decision.metrics))
                decision = replace(decision, action=_chosen)

            _action_map = {
                ActionKind.PROCESS: "process",
                ActionKind.REROLL: "reroll",
                ActionKind.RESET: "reset",
                ActionKind.FINISH: "finish",
                ActionKind.FAIL: "finish",
            }
            action: Optional[str] = _action_map[decision.action]
            action_reason = decision.reason
            _action_label = {
                "process": "process",
                "reroll": "reroll",
                "reset": "RESET",
                "finish": "FINISH",
            }[action]
            if action == "reroll":
                print(f"  action:  {_action_label}  ({action_reason}, "
                      f"{analysis.reroll_count} rerolls left)")
            else:
                print(f"  action:  {_action_label} ({action_reason})")

            # --- Build the JSONL turn record for this decision ---
            p_relic_for_log: Optional[float] = None
            if relic_table is not None:
                p_relic_for_log = relic_table.lookup(
                    analysis.state, analysis.turns_left,
                    rerolls=analysis.reroll_count)
            turn_record_kwargs = dict(
                turn=analysis.current_turn,
                turns_left=analysis.turns_left,
                state_before=analysis.state.clone(),
                offers=list(analysis.option_labels),
                action=action,
                action_reason=action_reason,
                p_goal=analysis.p_current,
                p_relic=p_relic_for_log,
                rerolls=analysis.reroll_count,
            )
            if action == "process":
                # Picked / state_after only knowable next iteration.
                pending_turn_record = dict(turn_record_kwargs,
                                           picked=None, state_after=None)
            else:
                logger.log_turn(picked=None, state_after=None,
                                **turn_record_kwargs)

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
                    # Reset starts a fresh cutting process — the reroll ticket
                    # is granted again (renews; not persisted as spent).
                    extra_ticket_available = ownable
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
                waiting_for_change = (
                    analysis.current_turn, det.rerolls, target,
                    _offer_signature(det) if action == "reroll" else None)
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
            _reroll_ticket_confirm = False  # track whether this is the reroll ticket
            if action == "reset" and reset_available:
                needs_confirm = True
            elif action == "reroll" and ticket_lent and free_rerolls <= 0:
                # No free rerolls remain, so this reroll spends the lent ticket
                # (the in-game "Charge" button) — it needs the ticket-confirm
                # dialog, and consumes the ticket for the rest of the run.
                needs_confirm = True
                _reroll_ticket_confirm = True

            if needs_confirm:
                time.sleep(TICKET_CONFIRM_DELAY)
                # Let the dialog's fade-in finish before sampling the verify
                # pixel — a too-early read catches a mid-animation color and
                # fails the signature check below (see TICKET_VERIFY_SETTLE_DELAY).
                time.sleep(TICKET_VERIFY_SETTLE_DELAY)
                # F6: Guard against blind-clicking when the confirmation dialog
                # has not actually appeared (e.g. reroll-count tracking drifted).
                # _get_pixel_rgb returns -1 (CLR_INVALID) when the coordinate is
                # outside the screen's clipping region (off-screen); any other
                # read may come from either dialog variant or the live cutting
                # screen.
                pixel = _get_pixel_rgb(*TICKET_ITEM_CHECK_POS, monitor)
                # F6: Verify *which* confirm dialog is up before clicking.  Each
                # variant renders a distinct, deterministic pixel at
                # TICKET_ITEM_CHECK_POS: the item-ticket dialog shows the teal
                # pill (TICKET_ITEM_CHECK_RGB); the standard (no-item) dialog
                # shows a dark opaque panel (one of TICKET_STANDARD_CHECK_RGBS).
                # A read matching neither (including -1 / off-screen) means the dialog
                # never appeared — e.g. reroll-count tracking drifted — and the
                # cutting screen is still up, so we must NOT click.
                if pixel == TICKET_ITEM_CHECK_RGB:
                    # Positive confirmation: item-ticket dialog is present.
                    confirm_pos = BTN_CONFIRM_TICKET_WITH_ITEM
                    variant = f"item ticket, pixel={pixel:#08x}"
                elif pixel in TICKET_STANDARD_CHECK_RGBS:
                    # Positive confirmation: standard (no-item) dialog is present.
                    confirm_pos = BTN_CONFIRM_TICKET
                    variant = f"standard, pixel={pixel:#08x}"
                else:
                    # No dialog signature matched — skip the confirm click to
                    # avoid a misclick.  The reset/reroll button was already
                    # clicked this iteration but the confirm dialog was NOT
                    # confirmed, so the action has not completed and we must not
                    # record it as complete.  Set waiting_for_change so the loop
                    # pauses for the screen to settle and re-detects (guarding
                    # against an immediate re-decide that could double-click the
                    # action button), then continue to skip all post-action
                    # bookkeeping.
                    reason = ("pixel read failed" if pixel == -1
                              else f"unrecognized pixel {pixel:#08x}")
                    print(
                        f"  [warn] ticket-confirm dialog not verified "
                        f"({reason} at {TICKET_ITEM_CHECK_POS}) — skipping "
                        f"confirm click to avoid misclick on cutting screen"
                    )
                    target = 1 if action == "reset" else None
                    # No offer signature: the action did NOT complete (dialog
                    # unverified), so the hand is not expected to change.
                    waiting_for_change = (
                        analysis.current_turn, det.rerolls, target, None)
                    # Mirror the post-action bookkeeping block below (must stay
                    # in sync with prev_analysis / prev_action / prev_action_reason
                    # assignments at the end of the normal action path).
                    prev_analysis = analysis
                    prev_action = action
                    prev_action_reason = action_reason
                    time.sleep(animation_delay)
                    continue

                print(f"  >>> Confirming ticket ({variant})...",
                      end="", flush=True)
                _click(*confirm_pos, monitor)
                print(" done")
                # Reroll ticket spent (the Charge button): close the per-cutting-
                # process lend gate and record the cumulative consumption.
                if _reroll_ticket_confirm:
                    extra_ticket_available = False
                    extra_ticket_consumed = True

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
                # Reset starts a fresh cutting process — the reroll ticket is
                # granted again (renews; not persisted as spent).
                extra_ticket_available = ownable
                turn_history.append({
                    "turn": analysis.current_turn,
                    "rerolls_used": current_turn_rerolls,
                    "action": "reset",
                    "action_reason": action_reason,
                })
                current_turn_rerolls = 0

            # F4: also guard after reroll — block re-decision until the
            # reroll count decrements on-screen (or, for a Charge reroll
            # where it can't, until the offer cards change), confirming the
            # animation has settled and the new offer set is visible.
            if action in ("process", "reset", "reroll"):
                target = 1 if action == "reset" else None
                waiting_for_change = (
                    analysis.current_turn, det.rerolls, target,
                    _offer_signature(det) if action == "reroll" else None)

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
                            f"P(goal)~={entry['p_goal']:.1%}  "
                            f"EARLY FINISH{reason_part}")
                    print(line)
                else:
                    sa = entry["state_after"]
                    act = entry.get("action", "process")
                    line = (f"  Turn {entry['turn']}: "
                            f"w={sa['will']} c={sa['chaos']} "
                            f"1st={sa['first']} 2nd={sa['second']}  "
                            f"(total={sa['total']})  "
                            f"P(goal)~={entry['p_goal']:.1%}")
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

        # --- Emit gem_end JSONL record ---
        if finish_state and prev_analysis:
            final_state_obj = GemState(
                will=finish_state["will"],
                chaos=finish_state["chaos"],
                first=finish_state["first"],
                second=finish_state["second"],
                first_effect=prev_analysis.state.first_effect,
                second_effect=prev_analysis.state.second_effect,
            )
        elif prev_analysis:
            final_state_obj = prev_analysis.state.clone()
        else:
            final_state_obj = GemState()

        side_coeff_value = GemAnalyzer._side_coeff(final_state_obj, optimize)
        success = _run_success(goal, final_state_obj, optimize,
                               bis_only, min_side_coeff)

        if pending_turn_record is not None:
            pending_turn_record["state_after"] = final_state_obj
            if pending_turn_record.get("picked") is None and prev_analysis is not None:
                pending_turn_record["picked"] = _infer_picked(
                    prev_analysis.state, final_state_obj)
            logger.log_turn(**pending_turn_record)
            pending_turn_record = None

        if stop_requested:
            reason = "stopped"
        elif prev_action == "finish":
            reason = "early_finish"
        elif gem_completed:
            reason = "ran_to_end"
        else:
            reason = "incomplete"

        logger.log_gem_end(
            success=success,
            total_points=final_state_obj.total_points(),
            side_coeff=side_coeff_value,
            reset_used=reset_used,
            extra_ticket_used=extra_ticket_consumed,
            final_state=final_state_obj,
            reason=reason,
        )

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

    # Close log files and restore stdout
    logger.log_run_end()
    log_path = logger.log_path
    jsonl_path = logger.jsonl_path
    logger.close()
    print(f"Log saved to: {log_path}")
    print(f"JSONL saved to: {jsonl_path}")
