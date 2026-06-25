import type { DetectionResult } from '../cv/types';
import { detectionToEngineInputs } from '../cv/adapter';
import { buildEngineContext, advise, type EngineContext, type AdvisorOutput, type ActionsSnapshot } from '../engine';
import { ticketEnabled } from '../engine/decision';
import { isCompleteDetection } from './optimize';
import { resolveResetAvailable } from './runTransition';
import { ticketAvailableFromDetection } from './ticket';
import { effectiveConfig, type AdvisorStoredConfig } from '../state/config';

let cache: { key: string; ctx: EngineContext } | null = null;
export function resetAdviceCache(): void { cache = null; }

export function computeAdvice(
  det: DetectionResult, stored: AdvisorStoredConfig, resetObserved = false, ticketSpent = false,
): { ready: boolean; output: AdvisorOutput | null } {
  if (!isCompleteDetection(det)) return { ready: false, output: null };

  const eff = effectiveConfig(stored, det);
  // Detected/overridden availability, then gated by the reset coeff + rarity policy.
  const resetAvailable =
    resolveResetAvailable(det.resetEnabled, resetObserved, eff.resetOverride) && eff.resetPolicyAllowed;

  // extraTicket=false here: inputs.rerolls is the FREE on-screen reroll count.
  // The extra ticket is lent per frame below (never folded into the count).
  const inputs = detectionToEngineInputs(det, {
    optimize: eff.optimize,
    extraTicket: false,
    resetAvailable,
  });

  const key = JSON.stringify([
    inputs.gem.gemType, inputs.gem.firstEffect, inputs.gem.secondEffect, eff.advisorConfig,
  ]);
  if (!cache || cache.key !== key) {
    cache = { key, ctx: buildEngineContext(inputs.gem, eff.advisorConfig) };
  }

  // Per-frame extra-ticket lend: the ticket adds +1 to the decision budget only
  // when the player owns it (tri-state !== false), it is still available on the
  // screen (Charge button up / free rerolls remain), and an enabler clears its
  // bar this frame. On a dead gem the enablers go false, so it is not lent.
  const free = inputs.rerolls;
  const owned = eff.advisorConfig.extraTicket !== false;
  const available = owned && !ticketSpent && ticketAvailableFromDetection(det, free);
  const lent = available
    && ticketEnabled(cache.ctx._decisionCtx, inputs.state, inputs.turnsLeft, free);
  const rerolls = free + (lent ? 1 : 0);

  const adviseAt = (r: number) => advise(cache!.ctx, {
    state: inputs.state, offers: inputs.offers, turn: inputs.turn,
    turnsLeft: inputs.turnsLeft, rerolls: r, resetAvailable: inputs.resetAvailable,
  });
  const output = adviseAt(rerolls);

  // With/without-ticket comparison (for the matrix) — only when the player owns
  // the ticket. Reuse the primary output for whichever budget it already used.
  if (owned) {
    const snap = (o: AdvisorOutput): ActionsSnapshot => ({
      pGoal: o.pGoal, pRelic: o.pRelic, pAncient: o.pAncient, eValue: o.eValue, actions: o.actions,
    });
    const outFree = rerolls === free ? output : adviseAt(free);
    const outTicket = rerolls === free + 1 ? output : adviseAt(free + 1);
    output.ticket = {
      owned: true, lent, spent: ticketSpent, free,
      withoutTicket: snap(outFree), withTicket: snap(outTicket),
    };
  } else {
    output.ticket = null;
  }
  return { ready: true, output };
}
