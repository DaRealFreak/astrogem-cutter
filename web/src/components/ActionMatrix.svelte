<script lang="ts">
  import type { AdvisorOutput, ActionsMap } from '../lib/engine';
  let { actions, recommended, ticket = null }: {
    actions: ActionsMap;
    recommended: string;
    ticket?: AdvisorOutput['ticket'];
  } = $props();
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  const rowsOf = (a: ActionsMap) => [
    { key: 'PROCESS', label: 'Process', m: a.process },
    { key: 'REROLL', label: 'Reroll', m: a.reroll },
    { key: 'RESET', label: 'Reset', m: a.reset },
  ];
</script>

{#snippet matrix(a: ActionsMap, highlight: boolean)}
  <table class="action-matrix">
    <thead><tr><th>Action</th><th>P(goal)</th><th>P(relic+)</th><th>P(ancient)</th><th>E[coeff]</th></tr></thead>
    <tbody>
      {#each rowsOf(a) as r (r.key)}
        <tr class:recommended={highlight && r.key === recommended}>
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
{/snippet}

{#if ticket}
  <!-- Owned extra ticket: show both budgets. A "✓ recommended" badge marks the
       budget the advice actually used; when the ticket is known spent this run,
       the With-extra column is greyed and captioned "already used". -->
  <div class="matrix-pair">
    <div class="matrix-variant">
      <div class="matrix-caption">Without extra reroll{!ticket.lent ? ' ✓ recommended' : ''}</div>
      {@render matrix(ticket.withoutTicket.actions, !ticket.lent)}
    </div>
    <div class="matrix-variant" class:spent={ticket.spent}>
      <div class="matrix-caption">With extra reroll{ticket.lent ? ' ✓ recommended' : ''}{ticket.spent ? ' — already used this gem' : ''}</div>
      {@render matrix(ticket.withTicket.actions, ticket.lent)}
    </div>
  </div>
{:else}
  {@render matrix(actions, true)}
{/if}

<style>
  .matrix-variant.spent { opacity: 0.5; }
  .matrix-variant.spent .matrix-caption { font-style: italic; }
</style>
