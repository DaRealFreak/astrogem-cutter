from __future__ import annotations

import argparse
from typing import List, Optional, Tuple

from itertools import combinations

from arkgrid.constants import (
    DPS_COEFF, DPS_EFFECTS, GEM_TYPES,
    SUPPORT_COEFF, SUPPORT_EFFECTS,
)
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
        p.add_argument("--reset-ticket", action="store_true", default=None,
                        help="Use reset ticket (default: run both with/without)")
        p.add_argument("--no-reset-ticket", action="store_false", dest="reset_ticket")
        p.add_argument("--side-threshold", type=float, default=0.5, metavar="F",
                        help="Goal-feasibility fraction above which side nodes are valued (default: 0.5)")
        p.add_argument("--prob-reset-threshold", type=float, default=0.0, metavar="F",
                        help="Reset proactively when goal probability drops below this "
                             "(0.0 = disabled, try 0.05-0.15)")
        p.add_argument("--bis-only", action="store_true", default=False,
                        help="Only value side nodes when effects are best-in-slot")
        p.add_argument("--dp-reroll-margin", type=float, default=0.03, metavar="F",
                        help="Margin for DP-based reroll override (default: 0.03)")
        p.add_argument("--reset-min-coeff", type=int, default=0, metavar="N",
                        help="Only use reset ticket when the sum of starting target-effect "
                             "coefficients meets this threshold (e.g. atk_power+additional_damage = "
                             "400+700 = 1100 passes, 1051 skips brand_power alone for support). "
                             "0 = always use. Default: 0")
        p.add_argument("--reroll-min-coeff", type=int, default=0, metavar="N",
                        help="Only use extra reroll ticket when the sum of starting target-effect "
                             "coefficients meets this threshold. Same logic as --reset-min-coeff "
                             "but for the extra reroll ticket. 0 = always use. Default: 0")
        p.add_argument("--side-quality", type=float, default=0.0, metavar="F",
                        help="Weight side-node quality by coefficient in reroll decisions. "
                             "0 = off (max goal probability), 2 = mild, 12 = aggressive "
                             "(tolerates ~40%% prob drop for +4 boss_damage). Default: 0")
        p.add_argument("--min-first", type=int, default=None, metavar="N",
                        help="Minimum level for first side node (1-5)")
        p.add_argument("--min-second", type=int, default=None, metavar="N",
                        help="Minimum level for second side node (1-5)")
        p.add_argument("--min-side-coeff", type=int, default=0, metavar="N",
                        help="Minimum coefficient-weighted level total from target side nodes. "
                             "Value = sum(level * coefficient). E.g. boss_damage(1000)*5 = 5000. "
                             "Requires --gem-type with --first/second-effect. Default: 0")
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

    return parser


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

    rarities = args.rarity if args.rarity else ["common", "rare", "epic"]

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
                bis_only=args.bis_only,
                dp_reroll_margin=args.dp_reroll_margin,
                side_quality_weight=args.side_quality,
                reset_min_coeff=args.reset_min_coeff,
                reroll_min_coeff=args.reroll_min_coeff,
                min_side_coeff=args.min_side_coeff,
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
        bis_only=args.bis_only,
        dp_reroll_margin=args.dp_reroll_margin,
        side_quality_weight=args.side_quality,
        reroll_min_coeff=args.reroll_min_coeff,
        min_side_coeff=args.min_side_coeff,
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
                state_line += f"  P(goal)={sa['goal_prob']:.1%}"
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
    from arkgrid.pool import OptionPool
    from arkgrid.probability import GoalProbabilityTable

    # --- Load and detect ---
    frame = cv2.imread(args.screenshot)
    if frame is None:
        raise SystemExit(f"Cannot read image: {args.screenshot}")

    det = detect(frame)
    if not det.found:
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

    prob_table = GoalProbabilityTable(
        goal, turns_total, pool,
        bis_only=bis_only, target_effects=target_effects,
        side_coeff_first=side_coeff_first,
        side_coeff_second=side_coeff_second,
        min_side_coeff=min_side_coeff,
    )
    p_current = prob_table.lookup(state, turns_left)

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
            p_after = prob_table.lookup(next_state, turns_left - 1)

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
    reset_str = "yes" if args.reset_ticket else "no" if args.reset_ticket is False else "n/a"
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
    print(f"P(goal):    {p_current:.1%}")
    print()

    # --- Reroll recommendation ---
    # Compare average offer probability against DP baseline (expected
    # value over all possible offer draws).  If the average is more than
    # dp_reroll_margin relatively worse than baseline, rerolling is advisable.
    p_best_option = max(p for _, _, _, p in option_probs)
    p_avg_offers = sum(p for _, _, _, p in option_probs) / len(option_probs)
    dp_margin = getattr(args, "dp_reroll_margin", 0.03)
    should_reroll = (reroll_count > 0
                     and current_turn != 1  # can't reroll on turn 1
                     and turns_left != 1    # can't reroll on last turn
                     and p_current > 0
                     and p_avg_offers < p_current * (1 - dp_margin))

    print("Options:")
    for i, (opt, kind, delta_val, p_after) in enumerate(option_probs):
        label = fmt_option(opt, kind, delta_val)
        best_marker = "  << best" if i == best_idx else ""
        kind_note = ""
        if kind in ("cost", "view", "other"):
            kind_note = f"  ({kind}, no stat change)"
        print(f"  {i+1}. {label:28s} -> P(goal) = {p_after:.1%}{kind_note}{best_marker}")

    print()
    reroll_threshold = p_current * (1 - dp_margin)
    can_reroll = reroll_count > 0 and current_turn != 1 and turns_left != 1
    print(f"  Avg offers: {p_avg_offers:.1%}  |  DP baseline: {p_current:.1%}  "
          f"|  Best pick: {p_best_option:.1%}"
          f"  |  Reroll below: {reroll_threshold:.1%}" if can_reroll else
          f"  Avg offers: {p_avg_offers:.1%}  |  DP baseline: {p_current:.1%}  "
          f"|  Best pick: {p_best_option:.1%}")
    if should_reroll:
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
        use_reset = args.reset_ticket if args.reset_ticket is not None else False
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
            dp_reroll_margin=getattr(args, "dp_reroll_margin", 0.03),
            side_quality_weight=getattr(args, "side_quality", 0.0),
            reset_min_coeff=getattr(args, "reset_min_coeff", 0),
            reroll_min_coeff=getattr(args, "reroll_min_coeff", 0),
            min_side_coeff=getattr(args, "min_side_coeff", 0),
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
    else:
        parser.print_help()
