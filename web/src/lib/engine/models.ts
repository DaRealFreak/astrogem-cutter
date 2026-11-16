// Port of arkgrid/models.py (Option, LastTurnGoal, GemState, AstroGem)
// RunResult is simulator-only and not ported here.

// ---------------------------------------------------------------------------
// Option
// ---------------------------------------------------------------------------

export interface Option {
  key: string;
  weight: number;
  kind: string;
  delta: number;
  resolvedEffect: string;
}

export function makeOption(
  key: string,
  weight: number,
  kind: string,
  delta = 0,
  resolvedEffect = ""
): Option {
  return { key, weight, kind, delta, resolvedEffect };
}

// ---------------------------------------------------------------------------
// LastTurnGoal
// ---------------------------------------------------------------------------

export interface GoalFields {
  minWill?: number;
  minChaos?: number;
  exactWill?: number;
  exactChaos?: number;
  minTotalWillChaos?: number;
  exactTotalWillChaos?: number;
  minFirst?: number;
  minSecond?: number;
  minTotal?: number;
}

export class LastTurnGoal {
  readonly minWill: number | undefined;
  readonly minChaos: number | undefined;
  readonly exactWill: number | undefined;
  readonly exactChaos: number | undefined;
  readonly minTotalWillChaos: number | undefined;
  readonly exactTotalWillChaos: number | undefined;
  readonly minFirst: number | undefined;
  readonly minSecond: number | undefined;
  readonly minTotal: number | undefined;

  constructor(fields?: GoalFields) {
    this.minWill = fields?.minWill;
    this.minChaos = fields?.minChaos;
    this.exactWill = fields?.exactWill;
    this.exactChaos = fields?.exactChaos;
    this.minTotalWillChaos = fields?.minTotalWillChaos;
    this.exactTotalWillChaos = fields?.exactTotalWillChaos;
    this.minFirst = fields?.minFirst;
    this.minSecond = fields?.minSecond;
    this.minTotal = fields?.minTotal;
  }

  /**
   * Port of models.py:30-55.
   * Defaults: first=5, second=5 (match Python signature).
   */
  satisfied(will: number, chaos: number, first = 5, second = 5): boolean {
    if (this.exactWill !== undefined && will !== this.exactWill) return false;
    if (this.exactChaos !== undefined && chaos !== this.exactChaos) return false;
    if (this.minWill !== undefined && will < this.minWill) return false;
    if (this.minChaos !== undefined && chaos < this.minChaos) return false;

    const total = will + chaos;
    if (this.exactTotalWillChaos !== undefined && total !== this.exactTotalWillChaos) return false;
    if (this.minTotalWillChaos !== undefined && total < this.minTotalWillChaos) return false;

    if (this.minFirst !== undefined && first < this.minFirst) return false;
    if (this.minSecond !== undefined && second < this.minSecond) return false;

    if (this.minTotal !== undefined && (will + chaos + first + second) < this.minTotal) return false;

    return true;
  }

  /**
   * Port of models.py:57-165.
   * Defaults: first=1, second=1, minSideCoeff=0, sideCoeffFirst=0, sideCoeffSecond=0,
   *           changeDestCoeffs=[0, 0].
   */
  feasible(
    will: number,
    chaos: number,
    turnsLeft: number,
    first = 1,
    second = 1,
    opts?: {
      minSideCoeff?: number;
      sideCoeffFirst?: number;
      sideCoeffSecond?: number;
      changeDestCoeffs?: readonly [number, number];
    }
  ): boolean {
    const minSideCoeff = opts?.minSideCoeff ?? 0;
    const sideCoeffFirst = opts?.sideCoeffFirst ?? 0;
    const sideCoeffSecond = opts?.sideCoeffSecond ?? 0;
    const changeDestCoeffs = opts?.changeDestCoeffs ?? [0, 0];

    const targetW = this.exactWill !== undefined ? this.exactWill : this.minWill;
    const targetC = this.exactChaos !== undefined ? this.exactChaos : this.minChaos;

    if (targetW !== undefined && targetW > 5) return false;
    if (targetC !== undefined && targetC > 5) return false;

    if (this.minTotalWillChaos !== undefined && this.minTotalWillChaos > 10) return false;
    if (this.exactTotalWillChaos !== undefined && this.exactTotalWillChaos > 10) return false;

    if (this.exactWill !== undefined && will > this.exactWill) return false;
    if (this.exactChaos !== undefined && chaos > this.exactChaos) return false;

    const reqW = targetW !== undefined ? Math.max(0, targetW - will) : 0;
    const reqC = targetC !== undefined ? Math.max(0, targetC - chaos) : 0;

    if (will + reqW > 5) return false;
    if (chaos + reqC > 5) return false;

    const reqF = this.minFirst !== undefined ? Math.max(0, this.minFirst - first) : 0;
    const reqS = this.minSecond !== undefined ? Math.max(0, this.minSecond - second) : 0;

    if (this.minFirst !== undefined && this.minFirst > 5) return false;
    if (this.minSecond !== undefined && this.minSecond > 5) return false;

    const turnsNeededW = reqW > 0 ? Math.ceil(reqW / 4) : 0;
    const turnsNeededC = reqC > 0 ? Math.ceil(reqC / 4) : 0;
    const turnsNeededF = reqF > 0 ? Math.ceil(reqF / 4) : 0;
    const turnsNeededS = reqS > 0 ? Math.ceil(reqS / 4) : 0;
    if (turnsNeededW + turnsNeededC + turnsNeededF + turnsNeededS > turnsLeft) return false;

    // Optional total constraints (loose safe bound)
    const total = will + chaos;
    if (this.exactTotalWillChaos !== undefined) {
      if (total > this.exactTotalWillChaos) return false;
      const reqTotal = this.exactTotalWillChaos - total;
      if (Math.ceil(Math.max(0, reqTotal) / 4) > turnsLeft) return false;
    }

    if (this.minTotalWillChaos !== undefined) {
      const reqTotal = this.minTotalWillChaos - total;
      if (Math.ceil(Math.max(0, reqTotal) / 4) > turnsLeft) return false;
    }

    if (this.minTotal !== undefined) {
      const currentTotal = will + chaos + first + second;
      const maxPossible = Math.min(20, currentTotal + 4 * turnsLeft);
      if (maxPossible < this.minTotal) return false;
    }

    if (minSideCoeff > 0) {
      // Upper bound on achievable side_coeff in remaining turns.
      // `available` is loose: shared between first/second leveling and
      // the change_effect option below (will/chaos turns are deducted).
      const available = turnsLeft - turnsNeededW - turnsNeededC;
      if (available < 0) return false;

      // Effect arrangements (first-slot coeff, second-slot coeff)
      // reachable after exactly k change_*_effect turns, with A/B the
      // equipped effects and C/D the two non-equipped pool members.
      // A change draws from the effects not currently equipped, so a
      // second change can pull the just-dropped effect into the other
      // slot, and a third completes the set with the full swap (B, A).
      // Each row lists only the arrangements NEW at that k: fewer
      // changes leave more levelling turns, so earlier rows dominate.
      const ca = sideCoeffFirst, cb = sideCoeffSecond;
      const [cc, cd] = changeDestCoeffs;
      const reach: [number, number][][] = [
        [[ca, cb]],
        [[cc, cb], [cd, cb], [ca, cc], [ca, cd]],
        [[cc, ca], [cd, ca], [cc, cd], [cd, cc], [cb, cc], [cb, cd]],
        [[cb, ca]],
      ];
      let upper = 0;
      for (let k = 0; k <= Math.min(available, 3); k++) {
        const rest = available - k;
        const lvlFirst = Math.min(5, first + 4 * rest);
        const lvlSecond = Math.min(5, second + 4 * rest);
        for (const [c1, c2] of reach[k]!) {
          upper = Math.max(upper, c1 * lvlFirst + c2 * lvlSecond);
        }
      }

      if (upper < minSideCoeff) return false;
    }

    return true;
  }
}

// ---------------------------------------------------------------------------
// AstroGem
// ---------------------------------------------------------------------------

export interface AstroGem {
  gemType: string;
  firstEffect: string;
  secondEffect: string;
  optimize: string;
}

// ---------------------------------------------------------------------------
// GemState
// ---------------------------------------------------------------------------

export class GemState {
  will: number;
  chaos: number;
  first: number;
  second: number;
  costRatio: number;
  rerolls: number;
  firstEffect: string;
  secondEffect: string;

  constructor(
    init?: Partial<{
      will: number;
      chaos: number;
      first: number;
      second: number;
      costRatio: number;
      rerolls: number;
      firstEffect: string;
      secondEffect: string;
    }>
  ) {
    this.will = init?.will ?? 1;
    this.chaos = init?.chaos ?? 1;
    this.first = init?.first ?? 1;
    this.second = init?.second ?? 1;
    this.costRatio = init?.costRatio ?? 0;
    this.rerolls = init?.rerolls ?? 0;
    this.firstEffect = init?.firstEffect ?? "";
    this.secondEffect = init?.secondEffect ?? "";
  }

  clone(): GemState {
    return new GemState({
      will: this.will,
      chaos: this.chaos,
      first: this.first,
      second: this.second,
      costRatio: this.costRatio,
      rerolls: this.rerolls,
      firstEffect: this.firstEffect,
      secondEffect: this.secondEffect,
    });
  }

  totalPoints(): number {
    return this.will + this.chaos + this.first + this.second;
  }
}
