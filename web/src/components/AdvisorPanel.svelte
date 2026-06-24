<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { output, waiting }: { output: AdvisorOutput | null; waiting: boolean } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
</script>

{#if waiting || !output}
  <div class="advisor waiting"><p>Waiting for cutting screen…</p></div>
{:else}
  <div class="advisor">
    <div class="action action-{output.action}">{output.action}</div>
    <p class="reason">{output.reason}</p>
    <dl class="metrics">
      <div><dt>P(goal)</dt><dd>{pct(output.pGoal)}</dd></div>
      <div><dt>P(relic+)</dt><dd>{pct(output.pRelic)}</dd></div>
      <div><dt>P(ancient)</dt><dd>{pct(output.pAncient)}</dd></div>
      <div><dt>E[coeff]</dt><dd>{output.eValue.toFixed(1)}</dd></div>
    </dl>
  </div>
{/if}
