"""Core template matching wrappers.

Ported from the TypeScript project's ``matcher.ts`` – wraps
``cv2.matchTemplate`` with ROI support, threshold filtering, and
best-of-N matching across a dictionary of templates.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from .constants import Roi


@dataclass
class MatchResult:
    """Result of a single template match."""
    key: str
    score: float
    location: Tuple[int, int]          # (x, y) top-left in full frame coords
    template_size: Tuple[int, int]     # (w, h)


def find_template(
    frame: np.ndarray,
    template: np.ndarray,
    roi: Optional[Roi] = None,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Tuple[float, Tuple[int, int]]:
    """Find *template* in *frame* (optionally within *roi*).

    Returns ``(score, (x, y))`` where the location is in full-frame
    coordinates (ROI offset is added back).
    """
    ox, oy = 0, 0
    target = frame
    if roi is not None:
        rx, ry, rw, rh = roi
        # Clamp to frame bounds
        rx = max(0, rx)
        ry = max(0, ry)
        rw = min(rw, frame.shape[1] - rx)
        rh = min(rh, frame.shape[0] - ry)
        if rw <= 0 or rh <= 0:
            return 0.0, (0, 0)
        target = frame[ry:ry + rh, rx:rx + rw]
        ox, oy = rx, ry

    # Template must fit inside target
    if template.shape[0] > target.shape[0] or template.shape[1] > target.shape[1]:
        return 0.0, (0, 0)

    result = cv2.matchTemplate(target, template, method)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    # Convert location back to full-frame coords
    x = max_loc[0] + ox
    y = max_loc[1] + oy
    return float(max_val), (x, y)


def find_best_match(
    frame: np.ndarray,
    templates: Dict[str, np.ndarray],
    roi: Optional[Roi] = None,
    threshold: float = 0.8,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Optional[MatchResult]:
    """Try all *templates*, return the best scoring match above *threshold*.

    This mirrors the TypeScript ``getBestMatch()`` function from
    ``matcher.ts``, which iterates atlas entries and returns the highest
    scoring match.
    """
    best: Optional[MatchResult] = None

    for key, tmpl in templates.items():
        score, loc = find_template(frame, tmpl, roi=roi, method=method)
        if score >= threshold and (best is None or score > best.score):
            best = MatchResult(
                key=key,
                score=score,
                location=loc,
                template_size=(tmpl.shape[1], tmpl.shape[0]),
            )

    return best


def find_all_matches(
    frame: np.ndarray,
    templates: Dict[str, np.ndarray],
    roi: Optional[Roi] = None,
    threshold: float = 0.8,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> list[MatchResult]:
    """Return *all* template matches above *threshold*, sorted by score descending."""
    matches: list[MatchResult] = []

    for key, tmpl in templates.items():
        score, loc = find_template(frame, tmpl, roi=roi, method=method)
        if score >= threshold:
            matches.append(MatchResult(
                key=key,
                score=score,
                location=loc,
                template_size=(tmpl.shape[1], tmpl.shape[0]),
            ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches
