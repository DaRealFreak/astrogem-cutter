from __future__ import annotations

import random
from typing import List

from arkgrid.models import Option, GemState


class OptionPool:
    def __init__(self) -> None:
        self.pool: List[Option] = self._build_pool()

    @staticmethod
    def _build_pool() -> List[Option]:
        pool: List[Option] = []

        def add(key: str, weight: float, kind: str, delta: int = 0) -> None:
            pool.append(Option(key, weight, kind, delta))

        # Willpower
        add("will+1", 11.6500, "will", 1)
        add("will+2", 4.4000, "will", 2)
        add("will+3", 1.7500, "will", 3)
        add("will+4", 0.4500, "will", 4)
        add("will-1", 3.0000, "will", -1)

        # Chaos
        add("chaos+1", 11.6500, "chaos", 1)
        add("chaos+2", 4.4000, "chaos", 2)
        add("chaos+3", 1.7500, "chaos", 3)
        add("chaos+4", 0.4500, "chaos", 4)
        add("chaos-1", 3.0000, "chaos", -1)

        # First
        add("first+1", 11.6500, "first", 1)
        add("first+2", 4.4000, "first", 2)
        add("first+3", 1.7500, "first", 3)
        add("first+4", 0.4500, "first", 4)
        add("first-1", 3.0000, "first", -1)

        # Second
        add("second+1", 11.6500, "second", 1)
        add("second+2", 4.4000, "second", 2)
        add("second+3", 1.7500, "second", 3)
        add("second+4", 0.4500, "second", 4)
        add("second-1", 3.0000, "second", -1)

        # Other
        add("change_first_effect", 3.2500, "other", 0)
        add("change_second_effect", 3.2500, "other", 0)
        add("maintain", 1.7500, "other", 0)

        # Cost modifiers
        add("cost+100", 1.7500, "cost", 0)
        add("cost-100", 1.7500, "cost", 0)

        # View => modeled as gaining rerolls
        add("view+1", 2.5000, "view", 1)
        add("view+2", 0.7500, "view", 2)

        return pool

    @staticmethod
    def _can_increase(cur: int, k: int) -> bool:
        return cur <= 5 - k

    @staticmethod
    def _can_decrease(cur: int) -> bool:
        return cur >= 2

    def eligible(self, opt: Option, state: GemState, turn: int, turns_left: int) -> bool:
        if opt.kind == "will":
            return self._can_increase(state.will, opt.delta) if opt.delta > 0 else self._can_decrease(state.will)
        if opt.kind == "chaos":
            return self._can_increase(state.chaos, opt.delta) if opt.delta > 0 else self._can_decrease(state.chaos)
        if opt.kind == "first":
            return self._can_increase(state.first, opt.delta) if opt.delta > 0 else self._can_decrease(state.first)
        if opt.kind == "second":
            return self._can_increase(state.second, opt.delta) if opt.delta > 0 else self._can_decrease(state.second)

        # cost options excluded on last turn
        if opt.kind == "cost":
            if turns_left == 1:
                return False
            if opt.key == "cost+100":
                return state.cost_ratio < 100
            if opt.key == "cost-100":
                return state.cost_ratio > -100
            return True

        # view options excluded on the last turn only (per the official
        # disclosure and verified in-game: they CAN appear among the turn-1
        # picks — the reroll BUTTON is what's locked on turn 1, and rerolls
        # banked from a turn-1 view pick are usable from turn 2).
        if opt.kind == "view":
            if turns_left == 1:
                return False
            return True

        return True

    @staticmethod
    def _weighted_choice(options: List[Option], rng: random.Random) -> Option:
        total = sum(o.weight for o in options)
        r = rng.random() * total
        acc = 0.0
        for o in options:
            acc += o.weight
            if r <= acc:
                return o
        return options[-1]

    def _weighted_sample_without_replacement(self, options: List[Option], k: int, rng: random.Random) -> List[Option]:
        chosen: List[Option] = []
        remaining = options[:]
        for _ in range(k):
            pick = self._weighted_choice(remaining, rng)
            chosen.append(pick)
            remaining.remove(pick)
        return chosen

    def generate_offers(self, state: GemState, turn: int, turns_left: int, rng: random.Random) -> List[Option]:
        elig = [o for o in self.pool if self.eligible(o, state, turn, turns_left)]
        if len(elig) <= 4:
            return elig
        return self._weighted_sample_without_replacement(elig, 4, rng)
