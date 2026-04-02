"""Vision constants: ROI offsets, thresholds, and name mappings."""

from typing import Tuple

# Type alias for ROI: (x, y, width, height) in pixels
Roi = Tuple[int, int, int, int]

# ---------------------------------------------------------------------------
# Match thresholds (0-1, higher = stricter).  Mirrors the TypeScript
# project's ``thresholdSet`` pattern.
# ---------------------------------------------------------------------------
THRESHOLD_ANCHOR = 0.70
THRESHOLD_GEM_INFO = 0.65
THRESHOLD_OPTION_NAME = 0.65
THRESHOLD_OPTION_DELTA = 0.65
THRESHOLD_STAT_LEVEL = 0.65
THRESHOLD_DIGIT = 0.65

# ---------------------------------------------------------------------------
# Reference resolution.  All ROI offsets below are measured at this size.
# When the capture is a different resolution the recognizer scales to FHD
# before matching.
# ---------------------------------------------------------------------------
REF_WIDTH = 1920
REF_HEIGHT = 1080

# ---------------------------------------------------------------------------
# Anchor region – "Processing" header text.
# We search the upper-center of the screen first.
# ---------------------------------------------------------------------------
ANCHOR_SEARCH_ROI: Roi = (650, 20, 700, 80)  # generous search area
ANCHOR_SIZE: Tuple[int, int] = (170, 22)  # expected template size

# ---------------------------------------------------------------------------
# All ROI offsets below are relative to the **top-left** corner of the
# detected anchor bounding-box (approx 895, 43 at FHD).
# Format: (dx, dy, width, height)
# ---------------------------------------------------------------------------

# Gem type icon (chaos/order gem subtype)
ROI_GEM_TYPE: Roi = (55, 68, 19, 23)

# Current astrogem points text (e.g. "4 Astrogem Points")
ROI_POINTS: Roi = (-11, 168, 140, 20)

# Diamond stat display – individual stat positions
# Willpower level (single digit, top of diamond)
ROI_STAT_WILLPOWER: Roi = (56, 309, 16, 16)
# First side node (left of diamond – effect name + Lv)
ROI_STAT_FIRST: Roi = (-72, 332, 102, 57)
# Second side node (right of diamond – effect name + Lv)
ROI_STAT_SECOND: Roi = (96, 332, 102, 57)
# Chaos/order points level (single digit, bottom of diamond)
ROI_STAT_CHAOS: Roi = (56, 427, 16, 16)

# ---------------------------------------------------------------------------
# Option cards – 4 cards arranged horizontally, 117px each, adjacent
# Centers: (781,598), (898,598), (1015,598), (1132,598)
# ---------------------------------------------------------------------------
OPTION_CARD_Y_OFFSET = 520  # dy from anchor top (598 - 35 - 43)
OPTION_CARD_HEIGHT = 70

# (dx, width) for each card
OPTION_CARD_POSITIONS = [
    (-172, 117),  # Card 1: abs 723..840
    (-55, 117),   # Card 2: abs 840..957
    (62, 117),    # Card 3: abs 957..1074
    (179, 117),   # Card 4: abs 1074..1191
]

# ---------------------------------------------------------------------------
# Bottom info area
# ---------------------------------------------------------------------------
# Reroll count indicator
ROI_REROLL: Roi = (340, 542, 56, 20)

# Process button – contains "Process (X/Y)" text; only the step digit
ROI_PROCESS_STEPS: Roi = (195, 714, 28, 18)

# ---------------------------------------------------------------------------
# Option name → internal key mapping
# Maps the display text (as recognized) to our domain option types.
# ---------------------------------------------------------------------------
OPTION_NAME_MAP = {
    "atk. power": "attack_power",
    "atk power": "attack_power",
    "attack power": "attack_power",
    "additional damage": "additional_damage",
    "boss damage": "boss_damage",
    "brand power": "brand_power",
    "ally damage enh.": "ally_damage",
    "ally damage": "ally_damage",
    "ally attack enh.": "ally_attack",
    "ally atk. enh.": "ally_attack",
    "ally attack": "ally_attack",
    "chaos points": "chaos",
    "willpower": "will",
    "willpower efficiency": "will",
    "processing cost": "cost",
    "view other items": "view",
    "view other options": "view",
    "processing modifier": "other",
    "maintain": "other",
}

# Delta text → (option_type, delta_value) mapping
DELTA_TEXT_MAP = {
    "lv": "level_change",       # followed by a number showing target level
    "+100%": ("cost", 100),
    "-100%": ("cost", -100),
    "+100": ("cost", 100),
    "-100": ("cost", -100),
    "effect changed": "effect_change",
    "+1 time": ("view", 1),
    "+2 times": ("view", 2),
    "+1 reroll": ("view", 1),
    "+2 rerolls": ("view", 2),
}

# Gem type display names → internal keys
GEM_TYPE_MAP = {
    "stability": "stability",
    "fortitude": "fortitude",
    "immutability": "immutability",
    "corrosion": "erosion",
    "erosion": "erosion",
    "distortion": "distortion",
    "collapse": "collapse",
}

# Gem attribute display names → internal keys
GEM_ATTR_MAP = {
    "chaos": "chaos",
    "order": "order",
}
