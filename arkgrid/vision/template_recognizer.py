"""Template-matching screen recognition.

Detects full game state from a screenshot using pre-cropped template
images matched via cv2.matchTemplate (TM_CCOEFF_NORMED).
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from . import constants as C
from .matcher import find_best_match
from .templates import TemplateStore

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OptionDetection:
    """One of the 4 detected option cards."""
    name_key: Optional[str] = None     # "attack_power", "will", "chaos", ...
    name_score: float = 0.0
    delta_key: Optional[str] = None    # "1_line_lvl+3", "cost+100", ...
    delta_score: float = 0.0


@dataclass
class FinishDetectionResult:
    """Recognition output for the finish/result screen."""
    found: bool = False
    willpower: Optional[int] = None
    willpower_score: float = 0.0
    chaos: Optional[int] = None
    chaos_score: float = 0.0
    first_level: Optional[int] = None
    first_level_score: float = 0.0
    second_level: Optional[int] = None
    second_level_score: float = 0.0


@dataclass
class DetectionResult:
    """Full recognition output for one frame."""
    found: bool = False

    # Gem info
    gem_type: Optional[str] = None         # template key: "chaos_corrosion"
    gem_type_score: float = 0.0

    # Diamond stats (1-5)
    willpower: Optional[int] = None
    willpower_score: float = 0.0
    chaos: Optional[int] = None
    chaos_score: float = 0.0

    # Side nodes
    first_effect: Optional[str] = None     # "attack_power", "ally_damage", ...
    first_effect_score: float = 0.0
    first_level: Optional[int] = None
    first_level_score: float = 0.0
    second_effect: Optional[str] = None
    second_effect_score: float = 0.0
    second_level: Optional[int] = None
    second_level_score: float = 0.0

    # Rerolls
    rerolls: Optional[str] = None          # "0_ticket_available", "1", "2", ...
    rerolls_score: float = 0.0

    # Turn info
    current_step: Optional[int] = None     # 1-9
    step_score: float = 0.0
    total_steps: Optional[int] = None      # 5, 7, or 9
    rarity_score: float = 0.0

    # 4 option cards
    options: List[OptionDetection] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Template cache (loaded once)
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_cache: Dict[str, Dict[str, np.ndarray]] = {}
_store: Optional[TemplateStore] = None

_VARIANT_SUFFIX = re.compile(r"_\d+$")


def _strip_variant(key: str) -> str:
    """'additional_damage_01' -> 'additional_damage'."""
    return _VARIANT_SUFFIX.sub("", key)


def _load(base_dir: str, subdir: str) -> Dict[str, np.ndarray]:
    """Load all PNG templates from base_dir/subdir/ as grayscale, with caching."""
    cache_key = os.path.join(base_dir, subdir)
    if cache_key in _cache:
        return _cache[cache_key]
    d = os.path.join(base_dir, subdir)
    templates = {}
    if os.path.isdir(d):
        for path in sorted(glob.glob(os.path.join(d, "*.png"))):
            key = os.path.splitext(os.path.basename(path))[0]
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                templates[key] = img
    _cache[cache_key] = templates
    return templates


def _get_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def _match(crop: np.ndarray, templates: Dict[str, np.ndarray],
           strip_variants: bool = False
           ) -> Tuple[Optional[str], float]:
    """Find best matching template in crop. Returns (key, score)."""
    best_key: Optional[str] = None
    best_score = 0.0

    for key, tmpl in templates.items():
        if tmpl.shape[0] > crop.shape[0] or tmpl.shape[1] > crop.shape[1]:
            continue
        result = cv2.matchTemplate(crop, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = max_val
            best_key = key

    if strip_variants and best_key:
        best_key = _strip_variant(best_key)
    return best_key, best_score


def _crop_roi(gray: np.ndarray, ax: int, ay: int,
              roi: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
    """Crop an anchor-relative ROI."""
    dx, dy, w, h = roi
    x, y = ax + dx, ay + dy
    fh, fw = gray.shape[:2]
    x, y = max(0, x), max(0, y)
    w = min(w, fw - x)
    h = min(h, fh - y)
    if w <= 0 or h <= 0:
        return None
    return gray[y:y + h, x:x + w]


def _side_node_level(delta_key: Optional[str]) -> Optional[int]:
    """Extract level from '2_line_lvl3' -> 3."""
    if not delta_key:
        return None
    m = re.search(r"lvl(\d)", delta_key)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Main detection
# ---------------------------------------------------------------------------

def detect(frame_bgr: np.ndarray) -> DetectionResult:
    """Detect full game state from a BGR screenshot.

    Normalizes to FHD, finds anchor, then runs template matching on
    all ROI regions. Returns structured DetectionResult.
    """
    result = DetectionResult()
    tdir = str(_TEMPLATES_DIR)

    # Normalize to FHD
    h, w = frame_bgr.shape[:2]
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        frame_bgr = cv2.resize(frame_bgr, (C.REF_WIDTH, C.REF_HEIGHT),
                                interpolation=cv2.INTER_AREA)

    if len(frame_bgr.shape) == 3:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame_bgr

    # Find anchor
    store = _get_store()
    anchors = store.get_anchor()
    if not anchors:
        return result
    match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                            threshold=C.THRESHOLD_ANCHOR)
    if match is None:
        return result

    result.found = True
    ax, ay = match.location

    # --- Gem type ---
    crop = _crop_roi(gray, ax, ay, C.ROI_GEM_TYPE)
    if crop is not None:
        gem_templates = _load(tdir, "gem_type")
        key, score = _match(crop, gem_templates, strip_variants=True)
        result.gem_type = key
        result.gem_type_score = score

    # --- Willpower ---
    crop = _crop_roi(gray, ax, ay, C.ROI_STAT_WILLPOWER)
    if crop is not None:
        wp_templates = _load(tdir, "willpower")
        key, score = _match(crop, wp_templates, strip_variants=True)
        if key and key.isdigit():
            result.willpower = int(key)
        result.willpower_score = score

    # --- Chaos ---
    crop = _crop_roi(gray, ax, ay, C.ROI_STAT_CHAOS)
    if crop is not None:
        ch_templates = _load(tdir, "chaos")
        key, score = _match(crop, ch_templates, strip_variants=True)
        if key and key.isdigit():
            result.chaos = int(key)
        result.chaos_score = score

    # --- Rerolls ---
    crop = _crop_roi(gray, ax, ay, C.ROI_REROLL)
    if crop is not None:
        rr_templates = _load(tdir, "rerolls")
        key, score = _match(crop, rr_templates, strip_variants=True)
        result.rerolls = key
        result.rerolls_score = score

    # --- Steps + Rarity (both from same crop) ---
    crop = _crop_roi(gray, ax, ay, C.ROI_PROCESS_STEPS)
    if crop is not None:
        # Current step
        st_templates = _load(tdir, "steps")
        key, score = _match(crop, st_templates, strip_variants=True)
        if key and key.isdigit():
            result.current_step = int(key)
        result.step_score = score

        # Rarity (total steps from same crop)
        ra_templates = _load(tdir, "rarity")
        key, score = _match(crop, ra_templates, strip_variants=True)
        if key and key in C.RARITY_TOTAL_STEPS:
            result.total_steps = C.RARITY_TOTAL_STEPS[key]
        result.rarity_score = score

    # --- Side nodes ---
    sn_name_templates = _load(os.path.join(tdir, "side_nodes"), "names")
    sn_delta_templates = _load(os.path.join(tdir, "side_nodes"), "deltas")

    for attr_prefix, roi in [("first", C.ROI_STAT_FIRST),
                              ("second", C.ROI_STAT_SECOND)]:
        crop = _crop_roi(gray, ax, ay, roi)
        if crop is None:
            continue

        name_key, name_score = _match(crop, sn_name_templates,
                                       strip_variants=True)
        delta_key, delta_score = _match(crop, sn_delta_templates)
        lvl = _side_node_level(delta_key)

        setattr(result, f"{attr_prefix}_effect", name_key)
        setattr(result, f"{attr_prefix}_effect_score", name_score)
        setattr(result, f"{attr_prefix}_level", lvl)
        setattr(result, f"{attr_prefix}_level_score", delta_score)

    # --- Option cards ---
    opt_name_templates = _load(os.path.join(tdir, "options"), "names")
    opt_delta_templates = _load(os.path.join(tdir, "options"), "deltas")

    for dx, card_w in C.OPTION_CARD_POSITIONS:
        card_x = ax + dx
        card_y = ay + C.OPTION_CARD_Y_OFFSET
        card_crop = gray[card_y:card_y + C.OPTION_CARD_HEIGHT,
                         card_x:card_x + card_w]

        name_key, name_score = _match(card_crop, opt_name_templates,
                                       strip_variants=True)
        delta_key, delta_score = _match(card_crop, opt_delta_templates)

        result.options.append(OptionDetection(
            name_key=name_key,
            name_score=name_score,
            delta_key=delta_key,
            delta_score=delta_score,
        ))

    return result


# ---------------------------------------------------------------------------
# Helpers for interpreting detection results
# ---------------------------------------------------------------------------

def parse_rerolls(reroll_key: Optional[str], extra_ticket: bool = False) -> int:
    """Convert reroll template key to integer count.

    If extra_ticket is True, adds +1 unless the key indicates the ticket
    is unavailable ('0_ticket_not_available').
    """
    if reroll_key is None:
        return 0
    if reroll_key == "0_ticket_not_available":
        return 0
    if reroll_key == "0_ticket_available":
        return 1 if extra_ticket else 0
    # Strip variant suffix for keys like "1_01" -> "1"
    base = _strip_variant(reroll_key)
    try:
        count = int(base)
    except ValueError:
        return 0
    if extra_ticket:
        count += 1
    return count


def parse_delta(delta_key: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """Parse a delta template key into (kind_hint, delta_value).

    Returns:
        kind_hint: "lvl", "points", "cost", "reroll", "effect_changed",
                   "maintained", or None
        delta_value: signed int (e.g. +3, -1) or None for non-stat deltas

    Examples:
        "1_line_lvl+3"       -> ("lvl", 3)
        "2_line_+2"          -> ("points", 2)
        "1_line_-1"          -> ("points", -1)
        "cost+100"           -> ("cost", None)
        "reroll+1"           -> ("reroll", None)
        "1_line_effect_changed" -> ("effect_changed", None)
        "maintained"         -> ("maintained", None)
    """
    if not delta_key:
        return None, None

    # Strip line prefix
    d = delta_key
    for prefix in ("1_line_", "2_line_"):
        if d.startswith(prefix):
            d = d[len(prefix):]
            break

    if d.startswith("lvl"):
        m = re.match(r"lvl([+-]?\d+)", d)
        if m:
            return "lvl", int(m.group(1))
        return "lvl", None
    elif d == "effect_changed":
        return "effect_changed", None
    elif d == "maintained":
        return "maintained", None
    elif d.startswith("cost"):
        return "cost", None
    elif d.startswith("reroll"):
        return "reroll", None
    else:
        # "+3", "-1", etc.
        m = re.match(r"([+-]?\d+)", d)
        if m:
            return "points", int(m.group(1))
        return None, None


def determine_option_kind(
    name_key: Optional[str],
    delta_key: Optional[str],
    first_effect: str,
    second_effect: str,
) -> Tuple[str, Optional[int]]:
    """Map a detected option to (pool_kind, stat_delta).

    pool_kind is one of: "will", "chaos", "first", "second",
    "cost", "view", "other".
    stat_delta is the signed change to the relevant stat, or None
    for options that don't change will/chaos/first/second.
    """
    kind_hint, delta_val = parse_delta(delta_key)

    if name_key == "will":
        return "will", delta_val
    elif name_key in ("chaos", "order"):
        return "chaos", delta_val
    elif name_key == "cost":
        return "cost", None
    elif name_key == "view":
        return "view", None
    elif name_key == "maintain":
        return "other", None
    elif kind_hint == "effect_changed":
        # Determine which effect is being changed
        if name_key == first_effect:
            return "other", None  # change_first_effect
        elif name_key == second_effect:
            return "other", None  # change_second_effect
        return "other", None
    elif kind_hint == "maintained":
        return "other", None
    else:
        # Side effect option (attack_power, additional_damage, etc.)
        if name_key == first_effect:
            return "first", delta_val
        elif name_key == second_effect:
            return "second", delta_val
        # Fallback: can't determine
        return "other", delta_val


# ---------------------------------------------------------------------------
# Finish screen detection
# ---------------------------------------------------------------------------

def detect_finish(frame_bgr: np.ndarray) -> FinishDetectionResult:
    """Detect finish screen stats from a BGR screenshot.

    The finish screen is identified by the absence of the cutting anchor
    and the presence of 4 stat digits at known absolute positions.
    Returns FinishDetectionResult with found=True when >= 3 stats matched.
    """
    result = FinishDetectionResult()
    tdir = str(_TEMPLATES_DIR)

    # Normalize to FHD
    h, w = frame_bgr.shape[:2]
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        frame_bgr = cv2.resize(frame_bgr, (C.REF_WIDTH, C.REF_HEIGHT),
                                interpolation=cv2.INTER_AREA)

    if len(frame_bgr.shape) == 3:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame_bgr

    # Verify anchor is NOT found (finish screen has no cutting UI)
    store = _get_store()
    anchors = store.get_anchor()
    if anchors:
        match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                                threshold=C.THRESHOLD_ANCHOR)
        if match is not None:
            return result  # Still on cutting screen

    # Load finish digit templates (1-5)
    finish_templates = _load(tdir, "finish")
    if not finish_templates:
        return result

    attrs = [
        ("willpower", "willpower_score"),
        ("chaos", "chaos_score"),
        ("first_level", "first_level_score"),
        ("second_level", "second_level_score"),
    ]

    matched_count = 0
    fh, fw = gray.shape[:2]
    for (attr, score_attr), (x, y, rw, rh) in zip(attrs, C.FINISH_STAT_POSITIONS):
        cx = max(0, x)
        cy = max(0, y)
        cw = min(rw, fw - cx)
        ch = min(rh, fh - cy)
        if cw <= 0 or ch <= 0:
            continue
        crop = gray[cy:cy + ch, cx:cx + cw]
        key, score = _match(crop, finish_templates)
        if key and key.isdigit() and score >= C.THRESHOLD_FINISH:
            setattr(result, attr, int(key))
            setattr(result, score_attr, score)
            matched_count += 1

    result.found = matched_count >= 3
    return result
