# Design: Project cleanup + consolidated template extraction tool

**Date:** 2026-05-18
**Status:** Approved

## Problem

The project root has accumulated overlapping one-off scripts, and the
`arkgrid/vision/` package carries two parallel screen-recognition
implementations. Two concrete goals:

1. **Clean up the project** so `arkgrid/` (plus `tests/`) is clearly the
   required core, and supporting scripts are organised rather than scattered
   across the root.
2. **Replace the scattered template-extraction scripts with one tool** that
   crops every template-able region from a handful of screenshots, so a game
   UI change only requires re-running it and re-sorting the crops by hand.

## Part 1 — Project cleanup

### Move analysis scripts into `tools/`

Create a new `tools/` directory with an empty `tools/__init__.py` (so the
directory is importable as a package for tests). Move:

- `benchmark_reroll.py` → `tools/benchmark_reroll.py`
- `calibration.py` → `tools/calibration.py`
- `scenario.py` → `tools/scenario.py`

Each moved script gets a 2-line project-root `sys.path` bootstrap at the top
so both `python tools/<name>.py` (run from the project root) and
`python -m tools.<name>` work:

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

`scenario.py` imports from `tests.test_scenarios`; with the bootstrap (project
root on `sys.path`) that import keeps working.

### Delete the overlapping vision scripts

These are superseded by the new extraction tool (Part 2):

- `extract_templates.py`
- `extract_new.py`
- `debug_regions.py`
- `debug_measure.py`
- `recognize_all.py`
- `dedup_templates.py`
- `test_ocr.py`

### Remove the legacy OCR recognizer path

The `live` and `auto` commands use `arkgrid/vision/template_recognizer.py`
(pure template matching). Only the `read` debug command uses the older
OCR-based recogniser. Remove that path entirely:

- Delete `arkgrid/vision/recognizer.py`
- Delete `arkgrid/vision/ocr.py`
- Delete `arkgrid/vision/mapping.py`
- Delete `arkgrid/vision/debug.py`
- Rewrite `arkgrid/vision/__init__.py` to export only the still-used symbols:
  `grab_screen`, `load_screenshot`, `normalize_to_fhd`, `TemplateStore`.
- `arkgrid/cli.py`: remove the `read` subparser (`p_read`), the `cmd_read`
  handler, and the `elif args.command == "read"` dispatch branch.
- `requirements.txt`: drop the OCR dependency (`pytesseract` / Tesseract-only
  entries) if present, since `ocr.py` was its only consumer.

Modules that **stay** (still used by `live`/`auto`): `capture.py`,
`constants.py`, `matcher.py` (`find_best_match` + its internal
`find_template`), `templates.py`, `template_recognizer.py`.

Verification: `test_cli.py` has no `read`/recogniser references, so removing
the command does not break the test suite.

### Other cleanup

- Delete `examples/debug_output/` — 18 tracked, regenerable debug PNGs
  produced by the old `debug_regions.py`.
- The 60 source screenshots in `examples/*.jpg` stay tracked (unchanged).
- `lostark-arkgrid-gem-locator-v2/` (separate untracked TypeScript project) is
  left untouched.

### Documentation updates

- `README.md`: remove the `### read` command section and its usage example.
- `CLAUDE.md`: update the vision-subpackage section (drop `recognizer.py`,
  `ocr.py`, `mapping.py`, `debug.py`); update the `cli.py` command list to
  `stats`, `sim`, `effects`, `live`, `auto`; note `tools/` and the extraction
  tool.

## Part 2 — `tools/extract_templates.py`

A single consolidated tool. Replaces all seven deleted vision scripts.

### Invocation

```
python tools/extract_templates.py                      # all examples/*.jpg
python tools/extract_templates.py shotA.jpg shotB.jpg   # specific files
python tools/extract_templates.py --out some/dir/       # custom output dir
```

Default output directory: `tools/extracted/` (added to `.gitignore`).

### Behaviour

For each input screenshot:

1. Normalise to the 1920×1080 reference resolution (reuse the existing
   `arkgrid.vision.constants` reference dimensions).
2. Find the cutting-screen anchor. If found, crop all cutting-screen regions.
   If not found, attempt a best-effort finish-screen pass (the 4 finish stat
   digits at their fixed absolute positions).
3. Write the cropped template candidates, grouped by region type.
4. Write one debug overlay image for the screenshot.

### Output layout

`tools/extracted/` mirrors the `arkgrid/vision/templates/` categories:

```
extracted/
  anchor/
  gem_type/
  points/
  willpower/
  chaos/
  rerolls/
  steps/
  side_node_names/
  side_node_deltas/
  option_names/
  option_deltas/
  finish/
  _overlays/
```

Crops are grouped by region type only. Assigning a crop to a specific
willpower/chaos/first/second slot (and discarding wrong-offset crops) is left
to the user — the tool only crops, it does not sort.

### Filenames

`<screenshot_basename>_<region>[_<variant>].png`, e.g.:

```
turn_1_02_gem_type.png
turn_1_02_willpower.png
turn_1_02_card1_name_1line.png
turn_1_02_card1_name_2line.png
turn_1_02_card1_delta_1line.png
turn_1_02_card1_delta_2line.png
turn_1_02_side1_name_1line.png
turn_1_02_side1_name_2line.png
turn_1_02_side1_lv_1line.png
turn_1_02_side1_lv_2line.png
```

The `_1line` / `_2line` variant suffix keeps each ambiguous pair adjacent when
the folder is sorted alphabetically, so the wrong one is easy to spot and
delete.

### 1-line vs 2-line handling

An effect name on an option card or a diamond side node is either 1 or 2 text
lines. The delta indicator (`+2 ▲`, `Lv. 1 ▲`, `Effect Changed`) sits on the
line below the name, so its vertical position shifts by one line depending on
whether the name wrapped.

The tool does **not** try to detect the line count. For every option card (×4)
and side node (×2) it always emits four crops:

- the name crop at the **1-line** offset (stops above the delta line),
- the name crop at the **2-line** offset (extends one line lower),
- the delta/Lv. crop at the **1-line** offset,
- the delta/Lv. crop at the **2-line** offset.

This is fully deterministic — no detector that could mis-fire on the exact UI
change that triggered the re-extraction. The user keeps the correct delta crop
and deletes the other while sorting.

### Debug overlay

One overlay PNG per screenshot in `extracted/_overlays/`. Draws, on a copy of
the full screenshot, a labelled coloured rectangle for every ROI — including
the option-card and side-node sub-regions (name, delta-1line, delta-2line) —
so region alignment can be eyeballed after a UI change before trusting the
crops. Ported from the old `debug_regions.py` overlay logic.

### Constants

Extraction-specific sub-region offsets — the name region, the 1-line delta
region and the 2-line delta region within an option card or side node — live
as constants **inside `tools/extract_templates.py`**, not in
`arkgrid/vision/constants.py`. The runtime recogniser
(`template_recognizer.py`) crops whole cards and matches templates by
sub-image search, so it never needs these offsets; keeping them in the tool
avoids polluting the runtime module. The tool still imports the existing
runtime constants it does need (anchor search ROI, reference resolution,
whole-card positions, single-region ROIs).

The exact offset values are calibrated during implementation from the existing
template files in `arkgrid/vision/templates/options/` and `side_nodes/` and by
inspecting the debug overlay.

## Testing

- **Cleanup** is verified by the full `unittest` suite passing
  (`python -m unittest discover -s tests -v`) plus a CLI-help smoke check
  (`python -m arkgrid --help` and each remaining subcommand's `--help`).
- **Extraction tool**: a new `tests/test_extract_templates.py`, skipped when
  `cv2` is unavailable (vision deps are optional). It runs the tool's
  `extract_regions` function on one bundled example screenshot and asserts the
  expected category folders are produced and contain non-empty crops.

## Out of scope

- Reworking `template_recognizer.py` or the `templates/` set itself.
- Touching `lostark-arkgrid-gem-locator-v2/`.
- Rewriting git history to shrink the tracked `examples/*.jpg` (~66 MB).
- Auto-detecting 1-line vs 2-line names (explicitly rejected in favour of the
  deterministic crop-both approach).
