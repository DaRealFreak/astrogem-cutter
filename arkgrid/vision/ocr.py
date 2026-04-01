"""OCR-based text recognition with auto-crop saving for template bootstrapping.

Primary recognition method for option names, stat values, and turn counter.
Falls back gracefully if Tesseract is not available.
"""

import os
import re
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from .constants import Roi

# Try to import pytesseract
try:
    import pytesseract

    # Auto-detect Tesseract on Windows
    _TESSERACT_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for p in _TESSERACT_PATHS:
        if os.path.isfile(p):
            pytesseract.pytesseract.tesseract_cmd = p
            break

    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False


def _templates_dir() -> Path:
    return Path(__file__).parent / "templates"


def _uncropped_dir() -> Path:
    d = _templates_dir() / "uncropped"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ocr_available() -> bool:
    """Return True if Tesseract OCR is available and working."""
    if not _HAS_TESSERACT:
        return False
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_region(
    frame: np.ndarray,
    roi: Roi,
    category: str = "unknown",
    *,
    save_crop: bool = True,
    psm: int = 6,
    scale: int = 4,
    threshold: int = 110,
    use_adaptive: bool = False,
) -> Optional[str]:
    """OCR a region of the frame.

    Parameters
    ----------
    frame : grayscale or BGR image
    roi : (x, y, w, h) region to OCR
    category : label for the auto-saved crop file
    save_crop : if True and text is recognized, save crop for future template creation
    psm : Tesseract page segmentation mode (6=block, 7=single line)
    scale : upscale factor before OCR
    threshold : binarization threshold (ignored if use_adaptive)
    use_adaptive : use adaptive thresholding instead of global

    Returns
    -------
    Recognized text (stripped), or None if OCR is unavailable or fails.
    """
    if not _HAS_TESSERACT:
        return None

    x, y, w, h = roi
    # Clamp to frame bounds
    fh, fw = frame.shape[:2]
    x = max(0, x)
    y = max(0, y)
    w = min(w, fw - x)
    h = min(h, fh - y)
    if w <= 0 or h <= 0:
        return None

    # Convert to grayscale if needed
    crop = frame[y:y + h, x:x + w]
    if len(crop.shape) == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Upscale for better OCR
    up = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale),
                    interpolation=cv2.INTER_CUBIC)

    # Binarize
    if use_adaptive:
        binary = cv2.adaptiveThreshold(
            up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 21, -20
        )
    else:
        _, binary = cv2.threshold(up, threshold, 255, cv2.THRESH_BINARY)

    # Light morphological cleanup
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    try:
        text = pytesseract.image_to_string(binary, config=f"--psm {psm} --oem 3").strip()
    except Exception:
        return None

    if text and save_crop:
        _save_uncropped(crop, category, text)

    return text if text else None


def ocr_option_card(
    frame: np.ndarray,
    card_roi: Roi,
) -> Tuple[Optional[str], Optional[str]]:
    """OCR an option card, returning (name_keywords, delta_text).

    Uses the full card area for recognition, then splits into
    identifiable keywords for option mapping.
    """
    if not _HAS_TESSERACT:
        return None, None

    x, y, w, h = card_roi
    fh, fw = frame.shape[:2]
    x, y = max(0, x), max(0, y)
    w = min(w, fw - x)
    h = min(h, fh - y)
    if w <= 0 or h <= 0:
        return None, None

    crop = frame[y:y + h, x:x + w]
    if len(crop.shape) == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Upscale 5x for better small-text OCR
    up = cv2.resize(crop, (crop.shape[1] * 5, crop.shape[0] * 5),
                    interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(up, 110, 255, cv2.THRESH_BINARY)
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    try:
        text = pytesseract.image_to_string(
            binary, config="--psm 6 --oem 3"
        ).strip()
    except Exception:
        return None, None

    if not text:
        return None, None

    # Save for template bootstrapping
    _save_uncropped(crop, "option_card", text)

    # Parse into name and delta
    name, delta = _parse_option_text(text)
    return name, delta


def _parse_option_text(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract option name and delta from raw OCR text.

    Uses keyword matching since OCR is imperfect with game fonts.
    """
    text = raw.lower().replace("\n", " ").replace("  ", " ")

    # Identify the option name via keywords
    name = _identify_option_name(text)

    # Identify the delta/modifier
    delta = _identify_delta(text)

    return name, delta


def _identify_option_name(text: str) -> Optional[str]:
    """Identify option name from OCR text using keyword matching."""
    # Ordered by specificity (most specific first)
    keyword_map = [
        # Effect change options
        (["effect", "changed"], "effect_changed"),
        (["change"], "effect_changed"),
        # Reroll
        (["view", "other"], "view"),
        (["other", "item"], "view"),
        # Cost
        (["cost"], "processing_cost"),
        # Willpower
        (["efficiency"], "willpower"),
        (["willpower"], "willpower"),
        # Chaos/Order points - OCR often misreads first letter
        (["chaos", "point"], "chaos"),
        (["haos", "point"], "chaos"),       # OCR reads "~haos"
        (["order", "point"], "order"),
        (["rder", "point"], "order"),       # OCR misread tolerance
        # Effects with "Enh" (Enhancement)
        (["ally", "damage", "enh"], "ally_damage"),
        (["ally", "atk", "enh"], "ally_attack"),
        (["ally", "attack", "enh"], "ally_attack"),
        (["additional", "damage"], "additional_damage"),
        # Shorter matches
        (["brand", "power"], "brand_power"),
        (["boss", "damage"], "boss_damage"),
        (["atk", "power"], "attack_power"),
        (["attack", "power"], "attack_power"),
        (["ally", "damage"], "ally_damage"),
        (["ally", "attack"], "ally_attack"),
        (["enh"], "enhancement"),  # generic enhancement
        (["damage"], "damage"),    # generic damage
        (["power"], "power"),      # generic power
        # Points - generic fallback (chaos or order, determined by gem type)
        (["point"], "points"),
        # Maintain/modifier
        (["maintain"], "maintain"),
        (["modifier"], "maintain"),
    ]

    for keywords, name in keyword_map:
        if all(kw in text for kw in keywords):
            return name

    return None


def _identify_delta(text: str) -> Optional[str]:
    """Identify delta/modifier from OCR text."""
    t = text.lower()

    # Cost modifiers: look for "100" anywhere when option is cost-related
    if "100" in text:
        if "-" in text or "minus" in t:
            return "-100%"
        return "+100%"

    # Effect Changed
    if "changed" in t or "change" in t:
        return "effect_changed"

    # View Other Items (reroll): look for "time" with a digit
    m = re.search(r"(\d)\s*(?:time|reroll)", t)
    if m:
        return f"+{m.group(1)}_reroll"

    # Level changes from "Lv" patterns (OCR often reads Lv as lv/ly/le/iv)
    m = re.search(r"(?:[Ll][VvYy]|[Ii][Vv])\.?\s*(\d)", text)
    if m:
        return f"Lv.{m.group(1)}"

    # Explicit "+N" pattern (not near "100")
    m = re.search(r"\+\s*([1-5])\b", text)
    if m:
        return f"+{m.group(1)}"

    return None


def _save_uncropped(crop: np.ndarray, category: str, ocr_text: str) -> None:
    """Save crop and OCR result for future template creation."""
    out_dir = _uncropped_dir()
    timestamp = int(time.time() * 1000)
    safe_text = "".join(
        c if c.isalnum() or c in "._- " else "_" for c in ocr_text[:40]
    )
    base = f"{category}_{safe_text}_{timestamp}"

    cv2.imwrite(str(out_dir / f"{base}.png"), crop)
    with open(str(out_dir / f"{base}.txt"), "w", encoding="utf-8") as f:
        f.write(ocr_text)
