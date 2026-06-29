// Port of arkgrid/probability.py:10-852 (GoalProbabilityTable only).
//
// Faithful transcription of the backward-induction DP. SideValueTable
// (probability.py:854+) is Task 7. The bis-only mode (_build_bis,
// lookup_bis_averaged, lookup_after_effect_change) is a documented no-op
// and is intentionally NOT ported.
//
// The Python _dp is a dict keyed by tuples; here it is a Map<string, number>
// with a comma-joined key builder. The key arity must match Python's tuple
// shapes per mode EXACTLY:
//   effect-aware + reroll: (w, c, f, s, fi, si, r, tl)
//   effect-aware:          (w, c, f, s, fi, si, tl)
//   reroll:                (w, c, f, s, r, tl)
//   standard:              (w, c, f, s, tl)

import { DPS_COEFF, DPS_EFFECTS, GEM_TYPES, SUPPORT_COEFF, SUPPORT_EFFECTS, fusionAvgCoeff } from './constants';
import type { Option, LastTurnGoal } from './models';
import { GemState } from './models';
import { OptionPool } from './pool';

export interface GoalTableOpts {
  sideCoeffFirst?: number;
  sideCoeffSecond?: number;
  minSideCoeff?: number;
  earlyFinish?: boolean;
  maxRerolls?: number;
  effectAware?: boolean;
  gemType?: string;
  optimize?: string;
}

// String key builder for the DP map (mirrors Python tuple keys by value).
const key = (...nums: number[]): string => nums.join(',');

const clampLevel = (x: number): number => Math.min(5, Math.max(1, x));

const SQRT2 = Math.sqrt(2.0);
const INV_SQRT_2PI = 1.0 / Math.sqrt(2.0 * Math.PI);

// A&S 7.1.26 erf — identical to arkgrid/probability.py::_erf for cross-language parity.
function erf(x: number): number {
  const sign = x >= 0 ? 1.0 : -1.0;
  const ax = Math.abs(x);
  const t = 1.0 / (1.0 + 0.3275911 * ax);
  const y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
    - 0.284496736) * t + 0.254829592) * t * Math.exp(-ax * ax);
  return sign * y;
}
function normCdf(x: number): number { return 0.5 * (1.0 + erf(x / SQRT2)); }
function normPdf(x: number): number { return INV_SQRT_2PI * Math.exp(-0.5 * x * x); }
function eMax(mu: number, sd: number, t: number): number {
  if (sd <= 0.0) return mu > t ? mu : t;
  const d = (mu - t) / sd;
  return t + (mu - t) * normCdf(d) + sd * normPdf(d);
}

// Effect-aware option-level transition entry:
//   [prob, optionKey, optionKind, nw, nc, nf, ns, viewDelta]
type EaTransEntry = [number, string, string, number, number, number, number, number];

// Reroll-aware (non-effect) transition entry:
//   [prob, nw, nc, nf, ns, viewDelta]
type RerollTransEntry = [number, number, number, number, number, number];

export class GoalProbabilityTable {
  readonly goal: LastTurnGoal;
  readonly maxTurns: number;
  readonly pool: OptionPool;
  readonly effectAware: boolean;

  private readonly _sideCoeffFirst: number;
  private readonly _sideCoeffSecond: number;
  private readonly _minSideCoeff: number;
  private readonly earlyFinish: boolean;
  private readonly _maxRerolls: number;
  private readonly _gemType: string;
  private readonly _optimize: string;

  private _effectTuple: readonly string[];
  private _effectCoeffs: readonly number[];
  // change-effect destinations keyed by "fi,si"
  private _changeDests: Map<string, number[]>;

  private _dp: Map<string, number>;

  constructor(goal: LastTurnGoal, maxTurns: number, pool: OptionPool, opts?: GoalTableOpts) {
    this.goal = goal;
    this.maxTurns = maxTurns;
    this.pool = pool;

    const effectAware = opts?.effectAware ?? false;
    const gemType = opts?.gemType ?? '';
    const optimize = opts?.optimize ?? 'dps';

    this.effectAware = effectAware && gemType in GEM_TYPES;
    this._sideCoeffFirst = opts?.sideCoeffFirst ?? 0;
    this._sideCoeffSecond = opts?.sideCoeffSecond ?? 0;
    this._minSideCoeff = opts?.minSideCoeff ?? 0;
    this.earlyFinish = opts?.earlyFinish ?? false;
    this._maxRerolls = opts?.maxRerolls ?? 0;
    this._gemType = gemType;
    this._optimize = optimize;

    // Precompute per-effect coefficient table indexed by the gem's
    // 4-effect tuple. Non-target effects contribute 0.
    if (this.effectAware) {
      // effectAware implies gemType in GEM_TYPES, so the lookup is defined.
      const effects = GEM_TYPES[gemType]!;
      const coeffMap = optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
      const targetSet = optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
      this._effectTuple = effects;
      this._effectCoeffs = effects.map((e) => (targetSet.has(e) ? (coeffMap[e] ?? 0) : 0));
      // Precompute change-effect destinations for each (fi, si) pair.
      this._changeDests = new Map();
      for (let fi = 0; fi < 4; fi++) {
        for (let si = 0; si < 4; si++) {
          if (fi === si) continue;
          const dests: number[] = [];
          for (let i = 0; i < 4; i++) {
            if (i !== fi && i !== si) dests.push(i);
          }
          this._changeDests.set(key(fi, si), dests);
        }
      }
    } else {
      this._effectTuple = [];
      this._effectCoeffs = [];
      this._changeDests = new Map();
    }

    this._dp = new Map();
    if (this.effectAware) {
      if (this._maxRerolls > 0) {
        this._buildEffectAwareWithRerolls();
      } else {
        this._buildEffectAware();
      }
    } else if (this._maxRerolls > 0) {
      // bis_only is a no-op in this port, so the `not self.bis_only` guard
      // is always satisfied for the non-effect-aware reroll build.
      this._buildWithRerolls();
    } else {
      this._build();
    }
  }

  // ------------------------------------------------------------------
  // Transition helpers (option probability assignment)
  // ------------------------------------------------------------------

  // Per-option applied probability (single-draw approximation), paired with
  // its option. Returning pairs avoids index-based array access (which is
  // `T | undefined` under noUncheckedIndexedAccess).
  private _optionProbs(eligible: Option[]): [Option, number][] {
    let totalW = 0;
    for (const o of eligible) totalW += o.weight;
    return eligible.map((o) => [o, o.weight / totalW]);
  }

  private _eligible(w: number, c: number, f: number, s: number, turn: number, turnsLeft: number): Option[] {
    const state = new GemState({ will: w, chaos: c, first: f, second: s });
    return this.pool.pool.filter((o) => this.pool.eligible(o, state, turn, turnsLeft));
  }

  private _coeffSatisfied(f: number, s: number, ft = 1, st = 1): boolean {
    if (this._minSideCoeff <= 0) return true;
    const coeffTotal = this._sideCoeffFirst * f * ft + this._sideCoeffSecond * s * st;
    return coeffTotal >= this._minSideCoeff;
  }

  // ------------------------------------------------------------------
  // Standard transitions and build
  // ------------------------------------------------------------------

  private _transitions(
    w: number,
    c: number,
    f: number,
    s: number,
    turn: number,
    turnsLeft: number
  ): Map<string, number> {
    const eligible = this._eligible(w, c, f, s, turn, turnsLeft);
    const dest = new Map<string, number>();
    if (eligible.length === 0) {
      dest.set(key(w, c, f, s), 1.0);
      return dest;
    }
    for (const [o, p] of this._optionProbs(eligible)) {
      let nw = w, nc = c, nf = f, ns = s;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      // cost/view/other/maintain -> no stat change
      const k = key(nw, nc, nf, ns);
      dest.set(k, (dest.get(k) ?? 0) + p);
    }
    return dest;
  }

  private _build(): void {
    const dp = this._dp;
    const mt = this.maxTurns;

    // Base case: turns_left == 0
    for (let w = 1; w <= 5; w++) {
      for (let c = 1; c <= 5; c++) {
        for (let f = 1; f <= 5; f++) {
          for (let s = 1; s <= 5; s++) {
            const sat = this.goal.satisfied(w, c, f, s) && this._coeffSatisfied(f, s) ? 1.0 : 0.0;
            dp.set(key(w, c, f, s, 0), sat);
          }
        }
      }
    }

    // Precompute transition tables for three turn types.
    const transCache: Record<string, Map<string, Map<string, number>>> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      const cache = new Map<string, Map<string, number>>();
      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              cache.set(key(w, c, f, s), this._transitions(w, c, f, s, turn, tl));
            }
          }
        }
      }
      transCache[label] = cache;
    }

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let tc: Map<string, Map<string, number>>;
      if (turnNumber === 1) tc = transCache['first']!;
      else if (tl === 1) tc = transCache['last']!;
      else tc = transCache['middle']!;

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              if (this.earlyFinish && this.goal.satisfied(w, c, f, s) && this._coeffSatisfied(f, s)) {
                dp.set(key(w, c, f, s, tl), 1.0);
                continue;
              }
              let val = 0.0;
              const trans = tc.get(key(w, c, f, s))!;
              for (const [destKey, p] of trans) {
                // destKey is "nw,nc,nf,ns"; append tl-1 for the DP lookup.
                val += p * dp.get(`${destKey},${tl - 1}`)!;
              }
              dp.set(key(w, c, f, s, tl), val);
            }
          }
        }
      }
    }
  }

  // ------------------------------------------------------------------
  // Reroll-aware transitions and build
  // ------------------------------------------------------------------

  private _transitionsReroll(
    w: number,
    c: number,
    f: number,
    s: number,
    turn: number,
    turnsLeft: number
  ): RerollTransEntry[] {
    const eligible = this._eligible(w, c, f, s, turn, turnsLeft);
    if (eligible.length === 0) {
      return [[1.0, w, c, f, s, 0]];
    }
    const result: RerollTransEntry[] = [];
    for (const [o, p] of this._optionProbs(eligible)) {
      let nw = w, nc = c, nf = f, ns = s;
      let vd = 0;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      else if (o.kind === 'view') vd = o.delta;
      // cost/other/maintain -> no stat change, no view delta
      result.push([p, nw, nc, nf, ns, vd]);
    }
    return result;
  }

  private _buildWithRerolls(): void {
    const dp = this._dp;
    const mt = this.maxTurns;
    const maxR = this._maxRerolls;

    // Base case: turns_left == 0
    for (let w = 1; w <= 5; w++) {
      for (let c = 1; c <= 5; c++) {
        for (let f = 1; f <= 5; f++) {
          for (let s = 1; s <= 5; s++) {
            const sat = this.goal.satisfied(w, c, f, s) && this._coeffSatisfied(f, s) ? 1.0 : 0.0;
            for (let r = 0; r <= maxR; r++) {
              dp.set(key(w, c, f, s, r, 0), sat);
            }
          }
        }
      }
    }

    // Precompute transition tables (with view deltas)
    const transCache: Record<string, Map<string, RerollTransEntry[]>> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      const cache = new Map<string, RerollTransEntry[]>();
      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              cache.set(key(w, c, f, s), this._transitionsReroll(w, c, f, s, turn, tl));
            }
          }
        }
      }
      transCache[label] = cache;
    }

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let tc: Map<string, RerollTransEntry[]>;
      if (turnNumber === 1) tc = transCache['first']!;
      else if (tl === 1) tc = transCache['last']!;
      else tc = transCache['middle']!;

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const trans = tc.get(key(w, c, f, s))!;
              for (let r = 0; r <= maxR; r++) {
                if (this.earlyFinish && this.goal.satisfied(w, c, f, s) && this._coeffSatisfied(f, s)) {
                  dp.set(key(w, c, f, s, r, tl), 1.0);
                  continue;
                }

                if (r > 0 && turnNumber !== 1) {
                  const rerollVal = dp.get(key(w, c, f, s, r - 1, tl))!;
                  let val = 0.0;
                  for (const [p, nw, nc, nf, ns, vd] of trans) {
                    const nr = Math.min(maxR, r + vd);
                    const post = dp.get(key(nw, nc, nf, ns, nr, tl - 1))!;
                    val += p * Math.max(post, rerollVal);
                  }
                  dp.set(key(w, c, f, s, r, tl), val);
                } else {
                  let val = 0.0;
                  for (const [p, nw, nc, nf, ns, vd] of trans) {
                    const nr = Math.min(maxR, r + vd);
                    val += p * dp.get(key(nw, nc, nf, ns, nr, tl - 1))!;
                  }
                  dp.set(key(w, c, f, s, r, tl), val);
                }
              }
            }
          }
        }
      }
    }
  }

  // ------------------------------------------------------------------
  // Effect-aware transitions and build
  // ------------------------------------------------------------------

  private _effectAwareTransitions(
    w: number,
    c: number,
    f: number,
    s: number,
    turn: number,
    turnsLeft: number
  ): EaTransEntry[] {
    const eligible = this._eligible(w, c, f, s, turn, turnsLeft);
    if (eligible.length === 0) {
      return [[1.0, '', '', w, c, f, s, 0]];
    }
    const result: EaTransEntry[] = [];
    for (const [o, p] of this._optionProbs(eligible)) {
      let nw = w, nc = c, nf = f, ns = s;
      let vd = 0;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      else if (o.kind === 'view') vd = o.delta;
      result.push([p, o.key, o.kind, nw, nc, nf, ns, vd]);
    }
    return result;
  }

  private _coeffSatisfiedIdx(f: number, s: number, fi: number, si: number): boolean {
    if (this._minSideCoeff <= 0) return true;
    const coeffTotal = this._effectCoeffs[fi]! * f + this._effectCoeffs[si]! * s;
    return coeffTotal >= this._minSideCoeff;
  }

  private _validEffectPairs(): [number, number][] {
    const pairs: [number, number][] = [];
    for (let fi = 0; fi < 4; fi++) {
      for (let si = 0; si < 4; si++) {
        if (fi !== si) pairs.push([fi, si]);
      }
    }
    return pairs;
  }

  private _buildEaTransCache(): Record<string, Map<string, EaTransEntry[]>> {
    const mt = this.maxTurns;
    const transCache: Record<string, Map<string, EaTransEntry[]>> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      const cache = new Map<string, EaTransEntry[]>();
      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              cache.set(key(w, c, f, s), this._effectAwareTransitions(w, c, f, s, turn, tl));
            }
          }
        }
      }
      transCache[label] = cache;
    }
    return transCache;
  }

  private _build_effect_aware_turnTable(turnNumber: number, tl: number, transCache: Record<string, Map<string, EaTransEntry[]>>): Map<string, EaTransEntry[]> {
    if (turnNumber === 1) return transCache['first']!;
    if (tl === 1) return transCache['last']!;
    return transCache['middle']!;
  }

  private _buildEffectAware(): void {
    const dp = this._dp;
    const mt = this.maxTurns;
    const validPairs = this._validEffectPairs();

    // Base case: turns_left == 0
    for (let w = 1; w <= 5; w++) {
      for (let c = 1; c <= 5; c++) {
        for (let f = 1; f <= 5; f++) {
          for (let s = 1; s <= 5; s++) {
            const goalSat = this.goal.satisfied(w, c, f, s);
            for (const [fi, si] of validPairs) {
              const sat = goalSat && this._coeffSatisfiedIdx(f, s, fi, si) ? 1.0 : 0.0;
              dp.set(key(w, c, f, s, fi, si, 0), sat);
            }
          }
        }
      }
    }

    const transCache = this._buildEaTransCache();

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      const tc = this._build_effect_aware_turnTable(turnNumber, tl, transCache);

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const trans = tc.get(key(w, c, f, s))!;
              const goalSat = this.goal.satisfied(w, c, f, s);
              for (const [fi, si] of validPairs) {
                if (this.earlyFinish && goalSat && this._coeffSatisfiedIdx(f, s, fi, si)) {
                  dp.set(key(w, c, f, s, fi, si, tl), 1.0);
                  continue;
                }
                const dests = this._changeDests.get(key(fi, si))!;
                const nDests = dests.length; // always 2
                let val = 0.0;
                for (const [p, optKey, , nw, nc, nf, ns] of trans) {
                  if (optKey === 'change_first_effect') {
                    for (const newFi of dests) {
                      val += (p / nDests) * dp.get(key(nw, nc, nf, ns, newFi, si, tl - 1))!;
                    }
                  } else if (optKey === 'change_second_effect') {
                    for (const newSi of dests) {
                      val += (p / nDests) * dp.get(key(nw, nc, nf, ns, fi, newSi, tl - 1))!;
                    }
                  } else {
                    val += p * dp.get(key(nw, nc, nf, ns, fi, si, tl - 1))!;
                  }
                }
                dp.set(key(w, c, f, s, fi, si, tl), val);
              }
            }
          }
        }
      }
    }
  }

  private _buildEffectAwareWithRerolls(): void {
    const dp = this._dp;
    const mt = this.maxTurns;
    const maxR = this._maxRerolls;
    const validPairs = this._validEffectPairs();

    // Base case: turns_left == 0
    for (let w = 1; w <= 5; w++) {
      for (let c = 1; c <= 5; c++) {
        for (let f = 1; f <= 5; f++) {
          for (let s = 1; s <= 5; s++) {
            const goalSat = this.goal.satisfied(w, c, f, s);
            for (const [fi, si] of validPairs) {
              const sat = goalSat && this._coeffSatisfiedIdx(f, s, fi, si) ? 1.0 : 0.0;
              for (let r = 0; r <= maxR; r++) {
                dp.set(key(w, c, f, s, fi, si, r, 0), sat);
              }
            }
          }
        }
      }
    }

    const transCache = this._buildEaTransCache();

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      const tc = this._build_effect_aware_turnTable(turnNumber, tl, transCache);

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const trans = tc.get(key(w, c, f, s))!;
              const goalSat = this.goal.satisfied(w, c, f, s);
              for (const [fi, si] of validPairs) {
                const dests = this._changeDests.get(key(fi, si))!;
                const nDests = dests.length;

                // post_val: V at a transition destination, routing
                // change_effect uniformly across non-equipped pool members.
                const postVal = (
                  optKey: string,
                  nw: number,
                  nc: number,
                  nf: number,
                  ns: number,
                  nr: number
                ): number => {
                  if (optKey === 'change_first_effect') {
                    let v = 0.0;
                    for (const newFi of dests) {
                      v += dp.get(key(nw, nc, nf, ns, newFi, si, nr, tl - 1))! / nDests;
                    }
                    return v;
                  }
                  if (optKey === 'change_second_effect') {
                    let v = 0.0;
                    for (const newSi of dests) {
                      v += dp.get(key(nw, nc, nf, ns, fi, newSi, nr, tl - 1))! / nDests;
                    }
                    return v;
                  }
                  return dp.get(key(nw, nc, nf, ns, fi, si, nr, tl - 1))!;
                };

                for (let r = 0; r <= maxR; r++) {
                  if (this.earlyFinish && goalSat && this._coeffSatisfiedIdx(f, s, fi, si)) {
                    dp.set(key(w, c, f, s, fi, si, r, tl), 1.0);
                    continue;
                  }

                  if (r > 0 && turnNumber !== 1) {
                    const rerollVal = dp.get(key(w, c, f, s, fi, si, r - 1, tl))!;
                    let val = 0.0;
                    for (const [p, optKey, , nw, nc, nf, ns, vd] of trans) {
                      const nr = Math.min(maxR, r + vd);
                      const post = postVal(optKey, nw, nc, nf, ns, nr);
                      val += p * Math.max(post, rerollVal);
                    }
                    dp.set(key(w, c, f, s, fi, si, r, tl), val);
                  } else {
                    let val = 0.0;
                    for (const [p, optKey, , nw, nc, nf, ns, vd] of trans) {
                      const nr = Math.min(maxR, r + vd);
                      val += p * postVal(optKey, nw, nc, nf, ns, nr);
                    }
                    dp.set(key(w, c, f, s, fi, si, r, tl), val);
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  private _effectIndices(state: GemState): [number, number] | null {
    const fi = this._effectTuple.indexOf(state.firstEffect);
    const si = this._effectTuple.indexOf(state.secondEffect);
    if (fi === -1 || si === -1) return null;
    if (fi === si) return null;
    return [fi, si];
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  /** Reroll budget the table was built with (mirrors Python `_max_rerolls`,
   *  read by `decision.compute_post_roll_metrics`). */
  get maxRerolls(): number {
    return this._maxRerolls;
  }

  lookup(state: GemState, turnsLeft: number, rerolls?: number): number {
    if (this.effectAware) {
      const idx = this._effectIndices(state);
      if (idx === null) return 0.0;
      const [fi, si] = idx;
      const w = state.will, c = state.chaos, f = state.first, s = state.second;
      if (this._maxRerolls > 0) {
        const r = Math.min(this._maxRerolls, rerolls ?? 0);
        return this._dp.get(key(w, c, f, s, fi, si, r, turnsLeft)) ?? 0.0;
      }
      return this._dp.get(key(w, c, f, s, fi, si, turnsLeft)) ?? 0.0;
    }
    if (this._maxRerolls > 0) {
      const r = Math.min(this._maxRerolls, rerolls ?? 0);
      return this._dp.get(key(state.will, state.chaos, state.first, state.second, r, turnsLeft)) ?? 0.0;
    }
    return this._dp.get(key(state.will, state.chaos, state.first, state.second, turnsLeft)) ?? 0.0;
  }

  expectedProbAfterClick(
    state: GemState,
    offers: Option[],
    turnsLeftAfter: number,
    rerolls?: number
  ): number {
    if (offers.length === 0) return 0.0;
    let total = 0.0;
    for (const o of offers) {
      const nw = o.kind === 'will' ? clampLevel(state.will + o.delta) : state.will;
      const nc = o.kind === 'chaos' ? clampLevel(state.chaos + o.delta) : state.chaos;
      const nf = o.kind === 'first' ? clampLevel(state.first + o.delta) : state.first;
      const ns = o.kind === 'second' ? clampLevel(state.second + o.delta) : state.second;

      if (this.effectAware) {
        const idx = this._effectIndices(state);
        if (idx === null) continue;
        const [fi, si] = idx;
        const r = rerolls ?? 0;
        const vd = o.kind === 'view' ? o.delta : 0;
        const nr = this._maxRerolls > 0 ? Math.min(this._maxRerolls, r + vd) : 0;
        const dests = this._changeDests.get(key(fi, si))!;
        const nDests = dests.length;
        if (o.key === 'change_first_effect') {
          let v = 0.0;
          for (const newFi of dests) {
            v += this._dpLookupEa(nw, nc, nf, ns, newFi, si, nr, turnsLeftAfter) / nDests;
          }
          total += v;
        } else if (o.key === 'change_second_effect') {
          let v = 0.0;
          for (const newSi of dests) {
            v += this._dpLookupEa(nw, nc, nf, ns, fi, newSi, nr, turnsLeftAfter) / nDests;
          }
          total += v;
        } else {
          total += this._dpLookupEa(nw, nc, nf, ns, fi, si, nr, turnsLeftAfter);
        }
      } else if (this._maxRerolls > 0) {
        const r = rerolls ?? 0;
        const vd = o.kind === 'view' ? o.delta : 0;
        const nr = Math.min(this._maxRerolls, r + vd);
        total += this._dp.get(key(nw, nc, nf, ns, nr, turnsLeftAfter)) ?? 0.0;
      } else {
        total += this._dp.get(key(nw, nc, nf, ns, turnsLeftAfter)) ?? 0.0;
      }
    }
    return total / offers.length;
  }

  private _dpLookupEa(
    w: number,
    c: number,
    f: number,
    s: number,
    fi: number,
    si: number,
    r: number,
    tl: number
  ): number {
    if (this._maxRerolls > 0) {
      return this._dp.get(key(w, c, f, s, fi, si, r, tl)) ?? 0.0;
    }
    return this._dp.get(key(w, c, f, s, fi, si, tl)) ?? 0.0;
  }

  shouldRerollDp(state: GemState, offers: Option[], turnsLeft: number, rerolls: number): boolean {
    if (this._maxRerolls <= 0 || rerolls <= 0) return false;
    const keepVal = this.expectedProbAfterClick(state, offers, turnsLeft - 1, rerolls);
    const rerollVal = this.lookup(state, turnsLeft, rerolls - 1);
    return rerollVal > keepVal;
  }
}

// ======================================================================
// SideValueTable (probability.py:854-1155)
// ======================================================================
// Expected final *gem value* under optimal finish / process play.
// A parallel DP to GoalProbabilityTable consulted once the goal is met
// to decide finish-vs-continue. The stored value is a coefficient, not
// a probability:
//   gem_value(state) = side_coeff(state) + tier_bonus(total_points)
// with goal-broken states valued 0. Backward induction takes
// max(finishNow=gemValue, processEV). When maxRerolls > 0 the state
// carries the reroll count and _buildReroll prices a keep-vs-reroll
// choice via a variance-aware Gaussian E[max(handEV, threshold)]
// (Phase A/B); maxRerolls === 0 builds the flat table.

export interface SideValueOpts {
  optimize?: string;
  minSideCoeff?: number;
  relicCoeff?: number | null;
  ancientCoeff?: number | null;
  valueMode?: 'side' | 'will_chaos' | 'grade_only';
  maxRerolls?: number;
  /** Policy-evaluation mode: report the `valueMode` value expected under the
   *  will+chaos decision policy (a coupled flat DP), not the value-iteration
   *  upper bound. Used for the displayed eValue under ignoreSideNodeValues. */
  policyValueMode?: 'will_chaos';
}

// SideValue-only transition entry (no reroll/view-delta bookkeeping):
//   [prob, optionKey, optionKind, nw, nc, nf, ns]
type SvTransEntry = [number, string, string, number, number, number, number];

export class SideValueTable {
  readonly enabled: boolean;
  readonly relicCoeff: number;
  readonly ancientCoeff: number;

  private readonly _goal: LastTurnGoal;
  private readonly _maxTurns: number;
  private readonly _pool: OptionPool;
  private readonly _gemType: string;
  private readonly _optimize: string;
  private readonly _minSideCoeff: number;
  private readonly _valueMode: 'side' | 'will_chaos' | 'grade_only';
  private readonly _maxRerolls: number;
  private readonly _policyValueMode: 'will_chaos' | null;

  private _effectTuple: readonly string[];
  private _effectCoeffs: readonly number[];
  private _changeDests: Map<string, number[]>;
  private _dp: Map<string, number>;

  constructor(
    goal: LastTurnGoal,
    maxTurns: number,
    pool: OptionPool,
    gemType: string,
    opts?: SideValueOpts
  ) {
    this._goal = goal;
    this._maxTurns = maxTurns;
    this._pool = pool;
    this._gemType = gemType;
    this._optimize = opts?.optimize ?? 'dps';
    this._minSideCoeff = opts?.minSideCoeff ?? 0;
    this._valueMode = opts?.valueMode ?? 'side';
    this._policyValueMode = opts?.policyValueMode ?? null;
    // Policy-evaluation tables are flat: the will_chaos policy they follow
    // has a discrete per-state finish-vs-continue choice, which the
    // variance-aware reroll model (a continuous E[max]) does not expose.
    this._maxRerolls = this._policyValueMode != null ? 0 : (opts?.maxRerolls ?? 0);

    this.enabled = gemType in GEM_TYPES;

    if (this.enabled) {
      // Default the tier weights to the fusion-derived average gem
      // coefficient for this gem type; an explicit value (incl. 0) overrides.
      this.relicCoeff = opts?.relicCoeff != null
        ? opts.relicCoeff
        : fusionAvgCoeff(gemType, this._optimize, 'relic');
      this.ancientCoeff = opts?.ancientCoeff != null
        ? opts.ancientCoeff
        : fusionAvgCoeff(gemType, this._optimize, 'ancient');
    } else {
      // Table self-disables when the gem type is unknown.
      this.relicCoeff = opts?.relicCoeff ?? 0;
      this.ancientCoeff = opts?.ancientCoeff ?? 0;
    }

    if (this._valueMode === 'will_chaos') {
      // will/chaos value ignores grade entirely.
      (this as any).relicCoeff = 0;
      (this as any).ancientCoeff = 0;
    }

    this._dp = new Map();

    if (!this.enabled) {
      this._effectTuple = [];
      this._effectCoeffs = [];
      this._changeDests = new Map();
      return;
    }

    const effects = GEM_TYPES[gemType]!;
    const coeffMap = this._optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
    const targetSet = this._optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
    this._effectTuple = effects;
    this._effectCoeffs = effects.map((e) => (targetSet.has(e) ? (coeffMap[e] ?? 0) : 0));
    this._changeDests = new Map();
    for (let fi = 0; fi < 4; fi++) {
      for (let si = 0; si < 4; si++) {
        if (fi === si) continue;
        const dests: number[] = [];
        for (let i = 0; i < 4; i++) {
          if (i !== fi && i !== si) dests.push(i);
        }
        this._changeDests.set(key(fi, si), dests);
      }
    }

    if (this._policyValueMode != null) {
      this._buildPolicyEval();
    } else if (this._maxRerolls > 0) {
      this._buildReroll();
    } else {
      this._build();
    }
  }

  // -- value model -------------------------------------------------

  private _tierBonus(totalPoints: number): number {
    if (totalPoints >= 19) return this.ancientCoeff;
    if (totalPoints >= 16) return this.relicCoeff;
    return 0;
  }

  private _gemValueIdx(w: number, c: number, f: number, s: number, fi: number, si: number): number {
    if (!this._goal.satisfied(w, c, f, s)) return 0.0;
    if (this._valueMode === 'will_chaos') {
      return w + c;
    }
    if (this._valueMode === 'grade_only') {
      return this._tierBonus(w + c + f + s);
    }
    // 'side' mode
    const coeff = this._effectCoeffs[fi]! * f + this._effectCoeffs[si]! * s;
    if (this._minSideCoeff > 0 && coeff < this._minSideCoeff) return 0.0;
    return coeff + this._tierBonus(w + c + f + s);
  }

  private _effectIndices(state: GemState): [number, number] | null {
    const fi = this._effectTuple.indexOf(state.firstEffect);
    const si = this._effectTuple.indexOf(state.secondEffect);
    if (fi === -1 || si === -1) return null;
    if (fi === si) return null;
    return [fi, si];
  }

  // -- transitions -------------------------------------------------

  private _transitions(
    w: number,
    c: number,
    f: number,
    s: number,
    turn: number,
    turnsLeft: number
  ): SvTransEntry[] {
    const state = new GemState({ will: w, chaos: c, first: f, second: s });
    const eligible = this._pool.pool.filter((o) => this._pool.eligible(o, state, turn, turnsLeft));
    if (eligible.length === 0) {
      return [[1.0, '', '', w, c, f, s]];
    }
    let totalW = 0;
    for (const o of eligible) totalW += o.weight;
    const result: SvTransEntry[] = [];
    for (const o of eligible) {
      const p = o.weight / totalW;
      let nw = w, nc = c, nf = f, ns = s;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      // cost/view/other/maintain -> no stat change
      result.push([p, o.key, o.kind, nw, nc, nf, ns]);
    }
    return result;
  }

  // V at a transition destination *in map `dpd`*, routing change_effect
  // uniformly across the two non-equipped pool members. Parameterizing the
  // map lets _buildPolicyEval read its two coupled tables (policy, display).
  private _postValIn(
    dpd: Map<string, number>,
    optKey: string,
    nw: number,
    nc: number,
    nf: number,
    ns: number,
    fi: number,
    si: number,
    dests: number[],
    nd: number,
    tl: number
  ): number {
    if (optKey === 'change_first_effect') {
      let v = 0.0;
      for (const d of dests) {
        v += (dpd.get(key(nw, nc, nf, ns, d, si, tl)) ?? 0.0);
      }
      return v / nd;
    }
    if (optKey === 'change_second_effect') {
      let v = 0.0;
      for (const d of dests) {
        v += (dpd.get(key(nw, nc, nf, ns, fi, d, tl)) ?? 0.0);
      }
      return v / nd;
    }
    return dpd.get(key(nw, nc, nf, ns, fi, si, tl)) ?? 0.0;
  }

  private _postVal(
    optKey: string,
    nw: number,
    nc: number,
    nf: number,
    ns: number,
    fi: number,
    si: number,
    dests: number[],
    nd: number,
    tl: number
  ): number {
    return this._postValIn(this._dp, optKey, nw, nc, nf, ns, fi, si, dests, nd, tl);
  }

  private _build(): void {
    const dp = this._dp;
    const mt = this._maxTurns;
    const validPairs: [number, number][] = [];
    for (let fi = 0; fi < 4; fi++) {
      for (let si = 0; si < 4; si++) {
        if (fi !== si) validPairs.push([fi, si]);
      }
    }

    // Terminal: turns_left == 0 -> gem_value.
    for (let w = 1; w <= 5; w++) {
      for (let c = 1; c <= 5; c++) {
        for (let f = 1; f <= 5; f++) {
          for (let s = 1; s <= 5; s++) {
            for (const [fi, si] of validPairs) {
              dp.set(key(w, c, f, s, fi, si, 0), this._gemValueIdx(w, c, f, s, fi, si));
            }
          }
        }
      }
    }

    // Option-level transition cache (independent of fi/si).
    // Mirror Python's three-label cache strategy.
    const transCache: Record<string, Map<string, SvTransEntry[]>> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      const cache = new Map<string, SvTransEntry[]>();
      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              cache.set(key(w, c, f, s), this._transitions(w, c, f, s, turn, tl));
            }
          }
        }
      }
      transCache[label] = cache;
    }

    // Backward induction: V = max(finish now, process).
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let tc: Map<string, SvTransEntry[]>;
      if (turnNumber === 1) tc = transCache['first']!;
      else if (tl === 1) tc = transCache['last']!;
      else tc = transCache['middle']!;

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const trans = tc.get(key(w, c, f, s))!;
              for (const [fi, si] of validPairs) {
                const dests = this._changeDests.get(key(fi, si))!;
                const nd = dests.length;
                const finishVal = this._gemValueIdx(w, c, f, s, fi, si);
                let proc = 0.0;
                for (const [p, optKey, , nw, nc, nf, ns] of trans) {
                  proc += p * this._postVal(optKey, nw, nc, nf, ns, fi, si, dests, nd, tl - 1);
                }
                dp.set(key(w, c, f, s, fi, si, tl), finishVal > proc ? finishVal : proc);
              }
            }
          }
        }
      }
    }
  }

  // Flat coupled DP: side display value under the will+chaos policy.
  // dpW holds the will_chaos policy value (w+c on goal-met states, else 0 —
  // what the decision layer maximizes under ignoreSideNodeValues); dpS
  // (== this._dp) holds the side display value accumulated along whichever
  // finish-vs-continue branch the policy picks, not the side-optimal branch.
  // So the policy chases will+chaos and locks in when satisfied; the side node
  // only rides along — the realistic expected coefficient, not the
  // value-iteration upper bound _build() produces. Process is the pool-average
  // continuation (the reroll arm is folded into process; flat, no reroll dim).
  // Mirrors arkgrid/probability.py::SideValueTable._build_policy_eval.
  private _buildPolicyEval(): void {
    const dpS = this._dp;
    const dpW = new Map<string, number>();
    const mt = this._maxTurns;
    const validPairs: [number, number][] = [];
    for (let fi = 0; fi < 4; fi++) {
      for (let si = 0; si < 4; si++) {
        if (fi !== si) validPairs.push([fi, si]);
      }
    }

    const wcFinish = (w: number, c: number, f: number, s: number): number =>
      this._goal.satisfied(w, c, f, s) ? w + c : 0.0;

    // Terminal: turns_left == 0.
    for (let w = 1; w <= 5; w++) {
      for (let c = 1; c <= 5; c++) {
        for (let f = 1; f <= 5; f++) {
          for (let s = 1; s <= 5; s++) {
            const fw = wcFinish(w, c, f, s);
            for (const [fi, si] of validPairs) {
              dpW.set(key(w, c, f, s, fi, si, 0), fw);
              dpS.set(key(w, c, f, s, fi, si, 0), this._gemValueIdx(w, c, f, s, fi, si));
            }
          }
        }
      }
    }

    // Option-level transition cache (same three-turn-type strategy as _build).
    const transCache: Record<string, Map<string, SvTransEntry[]>> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      const cache = new Map<string, SvTransEntry[]>();
      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              cache.set(key(w, c, f, s), this._transitions(w, c, f, s, turn, tl));
            }
          }
        }
      }
      transCache[label] = cache;
    }

    // Backward induction: follow the will_chaos finish-vs-continue choice.
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let tc: Map<string, SvTransEntry[]>;
      if (turnNumber === 1) tc = transCache['first']!;
      else if (tl === 1) tc = transCache['last']!;
      else tc = transCache['middle']!;

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const trans = tc.get(key(w, c, f, s))!;
              for (const [fi, si] of validPairs) {
                const dests = this._changeDests.get(key(fi, si))!;
                const nd = dests.length;
                const finishW = wcFinish(w, c, f, s);
                const finishS = this._gemValueIdx(w, c, f, s, fi, si);
                let procW = 0.0;
                let procS = 0.0;
                for (const [p, optKey, , nw, nc, nf, ns] of trans) {
                  procW += p * this._postValIn(dpW, optKey, nw, nc, nf, ns, fi, si, dests, nd, tl - 1);
                  procS += p * this._postValIn(dpS, optKey, nw, nc, nf, ns, fi, si, dests, nd, tl - 1);
                }
                if (finishW >= procW) {
                  dpW.set(key(w, c, f, s, fi, si, tl), finishW);
                  dpS.set(key(w, c, f, s, fi, si, tl), finishS);
                } else {
                  dpW.set(key(w, c, f, s, fi, si, tl), procW);
                  dpS.set(key(w, c, f, s, fi, si, tl), procS);
                }
              }
            }
          }
        }
      }
    }
  }

  private _buildReroll(): void {
    const dp = this._dp;
    const mt = this._maxTurns;
    const maxR = this._maxRerolls;
    const validPairs: [number, number][] = [];
    for (let fi = 0; fi < 4; fi++)
      for (let si = 0; si < 4; si++)
        if (fi !== si) validPairs.push([fi, si]);

    for (let w = 1; w <= 5; w++)
      for (let c = 1; c <= 5; c++)
        for (let f = 1; f <= 5; f++)
          for (let s = 1; s <= 5; s++)
            for (const [fi, si] of validPairs) {
              const v = this._gemValueIdx(w, c, f, s, fi, si);
              for (let r = 0; r <= maxR; r++) dp.set(key(w, c, f, s, fi, si, r, 0), v);
            }

    type RTrans = [number, string, string, number, number, number, number, number];
    const transitions = (w: number, c: number, f: number, s: number,
                         turn: number, tl: number): [RTrans[], number] => {
      const state = new GemState({ will: w, chaos: c, first: f, second: s });
      const elig = this._pool.pool.filter((o) => this._pool.eligible(o, state, turn, tl));
      if (elig.length === 0) return [[[1.0, '', '', w, c, f, s, 0]], 0];
      let tot = 0;
      for (const o of elig) tot += o.weight;
      const out: RTrans[] = [];
      for (const o of elig) {
        let nw = w, nc = c, nf = f, ns = s, vd = 0;
        if (o.kind === 'will') nw = clampLevel(w + o.delta);
        else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
        else if (o.kind === 'first') nf = clampLevel(f + o.delta);
        else if (o.kind === 'second') ns = clampLevel(s + o.delta);
        else if (o.kind === 'view') vd = o.delta;
        out.push([o.weight / tot, o.key, o.kind, nw, nc, nf, ns, vd]);
      }
      return [out, elig.length];
    };

    const labels: [string, number, number][] = [
      ['first', 1, mt], ['last', mt, 1], ['middle', 2, mt > 2 ? mt - 1 : 2]];
    const transCache: Record<string, Map<string, [RTrans[], number]>> = {};
    for (const [label, turn, tl] of labels) {
      const cache = new Map<string, [RTrans[], number]>();
      for (let w = 1; w <= 5; w++)
        for (let c = 1; c <= 5; c++)
          for (let f = 1; f <= 5; f++)
            for (let s = 1; s <= 5; s++)
              cache.set(key(w, c, f, s), transitions(w, c, f, s, turn, tl));
      transCache[label] = cache;
    }

    const cd = this._changeDests;
    const postVal = (optKey: string, nw: number, nc: number, nf: number, ns: number,
                     fi: number, si: number, nr: number, tl: number): number => {
      if (optKey === 'change_first_effect') {
        const d = cd.get(key(fi, si))!;
        let sum = 0;
        for (const di of d) sum += dp.get(key(nw, nc, nf, ns, di, si, nr, tl))!;
        return sum / d.length;
      }
      if (optKey === 'change_second_effect') {
        const d = cd.get(key(fi, si))!;
        let sum = 0;
        for (const di of d) sum += dp.get(key(nw, nc, nf, ns, fi, di, nr, tl))!;
        return sum / d.length;
      }
      return dp.get(key(nw, nc, nf, ns, fi, si, nr, tl))!;
    };

    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      const tc = turnNumber === 1 ? transCache['first']!
        : tl === 1 ? transCache['last']! : transCache['middle']!;
      for (let w = 1; w <= 5; w++)
        for (let c = 1; c <= 5; c++)
          for (let f = 1; f <= 5; f++)
            for (let s = 1; s <= 5; s++) {
              const [trans, nElig] = tc.get(key(w, c, f, s))!;
              const fpc = nElig > 4 ? (nElig - 4) / (nElig - 1) : 0.0;
              for (const [fi, si] of validPairs) {
                const finishVal = this._gemValueIdx(w, c, f, s, fi, si);
                for (let r = 0; r <= maxR; r++) {
                  const xs: [number, number][] = [];
                  let mu = 0;
                  for (const [p, optKey, , nw, nc, nf, ns, vd] of trans) {
                    const nr = Math.min(maxR, r + vd);
                    const x = postVal(optKey, nw, nc, nf, ns, fi, si, nr, tl - 1);
                    xs.push([p, x]);
                    mu += p * x;
                  }
                  let varv = 0;
                  for (const [p, x] of xs) varv += p * (x - mu) * (x - mu);
                  const sd = Math.sqrt(Math.max(0.0, (varv / 4.0) * fpc));
                  let t: number;
                  if (r > 0 && turnNumber !== 1) {
                    const rc = dp.get(key(w, c, f, s, fi, si, r - 1, tl))!;
                    t = finishVal > rc ? finishVal : rc;
                  } else {
                    t = finishVal;
                  }
                  dp.set(key(w, c, f, s, fi, si, r, tl), eMax(mu, sd, t));
                }
              }
            }
    }
  }

  // -- public API --------------------------------------------------

  /** Value of finishing the gem in its current state. */
  gemValue(state: GemState): number {
    if (!this.enabled) return 0.0;
    const idx = this._effectIndices(state);
    if (idx === null) return 0.0;
    const [fi, si] = idx;
    return this._gemValueIdx(state.will, state.chaos, state.first, state.second, fi, si);
  }

  /** Expected final gem value under optimal play from this state. */
  lookup(state: GemState, turnsLeft: number, rerolls?: number): number {
    if (!this.enabled) return 0.0;
    const idx = this._effectIndices(state);
    if (idx === null) return 0.0;
    const [fi, si] = idx;
    const w = state.will, c = state.chaos, f = state.first, s = state.second;
    if (this._maxRerolls > 0) {
      const r = Math.min(this._maxRerolls, rerolls ?? 0);
      return this._dp.get(key(w, c, f, s, fi, si, r, turnsLeft)) ?? 0.0;
    }
    return this._dp.get(key(w, c, f, s, fi, si, turnsLeft)) ?? 0.0;
  }

  /** Mean V across the 4 actual visible offers (uniform 25% pick).
   *  Mirrors GoalProbabilityTable.expectedProbAfterClick — the process-EV
   *  term of the finish decision uses the real offers, not the pool-model
   *  single draw the table is built with.
   */
  expectedValueAfterClick(state: GemState, offers: Option[], turnsLeftAfter: number,
                          rerolls?: number): number {
    if (!this.enabled || offers.length === 0) return 0.0;
    const idx = this._effectIndices(state);
    if (idx === null) return 0.0;
    const [fi, si] = idx;
    const dests = this._changeDests.get(key(fi, si))!;
    const nd = dests.length;
    const ra = this._maxRerolls > 0;
    let total = 0.0;
    for (const o of offers) {
      const nw = o.kind === 'will' ? clampLevel(state.will + o.delta) : state.will;
      const nc = o.kind === 'chaos' ? clampLevel(state.chaos + o.delta) : state.chaos;
      const nf = o.kind === 'first' ? clampLevel(state.first + o.delta) : state.first;
      const ns = o.kind === 'second' ? clampLevel(state.second + o.delta) : state.second;
      let kk: (a: number, b: number) => string;
      if (ra) {
        const vd = o.kind === 'view' ? o.delta : 0;
        const nr = Math.min(this._maxRerolls, (rerolls ?? 0) + vd);
        kk = (a, b) => key(nw, nc, nf, ns, a, b, nr, turnsLeftAfter);
      } else {
        kk = (a, b) => key(nw, nc, nf, ns, a, b, turnsLeftAfter);
      }
      if (o.key === 'change_first_effect') {
        let sum = 0;
        for (const d of dests) sum += this._dp.get(kk(d, si)) ?? 0.0;
        total += sum / nd;
      } else if (o.key === 'change_second_effect') {
        let sum = 0;
        for (const d of dests) sum += this._dp.get(kk(fi, d)) ?? 0.0;
        total += sum / nd;
      } else {
        total += this._dp.get(kk(fi, si)) ?? 0.0;
      }
    }
    return total / offers.length;
  }
}
