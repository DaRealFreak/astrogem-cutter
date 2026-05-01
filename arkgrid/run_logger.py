"""Per-run logger for the auto/sim commands.

Owns two output files per run:

  - ``logs/auto_YYYYMMDD_HHMMSS.log``  human-readable transcript (tees stdout)
  - ``logs/auto_YYYYMMDD_HHMMSS.jsonl`` one JSON record per event for analysis

JSONL is line-oriented and flushed after every write so a Ctrl+C kill leaves
the partial run readable. The path is announced on stdout immediately at
construction so the user knows where to look even if the run is killed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from arkgrid.models import AstroGem, GemState, LastTurnGoal


def _to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if is_dataclass(obj):
        return _to_jsonable(asdict(obj))
    if isinstance(obj, argparse.Namespace):
        return _to_jsonable(vars(obj))
    return str(obj)


def _state_dict(state: GemState) -> Dict[str, Any]:
    return {
        "will": state.will,
        "chaos": state.chaos,
        "first": state.first,
        "second": state.second,
        "first_effect": state.first_effect,
        "second_effect": state.second_effect,
        "rerolls": state.rerolls,
        "total": state.total_points(),
    }


class _Tee:
    """Mirror writes to the original stdout and a file handle."""

    def __init__(self, original, fh) -> None:
        self._original = original
        self._fh = fh

    def write(self, text: str) -> int:
        self._original.write(text)
        self._fh.write(text)
        self._fh.flush()
        return len(text)

    def flush(self) -> None:
        self._original.flush()
        self._fh.flush()


class RunLogger:
    """Owns the per-run log files and emits structured JSONL events."""

    def __init__(self, log_dir: str = "logs") -> None:
        os.makedirs(log_dir, exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"auto_{self.timestamp}.log")
        self.jsonl_path = os.path.join(log_dir, f"auto_{self.timestamp}.jsonl")

        self._log_file = open(self.log_path, "w", encoding="utf-8")
        self._jsonl_file = open(self.jsonl_path, "w", encoding="utf-8")
        self._original_stdout = sys.stdout
        sys.stdout = _Tee(self._original_stdout, self._log_file)

        # Announce immediately — Ctrl+C before run_end still tells the user
        # where the partial log lives.
        print(f"Logging to: {self.log_path}")
        print(f"           {self.jsonl_path}")

    # --- low-level emitters --------------------------------------------------

    def _emit(self, event: str, **fields: Any) -> None:
        record: Dict[str, Any] = {"event": event, "ts": self.timestamp}
        record.update(_to_jsonable(fields))
        self._jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._jsonl_file.flush()

    def info(self, msg: str) -> None:
        """Print a human-only [info] line to the .log (no JSONL record)."""
        print(f"  [info] {msg}")

    # --- structured events ---------------------------------------------------

    def log_run_start(
        self,
        args: Optional[argparse.Namespace],
        goal: LastTurnGoal,
        astro_gem: Optional[AstroGem],
    ) -> None:
        args_dict = vars(args) if args is not None else {}
        self._emit(
            "run_start",
            args=args_dict,
            goal=asdict(goal),
            astro_gem=asdict(astro_gem) if astro_gem else None,
        )

        # Human-readable settings dump — every flag the user passed.
        print(f"[LOG] Run started at {self.timestamp}")
        goal_parts = []
        for k, v in asdict(goal).items():
            if v is not None:
                goal_parts.append(f"{k}={v}")
        print(f"[LOG] Goal: {', '.join(goal_parts) if goal_parts else '(none)'}")

        if astro_gem is not None:
            print(f"[LOG] Gem: {astro_gem.gem_type} "
                  f"[{astro_gem.first_effect} + {astro_gem.second_effect}] "
                  f"optimize={astro_gem.optimize}")
        else:
            print(f"[LOG] Gem: random")

        if args is not None:
            print(f"[LOG] Settings:")
            for k in sorted(args_dict.keys()):
                v = args_dict[k]
                print(f"         {k} = {v}")
        print()

    def log_gem_start(self, gem_index: int) -> None:
        self._emit("gem_start", gem_index=gem_index)

    def log_gem_detected(
        self,
        gem_type: str,
        rarity: str,
        first_effect: str,
        second_effect: str,
        total_steps: int,
    ) -> None:
        self._emit(
            "gem_detected",
            gem_type=gem_type,
            rarity=rarity,
            first_effect=first_effect,
            second_effect=second_effect,
            total_steps=total_steps,
        )

    def log_turn(
        self,
        *,
        turn: int,
        turns_left: int,
        state_before: GemState,
        offers: List[str],
        picked: Optional[str],
        action: str,
        action_reason: str,
        p_goal: Optional[float],
        p_relic: Optional[float],
        rerolls: int,
        state_after: Optional[GemState] = None,
    ) -> None:
        """Emit a turn record. Called once per action click.

        A single logical turn may span multiple records (one reroll record
        per reroll action, then one process record). ``picked`` is set only
        for process actions; ``state_after`` is set only when the resulting
        state was observed.
        """
        self._emit(
            "turn",
            turn=turn,
            turns_left=turns_left,
            state_before=_state_dict(state_before),
            state_after=_state_dict(state_after) if state_after else None,
            offers=offers,
            picked=picked,
            action=action,
            action_reason=action_reason,
            p_goal=p_goal,
            p_relic=p_relic,
            rerolls=rerolls,
        )

    def log_gem_end(
        self,
        *,
        success: bool,
        total_points: int,
        side_coeff: int,
        reset_used: bool,
        extra_ticket_used: bool,
        final_state: GemState,
        reason: str,
    ) -> None:
        self._emit(
            "gem_end",
            success=success,
            total_points=total_points,
            side_coeff=side_coeff,
            reset_used=reset_used,
            extra_ticket_used=extra_ticket_used,
            final_state=_state_dict(final_state),
            reason=reason,
        )

    def log_run_end(self) -> None:
        self._emit("run_end")

    def close(self) -> None:
        """Restore stdout and close both files. Idempotent."""
        if self._log_file is None:
            return
        try:
            sys.stdout = self._original_stdout
        except Exception:
            pass
        try:
            self._log_file.close()
        finally:
            self._log_file = None  # type: ignore[assignment]
        try:
            self._jsonl_file.close()
        finally:
            self._jsonl_file = None  # type: ignore[assignment]
