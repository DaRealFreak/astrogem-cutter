"""Reset-button brightness detection (arkgrid/vision/template_recognizer.detect).

The Reset label is greyed when unavailable and bright white when available;
detect() reads this from the fraction of bright pixels in ROI_RESET_BUTTON.
"""

import os
import unittest

try:
    import cv2  # noqa: F401
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENABLED = os.path.join(PROJECT_ROOT, "examples", "20260403224002_1.jpg")
_DISABLED = os.path.join(PROJECT_ROOT, "examples", "turn_test_9.jpg")
_TURN1 = os.path.join(PROJECT_ROOT, "examples", "turn_1_02.jpg")


@unittest.skipUnless(_HAVE_CV2, "opencv-python not installed")
class TestResetDetection(unittest.TestCase):
    def _detect(self, path):
        import cv2
        from arkgrid.vision.template_recognizer import detect
        self.assertTrue(os.path.exists(path), path)
        return detect(cv2.imread(path))

    def test_enabled_reset_is_detected(self):
        d = self._detect(_ENABLED)
        self.assertTrue(d.found)
        self.assertIs(d.reset_enabled, True)

    def test_disabled_reset_is_detected(self):
        d = self._detect(_DISABLED)
        self.assertTrue(d.found)
        self.assertIs(d.reset_enabled, False)

    def test_turn_one_reads_as_unavailable(self):
        # Reset is greyed on turn 1 (it is a no-op there); detection must
        # report it unavailable rather than guessing it is enabled.
        d = self._detect(_TURN1)
        self.assertTrue(d.found)
        self.assertIs(d.reset_enabled, False)

    def test_bright_fraction_separates_states(self):
        # Sanity: the two states sit on opposite sides of the threshold with
        # a wide margin (enabled ~0.077, disabled ~0.001).
        from arkgrid.vision import constants as C
        en = self._detect(_ENABLED).reset_score
        dis = self._detect(_DISABLED).reset_score
        self.assertGreater(en, C.RESET_ENABLED_FRACTION)
        self.assertLess(dis, C.RESET_ENABLED_FRACTION)


if __name__ == "__main__":
    unittest.main()
