"""Crop and zoom into the option card area to measure exact pixel positions."""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from arkgrid.vision import constants as C
from arkgrid.vision.templates import TemplateStore
from arkgrid.vision.matcher import find_best_match


def main():
    store = TemplateStore()
    examples_dir = os.path.join(os.path.dirname(__file__), "examples")

    # Use a few different examples for measurement
    test_files = [
        "turn_1_01.jpg",   # Brand Power / Chaos Points / Atk. Power / Atk. Power
        "turn_1_02.jpg",   # Ally Damage / Chaos Points / Willpower / Additional Damage
        "turn_2_01.jpg",   # Processing Cost / View Other / View Other / Atk. Power
        "20260401130608_1.jpg",  # Different set
        "20260401130614_1.jpg",  # Another set
    ]

    for fname in test_files:
        path = os.path.join(examples_dir, fname)
        if not os.path.exists(path):
            continue

        frame = cv2.imread(path)
        h, w = frame.shape[:2]
        if h != C.REF_HEIGHT or w != C.REF_WIDTH:
            frame = cv2.resize(frame, (C.REF_WIDTH, C.REF_HEIGHT),
                               interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        anchors = store.get_anchor()
        match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                                threshold=C.THRESHOLD_ANCHOR)
        if match is None:
            continue

        ax, ay = match.location
        print(f"\n{fname}: anchor=({ax},{ay})")

        # Crop a wide area around the option cards for measurement
        # Go from well left of Card 1 to well right of Card 4
        crop_x = ax - 220  # wider than card 1
        crop_y = ay + 480  # start above "randomly applied" text
        crop_w = 550
        crop_h = 120  # covers options + some below

        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)

        crop = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]

        # Draw a grid every 10px for measurement, with labels
        zoomed = cv2.resize(crop, (crop_w * 3, crop_h * 3),
                            interpolation=cv2.INTER_NEAREST)

        for px in range(0, crop_w, 10):
            real_x = crop_x + px
            color = (0, 255, 0) if px % 50 == 0 else (80, 80, 80)
            cv2.line(zoomed, (px * 3, 0), (px * 3, crop_h * 3), color, 1)
            if px % 50 == 0:
                cv2.putText(zoomed, str(real_x), (px * 3 + 2, 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)

        for py in range(0, crop_h, 10):
            real_y = crop_y + py
            color = (0, 255, 0) if py % 50 == 0 else (80, 80, 80)
            cv2.line(zoomed, (0, py * 3), (crop_w * 3, py * 3), color, 1)
            if py % 50 == 0:
                cv2.putText(zoomed, str(real_y), (2, py * 3 + 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)

        # Mark current card boundaries (red) for comparison
        for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
            card_abs_x = ax + dx
            card_abs_y = ay + C.OPTION_CARD_Y_OFFSET
            # Convert to crop-relative coords
            rx = card_abs_x - crop_x
            ry = card_abs_y - crop_y
            cv2.rectangle(zoomed,
                          (rx * 3, ry * 3),
                          ((rx + card_w) * 3, (ry + C.OPTION_CARD_HEIGHT) * 3),
                          (0, 0, 255), 2)
            cv2.putText(zoomed, f"C{i+1}:x={card_abs_x}", (rx * 3, ry * 3 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        # Also draw anchor reference line
        ref_rx = ax - crop_x
        cv2.line(zoomed, (ref_rx * 3, 0), (ref_rx * 3, crop_h * 3),
                 (255, 255, 0), 2)
        cv2.putText(zoomed, f"AX={ax}", (ref_rx * 3 + 3, crop_h * 3 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)

        basename = os.path.splitext(fname)[0]
        out = os.path.join(examples_dir, f"debug_measure_{basename}.png")
        cv2.imwrite(out, zoomed)
        print(f"  -> {out}")


if __name__ == "__main__":
    main()
