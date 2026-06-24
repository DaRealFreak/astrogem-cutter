import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { decidePostRoll } from '../src/lib/engine/decision';
import { OptionPool } from '../src/lib/engine/pool';
import { GemState } from '../src/lib/engine/models';

// Local context builder mirroring tools/export_golden.py build_ctx().
// (In Task 9 this is replaced by the shared buildEngineContext from engine/index.ts.)
import { buildCtxForTest } from './helpers/buildCtx';

const recs = JSON.parse(readFileSync(
  new URL('./fixtures/decisions.json', import.meta.url), 'utf8')).records;

describe('decidePostRoll parity', () => {
  it('matches python action+branch for every record', () => {
    const pool = new OptionPool();
    const byKey = new Map(pool.pool.map(o => [o.key, o]));
    const cache = new Map<string, any>();
    for (const r of recs) {
      const i = r.inputs;
      const ckey = JSON.stringify([i.gt, i.fe, i.se, i.opt, i.g, i.rarity, i.config]);
      if (!cache.has(ckey)) cache.set(ckey, buildCtxForTest(i, pool));
      const ctx = cache.get(ckey);
      const [w, c, f, s] = i.state;
      const st = new GemState({ will: w, chaos: c, first: f, second: s,
        firstEffect: i.fe, secondEffect: i.se, rerolls: i.rerolls });
      const offers = i.offers.map((k: string) => byKey.get(k)!);
      const d = decidePostRoll(ctx, { state: st, offers, turn: i.turn,
        turnsLeft: i.turns_left, rerolls: i.rerolls, resetAvailable: i.reset_available });
      expect({ action: d.action, branch: d.branch })
        .toEqual({ action: r.expected.action, branch: r.expected.branch });
    }
  });
});
