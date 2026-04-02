"""Recognize all option cards from all example images.

Uses template matching for both option names and deltas.
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


def load_templates(subdir):
    """Load all PNG templates from a subdirectory as grayscale images."""
    d = os.path.join(TEMPLATES_DIR, "options", subdir)
    templates = {}
    for path in sorted(glob.glob(os.path.join(d, "*.png"))):
        key = os.path.splitext(os.path.basename(path))[0]
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            templates[key] = img
    return templates


def match_template(card_gray, templates, strip_variants=False):
    """Find the best matching template in a card crop via sub-image search.

    If strip_variants is True, the returned key has _NN suffixes stripped
    (e.g. 'additional_damage_01' -> 'additional_damage').
    """
    best_key = None
    best_score = 0.0

    for key, tmpl in templates.items():
        if tmpl.shape[0] > card_gray.shape[0] or tmpl.shape[1] > card_gray.shape[1]:
            continue

        result = cv2.matchTemplate(card_gray, tmpl, cv2.TM_CCOEFF_NORMED)
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

    # Strip 1_line_ / 2_line_ prefix
    d = delta_key
    for prefix in ("1_line_", "2_line_"):
        if d.startswith(prefix):
            d = d[len(prefix):]
            break

    if d.startswith("lvl"):
        return d.replace("lvl", "lvl")
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


def main():
    store = TemplateStore()
    name_templates = load_templates("names")
    delta_templates = load_templates("deltas")
    print(f"Loaded {len(name_templates)} name templates, "
          f"{len(delta_templates)} delta templates\n")

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

        options = []
        for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
            card_x = ax + dx
            card_y = ay + C.OPTION_CARD_Y_OFFSET
            card_crop = gray[card_y:card_y + C.OPTION_CARD_HEIGHT,
                             card_x:card_x + card_w]

            name_key, name_score = match_template(
                card_crop, name_templates, strip_variants=True)
            if name_score < 0.65:
                name_key = None

            delta_key, delta_score = match_template(card_crop, delta_templates)
            if delta_score < 0.65:
                delta_key = None

            formatted = format_option(name_key, delta_key)
            options.append((formatted, name_key, name_score,
                            delta_key, delta_score))

        has_low = any(ns < 0.9 or ds < 0.9
                      for _, _, ns, _, ds in options)
        print(f"{basename}:")
        for i, (fmt, nk, ns, dk, ds) in enumerate(options):
            low = ""
            if ns < 0.9:
                low += " *** LOW NAME"
            if ds < 0.9:
                low += " *** LOW DELTA"
            print(f"  option {i+1}: {fmt:30s} "
                  f"name={nk}({ns:.2f}) delta={dk}({ds:.2f}){low}")
        print()


if __name__ == "__main__":
    main()
