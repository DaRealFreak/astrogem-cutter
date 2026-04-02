"""Extract cropped template images from screenshot(s).

Usage:
  python extract_templates.py                        # all examples -> templates/
  python extract_templates.py input.jpg output_dir/  # single image -> output_dir/
"""

import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from arkgrid.vision import constants as C
from arkgrid.vision.templates import TemplateStore
from arkgrid.vision.matcher import find_best_match


def find_anchor(gray, store):
    anchors = store.get_anchor()
    if not anchors:
        return None
    match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                            threshold=C.THRESHOLD_ANCHOR)
    if match is not None:
        return match.location
    return None


def crop_roi(frame, ax, ay, roi):
    """Crop an anchor-relative ROI from a frame. Returns grayscale crop."""
    dx, dy, w, h = roi
    x, y = ax + dx, ay + dy
    fh, fw = frame.shape[:2]
    x, y = max(0, x), max(0, y)
    w = min(w, fw - x)
    h = min(h, fh - y)
    if w <= 0 or h <= 0:
        return None
    crop = frame[y:y + h, x:x + w]
    if len(crop.shape) == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return crop


def process_image(path, store, output_dir):
    """Extract all crop regions from a single image."""
    frame = cv2.imread(path)
    if frame is None:
        print(f"  SKIP: cannot read {path}")
        return

    h, w = frame.shape[:2]
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        frame = cv2.resize(frame, (C.REF_WIDTH, C.REF_HEIGHT),
                           interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    anchor = find_anchor(gray, store)
    if anchor is None:
        print(f"  SKIP (no anchor): {os.path.basename(path)}")
        return

    ax, ay = anchor
    basename = os.path.splitext(os.path.basename(path))[0]
    print(f"{basename} (anchor={ax},{ay}):")

    # Single-region crops
    single_rois = [
        ("gem_type", C.ROI_GEM_TYPE),
        ("points", C.ROI_POINTS),
        ("willpower", C.ROI_STAT_WILLPOWER),
        ("chaos", C.ROI_STAT_CHAOS),
        ("side_1", C.ROI_STAT_FIRST),
        ("side_2", C.ROI_STAT_SECOND),
        ("rerolls", C.ROI_REROLL),
        ("steps", C.ROI_PROCESS_STEPS),
    ]

    for name, roi in single_rois:
        crop = crop_roi(frame, ax, ay, roi)
        if crop is not None:
            out = os.path.join(output_dir, f"{name}_{basename}.png")
            cv2.imwrite(out, crop)
            print(f"  {name}: {crop.shape[1]}x{crop.shape[0]}")

    # Option cards (4 per image)
    for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
        card_roi = (dx, C.OPTION_CARD_Y_OFFSET, card_w, C.OPTION_CARD_HEIGHT)
        crop = crop_roi(frame, ax, ay, card_roi)
        if crop is not None:
            out = os.path.join(output_dir, f"card{i+1}_{basename}.png")
            cv2.imwrite(out, crop)
            print(f"  card_{i+1}: {crop.shape[1]}x{crop.shape[0]}")


def main():
    store = TemplateStore()

    if len(sys.argv) >= 3:
        # Single image mode: python extract_templates.py input.jpg output_dir/
        input_path = sys.argv[1]
        output_dir = sys.argv[2]
        os.makedirs(output_dir, exist_ok=True)
        process_image(input_path, store, output_dir)
    elif len(sys.argv) == 2:
        # Single image, output to current dir
        input_path = sys.argv[1]
        output_dir = os.path.dirname(input_path) or "."
        process_image(input_path, store, output_dir)
    else:
        # Batch mode: all examples
        examples_dir = os.path.join(os.path.dirname(__file__), "examples")
        templates_dir = os.path.join(os.path.dirname(__file__),
                                     "arkgrid", "vision", "templates")
        output_dir = templates_dir
        os.makedirs(output_dir, exist_ok=True)

        images = sorted(glob.glob(os.path.join(examples_dir, "*.jpg")))
        if not images:
            print("No example images found")
            return

        print(f"Extracting from {len(images)} images...\n")
        for path in images:
            process_image(path, store, output_dir)
            print()

    print("Done!")


if __name__ == "__main__":
    main()
