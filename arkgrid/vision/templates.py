"""Template loading, caching and resolution scaling.

Ported concept from the TypeScript project's ``matStore.ts``.
Unlike the TS version which packs sprites into atlases for browser perf,
this loads individual PNG files – equally fast on desktop.
"""

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np


def _templates_dir() -> Path:
    """Return the absolute path to the templates directory."""
    return Path(__file__).parent / "templates"


class TemplateStore:
    """Lazy-loading, caching template manager."""

    def __init__(self, base_resolution: Tuple[int, int] = (1920, 1080)):
        self._base = base_resolution
        self._cache: Dict[str, Dict[str, np.ndarray]] = {}
        self._scale: float = 1.0

    def set_scale(self, capture_width: int, capture_height: int) -> None:
        """Compute scale factor from capture resolution vs reference."""
        ref_w, ref_h = self._base
        self._scale = ref_h / capture_height if capture_height else 1.0
        # If the capture is already FHD, scale is 1.0
        # If capture is QHD (1440p), we need to scale templates up by 1440/1080 = 1.33
        # But since we resize the frame to FHD before matching, scale stays 1.0
        self._scale = 1.0  # We normalize frame to FHD, so templates stay as-is

    def _load_dir(self, subdir: str) -> Dict[str, np.ndarray]:
        """Load all .png files from a template subdirectory as grayscale."""
        if subdir in self._cache:
            return self._cache[subdir]

        templates: Dict[str, np.ndarray] = {}
        dirpath = _templates_dir() / subdir
        if not dirpath.exists():
            self._cache[subdir] = templates
            return templates

        for f in sorted(dirpath.iterdir()):
            if f.suffix.lower() == ".png":
                img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    key = f.stem  # filename without extension
                    templates[key] = img

        self._cache[subdir] = templates
        return templates

    def get_anchor(self) -> Dict[str, np.ndarray]:
        """Load anchor template(s)."""
        return self._load_dir("anchor")

    def get_options(self) -> Dict[str, np.ndarray]:
        """Load full option card templates."""
        return self._load_dir("options")

    def get_option_names(self) -> Dict[str, np.ndarray]:
        """Load option name-only templates (upper portion of card).

        Returns only templates whose key ends with ``_name``.
        """
        all_opts = self._load_dir("options")
        return {k: v for k, v in all_opts.items() if k.endswith("_name")}

    def get_deltas(self) -> Dict[str, np.ndarray]:
        """Load delta/effect templates."""
        return self._load_dir("deltas")

    def get_digits(self) -> Dict[str, np.ndarray]:
        """Load digit templates for turn counter."""
        return self._load_dir("digits")

    def get_gem_info(self) -> Dict[str, np.ndarray]:
        """Load gem info (rarity/type) templates."""
        return self._load_dir("gem_info")

    def get_template(self, subdir: str, name: str) -> Optional[np.ndarray]:
        """Load a specific template by subdirectory and filename stem."""
        templates = self._load_dir(subdir)
        return templates.get(name)

    def clear_cache(self) -> None:
        """Clear all cached templates."""
        self._cache.clear()
