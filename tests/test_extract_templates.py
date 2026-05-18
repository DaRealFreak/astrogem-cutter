"""Smoke tests for the template extraction tool (tools/extract_templates.py)."""

import os
import unittest

try:
    import cv2  # noqa: F401
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLE = os.path.join(PROJECT_ROOT, "examples", "turn_1_02.jpg")


@unittest.skipUnless(_HAVE_CV2, "opencv-python not installed")
@unittest.skipUnless(os.path.exists(_EXAMPLE), "example screenshot missing")
class TestExtractRegions(unittest.TestCase):
    def setUp(self):
        import cv2
        from arkgrid.vision.templates import TemplateStore
        from tools import extract_templates as ex
        self.ex = ex
        frame = cv2.imread(_EXAMPLE)
        self.gray = ex._to_fhd_gray(frame)
        self.anchor = ex.find_anchor(self.gray, TemplateStore())

    def test_anchor_found(self):
        self.assertIsNotNone(self.anchor)

    def test_single_region_categories_present(self):
        regions = self.ex.extract_regions(self.gray, self.anchor)
        for category in ("anchor", "gem_type", "points", "willpower",
                         "chaos", "rerolls", "steps"):
            self.assertIn(category, regions, category)
            self.assertEqual(len(regions[category]), 1, category)

    def test_crops_are_non_empty(self):
        regions = self.ex.extract_regions(self.gray, self.anchor)
        for category, items in regions.items():
            for label, crop in items:
                self.assertGreater(crop.size, 0, f"{category}/{label}")
