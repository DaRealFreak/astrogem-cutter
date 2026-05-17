"""Regression tests for arkgrid.log_analyzer (the `report` command).

The headline bug these guard against: a turn record's ``offers`` field uses
option labels from ``automation._fmt_option`` ("order +1", "boss_damage +2",
"boss_damage EC"), while its ``picked`` field is a *state-delta description*
from ``automation._infer_picked`` ("chaos +1", "first +2",
"first_effect -> X"). The two vocabularies coincide only for willpower, so the
old ``picks[picked]`` keying counted every chaos / effect / reroll pick as 0.
``option_stats`` now runs ``picked`` through ``_normalize_picked`` first.
"""

from __future__ import annotations

import unittest

from arkgrid.log_analyzer import GemRecord, option_stats


def _sb(will=1, chaos=1, first=1, second=1,
        first_effect="boss_damage", second_effect="attack_power"):
    """A turn's state_before dict, matching run_logger._state_dict's keys."""
    return {"will": will, "chaos": chaos, "first": first, "second": second,
            "first_effect": first_effect, "second_effect": second_effect,
            "rerolls": 0, "total": will + chaos + first + second}


def _turn(offers, picked, state_before, action="process"):
    return {"event": "turn", "action": action, "offers": offers,
            "picked": picked, "state_before": state_before}


def _record(turns, success=False, total_points=0):
    return GemRecord(args={}, log_path="t.jsonl", gem_index=1,
                     success=success, total_points=total_points, turns=turns)


def _by_key(records):
    _, stats = option_stats(records)
    return {s.key: s for s in stats}


class TestPickAttribution(unittest.TestCase):
    """`picked` (a state delta) must be matched to the offer it refers to."""

    def test_chaos_pick_attributed_to_order_option(self):
        # The reported bug: "order +1" appeared but showed 0 picks because the
        # chaos pick was logged as "chaos +1".
        rec = _record([_turn(
            offers=["will +1", "order +1", "boss_damage +2", "cost-100"],
            picked="chaos +1",
            state_before=_sb(will=2))])
        by_key = _by_key([rec])
        self.assertEqual(by_key["order +1"].appearances, 1)
        self.assertEqual(by_key["order +1"].picks, 1)
        # The raw delta string must not leak through as its own option.
        self.assertNotIn("chaos +1", by_key)

    def test_effect_level_pick_attributed_to_effect_option(self):
        # "first +2" = the first side node (boss_damage) leveled up by 2.
        rec = _record([_turn(
            offers=["will +1", "boss_damage +2", "attack_power +1", "maintain"],
            picked="first +2",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertEqual(by_key["boss_damage +2"].picks, 1)
        self.assertEqual(by_key["attack_power +1"].picks, 0)

    def test_effect_change_pick_attributed_to_ec_option(self):
        rec = _record([_turn(
            offers=["will +1", "boss_damage EC", "order +1", "cost+100"],
            picked="first_effect -> additional_damage",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertEqual(by_key["boss_damage EC"].picks, 1)

    def test_reroll_option_pick_attributed(self):
        rec = _record([_turn(
            offers=["will +1", "reroll+1", "order +1", "maintain"],
            picked="rerolls +1",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertEqual(by_key["reroll+1"].picks, 1)

    def test_will_pick_still_matches(self):
        # Willpower already worked (the two vocabularies coincide) — guard it.
        rec = _record([_turn(
            offers=["will +1", "order +2", "boss_damage +1", "maintain"],
            picked="will +1",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertEqual(by_key["will +1"].picks, 1)


class TestCapClamping(unittest.TestCase):
    """`_infer_picked` records the clamped delta, not the offer's nominal one."""

    def test_capped_levelup_disambiguated_by_clamped_delta(self):
        # will is 3; offers are "will +1" (3->4) and "will +3" (3->5, clamped
        # to +2). _infer_picked recorded "will +2", and only "will +3" yields
        # a clamped +2 from will=3.
        rec = _record([_turn(
            offers=["will +1", "will +3", "order +1", "maintain"],
            picked="will +2",
            state_before=_sb(will=3))])
        by_key = _by_key([rec])
        self.assertEqual(by_key["will +3"].picks, 1)
        self.assertEqual(by_key["will +1"].picks, 0)

    def test_single_offer_of_kind_matched_regardless_of_delta(self):
        # will is 4; the only willpower offer is "will +3", clamped 4->5, so
        # the delta logged was "will +1". Kind-based matching still finds it.
        rec = _record([_turn(
            offers=["will +3", "order +1", "boss_damage +1", "maintain"],
            picked="will +1",
            state_before=_sb(will=4))])
        by_key = _by_key([rec])
        self.assertEqual(by_key["will +3"].picks, 1)


class TestUnattributablePicks(unittest.TestCase):
    """No-op outcomes can't always be tied to one offer — but aren't lost."""

    def test_single_noop_offer_is_attributed(self):
        rec = _record([_turn(
            offers=["will +1", "order +1", "boss_damage +1", "maintain"],
            picked="maintain / cost",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertEqual(by_key["maintain"].picks, 1)

    def test_ambiguous_noop_pick_is_bucketed_not_dropped(self):
        # maintain + cost-100 both offered, state unchanged -> can't tell which.
        rec = _record([_turn(
            offers=["will +1", "order +1", "maintain", "cost-100"],
            picked="maintain / cost",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertIn("(no state change)", by_key)
        self.assertEqual(by_key["(no state change)"].picks, 1)
        # It is a picks-only diagnostic row, not an offered option.
        self.assertEqual(by_key["(no state change)"].appearances, 0)


class TestLabelCanonicalisation(unittest.TestCase):
    """The chaos stat is OCR'd as both "order" and "chaos" — fold to one row."""

    def test_order_and_chaos_offer_variants_merge(self):
        rec = _record([
            _turn(offers=["order +1", "will +1", "boss_damage +1", "maintain"],
                  picked="chaos +1", state_before=_sb()),
            _turn(offers=["chaos +1", "will +1", "boss_damage +1", "maintain"],
                  picked="chaos +1", state_before=_sb()),
        ])
        by_key = _by_key([rec])
        self.assertNotIn("chaos +1", by_key)
        self.assertEqual(by_key["order +1"].appearances, 2)
        self.assertEqual(by_key["order +1"].picks, 2)


class TestCompoundPicks(unittest.TestCase):
    """_infer_picked sometimes appends spurious reroll-budget drift."""

    def test_reroll_drift_stripped_from_compound_pick(self):
        # "chaos +2, rerolls +1": the reroll part is turn-boundary drift; the
        # real pick is the chaos change -> "order +2".
        rec = _record([_turn(
            offers=["will +1", "order +2", "boss_damage +1", "maintain"],
            picked="chaos +2, rerolls +1",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertEqual(by_key["order +2"].picks, 1)
        self.assertNotIn("chaos +2, rerolls +1", by_key)

    def test_genuinely_compound_pick_left_as_anomaly(self):
        # Two real components -> cannot pick one; surfaces as its own row.
        rec = _record([_turn(
            offers=["will +1", "order +1", "boss_damage +1", "maintain"],
            picked="will +1, chaos +1",
            state_before=_sb())])
        by_key = _by_key([rec])
        self.assertIn("will +1, chaos +1", by_key)
        self.assertEqual(by_key["will +1, chaos +1"].picks, 1)


class TestDownstreamMetrics(unittest.TestCase):
    """goal% / relic% are keyed on the normalized pick too."""

    def test_goal_and_relic_rate_use_normalized_pick(self):
        rec = _record([_turn(
            offers=["will +1", "order +1", "boss_damage +1", "maintain"],
            picked="chaos +1",
            state_before=_sb())], success=True, total_points=17)
        by_key = _by_key([rec])
        self.assertEqual(by_key["order +1"].picks, 1)
        self.assertEqual(by_key["order +1"].goal_success_rate_if_picked, 1.0)
        self.assertEqual(by_key["order +1"].relic_rate_if_picked, 1.0)


if __name__ == "__main__":
    unittest.main()
