<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { output, waiting, recomputing = false }:
    { output: AdvisorOutput | null; waiting: boolean; recomputing?: boolean } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
</script>

{#if waiting || !output}
  <div class="advisor waiting card"><p>Waiting for cutting screen…</p></div>
{:else}
  <div class="advisor card" class:recomputing>
    {#if recomputing}
      <div class="recalculating" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>Recalculating odds…
      </div>
    {/if}
    <div class="action action-{output.action} badge">{output.action.toUpperCase()}</div>
    {#if output.action === 'reroll' && output.ticket?.lent && output.ticket.free === 0}
      <p class="ticket-note">No free rerolls left — this reroll spends the reroll ticket (yellow Charge button, costs gold).</p>
    {/if}
    <p class="reason">{output.reason}</p>
    <dl class="metrics">
      <div><dt>P(goal)</dt><dd>{pct(output.pGoal)}</dd></div>
      <div><dt>P(relic+)</dt><dd>{pct(output.pRelic)}</dd></div>
      <div><dt>P(ancient)</dt><dd>{pct(output.pAncient)}</dd></div>
      <div><dt>E[coeff]</dt><dd>{output.eValue.toFixed(1)}</dd></div>
    </dl>
  </div>
{/if}
