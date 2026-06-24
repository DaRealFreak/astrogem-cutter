"""Export golden DetectionResults for the TS vision parity suite.

Run from repo root:  source .venv/Scripts/activate && python tools/export_vision_golden.py
Writes web/tests/fixtures/detection.json. Commit the output. Requires opencv-python.
"""
from __future__ import annotations
import json, glob, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
from arkgrid.vision.template_recognizer import detect

FIX = Path("web/tests/fixtures")
SCHEMA_VERSION = 1

def _sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"

def rec(file: str) -> dict:
    frame = cv2.imread(file)
    d = detect(frame)
    return {
        "file": os.path.basename(file),
        "expected": {
            "found": d.found,
            "gem_type": d.gem_type, "gem_type_score": d.gem_type_score,
            "willpower": d.willpower, "willpower_score": d.willpower_score,
            "chaos": d.chaos, "chaos_score": d.chaos_score,
            "first_effect": d.first_effect, "first_effect_score": d.first_effect_score,
            "first_level": d.first_level, "first_level_score": d.first_level_score,
            "second_effect": d.second_effect, "second_effect_score": d.second_effect_score,
            "second_level": d.second_level, "second_level_score": d.second_level_score,
            "rerolls": d.rerolls, "rerolls_score": d.rerolls_score,
            "current_step": d.current_step, "step_score": d.step_score,
            "total_steps": d.total_steps, "rarity_score": d.rarity_score,
            "options": [
                {"name_key": o.name_key, "name_score": o.name_score,
                 "delta_key": o.delta_key, "delta_score": o.delta_score}
                for o in d.options
            ],
        },
    }

def main():
    FIX.mkdir(parents=True, exist_ok=True)
    files = sorted(glob.glob("examples/*.jpg")) + sorted(glob.glob("examples/*.png"))
    records = [rec(f) for f in files]
    payload = {"meta": {"schema": SCHEMA_VERSION, "arkgrid_sha": _sha(),
                        "n": len(records)}, "records": records}
    (FIX / "detection.json").write_text(json.dumps(payload, indent=1))
    print(f"wrote detection.json ({len(records)} records)")

if __name__ == "__main__":
    main()
