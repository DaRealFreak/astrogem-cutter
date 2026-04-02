"""Run OCR on all extracted templates and on full example images via the recognizer."""

import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from arkgrid.vision import constants as C
from arkgrid.vision.templates import TemplateStore
from arkgrid.vision.matcher import find_best_match
from arkgrid.vision.ocr import ocr_available, ocr_region, ocr_option_card

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__),
                             "arkgrid", "vision", "templates")
EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "examples")


def find_anchor(gray, store):
    anchors = store.get_anchor()
    if not anchors:
        return None
    match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                            threshold=C.THRESHOLD_ANCHOR)
    return match.location if match else None


def ocr_template_crops():
    """Run OCR on every extracted template image and print results."""
    print("=" * 70)
    print("OCR ON EXTRACTED TEMPLATES")
    print("=" * 70)

    subdirs = ["gem_type", "points", "willpower", "chaos",
               "side_nodes", "options", "rerolls", "steps"]

    for subdir in subdirs:
        d = os.path.join(TEMPLATES_DIR, subdir)
        if not os.path.isdir(d):
            continue

        pngs = sorted(glob.glob(os.path.join(d, "*.png")))
        if not pngs:
            continue

        print(f"\n--- {subdir}/ ({len(pngs)} files) ---")

        # Choose OCR settings per region type
        if subdir in ("willpower", "chaos"):
            psm, scale, thresh = 10, 8, 150  # single char
        elif subdir == "steps":
            psm, scale, thresh = 7, 6, 150   # single line like "7/7"
        elif subdir == "rerolls":
            psm, scale, thresh = 7, 6, 150   # single line like "1 / 1"
        elif subdir == "gem_type":
            psm, scale, thresh = 10, 8, 130  # small icon, probably won't OCR
        elif subdir == "points":
            psm, scale, thresh = 7, 4, 120   # single line
        elif subdir == "side_nodes":
            psm, scale, thresh = 6, 4, 120   # multi-line block
        else:  # options
            psm, scale, thresh = 6, 5, 110   # multi-line block

        for path in pngs:
            img = cv2.imread(path)
            if img is None:
                continue
            fname = os.path.basename(path)
            h, w = img.shape[:2]
            roi = (0, 0, w, h)
            text = ocr_region(img, roi, subdir, save_crop=False,
                              psm=psm, scale=scale, threshold=thresh)
            text_repr = repr(text) if text else "None"
            print(f"  {fname:55s} -> {text_repr}")


def ocr_full_examples():
    """Run OCR on full example images using the corrected ROIs."""
    print("\n" + "=" * 70)
    print("OCR ON FULL EXAMPLE IMAGES (using corrected ROIs)")
    print("=" * 70)

    store = TemplateStore()
    images = sorted(glob.glob(os.path.join(EXAMPLES_DIR, "*.jpg")))

    for path in images:
        frame = cv2.imread(path)
        if frame is None:
            continue

        h, w = frame.shape[:2]
        if h != C.REF_HEIGHT or w != C.REF_WIDTH:
            frame = cv2.resize(frame, (C.REF_WIDTH, C.REF_HEIGHT),
                               interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        anchor = find_anchor(gray, store)
        if anchor is None:
            continue

        ax, ay = anchor
        basename = os.path.basename(path)

        print(f"\n--- {basename} (anchor={ax},{ay}) ---")

        # Gem type (icon - likely won't OCR well)
        roi = (ax + C.ROI_GEM_TYPE[0], ay + C.ROI_GEM_TYPE[1],
               C.ROI_GEM_TYPE[2], C.ROI_GEM_TYPE[3])
        text = ocr_region(frame, roi, "gem_type", save_crop=False,
                          psm=10, scale=8, threshold=130)
        print(f"  gem_type:    {repr(text)}")

        # Points
        roi = (ax + C.ROI_POINTS[0], ay + C.ROI_POINTS[1],
               C.ROI_POINTS[2], C.ROI_POINTS[3])
        text = ocr_region(frame, roi, "points", save_crop=False,
                          psm=7, scale=4, threshold=120)
        print(f"  points:      {repr(text)}")

        # Willpower level
        roi = (ax + C.ROI_STAT_WILLPOWER[0], ay + C.ROI_STAT_WILLPOWER[1],
               C.ROI_STAT_WILLPOWER[2], C.ROI_STAT_WILLPOWER[3])
        text = ocr_region(frame, roi, "willpower", save_crop=False,
                          psm=10, scale=8, threshold=150)
        print(f"  willpower:   {repr(text)}")

        # Chaos level
        roi = (ax + C.ROI_STAT_CHAOS[0], ay + C.ROI_STAT_CHAOS[1],
               C.ROI_STAT_CHAOS[2], C.ROI_STAT_CHAOS[3])
        text = ocr_region(frame, roi, "chaos", save_crop=False,
                          psm=10, scale=8, threshold=150)
        print(f"  chaos:       {repr(text)}")

        # Side node 1
        roi = (ax + C.ROI_STAT_FIRST[0], ay + C.ROI_STAT_FIRST[1],
               C.ROI_STAT_FIRST[2], C.ROI_STAT_FIRST[3])
        text = ocr_region(frame, roi, "side_1", save_crop=False,
                          psm=6, scale=4, threshold=120)
        print(f"  side_1:      {repr(text)}")

        # Side node 2
        roi = (ax + C.ROI_STAT_SECOND[0], ay + C.ROI_STAT_SECOND[1],
               C.ROI_STAT_SECOND[2], C.ROI_STAT_SECOND[3])
        text = ocr_region(frame, roi, "side_2", save_crop=False,
                          psm=6, scale=4, threshold=120)
        print(f"  side_2:      {repr(text)}")

        # Option cards
        for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
            card_roi = (ax + dx, ay + C.OPTION_CARD_Y_OFFSET,
                        card_w, C.OPTION_CARD_HEIGHT)
            name_key, delta_key = ocr_option_card(frame, card_roi)
            # Also get raw text
            raw = ocr_region(frame, card_roi, f"opt{i}",
                             save_crop=False, psm=6, scale=5, threshold=110)
            print(f"  card_{i+1}:     name={repr(name_key):30s} "
                  f"delta={repr(delta_key):15s} raw={repr(raw)}")

        # Rerolls
        roi = (ax + C.ROI_REROLL[0], ay + C.ROI_REROLL[1],
               C.ROI_REROLL[2], C.ROI_REROLL[3])
        text = ocr_region(frame, roi, "rerolls", save_crop=False,
                          psm=7, scale=6, threshold=150)
        print(f"  rerolls:     {repr(text)}")

        # Processing steps
        roi = (ax + C.ROI_PROCESS_STEPS[0], ay + C.ROI_PROCESS_STEPS[1],
               C.ROI_PROCESS_STEPS[2], C.ROI_PROCESS_STEPS[3])
        text = ocr_region(frame, roi, "steps", save_crop=False,
                          psm=7, scale=6, threshold=150)
        print(f"  steps:       {repr(text)}")


def main():
    if not ocr_available():
        print("ERROR: Tesseract OCR not available!")
        return

    print("Tesseract OCR available.\n")
    ocr_template_crops()
    ocr_full_examples()
    print("\nDone!")


if __name__ == "__main__":
    main()
