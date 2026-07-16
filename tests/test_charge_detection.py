"""Charge-button brightness detection (arkgrid/vision/template_recognizer.detect).

When free rerolls are exhausted the "View Other Options" button becomes a yellow
"Charge" button (spend the gold extra-reroll ticket); it is greyed when the
ticket is unavailable. detect() reads availability from the fraction of bright
pixels in ROI_CHARGE_BUTTON — the yellow fill is bright (~0.08), the greyed
button is near-zero. Mirrors the reset-button brightness read.
"""

import os
import unittest

try:
    import cv2  # noqa: F401
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENABLED = os.path.join(PROJECT_ROOT, "examples", "20260403224002_1.jpg")   # yellow Charge
_DISABLED = os.path.join(PROJECT_ROOT, "examples", "20260402072807_1.jpg")   # greyed Charge


@unittest.skipUnless(_HAVE_CV2, "opencv-python not installed")
class TestChargeDetection(unittest.TestCase):
    def _detect(self, path):
        import cv2
        from arkgrid.vision.template_recognizer import detect
        self.assertTrue(os.path.exists(path), path)
        return detect(cv2.imread(path))

    def test_enabled_charge_is_detected(self):
        d = self._detect(_ENABLED)
        self.assertTrue(d.found)
        self.assertIs(d.charge_enabled, True)

    def test_disabled_charge_is_detected(self):
        d = self._detect(_DISABLED)
        self.assertTrue(d.found)
        self.assertIs(d.charge_enabled, False)

    def test_bright_fraction_separates_states(self):
        # The two states sit on opposite sides of the threshold with a wide
        # margin (enabled ~0.080, disabled ~0.000).
        from arkgrid.vision import constants as C
        en = self._detect(_ENABLED).charge_score
        dis = self._detect(_DISABLED).charge_score
        self.assertGreater(en, C.CHARGE_ENABLED_FRACTION)
        self.assertLess(dis, C.CHARGE_ENABLED_FRACTION)


if __name__ == "__main__":
    unittest.main()
