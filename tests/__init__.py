"""Run-time defaults for the test suite.

The suite cycles through ~190 distinct DP tables. The table cache keeps 128
by default (`arkgrid.table_cache`), so on that default the suite rebuilds
tables on every run: ~20 minutes instead of ~7 once warm. The suite therefore
raises the cap for its own process — `setdefault`, so an explicit
`ASTROGEM_CACHE_MAX_FILES` still wins. Costs ~750MB of disk at ~4MB a table.

`python -m unittest tests.test_x` imports this package and gets the default
directly. `python -m unittest discover -s tests` imports the test files as
top-level modules and never imports the package on its own;
`tests/test_suite_env.py` imports it so discovery applies the default too.
"""
import os

TABLE_CACHE_MAX_FILES = 400

os.environ.setdefault("ASTROGEM_CACHE_MAX_FILES", str(TABLE_CACHE_MAX_FILES))
