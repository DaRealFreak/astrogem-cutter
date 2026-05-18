"""Extract template-candidate crops from astrogem-cutting screenshots.

Consolidates the old extract_templates / extract_new / debug_regions /
debug_measure / recognize_all / dedup_templates / test_ocr scripts.

For each screenshot it crops every template-able region, grouped by region
type into the output directory, plus a debug overlay so region alignment can
be eyeballed after a UI change. Sorting the crops into the real template
folders is left to the user.

Usage:
    python tools/extract_templates.py                      # all examples/*.jpg
    python tools/extract_templates.py shotA.jpg shotB.jpg   # specific files
    python tools/extract_templates.py --out some/dir/       # custom output dir
"""

import argparse
import glob
import os
import sys
from typing import Dict, List, Optional, Tuple

# Run as `python tools/extract_templates.py`: add the project root to
# sys.path so `arkgrid` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from arkgrid.vision import constants as C
from arkgrid.vision.matcher import find_best_match
from arkgrid.vision.templates import TemplateStore

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "tools", "extracted")
EXAMPLES_DIR = os.path.join(PROJECT_ROOT, "examples")

# (category, anchor-relative ROI) for regions cropped exactly once.
_SINGLE_REGIONS: List[Tuple[str, Tuple[int, int, int, int]]] = [
    ("gem_type", C.ROI_GEM_TYPE),
    ("points", C.ROI_POINTS),
    ("willpower", C.ROI_STAT_WILLPOWER),
    ("chaos", C.ROI_STAT_CHAOS),
    ("rerolls", C.ROI_REROLL),
    ("steps", C.ROI_PROCESS_STEPS),
]


def _crop(gray: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
    """Crop a region, clamped to the frame bounds. None if it would be empty."""
    fh, fw = gray.shape[:2]
    # Clamp the origin into the frame, shrinking width/height by the same
    # amount so a partially off-frame ROI does not over-extend.
    x0, y0 = x, y
    x, y = max(0, x), max(0, y)
    w = min(w - (x - x0), fw - x)
    h = min(h - (y - y0), fh - y)
    if w <= 0 or h <= 0:
        return None
    return gray[y:y + h, x:x + w]


def _to_fhd_gray(frame_bgr: np.ndarray) -> np.ndarray:
    """Normalise to the 1920x1080 reference resolution and convert to gray."""
    h, w = frame_bgr.shape[:2]
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        frame_bgr = cv2.resize(frame_bgr, (C.REF_WIDTH, C.REF_HEIGHT),
                               interpolation=cv2.INTER_AREA)
    if len(frame_bgr.shape) == 3:
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return frame_bgr


def find_anchor(gray: np.ndarray, store: TemplateStore
                ) -> Optional[Tuple[int, int]]:
    """Locate the 'Processing' anchor. Returns its (x, y) or None."""
    anchors = store.get_anchor()
    if not anchors:
        return None
    match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                            threshold=C.THRESHOLD_ANCHOR)
    return match.location if match else None


def extract_regions(gray: np.ndarray, anchor: Tuple[int, int]
                     ) -> Dict[str, List[Tuple[str, np.ndarray]]]:
    """Crop every cutting-screen region. `gray` must be FHD grayscale.

    Returns {category: [(label, crop), ...]}. `label` is the region name
    used in the output filename (no screenshot prefix, no extension).
    Categories with no successful crop are omitted.
    """
    ax, ay = anchor
    out: Dict[str, List[Tuple[str, np.ndarray]]] = {}

    def add(category: str, label: str, crop: Optional[np.ndarray]) -> None:
        if crop is not None and crop.size > 0:
            out.setdefault(category, []).append((label, crop))

    # The anchor itself.
    add("anchor", "anchor",
        _crop(gray, ax, ay, C.ANCHOR_SIZE[0], C.ANCHOR_SIZE[1]))

    # Fixed single-crop anchor-relative regions.
    for category, (dx, dy, w, h) in _SINGLE_REGIONS:
        add(category, category, _crop(gray, ax + dx, ay + dy, w, h))

    return out


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract template-candidate crops from screenshots.")
    parser.add_argument("images", nargs="*",
                        help="Screenshot paths (default: examples/*.jpg)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Output directory (default: {DEFAULT_OUT})")
    parser.parse_args(argv)
    print("extract_templates: not yet implemented")


if __name__ == "__main__":
    main()
