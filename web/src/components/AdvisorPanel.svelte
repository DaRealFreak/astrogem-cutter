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
      <div><dt title="Chance of reaching the goal if you stop the moment it is met.">P(goal)</dt><dd>{pct(output.pGoal)}</dd></div>
      <div><dt title="What following this advice actually delivers: it keeps cutting for side value after the goal is met (and can lose it), and it uses the reset ticket while one is available. A little below P(goal) without a reset, well above it with one.">P(bot)</dt><dd>{pct(output.pBot)}</dd></div>
      <div><dt>P(relic+)</dt><dd>{pct(output.pRelic)}</dd></div>
      <div><dt>P(ancient)</dt><dd>{pct(output.pAncient)}</dd></div>
      <div><dt>E[coeff]</dt><dd>{output.eValue.toFixed(1)}</dd></div>
    </dl>
  </div>
{/if}
