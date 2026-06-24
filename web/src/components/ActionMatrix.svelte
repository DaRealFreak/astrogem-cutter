<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { actions, recommended }: { actions: AdvisorOutput['actions']; recommended: string } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  const rows = $derived([
    { key: 'PROCESS', label: 'Process', m: actions.process },
    { key: 'REROLL', label: 'Reroll', m: actions.reroll },
    { key: 'RESET', label: 'Reset', m: actions.reset },
  ]);
</script>

<table class="action-matrix">
  <thead><tr><th>Action</th><th>P(goal)</th><th>P(relic+)</th><th>P(ancient)</th><th>E[coeff]</th></tr></thead>
  <tbody>
    {#each rows as r}
      <tr class:recommended={r.key === recommended}>
        <td>{r.label}</td>
        {#if r.m}
          <td>{pct(r.m.pGoal)}</td><td>{pct(r.m.pRelic)}</td><td>{pct(r.m.pAncient)}</td><td>{r.m.eValue.toFixed(1)}</td>
        {:else}
          <td>—</td><td>—</td><td>—</td><td>—</td>
        {/if}
      </tr>
    {/each}
  </tbody>
</table>
