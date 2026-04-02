"""Recognize option cards and gem state from all example images.

Uses template matching for option names/deltas and side node names/levels.
"""

import glob
import os
import re
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from arkgrid.vision import constants as C
from arkgrid.vision.templates import TemplateStore
from arkgrid.vision.matcher import find_best_match

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__),
                             "arkgrid", "vision", "templates")
EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "examples")

# Strip trailing _01, _02 etc. from template keys to get the base name
_VARIANT_SUFFIX = re.compile(r"_\d+$")


def strip_variant(key):
    """'additional_damage_01' -> 'additional_damage', 'chaos' -> 'chaos'."""
    return _VARIANT_SUFFIX.sub("", key)


def load_templates_from(base_dir, subdir):
    """Load all PNG templates from base_dir/subdir/ as grayscale images."""
    d = os.path.join(base_dir, subdir)
    templates = {}
    if not os.path.isdir(d):
        return templates
    for path in sorted(glob.glob(os.path.join(d, "*.png"))):
        key = os.path.splitext(os.path.basename(path))[0]
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates[key] = img
    return templates


def match_template(crop_gray, templates, strip_variants=False):
    """Find the best matching template in a crop via sub-image search."""
    best_key = None
    best_score = 0.0

    for key, tmpl in templates.items():
        if tmpl.shape[0] > crop_gray.shape[0] or tmpl.shape[1] > crop_gray.shape[1]:
            continue

        result = cv2.matchTemplate(crop_gray, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)

        if max_val > best_score:
            best_score = max_val
            best_key = key

    if strip_variants and best_key:
        best_key = strip_variant(best_key)

    return best_key, best_score


def delta_key_to_value(delta_key):
    """Convert delta template key to a signed value string."""
    if not delta_key:
        return None

    d = delta_key
    for prefix in ("1_line_", "2_line_"):
        if d.startswith(prefix):
            d = d[len(prefix):]
            break

    if d.startswith("lvl"):
        return d
    elif d == "effect_changed":
        return "ec"
    elif d == "maintained":
        return "maintained"
    elif d.startswith("cost"):
        return d
    elif d.startswith("reroll"):
        return d
    else:
        return d


def side_node_level(delta_key):
    """Extract level number from side node delta key like '1_line_lvl3'."""
    if not delta_key:
        return None
    m = re.search(r"lvl(\d)", delta_key)
    return int(m.group(1)) if m else None


def format_option(name, delta_key):
    """Format as 'name+delta' string."""
    if not name:
        return "???"

    delta = delta_key_to_value(delta_key)

    if delta is None:
        return name
    elif delta == "ec":
        return f"{name}_ec"
    elif delta == "maintained":
        return "maintained"
    elif delta.startswith("cost"):
        return delta
    elif delta.startswith("reroll"):
        return delta
    elif delta.startswith("lvl"):
        sign_and_num = delta[3:]
        return f"{name}{sign_and_num}"
    else:
        return f"{name}{delta}"


def crop_roi(gray, ax, ay, roi):
    """Crop an anchor-relative ROI."""
    dx, dy, w, h = roi
    x, y = ax + dx, ay + dy
    fh, fw = gray.shape[:2]
    x, y = max(0, x), max(0, y)
    w = min(w, fw - x)
    h = min(h, fh - y)
    if w <= 0 or h <= 0:
        return None
    return gray[y:y + h, x:x + w]


def main():
    store = TemplateStore()

    # Option templates
    opt_dir = os.path.join(TEMPLATES_DIR, "options")
    opt_name_templates = load_templates_from(opt_dir, "names")
    opt_delta_templates = load_templates_from(opt_dir, "deltas")

    # Side node templates
    sn_dir = os.path.join(TEMPLATES_DIR, "side_nodes")
    sn_name_templates = load_templates_from(sn_dir, "names")
    sn_delta_templates = load_templates_from(sn_dir, "deltas")

    # Willpower/chaos/reroll digit templates
    wp_templates = load_templates_from(TEMPLATES_DIR, "willpower")
    ch_templates = load_templates_from(TEMPLATES_DIR, "chaos")
    reroll_templates = load_templates_from(TEMPLATES_DIR, "rerolls")

    print(f"Options:    {len(opt_name_templates)} names, "
          f"{len(opt_delta_templates)} deltas")
    print(f"Side nodes: {len(sn_name_templates)} names, "
          f"{len(sn_delta_templates)} deltas")
    print(f"Willpower:  {len(wp_templates)} templates")
    print(f"Chaos:      {len(ch_templates)} templates")
    print(f"Rerolls:    {len(reroll_templates)} templates")
    print()

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
        anchors = store.get_anchor()
        match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                                threshold=C.THRESHOLD_ANCHOR)
        if match is None:
            continue

        ax, ay = match.location
        basename = os.path.basename(path)
        print(f"{basename}:")

        # --- Willpower ---
        wp_crop = crop_roi(gray, ax, ay, C.ROI_STAT_WILLPOWER)
        if wp_crop is not None and wp_templates:
            wp_key, wp_score = match_template(
                wp_crop, wp_templates, strip_variants=True)
            low = " *** LOW" if wp_score < 0.9 else ""
            print(f"  willpower:  {wp_key} ({wp_score:.2f}){low}")
        else:
            print(f"  willpower:  ? (no templates)")

        # --- Chaos ---
        ch_crop = crop_roi(gray, ax, ay, C.ROI_STAT_CHAOS)
        if ch_crop is not None and ch_templates:
            ch_key, ch_score = match_template(
                ch_crop, ch_templates, strip_variants=True)
            low = " *** LOW" if ch_score < 0.9 else ""
            print(f"  chaos:      {ch_key} ({ch_score:.2f}){low}")
        else:
            print(f"  chaos:      ? (no templates)")

        # --- Rerolls ---
        rr_crop = crop_roi(gray, ax, ay, C.ROI_REROLL)
        if rr_crop is not None and reroll_templates:
            rr_key, rr_score = match_template(
                rr_crop, reroll_templates, strip_variants=True)
            low = " *** LOW" if rr_score < 0.9 else ""
            print(f"  rerolls:    {rr_key} ({rr_score:.2f}){low}")
        else:
            print(f"  rerolls:    ? (no templates)")

        # --- Side nodes ---
        for side_idx, (label, roi) in enumerate([
            ("side_1", C.ROI_STAT_FIRST),
            ("side_2", C.ROI_STAT_SECOND),
        ]):
            sn_crop = crop_roi(gray, ax, ay, roi)
            if sn_crop is None:
                print(f"  {label}:    ? (crop failed)")
                continue

            sn_name, sn_name_score = match_template(
                sn_crop, sn_name_templates, strip_variants=True)
            sn_delta, sn_delta_score = match_template(
                sn_crop, sn_delta_templates)

            lvl = side_node_level(sn_delta)
            name_str = sn_name or "?"
            lvl_str = str(lvl) if lvl else "?"

            low = ""
            if sn_name_score < 0.9:
                low += " *** LOW NAME"
            if sn_delta_score < 0.9:
                low += " *** LOW DELTA"

            print(f"  {label}:    {name_str} Lv.{lvl_str:4s} "
                  f"name={sn_name}({sn_name_score:.2f}) "
                  f"delta={sn_delta}({sn_delta_score:.2f}){low}")

        # --- Option cards ---
        for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
            card_x = ax + dx
            card_y = ay + C.OPTION_CARD_Y_OFFSET
            card_crop = gray[card_y:card_y + C.OPTION_CARD_HEIGHT,
                             card_x:card_x + card_w]

            name_key, name_score = match_template(
                card_crop, opt_name_templates, strip_variants=True)
            if name_score < 0.65:
                name_key = None

            delta_key, delta_score = match_template(
                card_crop, opt_delta_templates)
            if delta_score < 0.65:
                delta_key = None

            formatted = format_option(name_key, delta_key)

            low = ""
            if name_score < 0.9:
                low += " *** LOW NAME"
            if delta_score < 0.9:
                low += " *** LOW DELTA"

            print(f"  option {i+1}: {formatted:30s} "
                  f"name={name_key}({name_score:.2f}) "
                  f"delta={delta_key}({delta_score:.2f}){low}")

        print()


if __name__ == "__main__":
    main()
