from __future__ import annotations

import argparse
from typing import List, Optional, Tuple

from itertools import combinations

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS,
)
from arkgrid.models import LastTurnGoal, AstroGem, GemState
from arkgrid.pool import OptionPool
from arkgrid.probability import GoalProbabilityTable
from arkgrid.simulator import GemSimulator
from arkgrid.analyzer import GemAnalyzer, pprint_result

ALL_EFFECTS = sorted(DPS_EFFECTS | SUPPORT_EFFECTS)

_RARITY_LEVEL = {"common": 1, "rare": 2, "epic": 3}


def _parse_reset_ticket(value: str) -> str:
    v = value.lower()
    if v in _RARITY_LEVEL:
        return v
    raise argparse.ArgumentTypeError(
        f"--reset-ticket value must be one of common/rare/epic (got {value!r})"
    )


def _reset_enabled_for_rarity(value, rarity: str) -> bool:
    """Resolve a --reset-ticket value (True/False/None/rarity string) against
    a gem rarity. Rarity strings act as a minimum threshold — pass "rare" to
    enable reset on rare and epic gems; pass "epic" to enable it only on
    epic gems.
    """
    if value is True:
        return True
    if not value:
        return False
    return _RARITY_LEVEL.get(rarity, 0) >= _RARITY_LEVEL[value]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lost Ark Astrogem cutting simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # ---- shared arguments ----
    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--rarity", choices=["common", "rare", "epic"], default=None,
                        nargs="+",
                        help="Gem rarity (one or more, default: run all three)")
        p.add_argument("--optimize", choices=["dps", "support"], default="dps",
                        help="Side-node optimisation target (default: dps)")
        p.add_argument("--min-will", type=int, default=None, metavar="N",
                        help="Minimum willpower goal")
        p.add_argument("--min-chaos", type=int, default=None, metavar="N",
                        help="Minimum chaos goal")
        p.add_argument("--exact-will", type=int, default=None, metavar="N")
        p.add_argument("--exact-chaos", type=int, default=None, metavar="N")
        p.add_argument("--extra-ticket", action="store_true", default=True,
                        help="Use extra reroll ticket (default: yes)")
        p.add_argument("--no-extra-ticket", action="store_false", dest="extra_ticket")
        p.add_argument("--reset-ticket", nargs="?", const=True, default=None,
                        type=_parse_reset_ticket, metavar="RARITY",
                        help="Use reset ticket. Bare flag enables it for every "
                             "gem. Pass a rarity (common/rare/epic) to use "
                             "the ticket only on gems of that rarity or "
                             "higher (e.g. 'epic' = epic-only, 'rare' = rare "
                             "and epic). Default: disabled for sim/auto; "
                             "stats runs both with/without.")
        p.add_argument("--no-reset-ticket", action="store_false", dest="reset_ticket")
        p.add_argument("--side-threshold", type=float, default=0.5, metavar="F",
                        help="Goal-feasibility fraction above which side nodes are valued (default: 0.5)")
        p.add_argument("--prob-reset-threshold", type=float, default=0.0, metavar="F",
                        help="Reset proactively when goal probability drops below this "
                             "(0.0 = disabled, try 0.05-0.15)")
        p.add_argument("--bis-only", action="store_true", default=False,
                        help="Only value side nodes when effects are best-in-slot")
        p.add_argument("--reset-min-coeff", type=int, default=0, metavar="N",
                        help="Only use reset ticket when the sum of starting target-effect "
                             "coefficients meets this threshold (e.g. atk_power+additional_damage = "
                             "400+700 = 1100 passes, 1051 skips brand_power alone for support). "
                             "0 = always use. Default: 0")
        p.add_argument("--reroll-min-coeff", type=int, default=0, metavar="N",
                        help="Only use extra reroll ticket when the sum of starting target-effect "
                             "coefficients meets this threshold. Same logic as --reset-min-coeff "
                             "but for the extra reroll ticket. 0 = always use. Default: 0")
        p.add_argument("--min-first", type=int, default=None, metavar="N",
                        help="Minimum level for first side node (1-5)")
        p.add_argument("--min-second", type=int, default=None, metavar="N",
                        help="Minimum level for second side node (1-5)")
        p.add_argument("--min-side-coeff", type=int, default=0, metavar="N",
                        help="Minimum coefficient-weighted level total from target side nodes. "
                             "Value = sum(level * coefficient). E.g. boss_damage(1000)*5 = 5000. "
                             "Requires --first-effect and --second-effect. Default: 0")
        p.add_argument("--endgame-risk", type=float, default=0.0, metavar="F",
                        help="Unattended risk margin for the side-value finish. "
                             "Once rerolls are exhausted, finish a goal-met gem "
                             "only when stopping beats processing by >= F "
                             "coefficient. 0 = EV-optimal (default); a large F "
                             "keeps processing to the last turn. No effect when "
                             "--confirm-min-coeff is set.")
        p.add_argument("--relic-coeff", type=int, default=0, metavar="N",
                        help="Coefficient-equivalent worth of holding the relic+ "
                             "grade (>=16 total points), added to gem_value in "
                             "the side-value DP. 0 = relic+ has no pull "
                             "(default).")
        p.add_argument("--ancient-coeff", type=int, default=0, metavar="N",
                        help="Coefficient-equivalent worth of holding the ancient "
                             "grade (>=19 total points). Expected >= --relic-coeff. "
                             "0 = ancient has no pull (default).")
        p.add_argument("--relic-reroll-threshold", type=float, default=0.0, metavar="F",
                        help="Use extra reroll ticket even when --reroll-min-coeff would "
                             "disable it, if P(relic+ >=16 total) from the current state "
                             "exceeds this threshold. 0.0 = disabled. Try 0.1-0.3. Default: 0.0")
        p.add_argument("--force-reroll-no-progress", type=int, default=0, metavar="N",
                        help="Heuristic override: when the gem's starting target-effect "
                             "coefficient is >= N, force a reroll (if rerolls available) "
                             "on any turn where no offer progresses the goal — i.e. none "
                             "increases will/chaos/needed side levels or side coefficient. "
                             "On high-coeff gems this boosts main-goal success at some "
                             "cost to relic+ / total-points upside. "
                             "0 = disabled. Try 1050+ on support, 1400+ on DPS. Default: 0.")
        p.add_argument("--confirm-min-coeff", type=int, default=None,
                        metavar="N",
                        help="Side-coefficient floor for the confirmation gate: "
                             "only prompt about gems whose current side "
                             "coefficient >= N. Setting this alone activates "
                             "the gate. Default when unset: 0 (every gem).")
        grp = p.add_argument_group("gem configuration (omit for random gem each run)")
        grp.add_argument("--gem-type", choices=list(GEM_TYPES.keys()), default=None,
                         help="Gem type (auto-resolved from effects if unambiguous)")
        grp.add_argument("--first-effect", choices=ALL_EFFECTS, default=None,
                         help="First effect on the gem (with --second-effect, auto-resolves gem type)")
        grp.add_argument("--second-effect", choices=ALL_EFFECTS, default=None,
                         help="Second effect on the gem (with --first-effect, auto-resolves gem type)")

    # ---- stats ----
    p_stats = sub.add_parser("stats", help="Run Monte Carlo probability estimation")
    add_common(p_stats)
    p_stats.add_argument("--trials", type=int, default=200_000,
                         help="Number of simulation trials (default: 200000)")
    p_stats.add_argument("--seed", type=int, default=12345,
                         help="RNG seed for reproducibility (default: 12345)")

    # ---- sim ----
    p_sim = sub.add_parser("sim", help="Run a single simulation with turn-by-turn log")
    add_common(p_sim)
    p_sim.add_argument("--seed", type=int, default=42,
                       help="RNG seed (default: 42)")

    # ---- effects ----
    p_eff = sub.add_parser("effects", help="Show effect change outcomes for gem types")
    p_eff.add_argument("--optimize", choices=["dps", "support"], default="dps",
                       help="Optimisation target (default: dps)")
    p_eff.add_argument("--gem-type", choices=list(GEM_TYPES.keys()), default=None,
                       help="Gem type (omit to show all)")
    p_eff.add_argument("--side-threshold", type=float, default=0.5, metavar="F",
                       help="Base side threshold for effective threshold display (default: 0.5)")

    # ---- live (vision + probability) ----
    p_live = sub.add_parser("live",
                            help="Detect game state from screenshot and show option probabilities")
    add_common(p_live)
    p_live.add_argument("--screenshot", type=str, required=True, metavar="FILE",
                        help="Path to screenshot image")
    p_live.add_argument("--trials", type=int, default=0,
                        help="Monte Carlo trials from current state (0 = DP only, default: 0)")
    p_live.add_argument("--seed", type=int, default=42,
                        help="RNG seed for Monte Carlo (default: 42)")

    # ---- read (vision) ----
    p_read = sub.add_parser("read", help="Read current game screen state via vision")
    p_read.add_argument("--screenshot", type=str, default=None, metavar="FILE",
                        help="Read from image file instead of live screen capture")
    p_read.add_argument("--debug", action="store_true", default=False,
                        help="Show debug visualization window")
    p_read.add_argument("--save-debug", type=str, default=None, metavar="FILE",
                        help="Save debug visualization to file")
    p_read.add_argument("--monitor", type=int, default=1,
                        help="Monitor index for live capture (default: 1 = primary)")

    # ---- auto (automation) ----
    p_auto = sub.add_parser("auto",
                            help="Automate gem cutting: detect, decide, click")
    add_common(p_auto)
    p_auto.add_argument("--monitor", type=int, default=1,
                        help="Monitor index for screen capture (default: 1 = primary)")
    p_auto.add_argument("--animation-delay", type=float, default=1.0, metavar="SECS",
                        help="Seconds to wait after each click for animation (default: 1.0)")
    p_auto.add_argument("--dry-run", action="store_true", default=False,
                        help="Analyze and print decisions without clicking")
    p_auto.add_argument("--all", action="store_true", default=False,
                        dest="all_gems",
                        help="Continuously cut gems: after finishing, confirm the "
                             "processed gem and select the next one from the "
                             "inventory. Stops when no new gem is detected.")

    # ---- report (analyze logged auto runs) ----
    p_report = sub.add_parser(
        "report",
        help="Aggregate stats from past auto-run JSONL logs")
    _add_report_filter_args(p_report)

    return parser


def _add_report_filter_args(p: argparse.ArgumentParser) -> None:
    """Filter args for the report command. All defaults are None / 0 / False
    so we can tell "user didn't filter" from "user wants this exact value".
    Mirrors :func:`add_common` for parity with the auto/stats commands.
    """
    p.add_argument("--log-dir", default="logs",
                   help="Directory containing *.jsonl logs (default: logs)")
    p.add_argument("--top-options", type=int, default=0,
                   help="Show top N options by appearance count "
                        "(default: 0 = all rows).")
    p.add_argument("--rarity", choices=["common", "rare", "epic"],
                   default=None, nargs="+",
                   help="Filter by detected gem rarity")
    p.add_argument("--optimize", choices=["dps", "support"], default=None,
                   help="Filter by --optimize value used in the run")
    p.add_argument("--min-will", type=int, default=None, metavar="N")
    p.add_argument("--min-chaos", type=int, default=None, metavar="N")
    p.add_argument("--exact-will", type=int, default=None, metavar="N")
    p.add_argument("--exact-chaos", type=int, default=None, metavar="N")
    p.add_argument("--min-first", type=int, default=None, metavar="N")
    p.add_argument("--min-second", type=int, default=None, metavar="N")
    p.add_argument("--min-side-coeff", type=int, default=0, metavar="N")
    p.add_argument("--endgame-risk", type=float, default=0.0, metavar="F")
    p.add_argument("--relic-coeff", type=int, default=0, metavar="N")
    p.add_argument("--ancient-coeff", type=int, default=0, metavar="N")
    p.add_argument("--reset-min-coeff", type=int, default=0, metavar="N")
    p.add_argument("--reroll-min-coeff", type=int, default=0, metavar="N")
    p.add_argument("--force-reroll-no-progress", type=int, default=0,
                   metavar="N")
    p.add_argument("--side-threshold", type=float, default=0.0, metavar="F")
    p.add_argument("--prob-reset-threshold", type=float, default=0.0,
                   metavar="F")
    p.add_argument("--relic-reroll-threshold", type=float, default=0.0,
                   metavar="F")
    p.add_argument("--bis-only", action="store_true", default=False)
    p.add_argument("--gem-type", choices=list(GEM_TYPES.keys()), default=None)
    p.add_argument("--first-effect", choices=ALL_EFFECTS, default=None)
    p.add_argument("--second-effect", choices=ALL_EFFECTS, default=None)
    p.add_argument("--reset-ticket", nargs="?", const=True, default=None,
                   type=_parse_reset_ticket, metavar="RARITY")
    p.add_argument("--extra-ticket", action="store_true", default=None)
    p.add_argument("--no-extra-ticket", action="store_false",
                   dest="extra_ticket")


def _resolve_args(args: argparse.Namespace) -> Tuple[
    LastTurnGoal, Optional[AstroGem], List[str], List[Optional[bool]]
]:
    goal = LastTurnGoal(
        min_will=args.min_will,
        min_chaos=args.min_chaos,
        exact_will=args.exact_will,
        exact_chaos=args.exact_chaos,
        min_first=getattr(args, "min_first", None),
        min_second=getattr(args, "min_second", None),
    )

    astro_gem: Optional[AstroGem] = None
    first = getattr(args, "first_effect", None)
    second = getattr(args, "second_effect", None)
    gem_type = getattr(args, "gem_type", None)

    if gem_type:
        pool = set(GEM_TYPES[gem_type])
        if not first or first not in pool:
            raise SystemExit(
                f"--first-effect must be one of {sorted(pool)} for {gem_type}"
            )
        if not second or second not in pool:
            raise SystemExit(
                f"--second-effect must be one of {sorted(pool)} for {gem_type}"
            )
        if first == second:
            raise SystemExit("--first-effect and --second-effect must differ")
        astro_gem = AstroGem(gem_type, first, second, args.optimize)
    elif first and second:
        if first == second:
            raise SystemExit("--first-effect and --second-effect must differ")
        # Auto-resolve gem type from effect pair
        matches = [name for name, pool in GEM_TYPES.items()
                   if first in pool and second in pool]
        if not matches:
            raise SystemExit(
                f"No gem type contains both {first} and {second}"
            )
        # Group by unique pool (order/chaos pairs share pools)
        seen_pools: dict = {}
        for name in matches:
            pool_key = tuple(sorted(GEM_TYPES[name]))
            if pool_key not in seen_pools:
                seen_pools[pool_key] = name
        if len(seen_pools) > 1:
            options = " or ".join(sorted(seen_pools.values()))
            raise SystemExit(
                f"{first} + {second} exists in multiple gem pools — "
                f"use --gem-type to disambiguate ({options})"
            )
        resolved_type = next(iter(seen_pools.values()))
        astro_gem = AstroGem(resolved_type, first, second, args.optimize)
    elif first or second:
        raise SystemExit("Both --first-effect and --second-effect are required")

    min_side_coeff = getattr(args, "min_side_coeff", 0)

    rarities = args.rarity if args.rarity else ["common", "rare", "epic"]

    if args.reset_ticket is None:
        reset_variants: List = [False, True]
    else:
        reset_variants = [args.reset_ticket]

    return goal, astro_gem, rarities, reset_variants


def _print_config(args: argparse.Namespace, goal: LastTurnGoal,
                  astro_gem: Optional[AstroGem]) -> None:
    parts: List[str] = []
    if goal.min_will is not None:
        parts.append(f"min_will={goal.min_will}")
    if goal.min_chaos is not None:
        parts.append(f"min_chaos={goal.min_chaos}")
    if goal.exact_will is not None:
        parts.append(f"exact_will={goal.exact_will}")
    if goal.exact_chaos is not None:
        parts.append(f"exact_chaos={goal.exact_chaos}")
    if goal.min_first is not None:
        parts.append(f"min_first={goal.min_first}")
    if goal.min_second is not None:
        parts.append(f"min_second={goal.min_second}")
    min_side_coeff = getattr(args, "min_side_coeff", 0)
    if min_side_coeff > 0:
        parts.append(f"min_side_coeff={min_side_coeff}")
    goal_str = ", ".join(parts) if parts else "(no goal constraints)"

    if astro_gem:
        gem_str = f"{astro_gem.gem_type} [{astro_gem.first_effect} + {astro_gem.second_effect}]"
    else:
        gem_str = "random"

    print(f"Goal:     {goal_str}")
    print(f"Gem:      {gem_str}")
    print(f"Optimize: {args.optimize}")
    print(f"Extra ticket: {'yes' if args.extra_ticket else 'no'}")
    print(f"Side threshold: {args.side_threshold}")
    print(f"Endgame risk:   {getattr(args, 'endgame_risk', 0.0):.0f} "
          f"(side-value finish margin)")
    print()


_SHARED_POOL = OptionPool()


def _enumerate_side_coeff_pairs(optimize: str):
    """Enumerate all unique (coeff_first, coeff_second) -> count for random gems.

    Iterates over all gem types × all ordered effect-pair assignments and
    maps each to its (side_coeff_first, side_coeff_second) values.
    Uses unordered grouping since first/second have symmetric pool weights,
    so DP((a,b)) == DP((b,a)) from state (1,1,1,1).
    Returns {(lo, hi): count}.
    """
    coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
    target_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS

    pairs: dict = {}
    for effects in GEM_TYPES.values():
        for i, first in enumerate(effects):
            for j, second in enumerate(effects):
                if i == j:
                    continue
                cf = coeff_map[first] if first in target_set else 0
                cs = coeff_map[second] if second in target_set else 0
                # Canonical unordered key (symmetric pool weights)
                key = (min(cf, cs), max(cf, cs))
                pairs[key] = pairs.get(key, 0) + 1
    return pairs


def _compute_dp_prob(
    goal: LastTurnGoal,
    rarity: str,
    astro_gem: Optional[AstroGem],
    optimize: str,
    bis_only: bool,
    min_side_coeff: int,
    early_finish: bool = False,
    max_rerolls: int = 0,
) -> float:
    """Compute analytical DP probability from initial state.

    Effect-aware and reroll-aware by default. Uses single-draw transition
    approximation (~20ms). When astro_gem is None and min_side_coeff > 0:
    averages over all possible random gem effect assignments.
    """
    pool = _SHARED_POOL
    turns = GemSimulator.RARITY_TURNS[rarity]

    side_coeff_first, side_coeff_second = 0, 0
    target_effects: frozenset = frozenset()

    if astro_gem:
        coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        target_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        if min_side_coeff > 0:
            if astro_gem.first_effect in target_set:
                side_coeff_first = coeff_map[astro_gem.first_effect]
            if astro_gem.second_effect in target_set:
                side_coeff_second = coeff_map[astro_gem.second_effect]
        if bis_only:
            target_effects = frozenset(
                set(GEM_TYPES[astro_gem.gem_type]) & target_set)

    if astro_gem and astro_gem.gem_type in GEM_TYPES:
        table = GoalProbabilityTable(
            goal, turns, pool,
            min_side_coeff=min_side_coeff,
            early_finish=early_finish,
            effect_aware=True,
            gem_type=astro_gem.gem_type,
            optimize=optimize,
            max_rerolls=max_rerolls,
        )
        initial = GemState(
            will=1, chaos=1, first=1, second=1,
            first_effect=astro_gem.first_effect,
            second_effect=astro_gem.second_effect,
        )
        return table.lookup(initial, turns, rerolls=max_rerolls)
    elif astro_gem is None:
        # Effect-aware over a random gem: average one table per gem type
        # across all valid (first, second) starts.
        total_p = 0.0
        n_configs = 0
        for gem_type, effs in GEM_TYPES.items():
            table = GoalProbabilityTable(
                goal, turns, pool,
                min_side_coeff=min_side_coeff,
                early_finish=early_finish,
                effect_aware=True,
                gem_type=gem_type,
                optimize=optimize,
                max_rerolls=max_rerolls,
            )
            for fi in range(len(effs)):
                for si in range(len(effs)):
                    if fi == si:
                        continue
                    initial = GemState(
                        will=1, chaos=1, first=1, second=1,
                        first_effect=effs[fi], second_effect=effs[si],
                    )
                    total_p += table.lookup(initial, turns, rerolls=max_rerolls)
                    n_configs += 1
        return total_p / n_configs if n_configs else 0.0
    elif bis_only and astro_gem:
        table = GoalProbabilityTable(
            goal, turns, pool,
            bis_only=True,
            target_effects=target_effects,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=min_side_coeff,
            early_finish=early_finish,
        )
        initial = GemState(
            will=1, chaos=1, first=1, second=1,
            first_effect=astro_gem.first_effect,
            second_effect=astro_gem.second_effect,
        )
        return table.lookup(initial, turns)
    elif bis_only:
        # No configured gem — average over all starting (ft, st) combos.
        # The BIS DP is gem-type-independent (only tracks target/non-target
        # binary state), so one table covers all gem types.
        table = GoalProbabilityTable(
            goal, turns, pool,
            bis_only=True,
            early_finish=early_finish,
        )
        return table.lookup_bis_averaged(turns)
    elif min_side_coeff > 0 and astro_gem is None:
        # No configured gem — average DP probability over all possible
        # random effect assignments (gem type × effect slot permutations).
        pairs = _enumerate_side_coeff_pairs(optimize)
        total_count = sum(pairs.values())
        prob_sum = 0.0
        initial = GemState(will=1, chaos=1, first=1, second=1)
        for (cf, cs), count in pairs.items():
            table = GoalProbabilityTable(
                goal, turns, pool,
                side_coeff_first=cf,
                side_coeff_second=cs,
                min_side_coeff=min_side_coeff,
                early_finish=early_finish,
            )
            prob_sum += table.lookup(initial, turns) * count
        return prob_sum / total_count
    else:
        table = GoalProbabilityTable(
            goal, turns, pool,
            side_coeff_first=side_coeff_first,
            side_coeff_second=side_coeff_second,
            min_side_coeff=min_side_coeff,
            early_finish=early_finish,
        )
        initial = GemState(will=1, chaos=1, first=1, second=1)
        return table.lookup(initial, turns)


def cmd_stats(args: argparse.Namespace) -> None:
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    _print_config(args, goal, astro_gem)

    for use_reset in reset_variants:
        if isinstance(use_reset, str):
            label = f"With reset ticket ({use_reset}+ only)"
        elif use_reset:
            label = "With reset ticket"
        else:
            label = "Without reset ticket"
        print(f"--- {label} ---")
        for rarity in rarities:
            resolved_reset = _reset_enabled_for_rarity(use_reset, rarity)
            base_rerolls = (GemSimulator.RARITY_REROLLS[rarity]
                            + (1 if args.extra_ticket else 0))
            dp_prob = _compute_dp_prob(
                goal, rarity, astro_gem, args.optimize,
                args.bis_only, args.min_side_coeff,
                early_finish=True,
                max_rerolls=base_rerolls,
            )
            dp_prob_no_reroll = _compute_dp_prob(
                goal, rarity, astro_gem, args.optimize,
                args.bis_only, args.min_side_coeff,
                early_finish=True,
                max_rerolls=0,
            )
            summary: dict = {"dp_prob": dp_prob, "dp_prob_no_reroll": dp_prob_no_reroll}

            # Relic+ DP probability (from initial state)
            relic_dp = _compute_dp_prob(
                LastTurnGoal(min_total=16), rarity, astro_gem, args.optimize,
                bis_only=False, min_side_coeff=0,
                early_finish=False,
                max_rerolls=base_rerolls,
            )
            summary["relic_dp_prob"] = relic_dp

            ancient_dp = _compute_dp_prob(
                LastTurnGoal(min_total=19), rarity, astro_gem, args.optimize,
                bis_only=False, min_side_coeff=0,
                early_finish=False,
                max_rerolls=base_rerolls,
            )
            summary["ancient_dp_prob"] = ancient_dp

            if args.trials > 0:
                sim = GemSimulator(
                    rarity=rarity,
                    use_extra_ticket=args.extra_ticket,
                    use_reset_ticket=resolved_reset,
                    goal=goal,
                    side_node_threshold=args.side_threshold,
                    astro_gem=astro_gem,
                    optimize=args.optimize,
                    prob_reset_threshold=args.prob_reset_threshold,
                    bis_only=args.bis_only,
                    reset_min_coeff=args.reset_min_coeff,
                    reroll_min_coeff=args.reroll_min_coeff,
                    min_side_coeff=args.min_side_coeff,
                    relic_reroll_threshold=args.relic_reroll_threshold,
                    force_reroll_no_progress=args.force_reroll_no_progress,
                    effect_aware=True,
                    confirm_min_coeff=args.confirm_min_coeff,
                    endgame_risk=args.endgame_risk,
                    relic_coeff=args.relic_coeff,
                    ancient_coeff=args.ancient_coeff,
                )
                mc = GemAnalyzer.estimate_summary(
                    trials=args.trials, simulator=sim, seed=args.seed,
                )
                summary.update(mc)

            pprint_result(f"  {rarity.capitalize()}", summary)


def cmd_sim(args: argparse.Namespace) -> None:
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    rarity = rarities[0]
    # [0] is load-bearing: when --reset-ticket is omitted reset_variants is
    # [False, True] so [0] selects the disabled default; stats iterates both.
    # Reverting to [-1] would silently enable the reset ticket by default.
    use_reset = _reset_enabled_for_rarity(reset_variants[0], rarity)
    _print_config(args, goal, astro_gem)

    sim = GemSimulator(
        rarity=rarity,
        use_extra_ticket=args.extra_ticket,
        use_reset_ticket=use_reset,
        goal=goal,
        side_node_threshold=args.side_threshold,
        astro_gem=astro_gem,
        optimize=args.optimize,
        prob_reset_threshold=args.prob_reset_threshold,
        bis_only=args.bis_only,
        reset_min_coeff=args.reset_min_coeff,
        reroll_min_coeff=args.reroll_min_coeff,
        min_side_coeff=args.min_side_coeff,
        relic_reroll_threshold=args.relic_reroll_threshold,
        force_reroll_no_progress=args.force_reroll_no_progress,
        effect_aware=True,
        confirm_min_coeff=args.confirm_min_coeff,
        endgame_risk=args.endgame_risk,
        relic_coeff=args.relic_coeff,
        ancient_coeff=args.ancient_coeff,
    )
    r = sim.simulate_one(seed=args.seed, log=True)

    print(f"Rarity: {rarity}  |  Seed: {args.seed}")
    print(f"Result: {'SUCCESS' if r.success else 'FAIL'} ({r.reason})")
    print(f"Reset used: {r.reset_used}")
    print(f"Final state: will={r.state.will} chaos={r.state.chaos} "
          f"first={r.state.first} second={r.state.second}  "
          f"(total={r.total_points})")
    print(f"Effects: {r.state.first_effect} / {r.state.second_effect}")
    print(f"Rerolls left: {r.rerolls_left}")
    print()

    print("(P(goal)~ is an optimistic estimate — reroll-aware DP)")
    print()
    for t in (r.turn_log or []):
        hdr = f"Turn {t['turn']} (left={t['turns_left']})"
        if t.get("goal_prob") is not None:
            hdr += f"  P(goal)~={t['goal_prob']:.1%}"
        if t.get("relic_prob") is not None:
            hdr += f"  P(r+)={t['relic_prob']:.1%}"
        if "rerolls_available" in t:
            hdr += f"  rerolls={t['rerolls_available']}"
        if "eff_threshold" in t:
            hdr += f"  threshold={t['eff_threshold']:.0%}"
        print(hdr)
        if "offers_history" in t:
            for i, offers in enumerate(t["offers_history"]):
                if i == 0:
                    print(f"  offers:  {offers}")
                else:
                    reroll_line = f"  reroll:  {offers}  reasons={t['reroll_reasons_history'][i - 1]}"
                    fh = t.get("reroll_feasible_history")
                    if fh and i - 1 < len(fh):
                        reroll_line += f"  feasible={fh[i - 1]:.0%}"
                    print(reroll_line)
        action_line = f"  action:  {t['action']}"
        if "feasible_frac" in t:
            action_line += f"  feasible={t['feasible_frac']:.0%}"
        if "prob_after_click" in t:
            action_line += f"  P(click)={t['prob_after_click']:.1%}"
        print(action_line)
        if "picked" in t:
            print(f"  picked:  {t['picked']}")
        sa = t.get("state_after") or t.get("state_before_reset")
        if sa:
            state_line = (f"  state:   w={sa['will']} c={sa['chaos']} "
                          f"1st={sa['first']} 2nd={sa['second']}  "
                          f"(total={sa['total_points']})  "
                          f"effects={sa['first_effect']}/{sa['second_effect']}")
            if sa.get("goal_prob") is not None:
                state_line += f"  P(goal)~={sa['goal_prob']:.1%}"
            if sa.get("relic_prob") is not None:
                state_line += f"  P(r+)={sa['relic_prob']:.1%}"
            print(state_line)
        print()

    print("--- Result ---")
    print(f"Result: {'SUCCESS' if r.success else 'FAIL'} ({r.reason})")
    print(f"Reset used: {r.reset_used}")
    print(f"Final state: will={r.state.will} chaos={r.state.chaos} "
          f"first={r.state.first} second={r.state.second}  "
          f"(total={r.total_points})")
    print(f"Effects: {r.state.first_effect} / {r.state.second_effect}")
    print(f"Rerolls left: {r.rerolls_left}")


def cmd_effects(args: argparse.Namespace) -> None:
    optimize = args.optimize
    coeff = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
    target = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
    max_coeff = max(coeff.values())
    threshold = args.side_threshold

    gem_types = [args.gem_type] if args.gem_type else list(GEM_TYPES.keys())

    for gem_type in gem_types:
        pool = GEM_TYPES[gem_type]
        print(f"=== {gem_type} ===")
        print(f"Pool: {', '.join(f'{e}({coeff.get(e, 0)})' for e in pool)}")
        print(f"Optimize: {optimize}  Base threshold: {threshold}")
        print()

        for first, second in combinations(pool, 2):
            available = [e for e in pool if e != first and e != second]
            first_val = coeff.get(first, 0)
            second_val = coeff.get(second, 0)
            best_val = max(first_val, second_val) if (first in target or second in target) else 0
            if best_val > 0:
                quality = best_val / max_coeff
                eff_thresh = threshold + (1 - threshold) * (1 - quality)
            else:
                eff_thresh = 1.0

            print(f"  {first}({first_val}) + {second}({second_val})"
                  f"  eff.threshold={eff_thresh:.0%}")

            for slot, cur_eff in [("first", first), ("second", second)]:
                cur_val = coeff.get(cur_eff, 0)
                outcomes = []
                for e in available:
                    e_val = coeff.get(e, 0)
                    is_target = e in target
                    outcomes.append(f"{e}({e_val}) {'GOOD' if is_target else 'BAD'}")
                target_count = sum(1 for e in available if e in target)
                print(f"    change_{slot}: {cur_eff}({cur_val}) -> [{', '.join(outcomes)}]"
                      f"  {target_count}/{len(available)} target")
            print()


def cmd_live(args: argparse.Namespace) -> None:
    """Detect game state from screenshot and display option probabilities."""
    import cv2
    from arkgrid.vision.template_recognizer import (
        detect, parse_rerolls, determine_option_kind, parse_delta,
    )
    from arkgrid.vision.constants import (
        GEM_TYPE_TEMPLATE_TO_DOMAIN, RARITY_FROM_TOTAL_STEPS,
    )

    # --- Load and detect ---
    frame = cv2.imread(args.screenshot)
    if frame is None:
        raise SystemExit(f"Cannot read image: {args.screenshot}")

    det = detect(frame)
    if not det.found:
        from arkgrid.vision.template_recognizer import detect_finish
        finish_det = detect_finish(frame)
        if finish_det.found:
            w = finish_det.willpower
            c = finish_det.chaos
            f1 = finish_det.first_level
            f2 = finish_det.second_level
            total = sum(x for x in (w, c, f1, f2) if x)
            print("=== Astrogem Finish Screen ===")
            print(f"  Willpower:  {w}  (confidence: {finish_det.willpower_score:.2f})")
            print(f"  Chaos:      {c}  (confidence: {finish_det.chaos_score:.2f})")
            print(f"  1st effect: {f1}  (confidence: {finish_det.first_level_score:.2f})")
            print(f"  2nd effect: {f2}  (confidence: {finish_det.second_level_score:.2f})")
            print(f"  Total:      {total}")
            return
        raise SystemExit("Anchor not found in screenshot — is the Processing dialog open?")

    # --- Validate detection ---
    warnings = []
    for field_name, score, label in [
        ("gem_type_score", det.gem_type_score, "gem_type"),
        ("willpower_score", det.willpower_score, "willpower"),
        ("chaos_score", det.chaos_score, "chaos"),
        ("first_effect_score", det.first_effect_score, "side_1 name"),
        ("first_level_score", det.first_level_score, "side_1 level"),
        ("second_effect_score", det.second_effect_score, "side_2 name"),
        ("second_level_score", det.second_level_score, "side_2 level"),
        ("rerolls_score", det.rerolls_score, "rerolls"),
        ("step_score", det.step_score, "step"),
        ("rarity_score", det.rarity_score, "rarity"),
    ]:
        if score < 0.9:
            warnings.append(f"  LOW: {label} = {score:.2f}")

    if det.gem_type is None or det.willpower is None or det.chaos is None:
        raise SystemExit("Critical detection failure — gem_type, willpower, or chaos not detected")
    if det.first_effect is None or det.second_effect is None:
        raise SystemExit("Critical detection failure — side node effects not detected")
    if det.current_step is None or det.total_steps is None:
        raise SystemExit("Critical detection failure — step/rarity not detected")

    # --- Map to domain ---
    gem_type_domain = GEM_TYPE_TEMPLATE_TO_DOMAIN.get(det.gem_type, det.gem_type)
    rarity = RARITY_FROM_TOTAL_STEPS.get(det.total_steps, "rare")
    turns_total = det.total_steps
    turns_left = det.current_step        # "X/Y" means X turns remaining
    current_turn = turns_total - turns_left + 1

    reroll_count = parse_rerolls(det.rerolls, extra_ticket=args.extra_ticket)

    from arkgrid.models import GemState
    state = GemState(
        will=det.willpower,
        chaos=det.chaos,
        first=det.first_level or 1,
        second=det.second_level or 1,
        cost_ratio=0,
        rerolls=reroll_count,
        first_effect=det.first_effect,
        second_effect=det.second_effect,
    )

    # --- Build goal and probability table ---
    goal = LastTurnGoal(
        min_will=args.min_will,
        min_chaos=args.min_chaos,
        exact_will=args.exact_will,
        exact_chaos=args.exact_chaos,
        min_first=getattr(args, "min_first", None),
        min_second=getattr(args, "min_second", None),
    )
    pool = OptionPool()

    # Build BIS-aware probability table if --bis-only
    bis_only = getattr(args, "bis_only", False)
    target_effects: frozenset = frozenset()
    if bis_only and gem_type_domain in GEM_TYPES:
        from arkgrid.constants import DPS_EFFECTS, SUPPORT_EFFECTS
        optimize = getattr(args, "optimize", "dps")
        opt_set = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        gem_pool = set(GEM_TYPES[gem_type_domain])
        target_effects = frozenset(gem_pool & opt_set)

    # Compute side-node coefficients for DP
    min_side_coeff = getattr(args, "min_side_coeff", 0)
    side_coeff_first, side_coeff_second = 0, 0
    if min_side_coeff > 0 and gem_type_domain in GEM_TYPES:
        from arkgrid.constants import DPS_COEFF, SUPPORT_COEFF
        optimize = getattr(args, "optimize", "dps")
        coeff_map = DPS_COEFF if optimize == "dps" else SUPPORT_COEFF
        opt_set_coeff = DPS_EFFECTS if optimize == "dps" else SUPPORT_EFFECTS
        if state.first_effect in opt_set_coeff:
            side_coeff_first = coeff_map[state.first_effect]
        if state.second_effect in opt_set_coeff:
            side_coeff_second = coeff_map[state.second_effect]

    optimize = getattr(args, "optimize", "dps")
    prob_table = GoalProbabilityTable(
        goal, turns_total, pool,
        bis_only=bis_only, target_effects=target_effects,
        side_coeff_first=side_coeff_first,
        side_coeff_second=side_coeff_second,
        min_side_coeff=min_side_coeff,
        early_finish=True,
        effect_aware=True,
        gem_type=gem_type_domain,
        optimize=optimize,
        max_rerolls=reroll_count,
    )
    p_current = prob_table.lookup(state, turns_left, rerolls=reroll_count)

    # --- Compute P(goal) for each option ---
    option_probs = []
    for opt in det.options:
        kind, delta_val = determine_option_kind(
            opt.name_key, opt.delta_key,
            state.first_effect, state.second_effect,
        )

        kind_hint, _ = parse_delta(opt.delta_key)

        if kind_hint == "effect_changed" and bis_only:
            # Probabilistic: new effect may or may not be target
            slot = "first" if opt.name_key == state.first_effect else "second"
            p_after = prob_table.lookup_after_effect_change(
                state, slot, turns_left - 1)
        else:
            next_state = state.clone()
            if delta_val is not None and kind in ("will", "chaos", "first", "second"):
                cur = getattr(next_state, kind)
                setattr(next_state, kind, min(5, max(1, cur + delta_val)))
            p_after = prob_table.lookup(next_state, turns_left - 1,
                                        rerolls=reroll_count)

        option_probs.append((opt, kind, delta_val, p_after))

    best_idx = max(range(len(option_probs)), key=lambda i: option_probs[i][3])

    # --- Format option display name ---
    def fmt_option(opt, kind, delta_val):
        kind_hint, _ = parse_delta(opt.delta_key)
        if kind_hint == "effect_changed":
            return f"{opt.name_key} EC"
        if kind_hint == "maintained":
            return "maintain"
        if kind_hint == "cost":
            return opt.delta_key  # "cost+100" or "cost-100"
        if kind_hint == "reroll":
            return opt.delta_key  # "reroll+1" or "reroll+2"
        if opt.name_key and delta_val is not None:
            sign = "+" if delta_val > 0 else ""
            return f"{opt.name_key} {sign}{delta_val}"
        return opt.name_key or "???"

    # --- Print output ---
    print("=== Astrogem Live Analysis ===")
    print(f"Gem:        {gem_type_domain} ({rarity.capitalize()})")
    first_bis = "BIS" if state.first_effect in target_effects else ""
    second_bis = "BIS" if state.second_effect in target_effects else ""
    if bis_only:
        print(f"Effects:    {det.first_effect} Lv.{det.first_level} {first_bis} / "
              f"{det.second_effect} Lv.{det.second_level} {second_bis}")
    else:
        print(f"Effects:    {det.first_effect} Lv.{det.first_level} / "
              f"{det.second_effect} Lv.{det.second_level}")
    print(f"State:      Will={state.will}  Chaos={state.chaos}  "
          f"First={state.first}  Second={state.second}  "
          f"(Total: {state.total_points()})")
    print(f"Turn:       {current_turn}/{turns_total}  ({turns_left} turns left)")
    print(f"Rerolls:    {reroll_count}")
    if args.reset_ticket is None:
        reset_str = "n/a"
    elif isinstance(args.reset_ticket, str):
        enabled = _reset_enabled_for_rarity(args.reset_ticket, rarity)
        reset_str = f"yes ({args.reset_ticket}+)" if enabled else f"no ({args.reset_ticket}+)"
    else:
        reset_str = "yes" if args.reset_ticket else "no"
    print(f"Tickets:    reset={reset_str}  extra_reroll={'yes' if args.extra_ticket else 'no'}")
    print()

    goal_parts = []
    if goal.min_will is not None:
        goal_parts.append(f"min_will={goal.min_will}")
    if goal.min_chaos is not None:
        goal_parts.append(f"min_chaos={goal.min_chaos}")
    if goal.exact_will is not None:
        goal_parts.append(f"exact_will={goal.exact_will}")
    if goal.exact_chaos is not None:
        goal_parts.append(f"exact_chaos={goal.exact_chaos}")
    if goal.min_first is not None:
        goal_parts.append(f"min_first={goal.min_first}")
    if goal.min_second is not None:
        goal_parts.append(f"min_second={goal.min_second}")
    if min_side_coeff > 0:
        goal_parts.append(f"min_side_coeff={min_side_coeff}")
    print(f"Goal:       {', '.join(goal_parts) if goal_parts else '(none)'}")
    print(f"P(goal)~:   {p_current:.1%}  (reroll-aware DP, optimistic estimate)")

    # Relic+ (>=16 total points) probability from current state
    relic_table = GoalProbabilityTable(
        LastTurnGoal(min_total=16), turns_total, pool,
        early_finish=False,
        max_rerolls=reroll_count,
    )
    p_relic = relic_table.lookup(state, turns_left, rerolls=reroll_count)
    print(f"P(relic+):  {p_relic:.1%}")
    print()

    # --- Reroll recommendation ---
    # Build Option objects for DP-optimal reroll decision.
    from arkgrid.models import Option as PoolOption
    pool_options = []
    for opt, kind, delta_val, _ in option_probs:
        key = kind
        if delta_val is not None and kind in ("will", "chaos", "first", "second"):
            sign = "+" if delta_val > 0 else ""
            key = f"{kind}{sign}{delta_val}"
        elif kind == "view":
            key = f"view+{delta_val}" if delta_val else "view+1"
        elif kind == "cost":
            key = opt.name_key
        pool_options.append(PoolOption(key=key, weight=1.0, kind=kind,
                                       delta=delta_val or 0))

    p_best_option = max(p for _, _, _, p in option_probs)
    p_avg_offers = sum(p for _, _, _, p in option_probs) / len(option_probs)
    should_reroll = (reroll_count > 0
                     and current_turn != 1
                     and turns_left != 1
                     and prob_table.should_reroll_dp(
                         state, pool_options, turns_left, reroll_count))

    print("Options:")
    for i, (opt, kind, delta_val, p_after) in enumerate(option_probs):
        label = fmt_option(opt, kind, delta_val)
        best_marker = "  << best" if i == best_idx else ""
        kind_note = ""
        if kind in ("cost", "view", "other"):
            kind_note = f"  ({kind}, no stat change)"
        print(f"  {i+1}. {label:28s} -> P(goal)~ = {p_after:.1%}{kind_note}{best_marker}")

    print()
    can_reroll = reroll_count > 0 and current_turn != 1 and turns_left != 1
    reroll_val_str = ""
    if can_reroll and reroll_count > 0:
        reroll_val = prob_table.lookup(state, turns_left, rerolls=reroll_count - 1)
        reroll_val_str = f"  |  Reroll value~: {reroll_val:.1%}"
    print(f"  Avg offers: {p_avg_offers:.1%}  |  DP baseline~: {p_current:.1%}  "
          f"|  Best pick: {p_best_option:.1%}{reroll_val_str}")
    # --- Early finish check (side-value DP) ---
    should_early_finish = False
    if (turns_left > 0
            and goal.satisfied(state.will, state.chaos,
                               state.first, state.second)
            and gem_type_domain in GEM_TYPES):
        from arkgrid.probability import SideValueTable
        svt = SideValueTable(
            goal, current_turn + turns_left - 1, pool,
            gem_type=gem_type_domain,
            optimize=getattr(args, "optimize", "dps"),
            min_side_coeff=getattr(args, "min_side_coeff", 0),
            relic_coeff=getattr(args, "relic_coeff", 0),
            ancient_coeff=getattr(args, "ancient_coeff", 0),
        )
        finish_val = svt.gem_value(state)
        process_ev = svt.expected_value_after_click(
            state, pool_options, turns_left - 1)
        reroll_v = (svt.lookup(state, turns_left)
                    if (reroll_count > 0 and current_turn != 1) else 0.0)
        continue_val = max(process_ev, reroll_v)
        should_early_finish = finish_val >= continue_val

    if should_early_finish:
        print(f"  >>> Finish (side-value DP: stopping is at least as "
              f"good as continuing)")
    elif should_reroll:
        print(f"  >>> Reroll (offers {p_current - p_avg_offers:+.1%} below baseline, "
              f"{reroll_count} rerolls available)")
    else:
        print(f"  >>> Process (best: option {best_idx + 1})")
    print()

    if warnings:
        print("Warnings (low confidence detections):")
        for w in warnings:
            print(w)
        print()

    # --- Optional Monte Carlo ---
    if args.trials > 0:
        astro_gem = AstroGem(gem_type_domain, state.first_effect,
                             state.second_effect, args.optimize)
        use_reset = _reset_enabled_for_rarity(args.reset_ticket, rarity)
        sim = GemSimulator(
            rarity=rarity,
            use_extra_ticket=args.extra_ticket,
            use_reset_ticket=use_reset,
            goal=goal,
            side_node_threshold=args.side_threshold,
            astro_gem=astro_gem,
            optimize=args.optimize,
            prob_reset_threshold=getattr(args, "prob_reset_threshold", 0.0),
            bis_only=getattr(args, "bis_only", False),
            reset_min_coeff=getattr(args, "reset_min_coeff", 0),
            reroll_min_coeff=getattr(args, "reroll_min_coeff", 0),
            min_side_coeff=getattr(args, "min_side_coeff", 0),
            force_reroll_no_progress=getattr(args, "force_reroll_no_progress", False),
            effect_aware=True,
            endgame_risk=getattr(args, "endgame_risk", 0.0),
            relic_coeff=getattr(args, "relic_coeff", 0),
            ancient_coeff=getattr(args, "ancient_coeff", 0),
        )
        summary = GemAnalyzer.estimate_summary(
            trials=args.trials, simulator=sim, seed=args.seed,
        )
        print(f"Monte Carlo ({args.trials} trials from turn 1): "
              f"{summary['p_success']:.1%} success  "
              f"[reset_rate={summary['reset_rate']:.1%}]")


def cmd_read(args: argparse.Namespace) -> None:
    """Read the game screen and print recognized state."""
    from arkgrid.vision import (
        ScreenRecognizer, draw_debug, describe_result,
        load_screenshot, grab_screen,
    )
    import cv2

    # Capture or load frame
    if args.screenshot:
        frame = load_screenshot(args.screenshot)
        print(f"Loaded screenshot: {args.screenshot} ({frame.shape[1]}x{frame.shape[0]})")
    else:
        frame = grab_screen(monitor_index=args.monitor)
        print(f"Captured screen ({frame.shape[1]}x{frame.shape[0]})")

    # Recognize
    recognizer = ScreenRecognizer()
    result = recognizer.recognize(frame)

    # Print results
    print()
    print(describe_result(result))

    # Debug output
    if args.debug or args.save_debug:
        debug_img = draw_debug(frame, result)
        if args.save_debug:
            cv2.imwrite(args.save_debug, debug_img)
            print(f"\nDebug image saved to {args.save_debug}")
        if args.debug:
            cv2.imshow("AstrogemCutter Vision Debug", debug_img)
            print("\nPress any key to close debug window...")
            cv2.waitKey(0)
            cv2.destroyAllWindows()


def cmd_auto(args: argparse.Namespace) -> None:
    """Automate gem cutting: detect, decide, click."""
    from arkgrid.automation import run_auto
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    _print_config(args, goal, astro_gem)

    # Pass the raw --reset-ticket value through (True/False/None or a rarity
    # string); run_auto resolves against the detected gem's rarity per run.
    # [0] is load-bearing: when --reset-ticket is omitted reset_variants is
    # [False, True] so [0] selects the disabled default; stats iterates both.
    # Reverting to [-1] would silently enable the reset ticket by default.
    use_reset = reset_variants[0]

    run_auto(
        monitor_index=args.monitor,
        goal=goal,
        extra_ticket=args.extra_ticket,
        reset_ticket=use_reset,
        optimize=args.optimize,
        bis_only=args.bis_only,
        min_side_coeff=args.min_side_coeff,
        prob_reset_threshold=args.prob_reset_threshold,
        side_threshold=args.side_threshold,
        animation_delay=args.animation_delay,
        dry_run=args.dry_run,
        astro_gem=astro_gem,
        reset_min_coeff=args.reset_min_coeff,
        reroll_min_coeff=args.reroll_min_coeff,
        relic_reroll_threshold=args.relic_reroll_threshold,
        force_reroll_no_progress=args.force_reroll_no_progress,
        all_gems=args.all_gems,
        effect_aware_dp=True,
        args=args,
        confirm_min_coeff=args.confirm_min_coeff,
        endgame_risk=args.endgame_risk,
        relic_coeff=args.relic_coeff,
        ancient_coeff=args.ancient_coeff,
    )


def cmd_report(args: argparse.Namespace) -> None:
    """Aggregate stats from past auto-run JSONL logs."""
    from arkgrid.log_analyzer import (
        load_runs, filter_records, print_summary,
    )

    records = load_runs(args.log_dir)
    if not records:
        print(f"No JSONL logs found in {args.log_dir}/")
        return
    filtered = filter_records(records, args)
    print_summary(args, filtered)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "sim":
        cmd_sim(args)
    elif args.command == "effects":
        cmd_effects(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "live":
        cmd_live(args)
    elif args.command == "auto":
        cmd_auto(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()
