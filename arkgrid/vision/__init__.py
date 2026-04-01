"""Vision module for screen recognition of the astrogem cutting UI."""

from .capture import grab_screen, load_screenshot, normalize_to_fhd
from .debug import draw_debug
from .mapping import describe_result, map_option_name, map_to_gem_state
from .recognizer import RecognitionResult, ScreenRecognizer
from .templates import TemplateStore

__all__ = [
    "grab_screen",
    "load_screenshot",
    "normalize_to_fhd",
    "draw_debug",
    "describe_result",
    "map_option_name",
    "map_to_gem_state",
    "RecognitionResult",
    "ScreenRecognizer",
    "TemplateStore",
]
