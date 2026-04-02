"""Extract option card crops from specific new example files."""

import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(__file__))

from arkgrid.vision import constants as C
from arkgrid.vision.templates import TemplateStore
from arkgrid.vision.matcher import find_best_match

FILES = [
    "20260401230720_1.jpg",
    "20260401230958_1.jpg",
    "20260401231058_1.jpg",
    "20260401231303_1.jpg",
]


def main():
    store = TemplateStore()
    examples_dir = os.path.join(os.path.dirname(__file__), "examples")
    out_dir = os.path.join(os.path.dirname(__file__),
                           "arkgrid", "vision", "templates", "options")

    for fname in FILES:
        path = os.path.join(examples_dir, fname)
        frame = cv2.imread(path)
        if frame is None:
            print(f"SKIP: {fname}")
            continue

        h, w = frame.shape[:2]
        if h != C.REF_HEIGHT or w != C.REF_WIDTH:
            frame = cv2.resize(frame, (C.REF_WIDTH, C.REF_HEIGHT),
                               interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        anchors = store.get_anchor()
        match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                                threshold=C.THRESHOLD_ANCHOR)
        if match is None:
            print(f"SKIP (no anchor): {fname}")
            continue

        ax, ay = match.location
        basename = os.path.splitext(fname)[0]
        print(f"\n{basename} (anchor={ax},{ay}):")

        for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
            x = ax + dx
            y = ay + C.OPTION_CARD_Y_OFFSET
            crop = frame[y:y + C.OPTION_CARD_HEIGHT, x:x + card_w]
            if len(crop.shape) == 3:
                crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            out = os.path.join(out_dir, f"card{i+1}_{basename}.png")
            cv2.imwrite(out, crop)
            print(f"  card_{i+1}: {out}")


if __name__ == "__main__":
    main()
