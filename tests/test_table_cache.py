"""Tests for the on-disk DP table cache (arkgrid.table_cache).

Usage:
    python -m unittest tests.test_table_cache -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from arkgrid import table_cache
from arkgrid.models import GemState, LastTurnGoal
from arkgrid.pool import OptionPool


class TestCachedTable(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(
            os.environ, {"ASTROGEM_CACHE_DIR": self._tmp.name}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_second_call_loads_from_disk_without_building(self):
        calls = []

        def build():
            calls.append(1)
            return {"payload": 42}

        a = table_cache.cached_table("k1", build)
        b = table_cache.cached_table("k1", build)
        self.assertEqual(a, {"payload": 42})
        self.assertEqual(b, {"payload": 42})
        self.assertEqual(len(calls), 1)

    def test_different_keys_build_separately(self):
        calls = []
        table_cache.cached_table("k1", lambda: calls.append(1) or 1)
        table_cache.cached_table("k2", lambda: calls.append(1) or 2)
        self.assertEqual(len(calls), 2)

    def test_corrupt_file_rebuilds(self):
        table_cache.cached_table("k1", lambda: {"v": 1})
        # Corrupt every cache file, then expect a clean rebuild.
        for root, _dirs, files in os.walk(self._tmp.name):
            for name in files:
                with open(os.path.join(root, name), "wb") as f:
                    f.write(b"not a pickle")
        got = table_cache.cached_table("k1", lambda: {"v": 2})
        self.assertEqual(got, {"v": 2})

    def test_disabled_by_env(self):
        calls = []
        with mock.patch.dict(os.environ, {"ASTROGEM_NO_DISK_CACHE": "1"}):
            table_cache.cached_table("k1", lambda: calls.append(1) or 1)
            table_cache.cached_table("k1", lambda: calls.append(1) or 1)
        self.assertEqual(len(calls), 2)

    def test_goal_table_roundtrip_lookups_identical(self):
        pool = OptionPool()
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        t1 = table_cache.goal_table(goal, 5, pool, early_finish=True)
        t2 = table_cache.goal_table(goal, 5, pool, early_finish=True)
        st = GemState(will=2, chaos=2, first=1, second=1,
                      first_effect="attack_power", second_effect="boss_damage")
        self.assertEqual(t1.lookup(st, 3), t2.lookup(st, 3))
        self.assertGreater(t2.lookup(st, 3), 0.0)

    def test_goal_table_distinguishes_goals_and_opts(self):
        pool = OptionPool()
        t1 = table_cache.goal_table(
            LastTurnGoal(min_will=3, min_chaos=3), 5, pool, early_finish=True)
        t2 = table_cache.goal_table(
            LastTurnGoal(min_will=4, min_chaos=3), 5, pool, early_finish=True)
        t3 = table_cache.goal_table(
            LastTurnGoal(min_will=3, min_chaos=3), 5, pool, early_finish=True,
            max_rerolls=1)
        st = GemState(will=2, chaos=2, first=1, second=1,
                      first_effect="attack_power", second_effect="boss_damage")
        self.assertNotEqual(t1.lookup(st, 3), t2.lookup(st, 3))
        self.assertNotEqual(t1.lookup(st, 3, rerolls=1),
                            t3.lookup(st, 3, rerolls=1))

    def test_side_value_table_roundtrip_lookups_identical(self):
        pool = OptionPool()
        goal = LastTurnGoal(min_will=3, min_chaos=3)
        t1 = table_cache.side_value_table(
            goal, 5, pool, gem_type="chaos_distortion", optimize="dps")
        t2 = table_cache.side_value_table(
            goal, 5, pool, gem_type="chaos_distortion", optimize="dps")
        st = GemState(will=3, chaos=3, first=2, second=1,
                      first_effect="attack_power", second_effect="ally_damage")
        self.assertEqual(t1.lookup(st, 3), t2.lookup(st, 3))
        self.assertEqual(t1.relic_coeff, t2.relic_coeff)

    def test_fingerprint_is_stable_and_hexish(self):
        fp1 = table_cache.model_fingerprint()
        fp2 = table_cache.model_fingerprint()
        self.assertEqual(fp1, fp2)
        self.assertGreaterEqual(len(fp1), 8)


if __name__ == "__main__":
    unittest.main()
