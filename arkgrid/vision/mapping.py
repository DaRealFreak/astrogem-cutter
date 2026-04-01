"""Map raw recognition results to domain models (GemState, Option)."""

from typing import List, Optional, Tuple

from ..models import GemState
from . import constants as C
from .recognizer import RecognitionResult


def map_to_gem_state(result: RecognitionResult) -> Optional[GemState]:
    """Convert a RecognitionResult into a GemState.

    Returns None if critical fields (willpower, chaos) are missing.
    """
    if not result.found:
        return None

    return GemState(
        will=result.willpower or 1,
        chaos=result.chaos or 1,
        first=result.first_level or 1,
        second=result.second_level or 1,
        cost_ratio=0,  # TODO: detect from Processing Cost line
        rerolls=result.rerolls or 0,
        first_effect=result.first_effect or "",
        second_effect=result.second_effect or "",
    )


def map_option_name(raw_name: Optional[str]) -> Optional[str]:
    """Map a recognized option name to an internal key.

    Returns the internal key (e.g. ``"attack_power"``, ``"chaos"``,
    ``"view"``) or None if unrecognized.
    """
    if raw_name is None:
        return None

    clean = raw_name.lower().replace("_", " ").strip()

    # Direct lookup
    if clean in C.OPTION_NAME_MAP:
        return C.OPTION_NAME_MAP[clean]

    # Fuzzy: check if any key is contained in the text
    for display, internal in C.OPTION_NAME_MAP.items():
        if display in clean or clean in display:
            return internal

    return None


def describe_result(result: RecognitionResult) -> str:
    """Return a human-readable summary of the recognition result."""
    if not result.found:
        return "Dialog not found (anchor not detected)"

    lines = []

    # Gem info
    gem_parts = []
    if result.gem_attr:
        gem_parts.append(result.gem_attr.capitalize())
    if result.gem_type:
        gem_parts.append(result.gem_type.capitalize())
    rarity = getattr(result, "rarity", None)
    if rarity:
        gem_parts.append(f"({rarity})")
    if gem_parts:
        lines.append(f"Gem: {' '.join(gem_parts)}")
    elif result.gem_info_ocr:
        lines.append(f"Gem (OCR): {result.gem_info_ocr}")

    # Current gem state
    lines.append("Current state:")
    will_str = str(result.willpower) if result.willpower is not None else "?"
    lines.append(f"  Willpower: {will_str}")
    pts_label = "Chaos" if result.gem_attr == "chaos" else "Order" if result.gem_attr == "order" else "Chaos/Order"
    pts_str = str(result.chaos) if result.chaos is not None else "?"
    lines.append(f"  {pts_label} Points: {pts_str}")
    first_name = result.first_effect or "?"
    first_lv = str(result.first_level) if result.first_level is not None else "?"
    lines.append(f"  Side 1: {first_name} Lv.{first_lv}")
    second_name = result.second_effect or "?"
    second_lv = str(result.second_level) if result.second_level is not None else "?"
    lines.append(f"  Side 2: {second_name} Lv.{second_lv}")

    # Options
    for opt in result.options:
        name = opt.name_text or "?"
        delta = opt.delta_text or ""
        lines.append(f"  Option {opt.card_index+1}: {name}"
                     f" [{delta}] (via {opt.source})"
                     f"{f' raw=[{opt.raw_ocr}]' if opt.raw_ocr and not opt.name_key else ''}")

    # Turn
    if result.current_turn is not None:
        total = result.total_turns or "?"
        lines.append(f"Turn: {result.current_turn}/{total}")
    elif result.turn_text_ocr:
        lines.append(f"Turn (OCR): {result.turn_text_ocr}")

    # Anchor confidence
    lines.append(f"Anchor confidence: {result.anchor_score:.3f}")

    return "\n".join(lines)
