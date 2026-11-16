"""The suite's own run-time defaults (they live in `tests/__init__.py`).

`python -m unittest discover -s tests` imports the test files as top-level
modules, so the package's `__init__` would never run. Every test file is
imported while the suite is collected, so importing the package from this one
applies the defaults before any test builds a table.
"""
from __future__ import annotations

import os
import unittest

import tests
from arkgrid import table_cache


class TestTableCacheCap(unittest.TestCase):
    def test_the_suite_runs_with_a_raised_cap(self) -> None:
        # The suite cycles through ~190 DP tables; on the default cap of 128
        # it rebuilds them on every run (~20 min instead of ~7).
        self.assertTrue("ASTROGEM_CACHE_MAX_FILES" in os.environ,
                        "tests/__init__.py did not set the cache cap")
        self.assertGreaterEqual(tests.TABLE_CACHE_MAX_FILES, 300)

    def test_the_default_is_what_the_cache_uses(self) -> None:
        if os.environ.get("ASTROGEM_CACHE_MAX_FILES") != str(
                tests.TABLE_CACHE_MAX_FILES):
            self.skipTest("ASTROGEM_CACHE_MAX_FILES was set by the developer")
        self.assertEqual(table_cache._max_files(), tests.TABLE_CACHE_MAX_FILES)


if __name__ == "__main__":
    unittest.main()
