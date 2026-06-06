"""Vision module for screen recognition of the astrogem cutting UI."""

from .capture import grab_screen, load_screenshot, normalize_to_fhd
from .templates import TemplateStore

__all__ = [
    "grab_screen",
    "load_screenshot",
    "normalize_to_fhd",
    "TemplateStore",
]
