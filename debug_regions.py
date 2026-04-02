"""Generate debug_regions_{filename}.png for all example screenshots.

Draws colored rectangles showing CURRENT (red) vs PROPOSED (green) crop
regions so we can verify the proposed fix captures all option text.
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

# ── Proposed new values (edit these, then re-run) ───────────────────
# Format: (dx_from_anchor, width)
# Anchor is at ~(895, 43) in all examples
PROPOSED_CARD_Y_OFFSET = 520       # vertical offset from anchor top (598 - 35 - 43)
PROPOSED_CARD_HEIGHT = 70          # card crop height
# Centers: (781,598), (898,598), (1015,598), (1132,598) — 117px spacing
# Width=117, boxes directly adjacent with no gap/overlap
PROPOSED_CARD_POSITIONS = [
    (-172, 117),   # Card 1: abs 723..840  (center 781)
    (-55,  117),   # Card 2: abs 840..957  (center 898)
    (62,   117),   # Card 3: abs 957..1074 (center 1015)
    (179,  117),   # Card 4: abs 1074..1191 (center 1132)
]

# Diamond stat boxes (anchor-relative: dx, dy, w, h)
PROPOSED_SIDE_NODE_1 = (-72, 332, 102, 57)   # abs x=823 y=375, center 874,404
PROPOSED_SIDE_NODE_2 = (96, 332, 102, 57)    # abs x=991 y=375, center 1042,404
PROPOSED_WILLPOWER   = (56, 309, 16, 16)     # abs x=951 y=352
PROPOSED_CHAOS       = (56, 427, 16, 16)     # abs x=951 y=470

# Gem info / UI boxes (anchor-relative: dx, dy, w, h)
PROPOSED_GEM_TYPE    = (55, 68, 19, 23)      # abs x=950 y=111
PROPOSED_POINTS      = (-11, 168, 140, 20)   # abs x=884 y=211
PROPOSED_REROLLS     = (340, 542, 56, 20)    # abs x=1235 y=585
PROPOSED_PROC_STEPS  = (195, 714, 28, 18)    # abs x=1090 y=757


def find_anchor(gray, store):
    anchors = store.get_anchor()
    if not anchors:
        return None
    match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                            threshold=C.THRESHOLD_ANCHOR)
    if match is not None:
        return match.location, match.score
    return None


def draw_roi(img, x, y, w, h, label, color, thickness=2):
    cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness)
    cv2.putText(img, label, (x, y - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1, cv2.LINE_AA)


def draw_anchor_roi(img, ax, ay, roi, label, color, thickness=2):
    dx, dy, w, h = roi
    draw_roi(img, ax + dx, ay + dy, w, h, label, color, thickness)


def process_image(path, store, output_dir):
    frame = cv2.imread(path)
    if frame is None:
        print(f"  SKIP: cannot read {path}")
        return

    h, w = frame.shape[:2]
    if h != C.REF_HEIGHT or w != C.REF_WIDTH:
        frame = cv2.resize(frame, (C.REF_WIDTH, C.REF_HEIGHT),
                           interpolation=cv2.INTER_AREA)

    debug = frame.copy()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    result = find_anchor(gray, store)
    if result is None:
        cv2.putText(debug, "ANCHOR NOT FOUND", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        basename = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(output_dir, f"debug_regions_{basename}.png")
        cv2.imwrite(out_path, debug)
        return

    (ax, ay), score = result
    print(f"  Anchor at ({ax}, {ay}), score={score:.3f}")

    # ── Anchor ──
    aw, ah = C.ANCHOR_SIZE
    cv2.rectangle(debug, (ax, ay), (ax + aw, ay + ah), (0, 255, 0), 2)
    cv2.putText(debug, f"ANCHOR {score:.2f}", (ax, ay - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

    # ── Gem info / UI ROIs ──
    draw_anchor_roi(debug, ax, ay, PROPOSED_GEM_TYPE, "GEM_TYPE", (255, 255, 0))
    draw_anchor_roi(debug, ax, ay, PROPOSED_POINTS, "POINTS", (255, 180, 0))
    draw_anchor_roi(debug, ax, ay, PROPOSED_REROLLS, "REROLLS", (255, 0, 255))
    draw_anchor_roi(debug, ax, ay, PROPOSED_PROC_STEPS, "STEPS", (200, 0, 255))

    # ── Diamond stat ROIs ──
    draw_anchor_roi(debug, ax, ay, PROPOSED_WILLPOWER, "WILL_LV", (0, 255, 255))
    draw_anchor_roi(debug, ax, ay, PROPOSED_CHAOS, "CHAOS_LV", (0, 200, 200))
    draw_anchor_roi(debug, ax, ay, PROPOSED_SIDE_NODE_1, "SIDE_1", (0, 255, 200))
    draw_anchor_roi(debug, ax, ay, PROPOSED_SIDE_NODE_2, "SIDE_2", (200, 255, 0))

    # ── Option card ROIs ──
    card_colors = [
        (0, 255, 0),    # Card 1: green
        (255, 200, 0),  # Card 2: cyan-ish
        (0, 200, 255),  # Card 3: orange
        (255, 0, 200),  # Card 4: magenta
    ]
    for i, (dx, card_w) in enumerate(PROPOSED_CARD_POSITIONS):
        card_x = ax + dx
        card_y = ay + PROPOSED_CARD_Y_OFFSET
        color = card_colors[i]

        # Full card ROI (thick)
        cv2.rectangle(debug, (card_x, card_y),
                      (card_x + card_w, card_y + PROPOSED_CARD_HEIGHT),
                      color, 2)
        cv2.putText(debug, f"CARD_{i+1}", (card_x, card_y + PROPOSED_CARD_HEIGHT + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)




    # ── Info panel ──
    panel_x, panel_y = 10, 10
    lines = [
        f"Anchor: ({ax}, {ay})  score={score:.3f}",
    ]
    for i, (dx, cw) in enumerate(PROPOSED_CARD_POSITIONS):
        cx = ax + dx
        cy = ay + PROPOSED_CARD_Y_OFFSET
        lines.append(
            f"Card{i+1}: x={cx} y={cy} w={cw} h={PROPOSED_CARD_HEIGHT} "
            f"[{cx}..{cx+cw}]"
        )
    ph = len(lines) * 16 + 10
    cv2.rectangle(debug, (panel_x, panel_y), (panel_x + 460, panel_y + ph),
                  (0, 0, 0), cv2.FILLED)
    for idx, line in enumerate(lines):
        cv2.putText(debug, line, (panel_x + 5, panel_y + 14 + idx * 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)

    basename = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(output_dir, f"debug_regions_{basename}.png")
    cv2.imwrite(out_path, debug)
    print(f"  SAVED: {out_path}")


def main():
    store = TemplateStore()
    examples_dir = os.path.join(os.path.dirname(__file__), "examples")
    output_dir = os.path.join(examples_dir, "debug_output")
    os.makedirs(output_dir, exist_ok=True)

    images = sorted(
        glob.glob(os.path.join(examples_dir, "*.jpg"))
    )

    if not images:
        print("No example images found in", examples_dir)
        return

    print(f"Processing {len(images)} images...")
    for path in images:
        print(f"\n{os.path.basename(path)}:")
        process_image(path, store, output_dir)

    print("\nDone!")


if __name__ == "__main__":
    main()
