// Port of arkgrid/probability.py:10-852 (GoalProbabilityTable only).
//
// Faithful transcription of the backward-induction DP. SideValueTable
// (probability.py:854+) is Task 7. The bis-only mode (_build_bis,
// lookup_bis_averaged, lookup_after_effect_change) is a documented no-op
// and is intentionally NOT ported.
//
// The Python _dp is a dict keyed by tuples; here it is a Map<string, number>
// with a comma-joined key builder. The key arity must match Python's tuple
// shapes per mode EXACTLY (cs = cost-saturation flag, 1 at cost_ratio ±100):
//   effect-aware + reroll: (w, c, f, s, cs, fi, si, r, tl)
//   effect-aware:          (w, c, f, s, cs, fi, si, tl)
//   reroll:                (w, c, f, s, cs, r, tl)
//   standard:              (w, c, f, s, cs, tl)

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

// The DP lives in flat Float64Arrays indexed arithmetically — the dense
// state space makes string-keyed Maps needlessly slow (key hashing used to
// dominate the build time).

// Dense 0..624 index over the 4 stat levels (each 1..5).
const s625 = (w: number, c: number, f: number, s: number): number =>
  (((w - 1) * 5 + (c - 1)) * 5 + (f - 1)) * 5 + (s - 1);

const clampLevel = (x: number): number => Math.min(5, Math.max(1, x));

// Exact hand statistics per weight class, keyed by the sorted eligible weights
// (a few hundred distinct multisets exist across all states).
interface HandStats {
  index: Map<number, number>; // weight -> class index
  applied: number[];          // per class: P(one given option is the applied one)
  pair: number[][];           // per class pair: P(two given distinct options are both in the hand)
}
const HAND_STATS = new Map<string, HandStats>();

/** Exact statistics of the 4-offer hand for one eligible-weight multiset.
 *
 * The game draws 4 distinct offers by successive weighted sampling without
 * replacement. Options sharing a weight are exchangeable, so the enumeration
 * runs over ordered draws of weight *classes* (<= 8 classes, <= 8**4 paths).
 * Mirrors arkgrid/probability.py::_hand_stats.
 */
function handStats(sorted: number[]): HandStats {
  const key = sorted.join(',');
  let stats = HAND_STATS.get(key);
  if (stats === undefined) {
    const classes: number[] = [];
    const counts: number[] = [];
    for (const w of sorted) {
      if (classes.length > 0 && classes[classes.length - 1] === w) {
        counts[counts.length - 1]!++;
      } else {
        classes.push(w);
        counts.push(1);
      }
    }
    const n = classes.length;
    // expected[i] = E[number of class-i options in the hand]
    const expected: number[] = new Array(n).fill(0.0);
    // joint[a][b] = E[number of slot pairs (earlier, later) holding classes (a, b)]
    const joint: number[][] = [];
    for (let a = 0; a < n; a++) joint.push(new Array(n).fill(0.0));
    const used: number[] = new Array(n).fill(0);
    const path: number[] = [];
    const draw = (depth: number, p: number, remaining: number): void => {
      for (let i = 0; i < n; i++) {
        const k = counts[i]! - used[i]!;
        if (k <= 0) continue;
        const c = classes[i]!;
        const q = (p * k * c) / remaining;
        expected[i]! += q;
        for (const j of path) joint[j]![i]! += q;
        if (depth < 3) {
          used[i]!++;
          path.push(i);
          draw(depth + 1, q, remaining - c);
          path.pop();
          used[i]!--;
        }
      }
    };
    let total = 0.0;
    for (const w of sorted) total += w;
    draw(0, 1.0, total);
    const applied = expected.map((e, i) => e / counts[i]! / 4.0);
    const pair: number[][] = [];
    for (let a = 0; a < n; a++) {
      const row: number[] = new Array(n).fill(0.0);
      for (let b = 0; b < n; b++) {
        if (a !== b) {
          row[b] = (joint[a]![b]! + joint[b]![a]!) / (counts[a]! * counts[b]!);
        } else if (counts[a]! >= 2) {
          row[a] = (2.0 * joint[a]![a]!) / (counts[a]! * (counts[a]! - 1));
        }
      }
      pair.push(row);
    }
    const index = new Map<number, number>();
    classes.forEach((c, i) => index.set(c, i));
    stats = { index, applied, pair };
    HAND_STATS.set(key, stats);
  }
  return stats;
}

/** Exact probability that each option is the one APPLIED by a click.
 *
 * The game draws 4 distinct offers by successive weighted sampling without
 * replacement and applies one of them uniformly, so an option's applied
 * probability is its hand-inclusion probability / 4 — not `weight / total`.
 * With <= 4 eligible options every one is offered (uniform pick).
 * Mirrors arkgrid/probability.py::applied_probs.
 */
export function appliedProbs(weights: number[]): number[] {
  const n = weights.length;
  if (n <= 4) return weights.map(() => 1.0 / n);
  const stats = handStats([...weights].sort((a, b) => a - b));
  return weights.map((w) => stats.applied[stats.index.get(w)!]!);
}

/** Everything `handTurnValue` needs to know about a state's eligible options
 *  (in pool order). `cls` is null when <= 4 options are eligible (the hand is
 *  then the whole set). Mirrors arkgrid/probability.py::hand_context. */
export interface HandContext {
  probs: number[];                  // applied probabilities
  cls: number[] | null;             // weight-class index per option
  diag: [number, number][];         // (class, pair coefficient) for same-class pairs
  off: [number, number, number][];  // (class a, class b, 2 * pair coefficient), a < b
  nc: number;                       // number of weight classes
}
const HAND_CONTEXTS = new Map<string, HandContext>();

export function handContext(weights: number[]): HandContext {
  const key = weights.join(',');
  let ctx = HAND_CONTEXTS.get(key);
  if (ctx === undefined) {
    const n = weights.length;
    if (n <= 4) {
      ctx = { probs: weights.map(() => 1.0 / n), cls: null, diag: [], off: [], nc: 0 };
    } else {
      const stats = handStats([...weights].sort((a, b) => a - b));
      const cls = weights.map((w) => stats.index.get(w)!);
      const nc = stats.applied.length;
      const diag: [number, number][] = [];
      const off: [number, number, number][] = [];
      for (let a = 0; a < nc; a++) {
        if (stats.pair[a]![a]! !== 0.0) diag.push([a, stats.pair[a]![a]!]);
      }
      for (let a = 0; a < nc; a++) {
        for (let b = a + 1; b < nc; b++) off.push([a, b, 2.0 * stats.pair[a]![b]!]);
      }
      ctx = { probs: cls.map((a) => stats.applied[a]!), cls, diag, off, nc };
    }
    HAND_CONTEXTS.set(key, ctx);
  }
  return ctx;
}

// Multinomial(4; 3 atoms): [n1, n2, n3, coefficient].
const FACT = [1, 1, 2, 6, 24];
const HAND_TRINOM: [number, number, number, number][] = [];
for (let n1 = 0; n1 <= 4; n1++) {
  for (let n2 = 0; n2 <= 4 - n1; n2++) {
    const n3 = 4 - n1 - n2;
    HAND_TRINOM.push([n1, n2, n3, 24.0 / (FACT[n1]! * FACT[n2]! * FACT[n3]!)]);
  }
}
const BINOM = [[1], [1, 1], [1, 2, 1], [1, 3, 3, 1], [1, 4, 6, 4, 1]];
const TWO_THIRDS_PI = (2.0 * Math.PI) / 3.0;

/** `handEMax` when the offers take only two distinct values (hit or miss —
 *  the last turn of a goal table). The hand mean is `lo + (hi - lo) * K / 4`,
 *  K = number of "hit" offers in the hand; K's mean (4q) and exact variance
 *  (`4 q (1-q) rho`) are matched by Binomial(n, 4q/n), mixing the two
 *  neighbouring integers for a fractional n. Mirrors `_hand_e_max2`. */
function handEMax2(mu: number, m2: number, m3: number, rho: number, t: number): number {
  const sd = Math.sqrt(m2);
  const g = m3 / (m2 * sd); // skewness
  const r = Math.sqrt(4.0 + g * g);
  // P(hit) = (1 - g/r) / 2, written to avoid cancellation.
  const q = g >= 0.0 ? 2.0 / (r * (r + g)) : 1.0 - 2.0 / (r * (r - g));
  const lo = mu - sd * Math.sqrt(q / (1.0 - q));
  const step = (mu + sd * Math.sqrt((1.0 - q) / q) - lo) / 4.0;
  const meanK = 4.0 * q;
  const denom = 1.0 - (1.0 - q) * rho;
  let n = denom > meanK / 4.0 ? meanK / denom : 4.0;
  const floorN = meanK < 1.0 ? 1.0 : meanK; // Binomial(n, 4q/n) needs n >= 4q
  if (n < floorN) n = floorN;
  const nLo = Math.floor(n);
  let parts: [number, number][];
  if (nLo >= 4) {
    parts = [[4, 1.0]];
  } else if (nLo < meanK) {
    parts = [[nLo + 1, 1.0]]; // only the upper neighbour is valid
  } else {
    const lam = (1.0 / n - 1.0 / (nLo + 1)) / (1.0 / nLo - 1.0 / (nLo + 1));
    parts = [[nLo, lam], [nLo + 1, 1.0 - lam]];
  }
  let total = 0.0;
  for (const [nj, share] of parts) {
    if (share <= 0.0) continue;
    const qj = meanK / nj;
    for (let k = 0; k <= nj; k++) {
      const h = lo + step * k;
      total += share * BINOM[nj]![k]! * qj ** k * (1.0 - qj) ** (nj - k) * (h > t ? h : t);
    }
  }
  return total;
}

/** E[max(H, t)], where H is the mean value of a 4-offer hand.
 *
 * A reroll rejects the whole hand, never a single offer. Inputs are the
 * single-offer value distribution's mean and central moments `m2..m5`, and
 * `rho` = (exact variance of the hand mean) / (m2 / 4).
 *
 * - Lumpy values: the distribution is replaced by its 3-node Gauss quadrature
 *   (matching `mu, m2..m5`) and the hand is 4 draws from it (15 values,
 *   multinomial weights). A 2-point fit loses the bulk's own spread and read
 *   low on hard goals.
 * - Distinct offers: the hand holds 4 DIFFERENT options, so every deviation
 *   is scaled by `sqrt(rho)` to make the hand variance exact; without it
 *   easy goals read 15-25% high.
 *
 * Mirrors arkgrid/probability.py::hand_e_max.
 */
export function handEMax(
  mu: number, m2: number, m3: number, m4: number, m5: number, rho: number, t: number
): number {
  const scale = mu * mu > t * t ? mu * mu : t * t;
  if (m2 <= 1e-12 * (scale > 1.0 ? scale : 1.0)) return mu > t ? mu : t;
  const sd = Math.sqrt(m2);
  const g = m3 / (m2 * sd);       // skewness
  const k = m4 / (m2 * m2);       // kurtosis
  const h5 = m5 / (m2 * m2 * sd);
  const det = k - g * g - 1.0;    // 0 for a two-valued distribution
  if (det <= 1e-9 * (k > 1.0 ? k : 1.0)) return handEMax2(mu, m2, m3, rho, t);
  // Monic degree-3 orthogonal polynomial z^3 + c2 z^2 + c1 z + c0 of the
  // standardized distribution; its roots are the quadrature nodes.
  const c2 = (g + g * k - h5) / det;
  const c1 = -k - g * c2;
  const c0 = -g - c2;
  const p = c1 - (c2 * c2) / 3.0;
  if (p >= 0.0) return handEMax2(mu, m2, m3, rho, t);
  const q = (2.0 * c2 * c2 * c2) / 27.0 - (c2 * c1) / 3.0 + c0;
  const amp = 2.0 * Math.sqrt(-p / 3.0);
  let arg = (3.0 * q) / (p * amp);
  arg = arg > 1.0 ? 1.0 : arg < -1.0 ? -1.0 : arg;
  const phi = Math.acos(arg) / 3.0;
  const shift = c2 / 3.0;
  const z1 = amp * Math.cos(phi) - shift;
  const z2 = amp * Math.cos(phi - TWO_THIRDS_PI) - shift;
  const z3 = amp * Math.cos(phi - 2.0 * TWO_THIRDS_PI) - shift;
  const w1 = (1.0 + z2 * z3) / ((z1 - z2) * (z1 - z3));
  const w2 = (1.0 + z1 * z3) / ((z2 - z1) * (z2 - z3));
  const w3 = 1.0 - w1 - w2;
  if (!(w1 > 0.0 && w2 > 0.0 && w3 > 0.0)) return handEMax2(mu, m2, m3, rho, t);
  const s = sd * Math.sqrt(rho) * 0.25;
  const a1 = s * z1;
  const a2 = s * z2;
  const a3 = s * z3;
  const p1 = [1.0, w1, w1 * w1, w1 * w1 * w1, w1 * w1 * w1 * w1];
  const p2 = [1.0, w2, w2 * w2, w2 * w2 * w2, w2 * w2 * w2 * w2];
  const p3 = [1.0, w3, w3 * w3, w3 * w3 * w3, w3 * w3 * w3 * w3];
  let total = 0.0;
  for (const [n1, n2, n3, coef] of HAND_TRINOM) {
    const h = mu + n1 * a1 + n2 * a2 + n3 * a3;
    total += coef * p1[n1]! * p2[n2]! * p3[n3]! * (h > t ? h : t);
  }
  return total;
}

/** `[mu, m2, m3, m4, m5, rho]` of a hand over `ctx`'s options with post-click
 *  values `posts`: the single-offer mean and central moments, and `rho`, the
 *  exact variance of the 4-distinct-offer hand mean relative to 4 independent
 *  draws (`m2 / 4`). Mirrors `_hand_moments`. */
export function handMoments(
  ctx: HandContext, posts: number[]
): [number, number, number, number, number, number] {
  const probs = ctx.probs;
  const n = probs.length;
  let mu = 0.0;
  for (let i = 0; i < n; i++) mu += probs[i]! * posts[i]!;
  const cls = ctx.cls;
  if (cls === null) return [mu, 0.0, 0.0, 0.0, 0.0, 0.0];
  let m2 = 0.0, m3 = 0.0, m4 = 0.0, m5 = 0.0;
  const sums: number[] = new Array(ctx.nc).fill(0.0);    // per class: sum of deviations
  const squares: number[] = new Array(ctx.nc).fill(0.0); // per class: sum of squared deviations
  for (let i = 0; i < n; i++) {
    const d = posts[i]! - mu;
    const d2 = d * d;
    const a = cls[i]!;
    sums[a]! += d;
    squares[a]! += d2;
    const pd = probs[i]! * d2;
    m2 += pd;
    m3 += pd * d;
    m4 += pd * d2;
    m5 += pd * d2 * d;
  }
  if (m2 <= 0.0) return [mu, 0.0, 0.0, 0.0, 0.0, 0.0];
  // 16 Var(hand mean) = sum_i pi_i d_i^2 + sum_{i != j} pi_ij d_i d_j,
  // with pi_i = 4 p_i; the cross term by class sums.
  let cross = 0.0;
  for (const [a, coef] of ctx.diag) cross += coef * (sums[a]! * sums[a]! - squares[a]!);
  for (const [a, b, coef] of ctx.off) cross += coef * sums[a]! * sums[b]!;
  const rho = 1.0 + cross / (4.0 * m2);
  return [mu, m2, m3, m4, m5, rho > 0.0 ? rho : 0.0];
}

/** Value of a turn whose 4-offer hand (options described by `ctx`; post-click
 *  values `posts`) is kept when its mean beats `alt` — the value of the
 *  alternative (redraw, or finishing) — and given up for that alternative
 *  otherwise. Mirrors `_hand_turn_value`. */
export function handTurnValue(ctx: HandContext, posts: number[], alt: number): number {
  const [mu, m2, m3, m4, m5, rho] = handMoments(ctx, posts);
  // Certain hand: <= 4 eligible options, or all offers worth the same.
  if (m2 <= 0.0) return mu > alt ? mu : alt;
  return handEMax(mu, m2, m3, m4, m5, rho, alt);
}

/** `handContext` per `${label},${cs}` and state625 — the same three-turn-type
 *  layout as the builds' transition caches. Mirrors `_hand_contexts`. */
function handContexts(pool: OptionPool, maxTurns: number): Record<string, HandContext[]> {
  const out: Record<string, HandContext[]> = {};
  const turnSpecs: [string, number, number][] = [
    ['first', 1, maxTurns],
    ['last', maxTurns, 1],
    ['middle', 2, maxTurns > 2 ? maxTurns - 1 : 2],
  ];
  for (const [label, turn, tl] of turnSpecs) {
    for (let cs = 0; cs <= 1; cs++) {
      const ctxs: HandContext[] = new Array(625);
      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const state = new GemState({ will: w, chaos: c, first: f, second: s, costRatio: cs ? 100 : 0 });
              ctxs[s625(w, c, f, s)] = handContext(
                pool.pool.filter((o) => pool.eligible(o, state, turn, tl)).map((o) => o.weight));
            }
          }
        }
      }
      out[`${label},${cs}`] = ctxs;
    }
  }
  return out;
}

// Effect-aware option-level transition entry:
//   [prob, optionKey, optionKind, nw, nc, nf, ns, ncs, viewDelta]
type EaTransEntry = [number, string, string, number, number, number, number, number, number];

// Reroll-aware (non-effect) transition entry:
//   [prob, nw, nc, nf, ns, ncs, viewDelta]
type RerollTransEntry = [number, number, number, number, number, number, number];

// Standard (non-reroll, non-effect) transition entry with duplicate
// destinations merged (mirrors Python's dict aggregation, in first-occurrence
// order so float summation order is identical):
//   [prob, nw, nc, nf, ns, ncs]
type StdTransEntry = [number, number, number, number, number, number];

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
  // change-effect destinations indexed by fi*4+si
  private _changeDests: (number[] | null)[];

  // Flat DP storage. Index layout mirrors the Python tuple keys:
  //   (state625, cs, fi*4+si [EA only], r [reroll only], tl)
  private _dp: Float64Array;
  private readonly _eaDim: number; // 16 when effect-aware, else 1
  private readonly _rDim: number;  // maxRerolls+1 when reroll-aware, else 1
  private readonly _tlDim: number; // maxTurns+1

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
      this._changeDests = new Array(16).fill(null);
      for (let fi = 0; fi < 4; fi++) {
        for (let si = 0; si < 4; si++) {
          if (fi === si) continue;
          const dests: number[] = [];
          for (let i = 0; i < 4; i++) {
            if (i !== fi && i !== si) dests.push(i);
          }
          this._changeDests[fi * 4 + si] = dests;
        }
      }
    } else {
      this._effectTuple = [];
      this._effectCoeffs = [];
      this._changeDests = new Array(16).fill(null);
    }

    this._eaDim = this.effectAware ? 16 : 1;
    this._rDim = this._maxRerolls > 0 ? this._maxRerolls + 1 : 1;
    this._tlDim = maxTurns + 1;
    // Unwritten slots stay 0.0, matching Python's dict .get(key, 0.0).
    this._dp = new Float64Array(625 * 2 * this._eaDim * this._rDim * this._tlDim);
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

  // Flat-array index. `st` is s625(w,c,f,s); `ea` is fi*4+si for
  // effect-aware tables (else 0); `r` is the reroll count for reroll-aware
  // tables (else 0).
  private _idx(st: number, cs: number, ea: number, r: number, tl: number): number {
    return (((st * 2 + cs) * this._eaDim + ea) * this._rDim + r) * this._tlDim + tl;
  }

  // ------------------------------------------------------------------
  // Transition helpers (option probability assignment)
  // ------------------------------------------------------------------

  // Exact per-option applied probability (`appliedProbs`), paired with its
  // option. Returning pairs avoids index-based array access (which is
  // `T | undefined` under noUncheckedIndexedAccess).
  private _optionProbs(eligible: Option[]): [Option, number][] {
    const probs = appliedProbs(eligible.map((o) => o.weight));
    return eligible.map((o, i) => [o, probs[i]!]);
  }

  private _eligible(w: number, c: number, f: number, s: number, cs: number, turn: number, turnsLeft: number): Option[] {
    const state = new GemState({ will: w, chaos: c, first: f, second: s, costRatio: cs ? 100 : 0 });
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
    cs: number,
    turn: number,
    turnsLeft: number
  ): StdTransEntry[] {
    const eligible = this._eligible(w, c, f, s, cs, turn, turnsLeft);
    if (eligible.length === 0) {
      return [[1.0, w, c, f, s, cs]];
    }
    // Merge duplicate destinations in first-occurrence order (mirrors the
    // Python dict aggregation, keeping float summation order identical).
    const list: StdTransEntry[] = [];
    const seen = new Map<number, number>();
    for (const [o, p] of this._optionProbs(eligible)) {
      let nw = w, nc = c, nf = f, ns = s, ncs = cs;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      else if (o.kind === 'cost') ncs = 1 - cs;
      // view/other/maintain -> no state change
      const packed = s625(nw, nc, nf, ns) * 2 + ncs;
      const at = seen.get(packed);
      if (at !== undefined) {
        list[at]![0] += p;
      } else {
        seen.set(packed, list.length);
        list.push([p, nw, nc, nf, ns, ncs]);
      }
    }
    return list;
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
            const st = s625(w, c, f, s);
            for (let cs = 0; cs <= 1; cs++) {
              dp[this._idx(st, cs, 0, 0, 0)] = sat;
            }
          }
        }
      }
    }

    // Precompute transition tables for three turn types x cost states,
    // indexed by state625.
    const transCache: Record<string, StdTransEntry[][]> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      for (let cs = 0; cs <= 1; cs++) {
        const cache: StdTransEntry[][] = new Array(625);
        for (let w = 1; w <= 5; w++) {
          for (let c = 1; c <= 5; c++) {
            for (let f = 1; f <= 5; f++) {
              for (let s = 1; s <= 5; s++) {
                cache[s625(w, c, f, s)] = this._transitions(w, c, f, s, cs, turn, tl);
              }
            }
          }
        }
        transCache[`${label},${cs}`] = cache;
      }
    }

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let label: string;
      if (turnNumber === 1) label = 'first';
      else if (tl === 1) label = 'last';
      else label = 'middle';

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const st = s625(w, c, f, s);
              if (this.earlyFinish && this.goal.satisfied(w, c, f, s) && this._coeffSatisfied(f, s)) {
                for (let cs = 0; cs <= 1; cs++) {
                  dp[this._idx(st, cs, 0, 0, tl)] = 1.0;
                }
                continue;
              }
              for (let cs = 0; cs <= 1; cs++) {
                const trans = transCache[`${label},${cs}`]![st]!;
                let val = 0.0;
                for (const [p, nw, nc, nf, ns, ncs] of trans) {
                  val += p * dp[this._idx(s625(nw, nc, nf, ns), ncs, 0, 0, tl - 1)]!;
                }
                dp[this._idx(st, cs, 0, 0, tl)] = val;
              }
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
    cs: number,
    turn: number,
    turnsLeft: number
  ): RerollTransEntry[] {
    const eligible = this._eligible(w, c, f, s, cs, turn, turnsLeft);
    if (eligible.length === 0) {
      return [[1.0, w, c, f, s, cs, 0]];
    }
    const result: RerollTransEntry[] = [];
    for (const [o, p] of this._optionProbs(eligible)) {
      let nw = w, nc = c, nf = f, ns = s, ncs = cs;
      let vd = 0;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      else if (o.kind === 'view') vd = o.delta;
      else if (o.kind === 'cost') ncs = 1 - cs;
      // other/maintain -> no state change, no view delta
      result.push([p, nw, nc, nf, ns, ncs, vd]);
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
            const st = s625(w, c, f, s);
            for (let cs = 0; cs <= 1; cs++) {
              for (let r = 0; r <= maxR; r++) {
                dp[this._idx(st, cs, 0, r, 0)] = sat;
              }
            }
          }
        }
      }
    }

    // Precompute transition tables (with view deltas) per cost state,
    // indexed by state625.
    const transCache: Record<string, RerollTransEntry[][]> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      for (let cs = 0; cs <= 1; cs++) {
        const cache: RerollTransEntry[][] = new Array(625);
        for (let w = 1; w <= 5; w++) {
          for (let c = 1; c <= 5; c++) {
            for (let f = 1; f <= 5; f++) {
              for (let s = 1; s <= 5; s++) {
                cache[s625(w, c, f, s)] = this._transitionsReroll(w, c, f, s, cs, turn, tl);
              }
            }
          }
        }
        transCache[`${label},${cs}`] = cache;
      }
    }
    const handCache = handContexts(this.pool, mt);

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let label: string;
      if (turnNumber === 1) label = 'first';
      else if (tl === 1) label = 'last';
      else label = 'middle';

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++) {
                const trans = transCache[`${label},${cs}`]![st]!;
                const hand = handCache[`${label},${cs}`]![st]!;
                for (let r = 0; r <= maxR; r++) {
                  if (this.earlyFinish && this.goal.satisfied(w, c, f, s) && this._coeffSatisfied(f, s)) {
                    dp[this._idx(st, cs, 0, r, tl)] = 1.0;
                    continue;
                  }

                  // Reroll decision is made on the whole 4-offer hand: keep
                  // it when its mean beats a redraw, otherwise reroll.
                  if (r > 0 && turnNumber !== 1) {
                    const rerollVal = dp[this._idx(st, cs, 0, r - 1, tl)]!;
                    const posts: number[] = [];
                    for (const [, nw, nc, nf, ns, ncs, vd] of trans) {
                      const nr = Math.min(maxR, r + vd);
                      posts.push(dp[this._idx(s625(nw, nc, nf, ns), ncs, 0, nr, tl - 1)]!);
                    }
                    dp[this._idx(st, cs, 0, r, tl)] = handTurnValue(hand, posts, rerollVal);
                  } else {
                    let val = 0.0;
                    for (const [p, nw, nc, nf, ns, ncs, vd] of trans) {
                      const nr = Math.min(maxR, r + vd);
                      val += p * dp[this._idx(s625(nw, nc, nf, ns), ncs, 0, nr, tl - 1)]!;
                    }
                    dp[this._idx(st, cs, 0, r, tl)] = val;
                  }
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
    cs: number,
    turn: number,
    turnsLeft: number
  ): EaTransEntry[] {
    const eligible = this._eligible(w, c, f, s, cs, turn, turnsLeft);
    if (eligible.length === 0) {
      return [[1.0, '', '', w, c, f, s, cs, 0]];
    }
    const result: EaTransEntry[] = [];
    for (const [o, p] of this._optionProbs(eligible)) {
      let nw = w, nc = c, nf = f, ns = s, ncs = cs;
      let vd = 0;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      else if (o.kind === 'view') vd = o.delta;
      else if (o.kind === 'cost') ncs = 1 - cs;
      result.push([p, o.key, o.kind, nw, nc, nf, ns, ncs, vd]);
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

  private _buildEaTransCache(): Record<string, EaTransEntry[][]> {
    const mt = this.maxTurns;
    const transCache: Record<string, EaTransEntry[][]> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      for (let cs = 0; cs <= 1; cs++) {
        const cache: EaTransEntry[][] = new Array(625);
        for (let w = 1; w <= 5; w++) {
          for (let c = 1; c <= 5; c++) {
            for (let f = 1; f <= 5; f++) {
              for (let s = 1; s <= 5; s++) {
                cache[s625(w, c, f, s)] = this._effectAwareTransitions(w, c, f, s, cs, turn, tl);
              }
            }
          }
        }
        transCache[`${label},${cs}`] = cache;
      }
    }
    return transCache;
  }

  private _build_effect_aware_turnTable(turnNumber: number, tl: number, cs: number, transCache: Record<string, EaTransEntry[][]>): EaTransEntry[][] {
    if (turnNumber === 1) return transCache[`first,${cs}`]!;
    if (tl === 1) return transCache[`last,${cs}`]!;
    return transCache[`middle,${cs}`]!;
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
            const st = s625(w, c, f, s);
            for (const [fi, si] of validPairs) {
              const sat = goalSat && this._coeffSatisfiedIdx(f, s, fi, si) ? 1.0 : 0.0;
              for (let cs = 0; cs <= 1; cs++) {
                dp[this._idx(st, cs, fi * 4 + si, 0, 0)] = sat;
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

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const goalSat = this.goal.satisfied(w, c, f, s);
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++) {
                const trans = this._build_effect_aware_turnTable(turnNumber, tl, cs, transCache)[st]!;
                for (const [fi, si] of validPairs) {
                  if (this.earlyFinish && goalSat && this._coeffSatisfiedIdx(f, s, fi, si)) {
                    dp[this._idx(st, cs, fi * 4 + si, 0, tl)] = 1.0;
                    continue;
                  }
                  const dests = this._changeDests[fi * 4 + si]!;
                  const nDests = dests.length; // always 2
                  let val = 0.0;
                  for (const [p, optKey, , nw, nc, nf, ns, ncs] of trans) {
                    const nst = s625(nw, nc, nf, ns);
                    if (optKey === 'change_first_effect') {
                      for (const newFi of dests) {
                        val += (p / nDests) * dp[this._idx(nst, ncs, newFi * 4 + si, 0, tl - 1)]!;
                      }
                    } else if (optKey === 'change_second_effect') {
                      for (const newSi of dests) {
                        val += (p / nDests) * dp[this._idx(nst, ncs, fi * 4 + newSi, 0, tl - 1)]!;
                      }
                    } else {
                      val += p * dp[this._idx(nst, ncs, fi * 4 + si, 0, tl - 1)]!;
                    }
                  }
                  dp[this._idx(st, cs, fi * 4 + si, 0, tl)] = val;
                }
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
            const st = s625(w, c, f, s);
            for (const [fi, si] of validPairs) {
              const sat = goalSat && this._coeffSatisfiedIdx(f, s, fi, si) ? 1.0 : 0.0;
              for (let cs = 0; cs <= 1; cs++) {
                for (let r = 0; r <= maxR; r++) {
                  dp[this._idx(st, cs, fi * 4 + si, r, 0)] = sat;
                }
              }
            }
          }
        }
      }
    }

    const transCache = this._buildEaTransCache();
    const handCache = handContexts(this.pool, mt);

    // Backward induction
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const goalSat = this.goal.satisfied(w, c, f, s);
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++) {
                const trans = this._build_effect_aware_turnTable(turnNumber, tl, cs, transCache)[st]!;
                const hand = handCache[`${turnNumber === 1 ? 'first' : tl === 1 ? 'last' : 'middle'},${cs}`]![st]!;
                for (const [fi, si] of validPairs) {
                  const dests = this._changeDests[fi * 4 + si]!;
                  const nDests = dests.length;

                  // post_val: V at a transition destination, routing
                  // change_effect uniformly across non-equipped pool members.
                  const postVal = (
                    optKey: string,
                    nst: number,
                    ncs: number,
                    nr: number
                  ): number => {
                    if (optKey === 'change_first_effect') {
                      let v = 0.0;
                      for (const newFi of dests) {
                        v += dp[this._idx(nst, ncs, newFi * 4 + si, nr, tl - 1)]! / nDests;
                      }
                      return v;
                    }
                    if (optKey === 'change_second_effect') {
                      let v = 0.0;
                      for (const newSi of dests) {
                        v += dp[this._idx(nst, ncs, fi * 4 + newSi, nr, tl - 1)]! / nDests;
                      }
                      return v;
                    }
                    return dp[this._idx(nst, ncs, fi * 4 + si, nr, tl - 1)]!;
                  };

                  for (let r = 0; r <= maxR; r++) {
                    if (this.earlyFinish && goalSat && this._coeffSatisfiedIdx(f, s, fi, si)) {
                      dp[this._idx(st, cs, fi * 4 + si, r, tl)] = 1.0;
                      continue;
                    }

                    if (r > 0 && turnNumber !== 1) {
                      const rerollVal = dp[this._idx(st, cs, fi * 4 + si, r - 1, tl)]!;
                      const posts: number[] = [];
                      for (const [, optKey, , nw, nc, nf, ns, ncs, vd] of trans) {
                        const nr = Math.min(maxR, r + vd);
                        posts.push(postVal(optKey, s625(nw, nc, nf, ns), ncs, nr));
                      }
                      dp[this._idx(st, cs, fi * 4 + si, r, tl)] = handTurnValue(hand, posts, rerollVal);
                    } else {
                      let val = 0.0;
                      for (const [p, optKey, , nw, nc, nf, ns, ncs, vd] of trans) {
                        const nr = Math.min(maxR, r + vd);
                        val += p * postVal(optKey, s625(nw, nc, nf, ns), ncs, nr);
                      }
                      dp[this._idx(st, cs, fi * 4 + si, r, tl)] = val;
                    }
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
    if (turnsLeft < 0 || turnsLeft >= this._tlDim) return 0.0;
    const cs = state.costRatio !== 0 ? 1 : 0;
    const st = s625(state.will, state.chaos, state.first, state.second);
    if (this.effectAware) {
      const idx = this._effectIndices(state);
      if (idx === null) return 0.0;
      const [fi, si] = idx;
      const r = this._maxRerolls > 0 ? Math.min(this._maxRerolls, rerolls ?? 0) : 0;
      return this._dp[this._idx(st, cs, fi * 4 + si, r, turnsLeft)]!;
    }
    const r = this._maxRerolls > 0 ? Math.min(this._maxRerolls, rerolls ?? 0) : 0;
    return this._dp[this._idx(st, cs, 0, r, turnsLeft)]!;
  }

  /** Post-click P(goal) for a single offer.
   *
   * Destination-blind by design: the change-effect card does not reveal
   * its destination in-game, so change offers are valued as the average
   * over the 2 non-equipped destinations (matching the transition model)
   * — `Option.resolvedEffect` is never consulted here.
   */
  probAfterOption(state: GemState, o: Option, turnsLeftAfter: number, rerolls?: number): number {
    if (turnsLeftAfter < 0 || turnsLeftAfter >= this._tlDim) return 0.0;
    const nw = o.kind === 'will' ? clampLevel(state.will + o.delta) : state.will;
    const nc = o.kind === 'chaos' ? clampLevel(state.chaos + o.delta) : state.chaos;
    const nf = o.kind === 'first' ? clampLevel(state.first + o.delta) : state.first;
    const ns = o.kind === 'second' ? clampLevel(state.second + o.delta) : state.second;
    const cs = state.costRatio !== 0 ? 1 : 0;
    const ncs = o.kind === 'cost' ? 1 - cs : cs;
    const nst = s625(nw, nc, nf, ns);

    if (this.effectAware) {
      const idx = this._effectIndices(state);
      if (idx === null) return 0.0;
      const [fi, si] = idx;
      const r = rerolls ?? 0;
      const vd = o.kind === 'view' ? o.delta : 0;
      const nr = this._maxRerolls > 0 ? Math.min(this._maxRerolls, r + vd) : 0;
      const dests = this._changeDests[fi * 4 + si]!;
      const nDests = dests.length;
      if (o.key === 'change_first_effect') {
        let v = 0.0;
        for (const newFi of dests) {
          v += this._dp[this._idx(nst, ncs, newFi * 4 + si, nr, turnsLeftAfter)]! / nDests;
        }
        return v;
      }
      if (o.key === 'change_second_effect') {
        let v = 0.0;
        for (const newSi of dests) {
          v += this._dp[this._idx(nst, ncs, fi * 4 + newSi, nr, turnsLeftAfter)]! / nDests;
        }
        return v;
      }
      return this._dp[this._idx(nst, ncs, fi * 4 + si, nr, turnsLeftAfter)]!;
    }
    let nr = 0;
    if (this._maxRerolls > 0) {
      const r = rerolls ?? 0;
      const vd = o.kind === 'view' ? o.delta : 0;
      nr = Math.min(this._maxRerolls, r + vd);
    }
    return this._dp[this._idx(nst, ncs, 0, nr, turnsLeftAfter)]!;
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
      total += this.probAfterOption(state, o, turnsLeftAfter, rerolls);
    }
    return total / offers.length;
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
// choice as E[max(hand mean, threshold)] with the same hand model as the
// goal table (handEMax); maxRerolls === 0 builds the flat table.

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
//   [prob, optionKey, optionKind, nw, nc, nf, ns, ncs]
type SvTransEntry = [number, string, string, number, number, number, number, number];

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
  private _changeDests: (number[] | null)[];
  // Flat DP storage, index layout (state625, cs, fi*4+si, r, tl) — mirrors
  // the Python tuple keys (see GoalProbabilityTable._idx).
  private _dp: Float64Array;
  private readonly _rDim: number;
  private readonly _tlDim: number;

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

    this._rDim = this._maxRerolls > 0 ? this._maxRerolls + 1 : 1;
    this._tlDim = maxTurns + 1;
    // Unwritten slots stay 0.0, matching Python's dict .get(key, 0.0).
    // (Disabled tables keep an empty array — lookups return 0 before access.)
    this._dp = new Float64Array(
      this.enabled ? 625 * 2 * 16 * this._rDim * this._tlDim : 0);

    if (!this.enabled) {
      this._effectTuple = [];
      this._effectCoeffs = [];
      this._changeDests = new Array(16).fill(null);
      return;
    }

    const effects = GEM_TYPES[gemType]!;
    const coeffMap = this._optimize === 'dps' ? DPS_COEFF : SUPPORT_COEFF;
    const targetSet = this._optimize === 'dps' ? DPS_EFFECTS : SUPPORT_EFFECTS;
    this._effectTuple = effects;
    this._effectCoeffs = effects.map((e) => (targetSet.has(e) ? (coeffMap[e] ?? 0) : 0));
    this._changeDests = new Array(16).fill(null);
    for (let fi = 0; fi < 4; fi++) {
      for (let si = 0; si < 4; si++) {
        if (fi === si) continue;
        const dests: number[] = [];
        for (let i = 0; i < 4; i++) {
          if (i !== fi && i !== si) dests.push(i);
        }
        this._changeDests[fi * 4 + si] = dests;
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
    cs: number,
    turn: number,
    turnsLeft: number
  ): SvTransEntry[] {
    const state = new GemState({ will: w, chaos: c, first: f, second: s, costRatio: cs ? 100 : 0 });
    const eligible = this._pool.pool.filter((o) => this._pool.eligible(o, state, turn, turnsLeft));
    if (eligible.length === 0) {
      return [[1.0, '', '', w, c, f, s, cs]];
    }
    const probs = appliedProbs(eligible.map((o) => o.weight));
    const result: SvTransEntry[] = [];
    for (let i = 0; i < eligible.length; i++) {
      const o = eligible[i]!;
      const p = probs[i]!;
      let nw = w, nc = c, nf = f, ns = s, ncs = cs;
      if (o.kind === 'will') nw = clampLevel(w + o.delta);
      else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
      else if (o.kind === 'first') nf = clampLevel(f + o.delta);
      else if (o.kind === 'second') ns = clampLevel(s + o.delta);
      else if (o.kind === 'cost') ncs = 1 - cs;
      // view/other/maintain -> no state change
      result.push([p, o.key, o.kind, nw, nc, nf, ns, ncs]);
    }
    return result;
  }

  // Flat-array index (state625, cs, fi*4+si, r, tl).
  private _idx(st: number, cs: number, ea: number, r: number, tl: number): number {
    return (((st * 2 + cs) * 16 + ea) * this._rDim + r) * this._tlDim + tl;
  }

  // V at a transition destination *in array `dpd`*, routing change_effect
  // uniformly across the two non-equipped pool members. Parameterizing the
  // array lets _buildPolicyEval read its two coupled tables (policy, display).
  private _postValIn(
    dpd: Float64Array,
    optKey: string,
    nst: number,
    ncs: number,
    fi: number,
    si: number,
    dests: number[],
    nd: number,
    tl: number
  ): number {
    if (optKey === 'change_first_effect') {
      let v = 0.0;
      for (const d of dests) {
        v += dpd[this._idx(nst, ncs, d * 4 + si, 0, tl)]!;
      }
      return v / nd;
    }
    if (optKey === 'change_second_effect') {
      let v = 0.0;
      for (const d of dests) {
        v += dpd[this._idx(nst, ncs, fi * 4 + d, 0, tl)]!;
      }
      return v / nd;
    }
    return dpd[this._idx(nst, ncs, fi * 4 + si, 0, tl)]!;
  }

  private _postVal(
    optKey: string,
    nst: number,
    ncs: number,
    fi: number,
    si: number,
    dests: number[],
    nd: number,
    tl: number
  ): number {
    return this._postValIn(this._dp, optKey, nst, ncs, fi, si, dests, nd, tl);
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
            const st = s625(w, c, f, s);
            for (const [fi, si] of validPairs) {
              const v = this._gemValueIdx(w, c, f, s, fi, si);
              for (let cs = 0; cs <= 1; cs++) {
                dp[this._idx(st, cs, fi * 4 + si, 0, 0)] = v;
              }
            }
          }
        }
      }
    }

    // Option-level transition cache (independent of fi/si).
    // Mirror Python's three-label cache strategy, per cost state.
    const transCache: Record<string, SvTransEntry[][]> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      for (let cs = 0; cs <= 1; cs++) {
        const cache: SvTransEntry[][] = new Array(625);
        for (let w = 1; w <= 5; w++) {
          for (let c = 1; c <= 5; c++) {
            for (let f = 1; f <= 5; f++) {
              for (let s = 1; s <= 5; s++) {
                cache[s625(w, c, f, s)] = this._transitions(w, c, f, s, cs, turn, tl);
              }
            }
          }
        }
        transCache[`${label},${cs}`] = cache;
      }
    }

    // Backward induction: V = max(finish now, process).
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let label: string;
      if (turnNumber === 1) label = 'first';
      else if (tl === 1) label = 'last';
      else label = 'middle';

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++) {
                const trans = transCache[`${label},${cs}`]![st]!;
                for (const [fi, si] of validPairs) {
                  const dests = this._changeDests[fi * 4 + si]!;
                  const nd = dests.length;
                  const finishVal = this._gemValueIdx(w, c, f, s, fi, si);
                  let proc = 0.0;
                  for (const [p, optKey, , nw, nc, nf, ns, ncs] of trans) {
                    proc += p * this._postVal(optKey, s625(nw, nc, nf, ns), ncs, fi, si, dests, nd, tl - 1);
                  }
                  dp[this._idx(st, cs, fi * 4 + si, 0, tl)] = finishVal > proc ? finishVal : proc;
                }
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
    const dpW = new Float64Array(dpS.length);
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
            const st = s625(w, c, f, s);
            for (const [fi, si] of validPairs) {
              const v = this._gemValueIdx(w, c, f, s, fi, si);
              for (let cs = 0; cs <= 1; cs++) {
                dpW[this._idx(st, cs, fi * 4 + si, 0, 0)] = fw;
                dpS[this._idx(st, cs, fi * 4 + si, 0, 0)] = v;
              }
            }
          }
        }
      }
    }

    // Option-level transition cache (same three-turn-type strategy as _build).
    const transCache: Record<string, SvTransEntry[][]> = {};
    const turnSpecs: [string, number, number][] = [
      ['first', 1, mt],
      ['last', mt, 1],
      ['middle', 2, mt > 2 ? mt - 1 : 2],
    ];
    for (const [label, turn, tl] of turnSpecs) {
      for (let cs = 0; cs <= 1; cs++) {
        const cache: SvTransEntry[][] = new Array(625);
        for (let w = 1; w <= 5; w++) {
          for (let c = 1; c <= 5; c++) {
            for (let f = 1; f <= 5; f++) {
              for (let s = 1; s <= 5; s++) {
                cache[s625(w, c, f, s)] = this._transitions(w, c, f, s, cs, turn, tl);
              }
            }
          }
        }
        transCache[`${label},${cs}`] = cache;
      }
    }

    // Backward induction: follow the will_chaos finish-vs-continue choice.
    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      let label: string;
      if (turnNumber === 1) label = 'first';
      else if (tl === 1) label = 'last';
      else label = 'middle';

      for (let w = 1; w <= 5; w++) {
        for (let c = 1; c <= 5; c++) {
          for (let f = 1; f <= 5; f++) {
            for (let s = 1; s <= 5; s++) {
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++) {
                const trans = transCache[`${label},${cs}`]![st]!;
                for (const [fi, si] of validPairs) {
                  const dests = this._changeDests[fi * 4 + si]!;
                  const nd = dests.length;
                  const finishW = wcFinish(w, c, f, s);
                  const finishS = this._gemValueIdx(w, c, f, s, fi, si);
                  let procW = 0.0;
                  let procS = 0.0;
                  for (const [p, optKey, , nw, nc, nf, ns, ncs] of trans) {
                    const nst = s625(nw, nc, nf, ns);
                    procW += p * this._postValIn(dpW, optKey, nst, ncs, fi, si, dests, nd, tl - 1);
                    procS += p * this._postValIn(dpS, optKey, nst, ncs, fi, si, dests, nd, tl - 1);
                  }
                  const ea = fi * 4 + si;
                  if (finishW >= procW) {
                    dpW[this._idx(st, cs, ea, 0, tl)] = finishW;
                    dpS[this._idx(st, cs, ea, 0, tl)] = finishS;
                  } else {
                    dpW[this._idx(st, cs, ea, 0, tl)] = procW;
                    dpS[this._idx(st, cs, ea, 0, tl)] = procS;
                  }
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
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++)
                for (let r = 0; r <= maxR; r++) dp[this._idx(st, cs, fi * 4 + si, r, 0)] = v;
            }

    type RTrans = [number, string, string, number, number, number, number, number, number];
    const transitions = (w: number, c: number, f: number, s: number, cs: number,
                         turn: number, tl: number): RTrans[] => {
      const state = new GemState({ will: w, chaos: c, first: f, second: s, costRatio: cs ? 100 : 0 });
      const elig = this._pool.pool.filter((o) => this._pool.eligible(o, state, turn, tl));
      if (elig.length === 0) return [[1.0, '', '', w, c, f, s, cs, 0]];
      const probs = appliedProbs(elig.map((o) => o.weight));
      const out: RTrans[] = [];
      for (let i = 0; i < elig.length; i++) {
        const o = elig[i]!;
        let nw = w, nc = c, nf = f, ns = s, ncs = cs, vd = 0;
        if (o.kind === 'will') nw = clampLevel(w + o.delta);
        else if (o.kind === 'chaos') nc = clampLevel(c + o.delta);
        else if (o.kind === 'first') nf = clampLevel(f + o.delta);
        else if (o.kind === 'second') ns = clampLevel(s + o.delta);
        else if (o.kind === 'view') vd = o.delta;
        else if (o.kind === 'cost') ncs = 1 - cs;
        out.push([probs[i]!, o.key, o.kind, nw, nc, nf, ns, ncs, vd]);
      }
      return out;
    };

    const labels: [string, number, number][] = [
      ['first', 1, mt], ['last', mt, 1], ['middle', 2, mt > 2 ? mt - 1 : 2]];
    const transCache: Record<string, RTrans[][]> = {};
    for (const [label, turn, tl] of labels) {
      for (let cs = 0; cs <= 1; cs++) {
        const cache: RTrans[][] = new Array(625);
        for (let w = 1; w <= 5; w++)
          for (let c = 1; c <= 5; c++)
            for (let f = 1; f <= 5; f++)
              for (let s = 1; s <= 5; s++)
                cache[s625(w, c, f, s)] = transitions(w, c, f, s, cs, turn, tl);
        transCache[`${label},${cs}`] = cache;
      }
    }

    const handCache = handContexts(this._pool, mt);
    const cd = this._changeDests;
    const postVal = (optKey: string, nst: number,
                     ncs: number, fi: number, si: number, nr: number, tl: number): number => {
      if (optKey === 'change_first_effect') {
        const d = cd[fi * 4 + si]!;
        let sum = 0;
        for (const di of d) sum += dp[this._idx(nst, ncs, di * 4 + si, nr, tl)]!;
        return sum / d.length;
      }
      if (optKey === 'change_second_effect') {
        const d = cd[fi * 4 + si]!;
        let sum = 0;
        for (const di of d) sum += dp[this._idx(nst, ncs, fi * 4 + di, nr, tl)]!;
        return sum / d.length;
      }
      return dp[this._idx(nst, ncs, fi * 4 + si, nr, tl)]!;
    };

    for (let tl = 1; tl <= mt; tl++) {
      const turnNumber = mt - tl + 1;
      const label = turnNumber === 1 ? 'first' : tl === 1 ? 'last' : 'middle';
      for (let w = 1; w <= 5; w++)
        for (let c = 1; c <= 5; c++)
          for (let f = 1; f <= 5; f++)
            for (let s = 1; s <= 5; s++) {
              const st = s625(w, c, f, s);
              for (let cs = 0; cs <= 1; cs++) {
                const trans = transCache[`${label},${cs}`]![st]!;
                const hand = handCache[`${label},${cs}`]![st]!;
                for (const [fi, si] of validPairs) {
                  const finishVal = this._gemValueIdx(w, c, f, s, fi, si);
                  for (let r = 0; r <= maxR; r++) {
                    const posts: number[] = [];
                    for (const [, optKey, , nw, nc, nf, ns, ncs, vd] of trans) {
                      const nr = Math.min(maxR, r + vd);
                      posts.push(postVal(optKey, s625(nw, nc, nf, ns), ncs, fi, si, nr, tl - 1));
                    }
                    // The hand is weighed against the best alternative:
                    // finishing now, or (with a reroll in hand) redrawing.
                    let t: number;
                    if (r > 0 && turnNumber !== 1) {
                      const rc = dp[this._idx(st, cs, fi * 4 + si, r - 1, tl)]!;
                      t = finishVal > rc ? finishVal : rc;
                    } else {
                      t = finishVal;
                    }
                    dp[this._idx(st, cs, fi * 4 + si, r, tl)] = handTurnValue(hand, posts, t);
                  }
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
    if (turnsLeft < 0 || turnsLeft >= this._tlDim) return 0.0;
    const idx = this._effectIndices(state);
    if (idx === null) return 0.0;
    const [fi, si] = idx;
    const st = s625(state.will, state.chaos, state.first, state.second);
    const cs = state.costRatio !== 0 ? 1 : 0;
    const r = this._maxRerolls > 0 ? Math.min(this._maxRerolls, rerolls ?? 0) : 0;
    return this._dp[this._idx(st, cs, fi * 4 + si, r, turnsLeft)]!;
  }

  /** Mean V across the 4 actual visible offers (uniform 25% pick).
   *  Mirrors GoalProbabilityTable.expectedProbAfterClick — the process-EV
   *  term of the finish decision uses the real offers, not the pool-wide
   *  expectation the table is built with.
   */
  expectedValueAfterClick(state: GemState, offers: Option[], turnsLeftAfter: number,
                          rerolls?: number): number {
    if (!this.enabled || offers.length === 0) return 0.0;
    if (turnsLeftAfter < 0 || turnsLeftAfter >= this._tlDim) return 0.0;
    const idx = this._effectIndices(state);
    if (idx === null) return 0.0;
    const [fi, si] = idx;
    const dests = this._changeDests[fi * 4 + si]!;
    const nd = dests.length;
    const ra = this._maxRerolls > 0;
    const cs = state.costRatio !== 0 ? 1 : 0;
    let total = 0.0;
    for (const o of offers) {
      const nw = o.kind === 'will' ? clampLevel(state.will + o.delta) : state.will;
      const nc = o.kind === 'chaos' ? clampLevel(state.chaos + o.delta) : state.chaos;
      const nf = o.kind === 'first' ? clampLevel(state.first + o.delta) : state.first;
      const ns = o.kind === 'second' ? clampLevel(state.second + o.delta) : state.second;
      const ncs = o.kind === 'cost' ? 1 - cs : cs;
      const nst = s625(nw, nc, nf, ns);
      let nr = 0;
      if (ra) {
        const vd = o.kind === 'view' ? o.delta : 0;
        nr = Math.min(this._maxRerolls, (rerolls ?? 0) + vd);
      }
      if (o.key === 'change_first_effect') {
        let sum = 0;
        for (const d of dests) sum += this._dp[this._idx(nst, ncs, d * 4 + si, nr, turnsLeftAfter)]!;
        total += sum / nd;
      } else if (o.key === 'change_second_effect') {
        let sum = 0;
        for (const d of dests) sum += this._dp[this._idx(nst, ncs, fi * 4 + d, nr, turnsLeftAfter)]!;
        total += sum / nd;
      } else {
        total += this._dp[this._idx(nst, ncs, fi * 4 + si, nr, turnsLeftAfter)]!;
      }
    }
    return total / offers.length;
  }
}
