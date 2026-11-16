"""Opt-in spending gates for the two scarce resources.

* `reset_keep_grade` — never spend the reset ticket on a gem that already
  holds relic / ancient grade.
* `ticket_min_goal_gain` / `ticket_min_value_gain` — spend the gold reroll
  ticket only when the reroll it buys is measurably worth it.

Both default to off, which must leave every decision unchanged.
"""
from __future__ import annotations

import unittest

from arkgrid.decision import ActionKind, TurnInput, decide_post_roll
from arkgrid.models import AstroGem, GemState, LastTurnGoal
from arkgrid.simulator import GemSimulator

GOAL = LastTurnGoal(min_will=4, min_chaos=5)


def _sim(**kw) -> GemSimulator:
    kw.setdefault("use_extra_ticket", None)
    kw.setdefault("use_reset_ticket", True)
    kw.setdefault("astro_gem", None)
    return GemSimulator("epic", goal=GOAL, **kw)


def _ctx(sim: GemSimulator):
    return sim._decision_context(p_fresh=sim.fresh_start_prob(sim.astro_gem))


def _offers(sim: GemSimulator, *keys: str):
    by_key = {o.key: o for o in sim.pool.pool}
    return [by_key[k] for k in keys]


class TestResetKeepGrade(unittest.TestCase):
    """A dead-goal last turn: no offer can reach will>=4, reset in hand."""

    OFFERS = ("chaos-1", "first+1", "second-1", "maintain")

    def _decide(self, sim, state):
        ti = TurnInput(state=state, offers=_offers(sim, *self.OFFERS),
                       turn=9, turns_left=1, rerolls=0, reset_available=True)
        return decide_post_roll(_ctx(sim), ti)

    def test_default_resets_a_relic_gem(self) -> None:
        relic = GemState(will=3, chaos=5, first=4, second=5)      # 17 points
        self.assertEqual(self._decide(_sim(), relic).action, ActionKind.RESET)

    def test_relic_gem_is_kept(self) -> None:
        relic = GemState(will=3, chaos=5, first=4, second=5)      # 17 points
        d = self._decide(_sim(reset_keep_grade="relic"), relic)
        self.assertNotEqual(d.action, ActionKind.RESET)
        self.assertIn("reset ticket kept", d.reason)

    def test_gem_below_the_grade_is_still_reset(self) -> None:
        legendary = GemState(will=3, chaos=5, first=3, second=3)  # 14 points
        d = self._decide(_sim(reset_keep_grade="relic"), legendary)
        self.assertEqual(d.action, ActionKind.RESET)

    def test_ancient_setting_does_not_protect_relic(self) -> None:
        relic = GemState(will=3, chaos=5, first=4, second=5)      # 17 points
        d = self._decide(_sim(reset_keep_grade="ancient"), relic)
        self.assertEqual(d.action, ActionKind.RESET)


class TestTicketSpendGate(unittest.TestCase):
    """Mid-game, goal still alive, free rerolls gone, ticket lent."""

    STATE = GemState(will=2, chaos=3, first=2, second=2)
    TURN = 6
    WEAK = ("first+1", "second+1", "first+2", "second+2")       # no progress
    AWFUL = ("will-1", "chaos-1", "first-1", "second-1")        # terrible hand

    def _decide(self, sim, offers, *, rerolls=1, ticket_lent=True):
        ti = TurnInput(state=self.STATE.clone(), offers=_offers(sim, *offers),
                       turn=self.TURN, turns_left=10 - self.TURN,
                       rerolls=rerolls, reset_available=False,
                       ticket_lent=ticket_lent)
        return decide_post_roll(_ctx(sim), ti)

    def _goal_gain(self, sim, offers):
        """What the ticket adds: redraw (ticket gone) vs keep (ticket kept)."""
        table = sim.prob_table
        tl = 10 - self.TURN
        return (table.lookup(self.STATE, tl, rerolls=0)
                - table.expected_prob_after_click(
                    self.STATE, _offers(sim, *offers), tl - 1, rerolls=1))

    def test_default_spends_the_ticket_on_any_positive_gain(self) -> None:
        sim = _sim()
        self.assertGreater(self._goal_gain(sim, self.WEAK), 0.0)
        self.assertEqual(self._decide(sim, self.WEAK).action, ActionKind.REROLL)

    def test_small_gain_holds_the_ticket(self) -> None:
        sim = _sim()
        gain = self._goal_gain(sim, self.WEAK)
        gated = _sim(ticket_min_goal_gain=gain + 0.01)
        d = self._decide(gated, self.WEAK)
        self.assertEqual(d.action, ActionKind.PROCESS)
        self.assertIn("reroll ticket held", d.reason)

    def test_large_gain_still_spends_the_ticket(self) -> None:
        sim = _sim()
        weak, awful = (self._goal_gain(sim, h) for h in (self.WEAK, self.AWFUL))
        self.assertGreater(awful, weak)
        gated = _sim(ticket_min_goal_gain=(weak + awful) / 2)
        self.assertEqual(self._decide(gated, self.AWFUL).action,
                         ActionKind.REROLL)
        self.assertEqual(self._decide(gated, self.WEAK).action,
                         ActionKind.PROCESS)

    def test_free_rerolls_are_never_gated(self) -> None:
        gated = _sim(ticket_min_goal_gain=0.9)
        # The only reroll is a free one.
        self.assertEqual(
            self._decide(gated, self.WEAK, rerolls=1, ticket_lent=False).action,
            ActionKind.REROLL)
        # Ticket lent, but a free reroll is spent first.
        self.assertEqual(
            self._decide(gated, self.WEAK, rerolls=2, ticket_lent=True).action,
            ActionKind.REROLL)

    def test_value_bar_does_not_gate_a_goal_reroll(self) -> None:
        # Each bar governs its own kind of reroll.
        gated = _sim(ticket_min_value_gain=10 ** 9)
        self.assertEqual(self._decide(gated, self.WEAK).action,
                         ActionKind.REROLL)


class TestTicketValueGate(unittest.TestCase):
    """Goal met: the ticket would be spent fishing for side value."""

    GEM = AstroGem("order_immutability", "boss_damage", "additional_damage",
                   "dps")

    def _decide(self, sim):
        state = GemState(will=4, chaos=5, first=2, second=2,
                         first_effect=self.GEM.first_effect,
                         second_effect=self.GEM.second_effect)
        ti = TurnInput(
            state=state,
            offers=_offers(sim, "maintain", "cost+100", "view+1", "second-1"),
            turn=6, turns_left=4, rerolls=1, reset_available=False,
            ticket_lent=True)
        return decide_post_roll(_ctx(sim), ti)

    def test_default_spends_it_and_a_high_bar_holds_it(self) -> None:
        self.assertEqual(self._decide(_sim(astro_gem=self.GEM)).action,
                         ActionKind.REROLL)
        held = self._decide(_sim(astro_gem=self.GEM,
                                 ticket_min_value_gain=10 ** 9))
        self.assertNotEqual(held.action, ActionKind.REROLL)
        self.assertIn("reroll ticket held", held.reason)

    def test_goal_bar_does_not_gate_a_value_reroll(self) -> None:
        d = self._decide(_sim(astro_gem=self.GEM, ticket_min_goal_gain=0.9))
        self.assertEqual(d.action, ActionKind.REROLL)


class TestTicketIsNotSpentWithoutUpside(unittest.TestCase):
    """A fully maxed gem with a harmless hand: finishing, processing and
    redrawing are all worth exactly the same. Free rerolls are still spent
    (they cost nothing), but the gold ticket must not be — with every gate
    off, and regardless of which way float noise tips the tie."""

    GEM = AstroGem("order_immutability", "boss_damage", "additional_damage",
                   "dps")

    def _decide(self, *, ticket_lent, rerolls=1, turn=5):
        sim = _sim(astro_gem=self.GEM)
        state = GemState(will=5, chaos=5, first=5, second=5,
                         first_effect=self.GEM.first_effect,
                         second_effect=self.GEM.second_effect)
        ti = TurnInput(
            state=state,
            offers=_offers(sim, "cost+100", "cost-100", "view+1", "view+2"),
            turn=turn, turns_left=10 - turn, rerolls=rerolls,
            reset_available=False, ticket_lent=ticket_lent)
        return decide_post_roll(_ctx(sim), ti)

    def test_ticket_is_not_spent(self) -> None:
        d = self._decide(ticket_lent=True)
        self.assertEqual(d.action, ActionKind.FINISH)
        self.assertIn("not spending the reroll ticket", d.reason)

    def test_free_reroll_is_still_spent(self) -> None:
        self.assertEqual(self._decide(ticket_lent=False).action,
                         ActionKind.REROLL)
        # Ticket lent but a free reroll goes first.
        self.assertEqual(self._decide(ticket_lent=True, rerolls=2).action,
                         ActionKind.REROLL)

    def test_no_rerolls_finishes_on_the_tie(self) -> None:
        self.assertEqual(self._decide(ticket_lent=False, rerolls=0).action,
                         ActionKind.FINISH)


class TestGatesInSimulation(unittest.TestCase):
    N = 400

    def _rates(self, **kw):
        sim = _sim(use_extra_ticket=True, **kw)
        results = [sim.simulate_one(seed=s) for s in range(self.N)]
        return (sum(r.extra_ticket_used for r in results) / self.N,
                sum(r.reset_used for r in results) / self.N,
                [(r.success, r.total_points) for r in results])

    def test_gates_off_change_nothing(self) -> None:
        base = self._rates()
        explicit = self._rates(reset_keep_grade=None, ticket_min_goal_gain=0.0,
                               ticket_min_value_gain=0.0)
        self.assertEqual(base, explicit)

    def test_goal_gain_bar_cuts_ticket_use(self) -> None:
        base_ticket, _resets, _ = self._rates()
        gated_ticket, _resets, _ = self._rates(ticket_min_goal_gain=0.03)
        self.assertLess(gated_ticket, base_ticket - 0.10)
        self.assertGreater(gated_ticket, 0.0)

    def test_keeping_relic_gems_cuts_resets(self) -> None:
        _t, base_resets, _ = self._rates()
        _t, kept_resets, _ = self._rates(reset_keep_grade="relic")
        self.assertLess(kept_resets, base_resets)


if __name__ == "__main__":
    unittest.main()
