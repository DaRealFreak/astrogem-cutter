<script lang="ts">
  import type { AdvisorOutput } from '../lib/engine';
  let { perOffer }: { perOffer: AdvisorOutput['perOffer'] } = $props();
  const favored = $derived(
    perOffer.length === 0 ? -1
      : perOffer.reduce((best, o, i, a) => (o.pGoalAfter > a[best].pGoalAfter ? i : best), 0),
  );
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
</script>

<table class="offers">
  <thead><tr><th>Offer</th><th>P(goal) after</th><th>E[coeff] after</th></tr></thead>
  <tbody>
    {#each perOffer as o, i}
      <tr class:favored={i === favored}>
        <td>{o.key}</td><td>{pct(o.pGoalAfter)}</td><td>{o.eValueAfter.toFixed(1)}</td>
      </tr>
    {/each}
  </tbody>
</table>
