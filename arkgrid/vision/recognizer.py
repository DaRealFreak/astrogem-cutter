"""Full recognition pipeline: anchor → ROIs → extract state.

Ported from the TypeScript project's ``captureWorker.ts``
``FrameProcessor.processFrame()`` method.

Uses template matching for anchor detection (stable UI element) and
OCR for variable text content (option names, stat values, turn counter).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from . import constants as C
from .matcher import MatchResult, find_best_match, find_template
from .ocr import ocr_available, ocr_option_card, ocr_region
from .templates import TemplateStore


@dataclass
class OptionCardResult:
    """A single recognized option card."""
    card_index: int
    name_key: Optional[str] = None    # internal key from OCR keyword matching
    delta_key: Optional[str] = None   # delta from OCR
    raw_ocr: Optional[str] = None     # raw OCR text for debugging
    source: str = "none"              # "ocr" or "none"

    @property
    def name_text(self) -> Optional[str]:
        return self.name_key

    @property
    def delta_text(self) -> Optional[str]:
        return self.delta_key


@dataclass
class RecognitionResult:
    """Complete recognition output for one frame."""
    found: bool = False
    anchor_location: Optional[Tuple[int, int]] = None
    anchor_score: float = 0.0

    # Gem info
    gem_type: Optional[str] = None       # e.g. "erosion", "collapse"
    gem_attr: Optional[str] = None       # "chaos" or "order"
    gem_info_ocr: Optional[str] = None   # raw OCR text

    # Current stat levels (from diamond display)
    willpower: Optional[int] = None
    chaos: Optional[int] = None          # or "order" points
    first_effect: Optional[str] = None
    first_level: Optional[int] = None
    second_effect: Optional[str] = None
    second_level: Optional[int] = None

    # 4 option cards
    options: List[OptionCardResult] = field(default_factory=list)

    # Turn info
    current_turn: Optional[int] = None
    total_turns: Optional[int] = None
    turn_text_ocr: Optional[str] = None

    # Reroll info
    rerolls: Optional[int] = None

    # Debug info
    debug_matches: List[Tuple[str, Optional[MatchResult]]] = field(
        default_factory=list
    )


class ScreenRecognizer:
    """Anchor-relative screen recognition pipeline.

    Uses template matching ONLY for anchor detection (stable UI element).
    All variable text (options, stats, turns) is read via OCR.
    """

    def __init__(self, template_store: Optional[TemplateStore] = None):
        self._store = template_store or TemplateStore()
        self._prev_anchor: Optional[Tuple[int, int]] = None
        self._use_ocr = ocr_available()

    def recognize(self, frame_bgr: np.ndarray) -> RecognitionResult:
        """Run the full recognition pipeline on a BGR frame."""
        result = RecognitionResult()

        # Keep color frame for OCR (better than grayscale for preprocessing)
        frame = frame_bgr

        # Grayscale for anchor matching
        if len(frame_bgr.shape) == 3:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame_bgr
            frame = frame_bgr

        # Normalize to FHD
        h, w = gray.shape[:2]
        if h != C.REF_HEIGHT or w != C.REF_WIDTH:
            gray = cv2.resize(gray, (C.REF_WIDTH, C.REF_HEIGHT),
                              interpolation=cv2.INTER_AREA)
            if len(frame.shape) == 3:
                frame = cv2.resize(frame, (C.REF_WIDTH, C.REF_HEIGHT),
                                   interpolation=cv2.INTER_AREA)
            else:
                frame = gray

        # Find anchor (template matching - works perfectly for stable UI)
        anchor_loc = self._find_anchor(gray, result)
        if anchor_loc is None:
            return result

        result.found = True
        ax, ay = anchor_loc

        # All variable text via OCR
        if self._use_ocr:
            self._extract_gem_info_ocr(frame, ax, ay, result)
            self._extract_diamond_stats_ocr(frame, ax, ay, result)
            self._extract_options_ocr(frame, ax, ay, result)
            self._extract_turn_counter_ocr(frame, ax, ay, result)
        else:
            for i in range(4):
                result.options.append(OptionCardResult(card_index=i))

        # Post-processing: infer missing info
        self._infer_missing(result)

        return result

    # ------------------------------------------------------------------
    # Anchor detection (template matching - always works)
    # ------------------------------------------------------------------

    def _find_anchor(
        self, gray: np.ndarray, result: RecognitionResult
    ) -> Optional[Tuple[int, int]]:
        anchors = self._store.get_anchor()
        if not anchors:
            return None

        # Cached location first
        if self._prev_anchor is not None:
            px, py = self._prev_anchor
            margin = 30
            narrow_roi = (px - margin, py - margin,
                          C.ANCHOR_SIZE[0] + 2 * margin,
                          C.ANCHOR_SIZE[1] + 2 * margin)
            match = find_best_match(gray, anchors, roi=narrow_roi,
                                    threshold=C.THRESHOLD_ANCHOR)
            if match is not None:
                self._prev_anchor = match.location
                result.anchor_location = match.location
                result.anchor_score = match.score
                result.debug_matches.append(("anchor_cached", match))
                return match.location

        # Full search
        match = find_best_match(gray, anchors, roi=C.ANCHOR_SEARCH_ROI,
                                threshold=C.THRESHOLD_ANCHOR)
        if match is not None:
            self._prev_anchor = match.location
            result.anchor_location = match.location
            result.anchor_score = match.score
            result.debug_matches.append(("anchor_full", match))
            return match.location

        self._prev_anchor = None
        return None

    # ------------------------------------------------------------------
    # Gem info via OCR
    # ------------------------------------------------------------------

    def _extract_gem_info_ocr(
        self, frame: np.ndarray, ax: int, ay: int, result: RecognitionResult
    ) -> None:
        """Try to extract gem info. Falls back to inference from other data."""
        # The subtitle text is highly ornamental and hard to OCR.
        # Try it but don't rely on it.
        roi = self._offset_roi(ax, ay, C.ROI_SUBTITLE)
        text = ocr_region(frame, roi, "gem_info", save_crop=False,
                          psm=7, scale=3, threshold=130)
        if text:
            result.gem_info_ocr = text
            text_lower = text.lower()
            for attr_name, attr_key in C.GEM_ATTR_MAP.items():
                if attr_name in text_lower:
                    result.gem_attr = attr_key
                    break
            for type_name, type_key in C.GEM_TYPE_MAP.items():
                if type_name in text_lower:
                    result.gem_type = type_key
                    break

    # ------------------------------------------------------------------
    # Diamond stats via OCR
    # ------------------------------------------------------------------

    def _extract_diamond_stats_ocr(
        self, frame: np.ndarray, ax: int, ay: int, result: RecognitionResult
    ) -> None:
        # Willpower (top gem - single digit, most reliable)
        will_roi = self._offset_roi(ax, ay, C.ROI_STAT_WILLPOWER)
        text = ocr_region(frame, will_roi, "stat_will",
                          save_crop=False, psm=10, scale=8, threshold=150)
        if text:
            digits = "".join(c for c in text if c.isdigit())
            if digits:
                result.willpower = int(digits[0])

        # Bottom gem: chaos/order points (full block - name + number)
        pts_roi = self._offset_roi(ax, ay, C.ROI_STAT_POINTS_FULL)
        text = ocr_region(frame, pts_roi, "stat_points",
                          save_crop=False, psm=6, scale=4, threshold=120)
        if text:
            t = text.lower()
            if "order" in t or "rder" in t:
                result.gem_attr = "order"
            elif "chaos" in t or "haos" in t:
                result.gem_attr = "chaos"
            elif "point" in t:
                pass  # detected points but can't determine chaos/order
            # Extract the level digit (usually on its own line)
            digits = [c for c in text if c.isdigit()]
            if digits:
                result.chaos = int(digits[-1])

        # First effect (left gem - full block)
        first_roi = self._offset_roi(ax, ay, C.ROI_STAT_FIRST_FULL)
        text = ocr_region(frame, first_roi, "stat_first",
                          save_crop=False, psm=6, scale=4, threshold=120)
        if text:
            result.first_effect = self._parse_effect_name(text)
            lv = self._extract_level(text)
            if lv is not None:
                result.first_level = lv

        # Second effect (right gem - full block)
        second_roi = self._offset_roi(ax, ay, C.ROI_STAT_SECOND_FULL)
        text = ocr_region(frame, second_roi, "stat_second",
                          save_crop=False, psm=6, scale=4, threshold=120)
        if text:
            result.second_effect = self._parse_effect_name(text)
            lv = self._extract_level(text)
            if lv is not None:
                result.second_level = lv

    # ------------------------------------------------------------------
    # Option cards via OCR
    # ------------------------------------------------------------------

    def _extract_options_ocr(
        self, frame: np.ndarray, ax: int, ay: int, result: RecognitionResult
    ) -> None:
        for i, (dx, card_w) in enumerate(C.OPTION_CARD_POSITIONS):
            card_x = ax + dx
            card_y = ay + C.OPTION_CARD_Y_OFFSET
            card_roi = (card_x, card_y, card_w, C.OPTION_CARD_HEIGHT)

            name_key, delta_key = ocr_option_card(frame, card_roi)

            card_result = OptionCardResult(
                card_index=i,
                name_key=name_key,
                delta_key=delta_key,
                source="ocr" if name_key else "none",
            )

            # Store raw OCR for debugging
            raw = ocr_region(frame, card_roi, f"opt{i}",
                             save_crop=False, psm=6, scale=5, threshold=110)
            card_result.raw_ocr = raw

            result.options.append(card_result)

    # ------------------------------------------------------------------
    # Turn counter via OCR
    # ------------------------------------------------------------------

    def _extract_turn_counter_ocr(
        self, frame: np.ndarray, ax: int, ay: int, result: RecognitionResult
    ) -> None:
        btn_roi = self._offset_roi(ax, ay, C.ROI_PROCESS_BUTTON)
        text = ocr_region(frame, btn_roi, "turn_counter",
                          save_crop=False, psm=7, scale=3, threshold=150)
        if text:
            result.turn_text_ocr = text
            m = re.search(r"(\d+)\s*/\s*(\d+)", text)
            if m:
                result.current_turn = int(m.group(1))
                result.total_turns = int(m.group(2))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _offset_roi(
        ax: int, ay: int, relative_roi: Tuple[int, int, int, int]
    ) -> Tuple[int, int, int, int]:
        dx, dy, w, h = relative_roi
        return (ax + dx, ay + dy, w, h)

    @staticmethod
    def _parse_effect_name(text: str) -> Optional[str]:
        """Extract effect name from OCR text using keywords."""
        t = text.lower()
        if "brand" in t and "power" in t:
            return "brand_power"
        if "boss" in t and "damage" in t:
            return "boss_damage"
        if "additional" in t and "damage" in t:
            return "additional_damage"
        if "ally" in t and "damage" in t:
            return "ally_damage"
        if "ally" in t and ("atk" in t or "attack" in t):
            return "ally_attack"
        if "atk" in t or "attack" in t:
            return "attack_power"
        if "damage" in t:
            return "additional_damage"  # fallback
        if "power" in t:
            return "brand_power"  # fallback
        return None

    @staticmethod
    def _extract_level(text: str) -> Optional[int]:
        """Extract level number from text like 'Lv. 3' or 'Lv 1'."""
        m = re.search(r"[Ll][Vv]\.?\s*(\d)", text)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _infer_missing(result: RecognitionResult) -> None:
        """Infer missing fields from other recognized data."""
        # Infer rarity from total turns
        if result.total_turns is not None:
            rarity_map = {5: "common", 7: "rare", 9: "epic"}
            rarity = rarity_map.get(result.total_turns)
            if rarity and not hasattr(result, "rarity"):
                result.rarity = rarity  # type: ignore[attr-defined]

        # Infer gem attribute from "chaos"/"order" option names
        if result.gem_attr is None:
            for opt in result.options:
                if opt.name_key == "chaos":
                    result.gem_attr = "chaos"
                    break
                if opt.name_key == "order":
                    result.gem_attr = "order"
                    break

        # Resolve generic "points" to chaos or order based on gem attribute
        for opt in result.options:
            if opt.name_key == "points":
                if result.gem_attr == "chaos":
                    opt.name_key = "chaos"
                elif result.gem_attr == "order":
                    opt.name_key = "order"
