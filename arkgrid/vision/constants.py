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

# Subtitle line: "Chaos Astrogem: Corrosion"
ROI_SUBTITLE = (-55, 100, 280, 60)

# Diamond stat display – individual stat positions
# All offsets relative to anchor top-left (approx 895, 43)
# Top gem = willpower number (single digit)
ROI_STAT_WILLPOWER = (55, 312, 45, 15)
# Left gem = first effect (full block: name + Lv)
ROI_STAT_FIRST_FULL = (-80, 350, 145, 50)
# Right gem = second effect (full block: name + Lv)
ROI_STAT_SECOND_FULL = (120, 350, 155, 50)
# Bottom gem = chaos/order points (full block: name + number)
ROI_STAT_POINTS_FULL = (-5, 407, 145, 58)

# "One of the following is randomly applied." text
ROI_RANDOMLY_APPLIED = (-105, 487, 330, 25)

# ---------------------------------------------------------------------------
# Option cards – 4 cards arranged horizontally
# Each card has: option name (line 1) and delta/effect (line 2)
# ---------------------------------------------------------------------------
OPTION_CARD_Y_OFFSET = 529  # dy from anchor top
OPTION_CARD_HEIGHT = 48

# (dx, width) for each card
OPTION_CARD_POSITIONS = [
    (-165, 130),  # Card 1
    (-40, 130),   # Card 2
    (80, 130),    # Card 3
    (195, 130),   # Card 4
]

# Within each card, the name and delta sub-regions (relative to card top-left)
CARD_NAME_ROI = (0, 11, 130, 17)   # option name text only (no icon)
CARD_DELTA_ROI = (0, 32, 130, 16)  # delta / effect text

# Reroll indicator
ROI_REROLL = (295, 530, 40, 22)

# ---------------------------------------------------------------------------
# Bottom info area
# ---------------------------------------------------------------------------
ROI_PROCESSING_COST = (-125, 582, 440, 18)
ROI_BALANCE = (-125, 602, 440, 18)
ROI_STATUS_TEXT = (-140, 672, 340, 18)

# Process button – contains "Process (X/Y)" text
ROI_PROCESS_BUTTON = (50, 710, 180, 24)

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
