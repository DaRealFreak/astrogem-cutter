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

# ── Proposed new values ──────────────────────────────────────────────
# Uniform 125px card spacing, 120px card width (5px gap between cards)
PROPOSED_CARD_Y_OFFSET = 528
PROPOSED_CARD_HEIGHT = 52
PROPOSED_CARD_POSITIONS = [
    (-195, 120),   # Card 1: abs 700..820
    (-70,  120),   # Card 2: abs 825..945
    (55,   120),   # Card 3: abs 950..1070
    (180,  120),   # Card 4: abs 1075..1195
]
# Sub-ROIs within each card (skip ~18px icon area on the left)
PROPOSED_CARD_NAME_ROI = (18, 8, 100, 17)
PROPOSED_CARD_DELTA_ROI = (18, 28, 100, 16)


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

    # ── Stat ROIs (cyan family) ──
    draw_anchor_roi(debug, ax, ay, C.ROI_SUBTITLE, "SUBTITLE", (255, 255, 0))
    draw_anchor_roi(debug, ax, ay, C.ROI_STAT_WILLPOWER, "WILL", (0, 255, 255))
    draw_anchor_roi(debug, ax, ay, C.ROI_STAT_FIRST_FULL, "1st_FULL", (0, 255, 200))
    draw_anchor_roi(debug, ax, ay, C.ROI_STAT_SECOND_FULL, "2nd_FULL", (200, 255, 0))
    draw_anchor_roi(debug, ax, ay, C.ROI_STAT_POINTS_FULL, "POINTS_FULL", (0, 200, 200))
    draw_anchor_roi(debug, ax, ay, C.ROI_RANDOMLY_APPLIED, "RANDOMLY", (180, 180, 180))

    # ── CURRENT option card ROIs (RED - dashed style via thin lines) ──
    for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
        card_x = ax + dx
        card_y = ay + C.OPTION_CARD_Y_OFFSET
        # Full card (red, thin)
        cv2.rectangle(debug, (card_x, card_y),
                      (card_x + card_w, card_y + C.OPTION_CARD_HEIGHT),
                      (0, 0, 255), 1)
        cv2.putText(debug, f"OLD_{i+1}", (card_x, card_y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 255), 1)

    # ── PROPOSED option card ROIs (GREEN - thick) ──
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
        cv2.putText(debug, f"NEW_{i+1}", (card_x, card_y + PROPOSED_CARD_HEIGHT + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

        # Name sub-region (thin)
        nx, ny, nw, nh = PROPOSED_CARD_NAME_ROI
        cv2.rectangle(debug, (card_x + nx, card_y + ny),
                      (card_x + nx + nw, card_y + ny + nh),
                      color, 1)

        # Delta sub-region (thin)
        dx2, dy2, dw, dh = PROPOSED_CARD_DELTA_ROI
        cv2.rectangle(debug, (card_x + dx2, card_y + dy2),
                      (card_x + dx2 + dw, card_y + dy2 + dh),
                      color, 1)

    # ── Bottom info ROIs ──
    draw_anchor_roi(debug, ax, ay, C.ROI_REROLL, "REROLL", (255, 0, 255))
    draw_anchor_roi(debug, ax, ay, C.ROI_PROCESSING_COST, "PROC_COST", (200, 200, 0))
    draw_anchor_roi(debug, ax, ay, C.ROI_BALANCE, "BALANCE", (200, 200, 0))
    draw_anchor_roi(debug, ax, ay, C.ROI_PROCESS_BUTTON, "PROCESS_BTN", (255, 0, 255))

    # ── Info panel ──
    panel_x, panel_y = 10, 10
    lines = [
        f"Anchor: ({ax}, {ay})  score={score:.3f}",
        "RED = current (broken)  |  COLORED = proposed (new)",
        "",
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
    output_dir = examples_dir

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
