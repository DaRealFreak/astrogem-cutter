import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { decidePostRoll } from '../src/lib/engine/decision';
import { OptionPool } from '../src/lib/engine/pool';
import { GemState, LastTurnGoal } from '../src/lib/engine/models';
import { buildEngineContext } from '../src/lib/engine';

const recs = JSON.parse(readFileSync(
  new URL('./fixtures/decisions.json', import.meta.url), 'utf8')).records;

// Map snake_case fixture goal keys to AdvisorConfig fields.
function goalFieldsFromFixture(g: Record<string, number>): {
  minWill?: number; minChaos?: number; minFirst?: number; minSecond?: number;
  minTotalWillChaos?: number; minTotal?: number;
} {
  return {
    minWill: g['min_will'],
    minChaos: g['min_chaos'],
    minFirst: g['min_first'],
    minSecond: g['min_second'],
    minTotalWillChaos: g['min_total_will_chaos'],
    minTotal: g['min_total'],
  };
}

describe('decidePostRoll parity', () => {
  // Reroll-aware value tables (Phase B) make each EngineContext build ~3-4x
  // heavier; the parity sweep builds one per distinct config, so allow headroom.
  it('matches python action+branch for every record', () => {
    const pool = new OptionPool();
    const byKey = new Map(pool.pool.map(o => [o.key, o]));
    const cache = new Map<string, ReturnType<typeof buildEngineContext>>();
    for (const r of recs) {
      const i = r.inputs;
      const cfg = i.config ?? {};

      // Derive turnsTotal and dpMaxRerolls from rarity+config — NOT from fixture.
      const ckey = JSON.stringify([i.gt, i.fe, i.se, i.opt, i.g, i.rarity, i.config]);
      if (!cache.has(ckey)) {
        const engCtx = buildEngineContext(
          { gemType: i.gt, firstEffect: i.fe, secondEffect: i.se, optimize: i.opt },
          {
            rarity: i.rarity,
            ...goalFieldsFromFixture(i.g),
            minSideCoeff: cfg.min_side_coeff,
            relicCoeff: cfg.relic_coeff ?? null,
            ancientCoeff: cfg.ancient_coeff ?? null,
            relicRerollThreshold: cfg.relic_thr,
            forceRerollNoProgress: cfg.force_reroll,
            endgameRisk: cfg.endgame_risk ?? undefined,
            ignoreSideNodeValues: cfg.ignore_side,
            extraTicket: cfg.extra_ticket ?? null,
          }
        );
        cache.set(ckey, engCtx);
      }
      const engCtx = cache.get(ckey)!;
      const ctx = engCtx._decisionCtx;

      const [w, c, f, s] = i.state;
      const st = new GemState({ will: w, chaos: c, first: f, second: s,
        firstEffect: i.fe, secondEffect: i.se, rerolls: i.rerolls });
      const offers = i.offers.map((k: string) => byKey.get(k)!);
      const d = decidePostRoll(ctx, { state: st, offers, turn: i.turn,
        turnsLeft: i.turns_left, rerolls: i.rerolls, resetAvailable: i.reset_available });
      expect({ action: d.action, branch: d.branch })
        .toEqual({ action: r.expected.action, branch: r.expected.branch });
    }
  }, 180_000);

  // Direct assertion: verify budget formula for specific rarity+config combos.
  it('derives dpMaxRerolls=3 for epic with no extra config', () => {
    const ctx = buildEngineContext(
      { gemType: 'chaos_distortion', firstEffect: 'attack_power', secondEffect: 'ally_damage', optimize: 'dps' },
      { rarity: 'epic' }  // extraTicket undefined (null-armed), relicRerollThreshold 0
    );
    // base = 2 + 1 (extraTicket !== false, undefined counts as armed/on) = 3
    // dpMaxRerolls = 3 + 0 = 3
    expect(ctx.dpMaxRerolls).toBe(3);
  });

  // A goal-met gem must never be reset/abandoned by the no_feasible_offer
  // branch. Reachable only with an unknown gem type (sideValueTable disabled,
  // Branch 0 defers): goal met, every offer would break it irrecoverably.
  it('never resets a goal-met gem on no_feasible_offer (unknown gem type)', () => {
    const pool = new OptionPool();
    const byKey = new Map(pool.pool.map(o => [o.key, o]));
    const engCtx = buildEngineContext(
      { gemType: '', firstEffect: 'attack_power', secondEffect: 'boss_damage', optimize: 'dps' },
      { rarity: 'epic', minWill: 5, minChaos: 5 }
    );
    const st = new GemState({ will: 5, chaos: 5, first: 1, second: 1,
      firstEffect: 'attack_power', secondEffect: 'boss_damage', rerolls: 0 });
    const offers = [byKey.get('will-1')!, byKey.get('chaos-1')!];
    // Last turn, no rerolls, reset ticket in hand: lock in the success.
    const d = decidePostRoll(engCtx._decisionCtx, { state: st, offers,
      turn: 9, turnsLeft: 1, rerolls: 0, resetAvailable: true });
    expect(d.action).toBe('finish');
    // Last turn with unspent rerolls: reroll for a safe hand instead.
    const st2 = new GemState({ will: 5, chaos: 5, first: 1, second: 1,
      firstEffect: 'attack_power', secondEffect: 'boss_damage', rerolls: 2 });
    const d2 = decidePostRoll(engCtx._decisionCtx, { state: st2, offers,
      turn: 9, turnsLeft: 1, rerolls: 2, resetAvailable: true });
    expect(d2.action).toBe('reroll');
  });

  it('derives dpMaxRerolls=3 for rare with relicRerollThreshold=0.3', () => {
    const ctx = buildEngineContext(
      { gemType: 'chaos_distortion', firstEffect: 'attack_power', secondEffect: 'ally_damage', optimize: 'dps' },
      { rarity: 'rare', relicRerollThreshold: 0.3 }
    );
    // base = 1 + 1 (extraTicket undefined) = 2
    // dpMaxRerolls = 2 + 1 (relicRerollThreshold > 0) = 3
    expect(ctx.dpMaxRerolls).toBe(3);
  });
});
