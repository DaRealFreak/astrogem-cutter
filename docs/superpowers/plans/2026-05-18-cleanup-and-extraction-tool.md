# Project Cleanup + Template Extraction Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tidy the project so `arkgrid/` + `tests/` is the clear core, and replace seven scattered vision scripts with one consolidated template-extraction tool.

**Architecture:** Three cleanup tasks (move analysis scripts into `tools/`, remove the dead legacy OCR recognizer path, delete superseded scripts) followed by three TDD tasks building `tools/extract_templates.py`, then a docs task. The extraction tool finds the cutting-screen anchor, crops every template-able region (emitting delta/Lv. crops at both the 1-line and 2-line name offsets), groups crops by region type for manual sorting, and writes a debug overlay per screenshot.

**Tech Stack:** Python 3 (stdlib + `opencv-python`/`numpy` for vision), `unittest`.

**Branch:** Work happens on `cleanup-and-extraction-tool` (already created off `master`). The design spec is `docs/superpowers/specs/2026-05-18-cleanup-and-extraction-tool-design.md`.

**Conventions:**
- Run Python via the project venv: `.venv/Scripts/python.exe` (from the project root).
- Full test suite: `.venv/Scripts/python.exe -m unittest discover -s tests`.
- Commit after each task. Git workflow for this project is delegated to the implementer (see project memory).

---

### Task 1: Create `tools/` package and move analysis scripts

Move `benchmark_reroll.py`, `calibration.py`, `scenario.py` out of the root into a new `tools/` package. Each gets a project-root `sys.path` bootstrap so it still runs when invoked as `python tools/<name>.py` (where `sys.path[0]` is `tools/`, not the root).

**Files:**
- Create: `tools/__init__.py`
- Move: `benchmark_reroll.py` → `tools/benchmark_reroll.py`
- Move: `calibration.py` → `tools/calibration.py`
- Move: `scenario.py` → `tools/scenario.py`

- [ ] **Step 1: Create the `tools/` package marker**

Create `tools/__init__.py` with exactly this content (so `tools` is importable as a package by tests):

```python
"""Standalone developer scripts and tooling (not part of the arkgrid package)."""
```

- [ ] **Step 2: Move the three scripts with git**

Run:

```bash
git mv benchmark_reroll.py tools/benchmark_reroll.py
git mv calibration.py tools/calibration.py
git mv scenario.py tools/scenario.py
```

- [ ] **Step 3: Add the path bootstrap to `tools/benchmark_reroll.py`**

In `tools/benchmark_reroll.py`, replace this block:

```python
from typing import Dict, List, Tuple

from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, SUPPORT_COEFF, SUPPORT_EFFECTS
```

with:

```python
import os
import sys
from typing import Dict, List, Tuple

# Run as `python tools/benchmark_reroll.py`: add the project root to sys.path
# so `arkgrid` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid.constants import DPS_COEFF, DPS_EFFECTS, SUPPORT_COEFF, SUPPORT_EFFECTS
```

Also update the docstring usage line from `python benchmark_reroll.py` to `python tools/benchmark_reroll.py`.

- [ ] **Step 4: Add the path bootstrap to `tools/calibration.py`**

In `tools/calibration.py`, replace this block:

```python
import random

from arkgrid.models import LastTurnGoal
```

with:

```python
import os
import random
import sys

# Run as `python tools/calibration.py`: add the project root to sys.path
# so `arkgrid` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid.models import LastTurnGoal
```

Also update the docstring usage line from `python calibration.py` to `python tools/calibration.py`.

- [ ] **Step 5: Add the path bootstrap to `tools/scenario.py`**

In `tools/scenario.py`, replace this block:

```python
from arkgrid import GemState, GoalProbabilityTable, OptionPool
from tests.test_scenarios import ScenarioHelper, LastTurnGoal
```

with:

```python
import os
import sys

# Run as `python tools/scenario.py`: add the project root to sys.path so
# `arkgrid` and `tests` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkgrid import GemState, GoalProbabilityTable, OptionPool
from tests.test_scenarios import ScenarioHelper, LastTurnGoal
```

Also update the docstring usage line from `python scenario.py` to `python tools/scenario.py`.

- [ ] **Step 6: Verify the moved scripts run from the new location**

Run:

```bash
.venv/Scripts/python.exe tools/benchmark_reroll.py --trials 200 --seed 1
.venv/Scripts/python.exe tools/scenario.py
```

Expected: both run to completion and print their normal output with no `ModuleNotFoundError`. (`tools/calibration.py` uses the identical bootstrap pattern; optionally spot-check it — it runs ~5000 trials and takes a few seconds.)

- [ ] **Step 7: Commit**

```bash
git add tools/ benchmark_reroll.py calibration.py scenario.py
git commit -m "refactor: move analysis scripts into tools/ package"
```

---

### Task 2: Remove the legacy OCR recognizer path

The `live` and `auto` commands use `template_recognizer.py`. Only the `read` debug command uses the older OCR-based recognizer (`recognizer.py` + `ocr.py` + `mapping.py` + `debug.py`). Those four modules and `read` are used nowhere else (verified: only `cli.py`'s `cmd_read` and the modules themselves reference the symbols). Remove the whole path.

**Files:**
- Delete: `arkgrid/vision/recognizer.py`, `arkgrid/vision/ocr.py`, `arkgrid/vision/mapping.py`, `arkgrid/vision/debug.py`
- Modify: `arkgrid/vision/__init__.py` (full rewrite)
- Modify: `arkgrid/cli.py` (remove `p_read` subparser, `cmd_read`, dispatch branch)
- Modify: `requirements.txt` (drop `pytesseract`)

- [ ] **Step 1: Delete the four legacy modules**

```bash
git rm arkgrid/vision/recognizer.py arkgrid/vision/ocr.py arkgrid/vision/mapping.py arkgrid/vision/debug.py
```

- [ ] **Step 2: Rewrite `arkgrid/vision/__init__.py`**

Replace the entire file content with:

```python
"""Vision module for screen recognition of the astrogem cutting UI."""

from .capture import grab_screen, load_screenshot, normalize_to_fhd
from .templates import TemplateStore

__all__ = [
    "grab_screen",
    "load_screenshot",
    "normalize_to_fhd",
    "TemplateStore",
]
```

- [ ] **Step 3: Remove the `read` subparser from `cli.py`**

In `arkgrid/cli.py`, delete this block (the `# ---- read (vision) ----` comment, the subparser, and its trailing blank line):

```python
    # ---- read (vision) ----
    p_read = sub.add_parser("read", help="Read current game screen state via vision")
    p_read.add_argument("--screenshot", type=str, default=None, metavar="FILE",
                        help="Read from image file instead of live screen capture")
    p_read.add_argument("--debug", action="store_true", default=False,
                        help="Show debug visualization window")
    p_read.add_argument("--save-debug", type=str, default=None, metavar="FILE",
                        help="Save debug visualization to file")
    p_read.add_argument("--monitor", type=int, default=1,
                        help="Monitor index for live capture (default: 1 = primary)")

```

So the `p_live` block is immediately followed by the `# ---- auto (automation) ----` block.

- [ ] **Step 4: Remove the `cmd_read` function from `cli.py`**

In `arkgrid/cli.py`, delete the entire `cmd_read` function:

```python
def cmd_read(args: argparse.Namespace) -> None:
    """Read the game screen and print recognized state."""
    from arkgrid.vision import (
        ScreenRecognizer, draw_debug, describe_result,
        load_screenshot, grab_screen,
    )
    import cv2

    # Capture or load frame
    if args.screenshot:
        frame = load_screenshot(args.screenshot)
        print(f"Loaded screenshot: {args.screenshot} ({frame.shape[1]}x{frame.shape[0]})")
    else:
        frame = grab_screen(monitor_index=args.monitor)
        print(f"Captured screen ({frame.shape[1]}x{frame.shape[0]})")

    # Recognize
    recognizer = ScreenRecognizer()
    result = recognizer.recognize(frame)

    # Print results
    print()
    print(describe_result(result))

    # Debug output
    if args.debug or args.save_debug:
        debug_img = draw_debug(frame, result)
        if args.save_debug:
            cv2.imwrite(args.save_debug, debug_img)
            print(f"\nDebug image saved to {args.save_debug}")
        if args.debug:
            cv2.imshow("AstrogemCutter Vision Debug", debug_img)
            print("\nPress any key to close debug window...")
            cv2.waitKey(0)
            cv2.destroyAllWindows()
```

Leave exactly two blank lines between the function before it (`cmd_live`) and the function after it (`cmd_auto`).

- [ ] **Step 5: Remove the `read` dispatch branch from `cli.py`**

In the `main()` function of `arkgrid/cli.py`, delete these two lines:

```python
    elif args.command == "read":
        cmd_read(args)
```

- [ ] **Step 6: Drop the OCR dependency from `requirements.txt`**

In `requirements.txt`, delete this line (`ocr.py` was its only consumer):

```
pytesseract>=0.3.10
```

- [ ] **Step 7: Verify imports, CLI, and the test suite**

Run:

```bash
.venv/Scripts/python.exe -c "import arkgrid.vision, arkgrid.cli; print('imports OK')"
.venv/Scripts/python.exe -m arkgrid --help
.venv/Scripts/python.exe -m unittest discover -s tests
```

Expected: `imports OK`; the `--help` output lists subcommands `stats`, `sim`, `effects`, `live`, `auto`, `report` and **no** `read`; the test suite passes (same pass count as before — `test_cli.py` never referenced `read`).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove legacy OCR recognizer path and read command"
```

---

### Task 3: Delete superseded vision scripts and stale debug output

The seven root vision scripts are replaced by the tool built in Tasks 4-6. `examples/debug_output/` holds 18 regenerable debug PNGs from the old `debug_regions.py`.

**Files:**
- Delete: `extract_templates.py`, `extract_new.py`, `debug_regions.py`, `debug_measure.py`, `recognize_all.py`, `dedup_templates.py`, `test_ocr.py`
- Delete: `examples/debug_output/` (directory, 18 PNGs)

- [ ] **Step 1: Delete the scripts and the debug-output directory**

```bash
git rm extract_templates.py extract_new.py debug_regions.py debug_measure.py recognize_all.py dedup_templates.py test_ocr.py
git rm -r examples/debug_output
```

- [ ] **Step 2: Verify the suite still passes and the 60 screenshots remain**

Run:

```bash
.venv/Scripts/python.exe -m unittest discover -s tests
git ls-files examples/*.jpg | wc -l
```

Expected: the test suite passes; `60` screenshots still tracked under `examples/`.

- [ ] **Step 3: Commit**

`git rm` in Step 1 already staged every deletion. Do NOT run `git add -A` — it
would sweep pre-existing untracked files (`.claude/`, `lostark-arkgrid-gem-locator-v2/`,
older `docs/superpowers/` files) into the commit. Just commit the staged deletions:

```bash
git status --short
git commit -m "chore: delete superseded vision scripts and stale debug output"
```

Confirm `git status --short` shows the deletions staged (`D`) and that the untracked
items above remain untracked.

---

### Task 4: Extraction tool — scaffold and single-region crops

Create `tools/extract_templates.py`. This task implements the module skeleton and `extract_regions` for the fixed single-crop regions (anchor, gem_type, points, willpower, chaos, rerolls, steps).

**Files:**
- Create: `tools/extract_templates.py`
- Create: `tests/test_extract_templates.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_extract_templates.py` with exactly this content:

```python
"""Smoke tests for the template extraction tool (tools/extract_templates.py)."""

import os
import unittest

try:
    import cv2  # noqa: F401
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLE = os.path.join(PROJECT_ROOT, "examples", "turn_1_02.jpg")


@unittest.skipUnless(_HAVE_CV2, "opencv-python not installed")
@unittest.skipUnless(os.path.exists(_EXAMPLE), "example screenshot missing")
class TestExtractRegions(unittest.TestCase):
    def setUp(self):
        import cv2
        from arkgrid.vision.templates import TemplateStore
        from tools import extract_templates as ex
        self.ex = ex
        frame = cv2.imread(_EXAMPLE)
        self.gray = ex._to_fhd_gray(frame)
        self.anchor = ex.find_anchor(self.gray, TemplateStore())

    def test_anchor_found(self):
        self.assertIsNotNone(self.anchor)

    def test_single_region_categories_present(self):
        regions = self.ex.extract_regions(self.gray, self.anchor)
        for category in ("anchor", "gem_type", "points", "willpower",
                         "chaos", "rerolls", "steps"):
            self.assertIn(category, regions, category)
            self.assertEqual(len(regions[category]), 1, category)

    def test_crops_are_non_empty(self):
        regions = self.ex.extract_regions(self.gray, self.anchor)
        for category, items in regions.items():
            for label, crop in items:
                self.assertGreater(crop.size, 0, f"{category}/{label}")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m unittest tests.test_extract_templates -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.extract_templates'` (raised in `setUp`).

- [ ] **Step 3: Create `tools/extract_templates.py` with the scaffold**

Create `tools/extract_templates.py` with exactly this content:

```python
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


def _crop(gray: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
    """Crop a region, clamped to the frame bounds. None if it would be empty."""
    fh, fw = gray.shape[:2]
    x, y = max(0, x), max(0, y)
    w = min(w, fw - x)
    h = min(h, fh - y)
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

    return out


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract template-candidate crops from screenshots.")
    parser.add_argument("images", nargs="*",
                        help="Screenshot paths (default: examples/*.jpg)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Output directory (default: {DEFAULT_OUT})")
    parser.parse_args(argv)
    print("extract_templates: not yet implemented")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m unittest tests.test_extract_templates -v`
Expected: PASS — `test_anchor_found`, `test_single_region_categories_present`, `test_crops_are_non_empty` all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/extract_templates.py tests/test_extract_templates.py
git commit -m "feat: extraction tool scaffold with single-region crops"
```

---

### Task 5: Extraction tool — option-card and side-node sub-region crops

Extend `extract_regions` to crop the 4 option cards and 2 diamond side nodes. For each, emit a name crop plus the delta/Lv. crop at **both** the 1-line and 2-line vertical offsets (since the name may wrap to 2 lines, shifting the delta down one row).

The offsets below were measured against the existing templates in `arkgrid/vision/templates/options/` and `side_nodes/` across five example screenshots: 1-line option names sit at card-y≈19 with the delta at y≈38; 2-line names at y≈9 with the delta at y≈49. Side nodes: 1-line name at y≈17 / Lv. at y≈34; 2-line name at y≈9 / Lv. at y≈43.

**Files:**
- Modify: `tools/extract_templates.py`
- Modify: `tests/test_extract_templates.py`

- [ ] **Step 1: Add the failing test methods**

In `tests/test_extract_templates.py`, add these two methods to the `TestExtractRegions` class (after `test_crops_are_non_empty`):

```python
    def test_option_card_crop_counts(self):
        regions = self.ex.extract_regions(self.gray, self.anchor)
        # 4 cards: one name crop each, two delta variants each.
        self.assertEqual(len(regions["option_names"]), 4)
        self.assertEqual(len(regions["option_deltas"]), 8)

    def test_side_node_crop_counts(self):
        regions = self.ex.extract_regions(self.gray, self.anchor)
        # 2 side nodes: one name crop each, two Lv. variants each.
        self.assertEqual(len(regions["side_node_names"]), 2)
        self.assertEqual(len(regions["side_node_deltas"]), 4)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m unittest tests.test_extract_templates -v`
Expected: FAIL — `test_option_card_crop_counts` and `test_side_node_crop_counts` raise `KeyError: 'option_names'` / `'side_node_names'`.

- [ ] **Step 3: Add the sub-region offset constants**

In `tools/extract_templates.py`, immediately after the `_SINGLE_REGIONS` list, add:

```python
# ---------------------------------------------------------------------------
# Extraction-specific sub-region offsets. Kept here (not in
# arkgrid/vision/constants.py) because the runtime recogniser crops whole
# cards and matches by sub-image search, so it never needs them.
#
# An effect name is 1 or 2 text lines; the delta/Lv. indicator sits on the
# line below it, so its vertical position shifts when the name wraps. The
# tool does not detect the line count -- it emits the delta crop at BOTH
# offsets and the user keeps the correct one.
#
# Each tuple is (dx, dy, w, h) relative to the parent crop's top-left corner.
# ---------------------------------------------------------------------------

# Within an option card (C.OPTION_CARD_POSITIONS width x C.OPTION_CARD_HEIGHT,
# i.e. 117 x 70). Name band covers a 1- or 2-line name; delta bands are the
# 1-line and 2-line offsets.
OPT_NAME_SUBREGION = (0, 6, 117, 42)
OPT_DELTA_1LINE = (0, 34, 117, 25)
OPT_DELTA_2LINE = (0, 44, 117, 25)

# Within a side node (C.ROI_STAT_FIRST width x height, i.e. 102 x 57).
SN_NAME_SUBREGION = (0, 5, 102, 40)
SN_LV_1LINE = (0, 30, 102, 22)
SN_LV_2LINE = (0, 39, 102, 18)
```

- [ ] **Step 4: Extend `extract_regions` with the card/side-node crops**

In `tools/extract_templates.py`, in `extract_regions`, replace this block:

```python
    # Fixed single-crop anchor-relative regions.
    for category, (dx, dy, w, h) in _SINGLE_REGIONS:
        add(category, category, _crop(gray, ax + dx, ay + dy, w, h))

    return out
```

with:

```python
    # Fixed single-crop anchor-relative regions.
    for category, (dx, dy, w, h) in _SINGLE_REGIONS:
        add(category, category, _crop(gray, ax + dx, ay + dy, w, h))

    # Option cards (x4): name crop + delta crop at both line offsets.
    for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
        card = _crop(gray, ax + dx, ay + C.OPTION_CARD_Y_OFFSET,
                     card_w, C.OPTION_CARD_HEIGHT)
        if card is None:
            continue
        n = i + 1
        nx, ny, nw, nh = OPT_NAME_SUBREGION
        add("option_names", f"card{n}_name", _crop(card, nx, ny, nw, nh))
        for variant, (sx, sy, sw, sh) in (("1line", OPT_DELTA_1LINE),
                                          ("2line", OPT_DELTA_2LINE)):
            add("option_deltas", f"card{n}_delta_{variant}",
                _crop(card, sx, sy, sw, sh))

    # Diamond side nodes (x2): name crop + Lv. crop at both line offsets.
    for label, (dx, dy, w, h) in (("side1", C.ROI_STAT_FIRST),
                                  ("side2", C.ROI_STAT_SECOND)):
        node = _crop(gray, ax + dx, ay + dy, w, h)
        if node is None:
            continue
        nx, ny, nw, nh = SN_NAME_SUBREGION
        add("side_node_names", f"{label}_name", _crop(node, nx, ny, nw, nh))
        for variant, (sx, sy, sw, sh) in (("1line", SN_LV_1LINE),
                                          ("2line", SN_LV_2LINE)):
            add("side_node_deltas", f"{label}_lv_{variant}",
                _crop(node, sx, sy, sw, sh))

    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m unittest tests.test_extract_templates -v`
Expected: PASS — all five tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/extract_templates.py tests/test_extract_templates.py
git commit -m "feat: option-card and side-node sub-region extraction"
```

---

### Task 6: Extraction tool — finish crops, overlay, CLI

Add the no-anchor finish-screen pass, the debug overlay, the per-image processing/IO, the working CLI, and gitignore the output directory.

**Files:**
- Modify: `tools/extract_templates.py`
- Modify: `tests/test_extract_templates.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add the failing test methods**

In `tests/test_extract_templates.py`, add these two methods to the `TestExtractRegions` class (after `test_side_node_crop_counts`):

```python
    def test_finish_regions_returns_four_crops(self):
        # extract_finish_regions crops 4 fixed positions; on any FHD frame
        # all four are in-bounds.
        regions = self.ex.extract_finish_regions(self.gray)
        self.assertIn("finish", regions)
        self.assertEqual(len(regions["finish"]), 4)

    def test_overlay_is_fhd_sized(self):
        import cv2
        from arkgrid.vision import constants as C
        frame = cv2.imread(_EXAMPLE)
        overlay = self.ex.draw_overlay(frame, self.anchor)
        self.assertEqual(overlay.shape[0], C.REF_HEIGHT)
        self.assertEqual(overlay.shape[1], C.REF_WIDTH)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/Scripts/python.exe -m unittest tests.test_extract_templates -v`
Expected: FAIL — `AttributeError: module 'tools.extract_templates' has no attribute 'extract_finish_regions'` / `'draw_overlay'`.

- [ ] **Step 3: Add `extract_finish_regions` and `draw_overlay`**

In `tools/extract_templates.py`, insert these two functions immediately after `extract_regions` (before `main`):

```python
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
        nx, ny, nw, nh = OPT_NAME_SUBREGION
        box(cx + nx, cy + ny, nw, nh, "", (0, 255, 0))
        for sx, sy, sw, sh in (OPT_DELTA_1LINE, OPT_DELTA_2LINE):
            box(cx + sx, cy + sy, sw, sh, "", (255, 0, 200))

    for label, (dx, dy, bw, bh) in (("SIDE1", C.ROI_STAT_FIRST),
                                    ("SIDE2", C.ROI_STAT_SECOND)):
        box(ax + dx, ay + dy, bw, bh, label, (0, 200, 255))
        nx, ny, nw, nh = SN_NAME_SUBREGION
        box(ax + dx + nx, ay + dy + ny, nw, nh, "", (0, 255, 0))
        for sx, sy, sw, sh in (SN_LV_1LINE, SN_LV_2LINE):
            box(ax + dx + sx, ay + dy + sy, sw, sh, "", (255, 0, 200))

    return debug
```

- [ ] **Step 4: Replace `main` with the working implementation**

In `tools/extract_templates.py`, replace the entire `main` function:

```python
def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Extract template-candidate crops from screenshots.")
    parser.add_argument("images", nargs="*",
                        help="Screenshot paths (default: examples/*.jpg)")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help=f"Output directory (default: {DEFAULT_OUT})")
    parser.parse_args(argv)
    print("extract_templates: not yet implemented")
```

with:

```python
def _write_crops(regions: Dict[str, List[Tuple[str, np.ndarray]]],
                 basename: str, out_dir: str) -> int:
    """Write every crop to <out_dir>/<category>/<basename>_<label>.png."""
    count = 0
    for category, items in regions.items():
        cat_dir = os.path.join(out_dir, category)
        os.makedirs(cat_dir, exist_ok=True)
        for label, crop in items:
            cv2.imwrite(os.path.join(cat_dir, f"{basename}_{label}.png"), crop)
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
```

- [ ] **Step 5: Gitignore the output directory**

In `.gitignore`, append at the end of the file:

```
# Template extraction tool output
tools/extracted/
```

- [ ] **Step 6: Run the test suite**

Run: `.venv/Scripts/python.exe -m unittest tests.test_extract_templates -v`
Expected: PASS — all seven tests pass.

- [ ] **Step 7: Smoke-run the CLI**

Run:

```bash
.venv/Scripts/python.exe tools/extract_templates.py examples/turn_1_02.jpg examples/turn_1_01.jpg
```

Expected: prints `2 crops` summary lines; `tools/extracted/` now contains category folders (`option_names/`, `option_deltas/`, `side_node_names/`, `side_node_deltas/`, `gem_type/`, `willpower/`, etc.) with `turn_1_02_*.png` / `turn_1_01_*.png` crops, and `tools/extracted/_overlays/turn_1_02.png` + `turn_1_01.png`. Open an overlay and confirm the coloured boxes sit on the right UI elements. Confirm `git status` does **not** list `tools/extracted/`.

- [ ] **Step 8: Commit**

```bash
git add tools/extract_templates.py tests/test_extract_templates.py .gitignore
git commit -m "feat: finish-screen crops, debug overlay, and CLI for extraction tool"
```

---

### Task 7: Update README and CLAUDE.md

Reflect the removed `read` command and the new `tools/` layout in the docs.

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Remove the `read` section from `README.md`**

In `README.md`, delete this block (the section heading, body, code fence, and trailing blank line):

```markdown
### `read` - Vision debug

Read the game screen (from screenshot or live capture) and print the recognized state.

```bash
python -m arkgrid read [--screenshot FILE] [--debug] [--save-debug FILE]
```

```

So the `### `auto`` section's content is followed directly by `## Options`.

- [ ] **Step 2: Update the vision-features line in `README.md`**

In `README.md`, replace:

```
No external dependencies required for the simulator (stdlib only). Vision features (`live`, `read`) require `opencv-python`, `numpy`, and `mss`. Automation (`auto`) additionally requires Windows.
```

with:

```
No external dependencies required for the simulator (stdlib only). Vision features (`live`) require `opencv-python`, `numpy`, and `mss`. Automation (`auto`) additionally requires Windows.
```

- [ ] **Step 3: Update the vision-features line in `CLAUDE.md`**

In `CLAUDE.md`, replace:

```
No external dependencies for the simulator — stdlib only (`dataclasses`, `random`, `math`, `typing`). Vision features (`live`, `read`) require `opencv-python`, `numpy`, and `mss`. Automation (`auto`) additionally requires Windows (`ctypes` user32.dll). No build step, no linter configured.
```

with:

```
No external dependencies for the simulator — stdlib only (`dataclasses`, `random`, `math`, `typing`). Vision features (`live`) require `opencv-python`, `numpy`, and `mss`. Automation (`auto`) additionally requires Windows (`ctypes` user32.dll). No build step, no linter configured.
```

- [ ] **Step 4: Update the `cli.py` command list in `CLAUDE.md`**

In `CLAUDE.md`, replace:

```
- **`cli.py`** — CLI argument parsing and command handlers (`stats`, `sim`, `effects`, `live`, `read`, `auto`). Gem type auto-resolution from effect pairs in `_resolve_args()`.
```

with:

```
- **`cli.py`** — CLI argument parsing and command handlers (`stats`, `sim`, `effects`, `live`, `auto`, `report`). Gem type auto-resolution from effect pairs in `_resolve_args()`.
```

- [ ] **Step 5: Remove the legacy `recognizer.py` bullet in `CLAUDE.md`**

In `CLAUDE.md`, in the "Vision subpackage" section, delete this line:

```
- **`recognizer.py`** — `ScreenRecognizer`: anchor-relative detection pipeline using template matching for gem type, stats, effects, options, turn/step info
```

- [ ] **Step 6: Document `tools/` in `CLAUDE.md`**

In `CLAUDE.md`, immediately after the line `Tests live in \`tests/\`, split by module (e.g. \`test_pool.py\`, \`test_simulator.py\`).`, add a blank line and then:

```markdown
Developer scripts live in `tools/` (not part of the `arkgrid` package): `extract_templates.py` (crops template-candidate regions from screenshots into `tools/extracted/` for manual sorting, with a debug overlay per screenshot), plus `benchmark_reroll.py`, `calibration.py`, and `scenario.py` analysis scripts. Run them from the project root, e.g. `python tools/extract_templates.py`.
```

- [ ] **Step 7: Verify the docs reference no removed command**

Run:

```bash
grep -rn "arkgrid read\|recognizer.py\|extract_templates.py" README.md CLAUDE.md
```

Expected: the only match is the new `CLAUDE.md` line mentioning `tools/extract_templates.py`. No `arkgrid read` or `recognizer.py` references remain.

- [ ] **Step 8: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: drop read command, document tools/ directory"
```

---

## Self-Review

**Spec coverage:**
- Move `benchmark_reroll.py`/`calibration.py`/`scenario.py` to `tools/` → Task 1.
- Delete the 7 overlapping vision scripts → Task 3.
- Remove legacy OCR path (4 modules, `__init__.py`, `read` command, `requirements.txt`) → Task 2.
- Delete `examples/debug_output/` → Task 3.
- README/CLAUDE.md updates → Task 7.
- `tools/extract_templates.py`: invocation/output dir → Tasks 4 & 6; grouped-by-region output → Tasks 4-6; 1-line/2-line both-offsets → Task 5; debug overlay → Task 6; finish-screen pass → Task 6; extraction-specific constants in the tool → Task 5; `.gitignore` for `tools/extracted/` → Task 6.
- Testing: full-suite + CLI-help checks → Tasks 2, 3; `tests/test_extract_templates.py` skipped without `cv2` → Tasks 4-6.
- All spec sections map to a task.

**Placeholder scan:** No TBD/TODO. Every code step shows complete content. Pixel offsets in Task 5 are concrete measured values, not placeholders.

**Type consistency:** `extract_regions(gray, anchor)`, `extract_finish_regions(gray)`, `find_anchor(gray, store)`, `draw_overlay(frame_bgr, anchor)`, `_crop(gray, x, y, w, h)`, `_to_fhd_gray(frame_bgr)`, `process_image(path, store, out_dir)`, `_write_crops(regions, basename, out_dir)` — signatures are consistent across the tool and the test file. All return-shape contracts (`{category: [(label, crop)]}`) match between producer and test consumers.
