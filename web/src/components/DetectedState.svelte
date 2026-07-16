<script lang="ts">
  import type { DetectionResult } from '../lib/cv/types';
  import type { TicketComparison } from '../lib/engine';
  import { effectLabel } from '../lib/app/offerLabel';
  import { parseRerolls } from '../lib/cv/parse';
  let { detection, ticket = null }:
    { detection: DetectionResult | null; ticket?: TicketComparison | null } = $props();

  // Base free rerolls granted by the rarity (common 0 / rare 1 / epic 2),
  // derived from the detected total steps — mirrors the in-game counter's
  // "N / base" denominator so the display is verifiable against the screen.
  const BASE_REROLLS: Record<number, number> = { 5: 0, 7: 1, 9: 2 };

  // "free(+1)/base": detected free rerolls, "(+1)" while the reroll ticket is
  // lent to the decision budget this frame, "/base" the rarity's free-reroll
  // grant. E.g. "4(+1)/2". The raw template key stays in the tooltip.
  const rerollDisplay = $derived.by(() => {
    if (!detection || detection.rerolls == null) return '—';
    const free = parseRerolls(detection.rerolls, false);
    const lent = ticket?.lent ? '(+1)' : '';
    const base = BASE_REROLLS[detection.totalSteps ?? -1];
    return `${free}${lent}${base === undefined ? '' : `/${base}`}`;
  });
</script>

{#if detection}
  <dl class="detected">
    <div><dt>Gem</dt><dd>{detection.gemType ?? '—'} <span class="score">{detection.gemTypeScore.toFixed(2)}</span></dd></div>
    <div><dt>Will</dt><dd>{detection.willpower ?? '—'}</dd></div>
    <div><dt>Chaos</dt><dd>{detection.chaos ?? '—'}</dd></div>
    <div><dt>1st</dt><dd>{effectLabel(detection.firstEffect) || '—'} Lv{detection.firstLevel ?? '—'}</dd></div>
    <div><dt>2nd</dt><dd>{effectLabel(detection.secondEffect) || '—'} Lv{detection.secondLevel ?? '—'}</dd></div>
    <div><dt>Rerolls</dt><dd title={detection.rerolls ?? undefined}>{rerollDisplay}</dd></div>
    <div><dt>Reset</dt><dd>{detection.resetEnabled == null ? '—' : detection.resetEnabled ? 'available' : 'locked'}</dd></div>
    <div><dt>Charge</dt><dd>{detection.chargeEnabled == null ? '—' : detection.chargeEnabled ? 'available' : 'locked'}</dd></div>
    <div><dt>Step</dt><dd>{detection.currentStep ?? '—'}/{detection.totalSteps ?? '—'}</dd></div>
  </dl>
{/if}
