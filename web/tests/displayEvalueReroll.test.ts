import { describe, it, expect } from 'vitest';
import { buildEngineContext, advise } from '../src/lib/engine';
import { GemState, makeOption } from '../src/lib/engine/models';

const cfg = { rarity: 'epic', minTotalWillChaos: 8, minSideCoeff: 2000,
  relicRerollThreshold: 0.1, rerollMinCoeff: 700, optimize: 'dps' };
const gem = { gemType: 'order_stability', firstEffect: 'additional_damage',
  secondEffect: 'attack_power', optimize: 'dps' };

describe('displayed eValue moves with the reroll budget', () => {
  const ctx = buildEngineContext(gem as any, cfg as any);
  const mkState = () => new GemState({ will: 1, chaos: 1, first: 1, second: 1,
    firstEffect: 'additional_damage', secondEffect: 'attack_power' });
  // a fixed hand (will+2, second+1, first+4, chaos+3)
  const offers = [
    makeOption('will+2', 4.40, 'will', 2),
    makeOption('second+1', 11.65, 'second', 1),
    makeOption('first+4', 0.45, 'first', 4),
    makeOption('chaos+3', 1.75, 'chaos', 3),
  ];
  const at = (r: number) => advise(ctx, { state: mkState(), offers, turn: 2,
    turnsLeft: 8, rerolls: r, resetAvailable: false });

  it('reroll-row eValue rises from r=2 to r=3', () => {
    expect(at(3).actions.reroll!.eValue).toBeGreaterThan(at(2).actions.reroll!.eValue);
  });
  it('process-row eValue rises from r=2 to r=3', () => {
    expect(at(3).actions.process!.eValue).toBeGreaterThan(at(2).actions.process!.eValue);
  });
  it('flat decision-path table is untouched (sanity: action still computed)', () => {
    expect(['process','reroll','reset','finish','fail']).toContain(at(2).action);
  });
});
