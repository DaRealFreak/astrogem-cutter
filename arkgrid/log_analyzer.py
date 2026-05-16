"""Parse JSONL logs from past auto runs and compute aggregate statistics.

Each ``logs/auto_YYYYMMDD_HHMMSS.jsonl`` file contains a stream of events
(``run_start``, ``gem_start``, ``gem_detected``, ``turn``, ``gem_end``,
``run_run_end``). ``load_runs`` walks a directory of such files and yields
one ``GemRecord`` per finished gem. ``filter_records`` applies CLI-style
filter args, ``aggregate`` computes summary stats, and ``option_stats``
computes per-offer appearance/pick rates.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from arkgrid.analyzer import GemAnalyzer


@dataclass
class GemRecord:
    """One finished gem from a logged auto run."""
    args: Dict[str, Any]
    log_path: str
    gem_index: int
    # gem_detected fields (may be empty for runs that died before detection)
    gem_type: str = ""
    rarity: str = ""
    first_effect: str = ""
    second_effect: str = ""
    total_steps: int = 0
    # gem_end fields
    success: bool = False
    total_points: int = 0
    side_coeff: int = 0
    reset_used: bool = False
    extra_ticket_used: bool = False
    final_state: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    # all turn events for this gem
    turns: List[Dict[str, Any]] = field(default_factory=list)


def _iter_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    """Yield JSON records from a JSONL file, skipping malformed trailing lines."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # Partial line from a Ctrl+C kill — stop here.
                    return
    except OSError:
        return


def load_runs(log_dir: str = "logs") -> List[GemRecord]:
    """Walk ``log_dir`` for ``*.jsonl`` files and return one record per gem."""
    records: List[GemRecord] = []
    paths = sorted(glob.glob(os.path.join(log_dir, "*.jsonl")))
    for path in paths:
        run_args: Dict[str, Any] = {}
        gem_index: int = 0
        gem: Optional[GemRecord] = None
        for ev in _iter_jsonl(path):
            kind = ev.get("event")
            if kind == "run_start":
                run_args = ev.get("args") or {}
            elif kind == "gem_start":
                gem_index = int(ev.get("gem_index", gem_index + 1))
                gem = GemRecord(args=run_args, log_path=path, gem_index=gem_index)
            elif kind == "gem_detected":
                if gem is None:
                    gem = GemRecord(args=run_args, log_path=path,
                                    gem_index=gem_index or 1)
                gem.gem_type = ev.get("gem_type", "") or ""
                gem.rarity = ev.get("rarity", "") or ""
                gem.first_effect = ev.get("first_effect", "") or ""
                gem.second_effect = ev.get("second_effect", "") or ""
                gem.total_steps = int(ev.get("total_steps", 0) or 0)
            elif kind == "turn":
                if gem is None:
                    gem = GemRecord(args=run_args, log_path=path,
                                    gem_index=gem_index or 1)
                gem.turns.append(ev)
            elif kind == "gem_end":
                if gem is None:
                    gem = GemRecord(args=run_args, log_path=path,
                                    gem_index=gem_index or 1)
                gem.success = bool(ev.get("success", False))
                gem.total_points = int(ev.get("total_points", 0) or 0)
                gem.side_coeff = int(ev.get("side_coeff", 0) or 0)
                gem.reset_used = bool(ev.get("reset_used", False))
                gem.extra_ticket_used = bool(ev.get("extra_ticket_used", False))
                gem.final_state = ev.get("final_state") or {}
                gem.reason = ev.get("reason", "") or ""
                records.append(gem)
                gem = None
            elif kind == "run_end":
                gem = None
        # Anything left in ``gem`` was a partial gem (Ctrl+C) — drop it.
    return records


# ----- filtering ----------------------------------------------------------------

# Filter args whose CLI default is None: a None value means "don't filter".
_NULLABLE_INT_FILTERS = (
    "min_will", "min_chaos", "exact_will", "exact_chaos",
    "min_first", "min_second",
)
# Filter args whose CLI default is 0 / False / empty: a "falsy" value means
# "don't filter on this". Comparisons are exact.
_INT_FILTERS = (
    "min_side_coeff", "early_finish_coeff", "reset_min_coeff",
    "reroll_min_coeff", "force_reroll_no_progress",
)
_FLOAT_FILTERS = (
    "side_threshold", "prob_reset_threshold",
    "relic_no_early_finish", "relic_reroll_threshold",
)


def _filter_value(args: argparse.Namespace, name: str, default=None):
    return getattr(args, name, default)


def filter_records(
    records: Iterable[GemRecord],
    args: argparse.Namespace,
) -> List[GemRecord]:
    """Filter ``records`` to those matching the user's filter args.

    Filter semantics: a CLI flag matches when the recorded run's ``args[name]``
    equals the filter value. Filters left at their "unset" default
    (``None`` / ``0`` / ``False`` / empty list) are not applied.
    """
    out: List[GemRecord] = []
    for rec in records:
        if not _matches(rec, args):
            continue
        out.append(rec)
    return out


def _matches(rec: GemRecord, args: argparse.Namespace) -> bool:
    a = rec.args

    # Rarity is detected per-gem (not stored in run args), so filter on the
    # detected value.
    rarity = _filter_value(args, "rarity")
    if rarity:  # list of rarities or single str
        wanted = rarity if isinstance(rarity, list) else [rarity]
        if rec.rarity and rec.rarity not in wanted:
            return False

    # Gem-type / effect filters resolve against detected fields.
    gem_type = _filter_value(args, "gem_type")
    if gem_type and rec.gem_type and rec.gem_type != gem_type:
        return False
    first_eff = _filter_value(args, "first_effect")
    if first_eff and rec.first_effect and rec.first_effect != first_eff:
        return False
    second_eff = _filter_value(args, "second_effect")
    if second_eff and rec.second_effect and rec.second_effect != second_eff:
        return False

    # Optimize is the only common arg always present in run_start.args
    optimize = _filter_value(args, "optimize")
    if optimize and a.get("optimize") and a.get("optimize") != optimize:
        return False

    for name in _NULLABLE_INT_FILTERS:
        v = _filter_value(args, name)
        if v is None:
            continue
        if a.get(name) != v:
            return False

    for name in _INT_FILTERS:
        v = _filter_value(args, name, 0)
        if not v:
            continue
        if int(a.get(name) or 0) != int(v):
            return False

    for name in _FLOAT_FILTERS:
        v = _filter_value(args, name, 0.0)
        if not v:
            continue
        if float(a.get(name) or 0.0) != float(v):
            return False

    bis_only = _filter_value(args, "bis_only", False)
    if bis_only:
        if not bool(a.get("bis_only")):
            return False

    effect_aware = _filter_value(args, "effect_aware_dp", None)
    if effect_aware is not None:
        if bool(a.get("effect_aware_dp")) != bool(effect_aware):
            return False

    extra_ticket = _filter_value(args, "extra_ticket", None)
    if extra_ticket is not None:
        if bool(a.get("extra_ticket")) != bool(extra_ticket):
            return False

    reset_ticket = _filter_value(args, "reset_ticket", None)
    if reset_ticket is not None:
        # reset_ticket can be True/False/None or a rarity string; require
        # equality.
        if a.get("reset_ticket") != reset_ticket:
            return False

    return True


# ----- aggregation --------------------------------------------------------------

def aggregate(records: List[GemRecord]) -> Dict[str, float]:
    """Compute aggregate stats matching :func:`pprint_result`'s output."""
    n = len(records)
    if n == 0:
        return {"n": 0}

    wins = sum(1 for r in records if r.success)
    p_success = wins / n
    lo, hi = GemAnalyzer.wilson_ci(p_success, n)

    return {
        "n": n,
        "p_success": p_success,
        "p_success_ci_lo": lo,
        "p_success_ci_hi": hi,
        "avg_total_points": sum(r.total_points for r in records) / n,
        "avg_side_coeff": sum(r.side_coeff for r in records) / n,
        "p_relic_plus": sum(1 for r in records if r.total_points >= 16) / n,
        "p_ancient": sum(1 for r in records if r.total_points >= 19) / n,
        "reset_rate": sum(1 for r in records if r.reset_used) / n,
        "extra_ticket_rate": sum(1 for r in records if r.extra_ticket_used) / n,
    }


# ----- option statistics --------------------------------------------------------

@dataclass
class OptionStat:
    key: str
    appearances: int   # appearances on process turns (decision moments)
    picks: int
    pick_rate: float                  # picks / appearances
    goal_success_rate_if_picked: float  # P(gem succeeded | this option was picked), per-pick weighted
    relic_rate_if_picked: float        # P(gem >=16 pts | this option was picked), per-pick weighted


def option_stats(records: Iterable[GemRecord]) -> Tuple[int, List[OptionStat]]:
    """Return (process_turns, stats list sorted by appearances desc).

    appearances = number of process-turn records where the option was offered.
    Reroll/reset/finish records discard all 4 offers together, so counting
    them inflates the pick_rate denominator without representing a real
    accept/reject decision.
    pick_rate = picks / appearances.
    goal_success_rate_if_picked = picks-in-successful-gems / picks (per-pick).
    relic_rate_if_picked = picks-in-relic-plus-gems / picks (per-pick).
    """
    process_turns = 0
    appearances: Dict[str, int] = {}
    picks: Dict[str, int] = {}
    picks_in_success: Dict[str, int] = {}
    picks_in_relic: Dict[str, int] = {}

    for rec in records:
        rec_success = bool(rec.success)
        rec_relic = int(rec.total_points) >= 16
        for turn in rec.turns:
            action = turn.get("action") or ""
            is_process = action in ("process", "click")
            if not is_process:
                continue
            process_turns += 1
            seen: set = set()
            for opt in (turn.get("offers") or []):
                seen.add(str(opt))
            for opt in seen:
                appearances[opt] = appearances.get(opt, 0) + 1
            picked = turn.get("picked")
            if picked:
                picks[picked] = picks.get(picked, 0) + 1
                if rec_success:
                    picks_in_success[picked] = picks_in_success.get(picked, 0) + 1
                if rec_relic:
                    picks_in_relic[picked] = picks_in_relic.get(picked, 0) + 1

    stats: List[OptionStat] = []
    for key, app in appearances.items():
        pk = picks.get(key, 0)
        pk_rate = (pk / app) if app else 0.0
        gs = (picks_in_success.get(key, 0) / pk) if pk else 0.0
        rs = (picks_in_relic.get(key, 0) / pk) if pk else 0.0
        stats.append(OptionStat(
            key=key, appearances=app, picks=pk, pick_rate=pk_rate,
            goal_success_rate_if_picked=gs, relic_rate_if_picked=rs))
    stats.sort(key=lambda s: (-s.appearances, -s.picks, s.key))
    return process_turns, stats


# ----- pretty printing ----------------------------------------------------------

def print_summary(args: argparse.Namespace, records: List[GemRecord]) -> None:
    print(f"Matched {len(records)} gems from {args.log_dir}")
    if not records:
        return
    summary = aggregate(records)
    print("")
    print(
        f"  Success rate: {summary['p_success'] * 100:.2f}% "
        f"(CI: {summary['p_success_ci_lo'] * 100:.2f}% - "
        f"{summary['p_success_ci_hi'] * 100:.2f}%)")
    print(f"  Average total points: {summary['avg_total_points']:.3f}")
    print(f"  Average side coefficient: {summary['avg_side_coeff']:.0f}")
    print(f"  Relic+ rate (>=16): {summary['p_relic_plus'] * 100:.2f}%")
    print(f"  Ancient rate (>=19): {summary['p_ancient'] * 100:.2f}%")
    print(f"  Reset usage rate: {summary['reset_rate'] * 100:.2f}%")
    print(f"  Extra ticket usage rate: {summary['extra_ticket_rate'] * 100:.2f}%")
    print("")

    process_turns, stats = option_stats(records)
    if process_turns == 0:
        return
    top_n = getattr(args, "top_options", 20)
    if top_n <= 0:
        top_n = len(stats)
    print(f"Options (across {process_turns} process turns):")
    print(f"  {'option':<24}  {'appear':>6}  {'picked':>6}  "
          f"{'pick %':>7}  {'goal % if picked':>16}  {'relic+ % if picked':>18}")
    for s in stats[:top_n]:
        if s.picks > 0:
            goal_str = f"{s.goal_success_rate_if_picked * 100:6.2f}%"
            relic_str = f"{s.relic_rate_if_picked * 100:6.2f}%"
        else:
            goal_str = "-"
            relic_str = "-"
        print(f"  {s.key:<24}  {s.appearances:>6}  {s.picks:>6}  "
              f"{s.pick_rate * 100:6.2f}%  {goal_str:>16}  {relic_str:>18}")
