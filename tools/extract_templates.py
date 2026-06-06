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

# ---------------------------------------------------------------------------
# Extraction-specific sub-region offsets. Kept here (not in
# arkgrid/vision/constants.py) because the runtime recogniser crops whole
# cards and matches by sub-image search, so it never needs them.
#
# An effect name is 1 or 2 text lines; the delta/Lv. indicator sits on the
# line below it, so its vertical position shifts when the name wraps. The
# tool does not detect the line count -- it emits the name crop AND the
# delta crop at BOTH offsets and the user keeps the matching pair.
#
# Each tuple is (dx, dy, w, h) relative to the parent crop's top-left corner.
# ---------------------------------------------------------------------------

# Within an option card (C.OPTION_CARD_POSITIONS width x C.OPTION_CARD_HEIGHT,
# i.e. 117 x 70). The name itself is 1 or 2 text lines, so -- like the delta
# -- it is cropped at two sizes: the 1-line crop stops above the delta line,
# the 2-line crop extends one line lower to cover the wrapped name.
OPT_NAME_1LINE = (0, 6, 117, 28)
OPT_NAME_2LINE = (0, 6, 117, 38)
OPT_DELTA_1LINE = (0, 34, 117, 25)
OPT_DELTA_2LINE = (0, 44, 117, 25)

# Within a side node (C.ROI_STAT_FIRST width x height, i.e. 102 x 57).
SN_NAME_1LINE = (0, 5, 102, 25)
SN_NAME_2LINE = (0, 5, 102, 34)
SN_LV_1LINE = (0, 30, 102, 22)
SN_LV_2LINE = (0, 39, 102, 18)


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

    # Option cards (x4): name crop + delta crop, each at both line offsets.
    for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
        card = _crop(gray, ax + dx, ay + C.OPTION_CARD_Y_OFFSET,
                     card_w, C.OPTION_CARD_HEIGHT)
        if card is None:
            continue
        n = i + 1
        for variant, (nx, ny, nw, nh) in (("1line", OPT_NAME_1LINE),
                                          ("2line", OPT_NAME_2LINE)):
            add("option_names", f"card{n}_name_{variant}",
                _crop(card, nx, ny, nw, nh))
        for variant, (sx, sy, sw, sh) in (("1line", OPT_DELTA_1LINE),
                                          ("2line", OPT_DELTA_2LINE)):
            add("option_deltas", f"card{n}_delta_{variant}",
                _crop(card, sx, sy, sw, sh))

    # Diamond side nodes (x2): name crop + Lv. crop, each at both line offsets.
    for label, (dx, dy, w, h) in (("side1", C.ROI_STAT_FIRST),
                                  ("side2", C.ROI_STAT_SECOND)):
        node = _crop(gray, ax + dx, ay + dy, w, h)
        if node is None:
            continue
        for variant, (nx, ny, nw, nh) in (("1line", SN_NAME_1LINE),
                                          ("2line", SN_NAME_2LINE)):
            add("side_node_names", f"{label}_name_{variant}",
                _crop(node, nx, ny, nw, nh))
        for variant, (sx, sy, sw, sh) in (("1line", SN_LV_1LINE),
                                          ("2line", SN_LV_2LINE)):
            add("side_node_deltas", f"{label}_lv_{variant}",
                _crop(node, sx, sy, sw, sh))

    return out


def extract_finish_regions(gray: np.ndarray
                            ) -> Dict[str, List[Tuple[str, np.ndarray]]]:
    """Crop the 4 finish-screen stat digits (no anchor). FHD grayscale in."""
    out: Dict[str, List[Tuple[str, np.ndarray]]] = {}
    labels = ["willpower", "chaos", "first_level", "second_level"]
    for label, (x, y, w, h) in zip(labels, C.FINISH_STAT_POSITIONS):
        crop = _crop(gray, x, y, w, h)
        if crop is not None and crop.size > 0:
            out.setdefault("finish", []).append((f"finish_{label}", crop))
    return out


def draw_overlay(frame_bgr: np.ndarray, anchor: Optional[Tuple[int, int]]
                 ) -> np.ndarray:
    """Return an FHD copy of the frame with every ROI drawn as a labelled box."""
    h, w = frame_bgr.shape[:2]
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        frame_bgr = cv2.resize(frame_bgr, (C.REF_WIDTH, C.REF_HEIGHT),
                               interpolation=cv2.INTER_AREA)
    debug = frame_bgr.copy()

    def box(x: int, y: int, bw: int, bh: int, label: str,
            color: Tuple[int, int, int]) -> None:
        cv2.rectangle(debug, (x, y), (x + bw, y + bh), color, 1)
        if label:
            cv2.putText(debug, label, (x, y - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

    if anchor is None:
        cv2.putText(debug, "NO ANCHOR - finish screen?", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        for x, y, bw, bh in C.FINISH_STAT_POSITIONS:
            box(x, y, bw, bh, "FINISH", (0, 255, 255))
        return debug

    ax, ay = anchor
    box(ax, ay, C.ANCHOR_SIZE[0], C.ANCHOR_SIZE[1], "ANCHOR", (0, 255, 0))
    for category, (dx, dy, bw, bh) in _SINGLE_REGIONS:
        box(ax + dx, ay + dy, bw, bh, category.upper(), (255, 255, 0))

    for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
        cx, cy = ax + dx, ay + C.OPTION_CARD_Y_OFFSET
        box(cx, cy, card_w, C.OPTION_CARD_HEIGHT, f"CARD{i + 1}", (0, 200, 255))
        for nx, ny, nw, nh in (OPT_NAME_1LINE, OPT_NAME_2LINE):
            box(cx + nx, cy + ny, nw, nh, "", (0, 255, 0))
        for sx, sy, sw, sh in (OPT_DELTA_1LINE, OPT_DELTA_2LINE):
            box(cx + sx, cy + sy, sw, sh, "", (255, 0, 200))

    for label, (dx, dy, bw, bh) in (("SIDE1", C.ROI_STAT_FIRST),
                                    ("SIDE2", C.ROI_STAT_SECOND)):
        box(ax + dx, ay + dy, bw, bh, label, (0, 200, 255))
        for nx, ny, nw, nh in (SN_NAME_1LINE, SN_NAME_2LINE):
            box(ax + dx + nx, ay + dy + ny, nw, nh, "", (0, 255, 0))
        for sx, sy, sw, sh in (SN_LV_1LINE, SN_LV_2LINE):
            box(ax + dx + sx, ay + dy + sy, sw, sh, "", (255, 0, 200))

    return debug


def _write_crops(regions: Dict[str, List[Tuple[str, np.ndarray]]],
                 basename: str, out_dir: str) -> int:
    """Write every crop to <out_dir>/<category>/<basename>_<label>.png."""
    count = 0
    for category, items in regions.items():
        cat_dir = os.path.join(out_dir, category)
        os.makedirs(cat_dir, exist_ok=True)
        for label, crop in items:
            if cv2.imwrite(os.path.join(cat_dir, f"{basename}_{label}.png"), crop):
                count += 1
    return count


def process_image(path: str, store: TemplateStore, out_dir: str) -> None:
    """Extract crops + overlay for one screenshot."""
    frame = cv2.imread(path)
    if frame is None:
        print(f"  SKIP (cannot read): {path}")
        return
    basename = os.path.splitext(os.path.basename(path))[0]
    gray = _to_fhd_gray(frame)
    anchor = find_anchor(gray, store)
    if anchor is not None:
        regions = extract_regions(gray, anchor)
        state = f"anchor={anchor}"
    else:
        regions = extract_finish_regions(gray)
        state = "no anchor (finish screen)"
    count = _write_crops(regions, basename, out_dir)
    overlay_dir = os.path.join(out_dir, "_overlays")
    os.makedirs(overlay_dir, exist_ok=True)
    cv2.imwrite(os.path.join(overlay_dir, f"{basename}.png"),
                draw_overlay(frame, anchor))
    print(f"  {basename}: {count} crops, {state}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract template-candidate crops from screenshots.")
    parser.add_argument("images", nargs="*",
                        help="Screenshot paths (default: examples/*.jpg)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Output directory (default: {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    images = args.images or sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.jpg")))
    if not images:
        print("No input images found.")
        return
    os.makedirs(args.out, exist_ok=True)
    store = TemplateStore()
    print(f"Extracting from {len(images)} image(s) -> {args.out}")
    for path in images:
        process_image(path, store, args.out)
    print("Done.")


if __name__ == "__main__":
    main()
