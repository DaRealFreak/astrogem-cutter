import { describe, it, expect, beforeEach } from 'vitest';
import { syncAdvice, type AdviceSink } from '../../src/lib/app/adviceSync';
import { resetAdviceCache } from '../../src/lib/app/computeAdvice';
import { DEFAULT_CONFIG, type AdvisorStoredConfig } from '../../src/lib/state/config';
import type { DetectionResult } from '../../src/lib/cv/types';
import type { AdvisorOutput } from '../../src/lib/engine';

// order_solidity → domain order_fortitude, whose pool contains both equipped
// effects (attack_power, boss_damage) — a self-consistent gem, so pGoal is a
// meaningful, goal-ordered probability rather than the degenerate 0 you get when
// an effect is outside the gem-type pool.
const complete: DetectionResult = {
  found: true, gemType: 'order_solidity', gemTypeScore: 0.9, willpower: 3, willpowerScore: 0.9,
  chaos: 2, chaosScore: 0.9, firstEffect: 'attack_power', firstEffectScore: 0.9, firstLevel: 1,
  firstLevelScore: 0.9, secondEffect: 'boss_damage', secondEffectScore: 0.9, secondLevel: 1,
  secondLevelScore: 0.9, rerolls: '1', rerollsScore: 0.9, currentStep: 5, stepScore: 0.9,
  totalSteps: 7, rarityScore: 0.9,
  options: [
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'chaos', nameScore: 0.9, deltaKey: '1_line_+1', deltaScore: 0.9 },
    { nameKey: 'will', nameScore: 0.9, deltaKey: '1_line_+2', deltaScore: 0.9 },
    { nameKey: 'view', nameScore: 0.9, deltaKey: 'reroll+1', deltaScore: 0.9 },
  ],
};

// Current will+chaos = 5. comb4 is already met (pGoal = 1.0); comb8 is a real
// stretch (pGoal ≈ 0.52) — so a recompute under the harder goal must drop pGoal.
const easyGoal: AdvisorStoredConfig = { ...DEFAULT_CONFIG, goalMode: 'combined', minWillChaosTotal: 4 };
const harderGoal: AdvisorStoredConfig = { ...DEFAULT_CONFIG, goalMode: 'combined', minWillChaosTotal: 8 };

function recordingSink() {
  const applied: AdvisorOutput[] = [];
  const observed: AdvisorOutput[] = [];
  const sink: AdviceSink = {
    applyAdvice: (_det, output) => applied.push(output),
    observeTurn: (_det, output) => observed.push(output),
  };
  return { sink, applied, observed };
}

describe('syncAdvice', () => {
  beforeEach(() => resetAdviceCache());

  it('applies advice and logs a turn for a fresh detection', () => {
    const { sink, applied, observed } = recordingSink();
    const ok = syncAdvice(complete, easyGoal, false, false, true, sink);
    expect(ok).toBe(true);
    expect(applied).toHaveLength(1);
    expect(observed).toHaveLength(1);
  });

  it('recomputes advice on a config change WITHOUT logging a turn', () => {
    const { sink, applied, observed } = recordingSink();
    // Fresh detection logs a turn under the easy goal.
    syncAdvice(complete, easyGoal, false, false, true, sink);
    // Config changes (goal raised); same reading → recompute only, no new turn.
    const ok = syncAdvice(complete, harderGoal, false, false, false, sink);
    expect(ok).toBe(true);
    expect(observed).toHaveLength(1); // still one turn — no phantom log entry from the recompute
    expect(applied).toHaveLength(2);  // but advice WAS re-applied
    // The recomputed advice reflects the harder goal, proving the new config was used.
    expect(applied[1].pGoal).toBeLessThan(applied[0].pGoal);
  });

  it('produces no advice and no side effects for an incomplete detection', () => {
    const { sink, applied, observed } = recordingSink();
    const ok = syncAdvice({ ...complete, found: false }, easyGoal, false, false, true, sink);
    expect(ok).toBe(false);
    expect(applied).toHaveLength(0);
    expect(observed).toHaveLength(0);
  });

  it('forwards ticketSpent so an already-used ticket is not lent', () => {
    const cfg: AdvisorStoredConfig = { ...DEFAULT_CONFIG, relicRerollThreshold: 0.01 };
    const lent = recordingSink();
    syncAdvice(complete, cfg, false, false, true, lent.sink);
    expect(lent.applied[0].ticket!.lent).toBe(true);

    const spent = recordingSink();
    syncAdvice(complete, cfg, false, true, true, spent.sink);
    expect(spent.applied[0].ticket!.lent).toBe(false);
    expect(spent.applied[0].ticket!.spent).toBe(true);
  });
});
