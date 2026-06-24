<script lang="ts">
  import type { TurnLogEntry } from '../lib/state/turnLog.state.svelte';
  let { entries }: { entries: TurnLogEntry[] } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
</script>

{#if entries.length > 0}
  <table class="turn-log">
    <thead>
      <tr>
        <th>Turn</th><th>Will</th><th>Chaos</th><th>Side 1</th><th>Side 2</th>
        <th>Action</th><th>P(goal)</th><th>P(relic+)</th><th>P(ancient)</th><th>E[coeff]</th>
      </tr>
    </thead>
    <tbody>
      {#each entries as e}
        <tr>
          <td>{e.turn}</td><td>{e.will}</td><td>{e.chaos}</td><td>{e.firstLevel}</td><td>{e.secondLevel}</td>
          <td>{e.action}</td><td>{pct(e.pGoal)}</td><td>{pct(e.pRelic)}</td><td>{pct(e.pAncient)}</td><td>{e.eValue.toFixed(1)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p class="turn-log empty">No turns recorded yet.</p>
{/if}
