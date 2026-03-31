from __future__ import annotations

import argparse
from typing import List, Optional, Tuple

from arkgrid.constants import DPS_EFFECTS, GEM_TYPES, SUPPORT_EFFECTS
from arkgrid.models import LastTurnGoal, AstroGem
from arkgrid.simulator import GemSimulator
from arkgrid.analyzer import GemAnalyzer, pprint_result

ALL_EFFECTS = sorted(DPS_EFFECTS | SUPPORT_EFFECTS)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lost Ark Astrogem cutting simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # ---- shared arguments ----
    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--rarity", choices=["common", "rare", "epic"], default=None,
                        help="Gem rarity (default: run all three)")
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
        p.add_argument("--reset-ticket", action="store_true", default=None,
                        help="Use reset ticket (default: run both with/without)")
        p.add_argument("--no-reset-ticket", action="store_false", dest="reset_ticket")
        p.add_argument("--side-threshold", type=float, default=0.5, metavar="F",
                        help="Goal-feasibility fraction above which side nodes are valued (default: 0.5)")
        p.add_argument("--prob-reset-threshold", type=float, default=0.0, metavar="F",
                        help="Reset proactively when goal probability drops below this "
                             "(0.0 = disabled, try 0.05-0.15)")
        grp = p.add_argument_group("gem configuration (omit for random gem each run)")
        grp.add_argument("--gem-type", choices=list(GEM_TYPES.keys()), default=None,
                         help="Gem type")
        grp.add_argument("--first-effect", choices=ALL_EFFECTS, default=None,
                         help="First effect on the gem")
        grp.add_argument("--second-effect", choices=ALL_EFFECTS, default=None,
                         help="Second effect on the gem")

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

    return parser


def _resolve_args(args: argparse.Namespace) -> Tuple[
    LastTurnGoal, Optional[AstroGem], List[str], List[Optional[bool]]
]:
    goal = LastTurnGoal(
        min_will=args.min_will,
        min_chaos=args.min_chaos,
        exact_will=args.exact_will,
        exact_chaos=args.exact_chaos,
    )

    astro_gem: Optional[AstroGem] = None
    if args.gem_type:
        pool = set(GEM_TYPES[args.gem_type])
        first = args.first_effect
        second = args.second_effect
        if not first or first not in pool:
            raise SystemExit(
                f"--first-effect must be one of {sorted(pool)} for {args.gem_type}"
            )
        if not second or second not in pool:
            raise SystemExit(
                f"--second-effect must be one of {sorted(pool)} for {args.gem_type}"
            )
        if first == second:
            raise SystemExit("--first-effect and --second-effect must differ")
        astro_gem = AstroGem(args.gem_type, first, second, args.optimize)

    rarities = [args.rarity] if args.rarity else ["common", "rare", "epic"]

    if args.reset_ticket is None:
        reset_variants: List[Optional[bool]] = [False, True]
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
    print()


def cmd_stats(args: argparse.Namespace) -> None:
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    _print_config(args, goal, astro_gem)

    for use_reset in reset_variants:
        label = "With reset ticket" if use_reset else "Without reset ticket"
        print(f"--- {label} ---")
        for rarity in rarities:
            sim = GemSimulator(
                rarity=rarity,
                use_extra_ticket=args.extra_ticket,
                use_reset_ticket=use_reset,
                goal=goal,
                side_node_threshold=args.side_threshold,
                astro_gem=astro_gem,
                optimize=args.optimize,
                prob_reset_threshold=args.prob_reset_threshold,
            )
            summary = GemAnalyzer.estimate_summary(
                trials=args.trials, simulator=sim, seed=args.seed,
            )
            pprint_result(f"  {rarity.capitalize()}", summary)


def cmd_sim(args: argparse.Namespace) -> None:
    goal, astro_gem, rarities, reset_variants = _resolve_args(args)
    rarity = rarities[0]
    use_reset = reset_variants[-1]
    _print_config(args, goal, astro_gem)

    sim = GemSimulator(
        rarity=rarity,
        use_extra_ticket=args.extra_ticket,
        use_reset_ticket=use_reset,
        goal=goal,
        side_node_threshold=args.side_threshold,
        astro_gem=astro_gem,
        optimize=args.optimize,
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

    for t in (r.turn_log or []):
        hdr = f"Turn {t['turn']} (left={t['turns_left']})"
        if t.get("goal_prob") is not None:
            hdr += f"  P(goal)={t['goal_prob']:.1%}"
        if "rerolls_available" in t:
            hdr += f"  rerolls={t['rerolls_available']}"
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
                state_line += f"  P(goal)={sa['goal_prob']:.1%}"
            print(state_line)
        print()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "sim":
        cmd_sim(args)
    else:
        parser.print_help()
