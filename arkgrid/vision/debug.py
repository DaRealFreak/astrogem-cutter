"""Debug visualization – draw ROI rectangles and match results.

Ported from the TypeScript project's ``debug.ts`` ``showMatch()`` function.
"""

from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import constants as C
from .matcher import MatchResult
from .recognizer import RecognitionResult


def draw_debug(
    frame_bgr: np.ndarray,
    result: RecognitionResult,
) -> np.ndarray:
    """Draw debug overlay on a copy of the frame.

    - White rectangles: ROI search areas
    - Green rectangles + score: matches above threshold
    - Red rectangles + score: matches below threshold (if any recorded)
    - Text labels for recognized values
    """
    debug = frame_bgr.copy()
    h, w = debug.shape[:2]

    # Normalize to FHD if needed (for consistent drawing)
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        debug = cv2.resize(debug, (C.REF_WIDTH, C.REF_HEIGHT))

    if not result.found or result.anchor_location is None:
        cv2.putText(debug, "ANCHOR NOT FOUND", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        return debug

    ax, ay = result.anchor_location

    # Draw anchor
    _draw_roi(debug, C.ANCHOR_SEARCH_ROI, "ANCHOR_SEARCH", (100, 100, 100))
    cv2.rectangle(debug,
                  (ax, ay),
                  (ax + C.ANCHOR_SIZE[0], ay + C.ANCHOR_SIZE[1]),
                  (0, 255, 0), 2)
    cv2.putText(debug, f"ANCHOR {result.anchor_score:.2f}",
                (ax, ay - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    # Draw ROI regions
    _draw_anchor_roi(debug, ax, ay, C.ROI_SUBTITLE, "SUBTITLE", (255, 255, 0))
    _draw_anchor_roi(debug, ax, ay, C.ROI_STAT_WILLPOWER, "WILL", (0, 200, 255))
    _draw_anchor_roi(debug, ax, ay, C.ROI_STAT_FIRST_NAME, "1st_NAME", (0, 255, 200))
    _draw_anchor_roi(debug, ax, ay, C.ROI_STAT_FIRST_LV, "1st_LV", (0, 255, 200))
    _draw_anchor_roi(debug, ax, ay, C.ROI_STAT_SECOND_NAME, "2nd_NAME", (200, 255, 0))
    _draw_anchor_roi(debug, ax, ay, C.ROI_STAT_SECOND_LV, "2nd_LV", (200, 255, 0))
    _draw_anchor_roi(debug, ax, ay, C.ROI_STAT_CHAOS, "CHAOS", (0, 200, 200))
    _draw_anchor_roi(debug, ax, ay, C.ROI_PROCESS_BUTTON, "PROCESS_BTN", (255, 0, 255))

    # Draw option card ROIs
    for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
        card_roi = (ax + dx, ay + C.OPTION_CARD_Y_OFFSET,
                    card_w, C.OPTION_CARD_HEIGHT)
        _draw_roi(debug, card_roi, f"OPT{i+1}", (0, 128, 255))

    # Draw all match results
    for label, match in result.debug_matches:
        if match is not None:
            _draw_match(debug, match, label)

    # Draw recognized state as text overlay
    _draw_state_text(debug, result)

    return debug


def _draw_roi(
    img: np.ndarray,
    roi: Tuple[int, int, int, int],
    label: str,
    color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    """Draw a ROI rectangle with label."""
    x, y, w, h = roi
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 1)
    cv2.putText(img, label, (x, y - 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)


def _draw_anchor_roi(
    img: np.ndarray,
    ax: int, ay: int,
    relative_roi: Tuple[int, int, int, int],
    label: str,
    color: Tuple[int, int, int],
) -> None:
    """Draw an anchor-relative ROI."""
    dx, dy, w, h = relative_roi
    _draw_roi(img, (ax + dx, ay + dy, w, h), label, color)


def _draw_match(
    img: np.ndarray,
    match: MatchResult,
    label: str,
) -> None:
    """Draw a match result (green if good score, yellow if marginal)."""
    x, y = match.location
    w, h = match.template_size
    color = (0, 255, 0) if match.score > 0.8 else (0, 255, 255)
    cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
    cv2.putText(img, f"{label} {match.score:.2f}",
                (x, y + h + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)


def _draw_state_text(img: np.ndarray, result: RecognitionResult) -> None:
    """Draw the recognized state as a text panel in the top-right corner."""
    lines = []

    if result.gem_attr or result.gem_type:
        lines.append(f"Gem: {result.gem_attr or '?'} {result.gem_type or '?'}")
    if result.gem_info_ocr:
        lines.append(f"Gem OCR: {result.gem_info_ocr}")

    stats = []
    if result.willpower is not None:
        stats.append(f"W={result.willpower}")
    if result.chaos is not None:
        stats.append(f"C={result.chaos}")
    if result.first_level is not None:
        stats.append(f"1st={result.first_level}")
    if result.second_level is not None:
        stats.append(f"2nd={result.second_level}")
    if stats:
        lines.append("Stats: " + " ".join(stats))

    for opt in result.options:
        name = opt.name_text or "?"
        delta = opt.delta_text or ""
        src = "T" if opt.name_match else ("O" if opt.name_ocr else "?")
        lines.append(f"  Opt{opt.card_index+1}[{src}]: {name} {delta}")

    if result.current_turn is not None:
        lines.append(f"Turn: {result.current_turn}/{result.total_turns}")
    elif result.turn_text_ocr:
        lines.append(f"Turn OCR: {result.turn_text_ocr}")

    # Draw background panel
    x0, y0 = 1400, 30
    line_h = 16
    panel_h = len(lines) * line_h + 10
    panel_w = 500
    cv2.rectangle(img, (x0, y0), (x0 + panel_w, y0 + panel_h),
                  (0, 0, 0), cv2.FILLED)
    cv2.rectangle(img, (x0, y0), (x0 + panel_w, y0 + panel_h),
                  (200, 200, 200), 1)

    for i, line in enumerate(lines):
        cv2.putText(img, line, (x0 + 5, y0 + 14 + i * line_h),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
