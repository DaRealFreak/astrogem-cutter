<script lang="ts">
  import type { TurnLogEntry } from '../lib/state/turnLog.state.svelte';
  let { entries }: { entries: TurnLogEntry[] } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
</script>

{#if entries.length > 0}
  <table class="turn-log">
    <thead><tr><th>Turn</th><th>Will</th><th>Chaos</th><th>Action</th><th>P(goal)</th></tr></thead>
    <tbody>
      {#each entries as e}
        <tr><td>{e.turn}</td><td>{e.will}</td><td>{e.chaos}</td><td>{e.action}</td><td>{pct(e.pGoal)}</td></tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p class="turn-log empty">No turns recorded yet.</p>
{/if}
