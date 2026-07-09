"""On-disk cache for pre-built DP tables (stdlib only).

CPython builds the effect-aware reroll tables in seconds (no JIT — the
interpreter loop dominates, so the flat-list storage that made the web
engine ~7x faster barely helps here). A pickle round-trip is ~20x faster
than a build, so `sim`/`auto`/`stats` startup drops from ~10-20s of table
builds to ~1s once warm.

Invalidation is automatic: cache entries live under a directory named by
`model_fingerprint()` — a hash of the model source files — so ANY change
to the probability model, pool, constants, or state dataclasses starts a
fresh cache and stale tables can never be served. Older fingerprint
directories are removed on first use, and the newest-N files are kept per
fingerprint (each pickle is ~2-7MB on top of the flat-list storage).

Environment knobs:
    ASTROGEM_CACHE_DIR      override the cache root (used by tests)
    ASTROGEM_NO_DISK_CACHE  set to any non-empty value to disable entirely
"""
from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path
from typing import Callable, Optional, TypeVar

from arkgrid.models import LastTurnGoal
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable, SideValueTable

T = TypeVar("T")

# Any change to these files changes DP values or pickled layouts.
_MODEL_SOURCES = ("probability.py", "pool.py", "constants.py", "models.py")

# One full `auto --all` sweep across the 6 gem types produces ~26 pickles
# (goal + reset + side-value + grade-value per type, plus shared tables) at
# up to ~9MB each; 32 caused silent eviction thrash the moment a second
# goal/config entered the mix. 128 (~1GB worst case) fits several configs.
_MAX_FILES_PER_FINGERPRINT = 128

_fingerprint: Optional[str] = None
_pruned_stale = False


def model_fingerprint() -> str:
    """Hash of the model source files — the cache generation id."""
    global _fingerprint
    if _fingerprint is None:
        h = hashlib.sha256()
        pkg = Path(__file__).resolve().parent
        for name in _MODEL_SOURCES:
            h.update((pkg / name).read_bytes())
        _fingerprint = h.hexdigest()[:16]
    return _fingerprint


def _cache_root() -> Path:
    override = os.environ.get("ASTROGEM_CACHE_DIR")
    if override:
        return Path(override) / "dp-cache"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        return base / "AstrogemCutter" / "dp-cache"
    base = Path(os.environ.get("XDG_CACHE_HOME",
                               str(Path.home() / ".cache")))
    return base / "astrogem-cutter" / "dp-cache"


def cache_dir() -> Path:
    """Per-fingerprint cache directory (not created until first write)."""
    return _cache_root() / model_fingerprint()


def _prune_stale_fingerprints() -> None:
    """Drop directories from older model versions (best-effort)."""
    global _pruned_stale
    if _pruned_stale:
        return
    _pruned_stale = True
    root = _cache_root()
    current = model_fingerprint()
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name != current:
                for f in child.iterdir():
                    try:
                        f.unlink()
                    except OSError:
                        pass
                try:
                    child.rmdir()
                except OSError:
                    pass
    except OSError:
        pass


def _prune_excess_files(d: Path) -> None:
    """Keep only the newest N pickles (best-effort)."""
    try:
        files = sorted(d.glob("*.pkl"), key=lambda p: p.stat().st_mtime)
        for f in files[:-_MAX_FILES_PER_FINGERPRINT]:
            try:
                f.unlink()
            except OSError:
                pass
    except OSError:
        pass


def cached_table(key: str, build: Callable[[], T]) -> T:
    """Return the cached object for `key`, building and persisting on miss.

    Failures are never fatal: a corrupt/unreadable entry rebuilds, and a
    failed write just skips caching.
    """
    if os.environ.get("ASTROGEM_NO_DISK_CACHE"):
        return build()
    d = cache_dir()
    fname = d / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + ".pkl")
    if fname.exists():
        try:
            with open(fname, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass  # corrupt/incompatible -> rebuild below
    obj = build()
    try:
        _prune_stale_fingerprints()
        d.mkdir(parents=True, exist_ok=True)
        tmp = fname.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, fname)
        _prune_excess_files(d)
    except Exception:
        pass  # cache write failure is non-fatal
    return obj


def _key(kind: str, goal: LastTurnGoal, max_turns: int, opts: dict) -> str:
    # Dataclass reprs are deterministic and include every field; the pool is
    # excluded because pool.py is part of the fingerprint and OptionPool is
    # parameterless.
    parts = [kind, repr(goal), str(max_turns)]
    parts.extend(f"{k}={opts[k]!r}" for k in sorted(opts))
    return "|".join(parts)


def goal_table(goal: LastTurnGoal, max_turns: int, pool: OptionPool,
               **opts) -> GoalProbabilityTable:
    """Disk-cached drop-in for `GoalProbabilityTable(goal, turns, pool, **opts)`."""
    return cached_table(
        _key("goal", goal, max_turns, opts),
        lambda: GoalProbabilityTable(goal, max_turns, pool, **opts))


def side_value_table(goal: LastTurnGoal, max_turns: int, pool: OptionPool,
                     **opts) -> SideValueTable:
    """Disk-cached drop-in for `SideValueTable(goal, turns, pool, **opts)`."""
    return cached_table(
        _key("side", goal, max_turns, opts),
        lambda: SideValueTable(goal, max_turns, pool, **opts))
