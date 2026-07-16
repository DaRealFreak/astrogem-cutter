"""Option-card detection on the 2026-07 game-UI update (arkgrid/vision).

The July 2026 game update shrank the option-card text to ~93% of its old
size and re-wrapped some names ("Processing Cost" / "Processing State" now
fit on one line).  The option templates were re-extracted from new-UI
screenshots (old-UI compatibility deliberately dropped); detect() strips
numeric variant suffixes so downstream consumers see canonical keys
("cost+100", "maintained", ...).

These tests pin:
  * correct option name/delta detection on the new-UI screenshots
    (would fail against the pre-update template set),
  * no variant suffix leaking out of detect() (raw delta keys feed DP
    Option keys such as "cost+100"/"cost-100" and parse_delta's exact
    string matches).
"""

import os
import re
import unittest

try:
    import cv2  # noqa: F401
    _HAVE_CV2 = True
except ImportError:
    _HAVE_CV2 = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLES = os.path.join(PROJECT_ROOT, "examples")

# file -> [(name_key, delta_key), ...] for the 4 option cards, ground truth
# read off the screenshots by hand.
_NEW_UI_CARDS = {
    "20260716010621_1.jpg": [
        ("order", "1_line_+1"),                 # Order Points +1
        ("additional_damage", "2_line_lvl+1"),  # Additional Damage Lv. 1
        ("will", "2_line_+1"),                  # Willpower Efficiency +1
        ("cost", "cost+100"),                   # Processing Cost +100%
    ],
    "20260716010904_1.jpg": [
        ("brand_power", "1_line_lvl+1"),        # Brand Power Lv. 1
        ("additional_damage", "2_line_lvl+1"),  # Additional Damage Lv. 1
        ("cost", "cost-100"),                   # Processing Cost -100%
        ("order", "1_line_+1"),                 # Order Points +1
    ],
    "20260716011107_1.jpg": [
        ("brand_power", "1_line_lvl+1"),        # Brand Power Lv. 1
        ("maintain", "maintained"),             # Processing State Maintained
        ("brand_power", "1_line_effect_changed"),  # Brand Power Effect Changed
        ("additional_damage", "2_line_lvl+2"),  # Additional Damage Lv. 2
    ],
}

# Batch 2/3 screenshots covering the card types absent from the first three
# shots (chaos points, view, attack power, ally/boss damage, ally attack,
# multi-point deltas, level 3/4, willpower -1, level-down, effect-changed
# layouts). Ground truth eyeballed from the offer-row strips.
_UI_UPDATE_CARDS = {
    "20260716015255_1.jpg": [
        ("additional_damage", "2_line_lvl+1"),
        ("chaos", "1_line_+1"),                 # Chaos Points +1
        ("attack_power", "1_line_lvl+1"),       # Atk. Power Lv. 1
        ("additional_damage", "2_line_lvl+2"),
    ],
    "20260716015332_1.jpg": [
        ("ally_damage", "2_line_effect_changed"),  # Ally Damage Enh. EC
        ("brand_power", "1_line_lvl+1"),
        ("view", "reroll+2"),                   # View Other Items +2 times
        ("will", "2_line_+1"),
    ],
    "20260716015355_1.jpg": [
        ("order", "1_line_+1"),
        ("view", "reroll+1"),                   # View Other Items +1 time
        ("additional_damage", "2_line_lvl+2"),
        ("brand_power", "1_line_lvl+1"),
    ],
    "20260716015222_1.jpg": [
        ("will", "2_line_-1"),                  # Willpower Efficiency -1
        ("maintain", "maintained"),
        ("brand_power", "1_line_lvl+3"),
        ("will", "2_line_+1"),
    ],
    "20260716015210_1.jpg": [
        ("order", "1_line_+1"),
        ("will", "2_line_+3"),
        ("brand_power", "1_line_lvl+4"),
        ("will", "2_line_+2"),
    ],
    "20260716015318_1.jpg": [
        ("ally_damage", "2_line_lvl+3"),        # Ally Damage Enh. Lv. 3
        ("will", "2_line_+1"),
        ("order", "1_line_+1"),
        ("will", "2_line_+2"),
    ],
    "20260716015133_1.jpg": [
        ("will", "2_line_+1"),
        ("additional_damage", "2_line_lvl+1"),
        ("additional_damage", "2_line_effect_changed"),
        ("will", "2_line_+2"),
    ],
    "20260716015351_1.jpg": [
        ("attack_power", "1_line_lvl+2"),
        ("will", "2_line_+1"),
        ("ally_damage", "2_line_lvl+2"),
        ("attack_power", "1_line_effect_changed"),
    ],
    "20260716023628_1.jpg": [
        ("will", "2_line_+3"),
        ("cost", "cost+100"),
        ("boss_damage", "1_line_lvl+1"),        # Boss Damage Lv. 1
        ("will", "2_line_+1"),
    ],
    "20260716023727_1.jpg": [
        ("additional_damage", "2_line_lvl+1"),
        ("attack_power", "1_line_lvl+1"),
        ("will", "2_line_+1"),
        ("additional_damage", "2_line_lvl-1"),  # Additional Damage Lv. 1 (down)
    ],
    "20260716023749_1.jpg": [
        ("order", "1_line_+1"),
        ("will", "2_line_+1"),
        ("order", "1_line_+2"),
        ("ally_attack", "1_line_lvl+1"),        # Ally Attack Enh. Lv. 1
    ],
    "20260716034755_1.jpg": [
        ("attack_power", "1_line_lvl+1"),
        ("will", "2_line_-1"),                  # Willpower Efficiency -1
        ("order", "1_line_-1"),                 # Order Points -1 (red on gold)
        ("attack_power", "1_line_lvl-1"),       # Atk. Power Lv. 1 (down)
    ],
    # New-UI replacements for the last two pre-update shots (2026-07-16);
    # kept in the covering set for reroll counts 3 and 4.
    "reroll_3.jpg": [
        ("order", "1_line_+1"),                 # Order Points +1
        ("ally_damage", "2_line_lvl+1"),        # Ally Damage Enh. Lv. 1
        ("attack_power", "1_line_lvl+1"),       # Atk. Power Lv. 1
        ("cost", "cost+100"),                   # Processing Cost +100%
    ],
    "reroll_4.jpg": [
        ("boss_damage", "1_line_lvl+1"),        # Boss Damage Lv. 1
        ("additional_damage", "2_line_lvl+1"),  # Additional Damage Lv. 1
        ("boss_damage", "1_line_effect_changed"),  # Boss Damage Effect Changed
        ("chaos", "1_line_+2"),                 # Chaos Points +2
    ],
}

_VARIANT_SUFFIX = re.compile(r"_\d+$")


@unittest.skipUnless(_HAVE_CV2, "opencv-python not installed")
class TestNewUiOptionDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        from arkgrid.vision.template_recognizer import detect
        cls.results = {}
        for name in _NEW_UI_CARDS:
            path = os.path.join(_EXAMPLES, name)
            assert os.path.exists(path), path
            cls.results[name] = detect(cv2.imread(path))
        cls.ui_update_results = {}
        for name in _UI_UPDATE_CARDS:
            path = os.path.join(_EXAMPLES, name)
            assert os.path.exists(path), path
            cls.ui_update_results[name] = detect(cv2.imread(path))

    def test_new_ui_screens_are_found(self):
        for name in _NEW_UI_CARDS:
            self.assertTrue(self.results[name].found, name)

    def test_new_ui_option_cards(self):
        from arkgrid.vision import constants as C
        for name, expected in _NEW_UI_CARDS.items():
            d = self.results[name]
            self.assertEqual(len(d.options), 4, name)
            for i, ((want_name, want_delta), opt) in enumerate(
                    zip(expected, d.options)):
                label = f"{name} card{i + 1}"
                self.assertEqual(opt.name_key, want_name, label)
                self.assertEqual(opt.delta_key, want_delta, label)
                self.assertGreaterEqual(opt.name_score,
                                        C.THRESHOLD_OPTION_NAME, label)
                self.assertGreaterEqual(opt.delta_score,
                                        C.THRESHOLD_OPTION_DELTA, label)

    def test_new_ui_gem_state(self):
        d = self.results["20260716010621_1.jpg"]
        self.assertEqual(d.gem_type, "order_stability")
        self.assertEqual(d.willpower, 1)
        self.assertEqual(d.chaos, 1)
        self.assertEqual(d.first_effect, "brand_power")
        self.assertEqual(d.first_level, 1)
        self.assertEqual(d.second_effect, "additional_damage")
        self.assertEqual(d.second_level, 1)
        self.assertEqual(d.rerolls, "2")
        self.assertEqual(d.current_step, 9)
        self.assertEqual(d.total_steps, 9)
        self.assertIs(d.reset_enabled, False)  # turn 1: reset greyed

    def test_ui_update_option_cards(self):
        from arkgrid.vision import constants as C
        for name, expected in _UI_UPDATE_CARDS.items():
            d = self.ui_update_results[name]
            self.assertTrue(d.found, name)
            self.assertEqual(len(d.options), 4, name)
            for i, ((want_name, want_delta), opt) in enumerate(
                    zip(expected, d.options)):
                label = f"{name} card{i + 1}"
                self.assertEqual(opt.name_key, want_name, label)
                self.assertEqual(opt.delta_key, want_delta, label)
                self.assertGreaterEqual(opt.name_score,
                                        C.THRESHOLD_OPTION_NAME, label)
                self.assertGreaterEqual(opt.delta_score,
                                        C.THRESHOLD_OPTION_DELTA, label)

    def test_reroll_counts_3_and_4_on_new_ui(self):
        # reroll_3.jpg / reroll_4.jpg are new-UI shots (2026-07-16) pinning
        # the higher reroll-counter values; the counter renders as
        # "N / base" in-game and the template key is the available count.
        d3 = self.ui_update_results["reroll_3.jpg"]
        self.assertEqual(d3.rerolls, "3")
        self.assertEqual(d3.current_step, 5)
        self.assertEqual(d3.total_steps, 7)   # rare (base 1 free reroll)
        d4 = self.ui_update_results["reroll_4.jpg"]
        self.assertEqual(d4.rerolls, "4")
        self.assertEqual(d4.current_step, 8)
        self.assertEqual(d4.total_steps, 9)   # epic (base 2 free rerolls)

    def test_no_variant_suffix_leaks(self):
        # New-UI variants ("cost+100_02", ...) must be stripped by detect():
        # raw delta keys become DP Option keys and parse_delta exact matches.
        for results in (self.results, self.ui_update_results):
            for name, d in results.items():
                for i, opt in enumerate(d.options):
                    self.assertIsNone(
                        _VARIANT_SUFFIX.search(opt.delta_key or ""),
                        f"{name} card{i + 1}: {opt.delta_key}")
