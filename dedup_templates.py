"""Deduplicate extracted templates and run OCR on unique ones.

Uses pixel-level similarity (normalized cross-correlation) to find
duplicates, keeps one representative per group, and runs OCR on each.
"""

import glob
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from arkgrid.vision.ocr import ocr_available, ocr_region

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__),
                             "arkgrid", "vision", "templates")

# Similarity threshold for considering two crops as duplicates
DUPE_THRESHOLD = 0.97


def image_similarity(a, b):
    """Normalized cross-correlation between two grayscale images."""
    if a.shape != b.shape:
        return 0.0
    a_f = a.astype(np.float32).flatten()
    b_f = b.astype(np.float32).flatten()
    a_f -= a_f.mean()
    b_f -= b_f.mean()
    norm = np.linalg.norm(a_f) * np.linalg.norm(b_f)
    if norm == 0:
        return 0.0
    return float(np.dot(a_f, b_f) / norm)


def ocr_image(img, category):
    """Run OCR with settings tuned per category."""
    h, w = img.shape[:2]
    roi = (0, 0, w, h)

    if category in ("willpower", "chaos"):
        return ocr_region(img, roi, category, save_crop=False,
                          psm=10, scale=8, threshold=150)
    elif category == "steps":
        return ocr_region(img, roi, category, save_crop=False,
                          psm=7, scale=6, threshold=150)
    elif category == "rerolls":
        return ocr_region(img, roi, category, save_crop=False,
                          psm=7, scale=6, threshold=150)
    elif category == "gem_type":
        return ocr_region(img, roi, category, save_crop=False,
                          psm=10, scale=8, threshold=130)
    elif category == "points":
        return ocr_region(img, roi, category, save_crop=False,
                          psm=7, scale=4, threshold=120)
    elif category == "side_nodes":
        return ocr_region(img, roi, category, save_crop=False,
                          psm=6, scale=4, threshold=120)
    else:  # options
        return ocr_region(img, roi, category, save_crop=False,
                          psm=6, scale=5, threshold=110)


def process_subdir(subdir_name):
    """Deduplicate one template subdirectory."""
    d = os.path.join(TEMPLATES_DIR, subdir_name)
    if not os.path.isdir(d):
        return

    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    if not pngs:
        return

    # Load all images
    images = []
    for p in pngs:
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            images.append((p, img))

    # Group duplicates
    groups = []  # list of lists of (path, img)
    used = set()

    for i, (p1, img1) in enumerate(images):
        if i in used:
            continue
        group = [(p1, img1)]
        used.add(i)
        for j, (p2, img2) in enumerate(images):
            if j in used:
                continue
            sim = image_similarity(img1, img2)
            if sim >= DUPE_THRESHOLD:
                group.append((p2, img2))
                used.add(j)
        groups.append(group)

    print(f"\n{'='*70}")
    print(f"{subdir_name}/ — {len(pngs)} files -> {len(groups)} unique")
    print(f"{'='*70}")

    # For each group: run OCR on representative, remove duplicates
    kept = []
    removed = 0
    for group in groups:
        # Keep first file, remove rest
        keep_path, keep_img = group[0]
        ocr_text = ocr_image(keep_img, subdir_name)

        keep_name = os.path.basename(keep_path)
        dupe_names = [os.path.basename(p) for p, _ in group[1:]]

        print(f"\n  KEEP: {keep_name}")
        print(f"  OCR:  {repr(ocr_text)}")
        if dupe_names:
            print(f"  DUPES ({len(dupe_names)}): {', '.join(dupe_names[:5])}"
                  f"{'...' if len(dupe_names) > 5 else ''}")

        # Delete duplicates
        for dup_path, _ in group[1:]:
            os.remove(dup_path)
            removed += 1

        kept.append((keep_path, ocr_text))

    print(f"\n  Summary: kept {len(kept)}, removed {removed}")
    return kept


def main():
    if not ocr_available():
        print("ERROR: Tesseract OCR not available!")
        return

    subdirs = ["options", "side_nodes", "willpower", "chaos",
               "gem_type", "points", "rerolls", "steps"]

    for subdir in subdirs:
        process_subdir(subdir)

    print("\n\nDone!")


if __name__ == "__main__":
    main()
