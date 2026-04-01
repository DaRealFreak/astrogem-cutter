"""Screen capture via mss."""

from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import mss
except ImportError:
    mss = None  # type: ignore[assignment]


def grab_screen(monitor_index: int = 0) -> np.ndarray:
    """Capture the full monitor, return a BGR numpy array.

    *monitor_index* 0 = all monitors combined, 1 = primary, 2 = secondary, etc.
    """
    if mss is None:
        raise RuntimeError("mss is not installed – run: pip install mss")

    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 0
        monitor = monitors[monitor_index]
        screenshot = sct.grab(monitor)
        # mss returns BGRA; convert to BGR for OpenCV
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def grab_region(x: int, y: int, w: int, h: int) -> np.ndarray:
    """Capture a specific screen region, return BGR numpy array."""
    if mss is None:
        raise RuntimeError("mss is not installed – run: pip install mss")

    with mss.mss() as sct:
        region = {"top": y, "left": x, "width": w, "height": h}
        screenshot = sct.grab(region)
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)


def load_screenshot(path: str) -> np.ndarray:
    """Load an image file as a BGR numpy array (for offline testing)."""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Could not load image: {path}")
    return img


def normalize_to_fhd(frame: np.ndarray) -> Tuple[np.ndarray, float]:
    """Resize frame to 1920×1080 if needed.  Returns (resized, scale_factor).

    The scale_factor is ``original_height / 1080``.  If the frame is
    already 1080p the factor is 1.0 and no resize occurs.
    """
    h, w = frame.shape[:2]
    if h == 1080 and w == 1920:
        return frame, 1.0

    scale = h / 1080.0
    resized = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
    return resized, scale
