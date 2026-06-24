<script lang="ts">
  import { config } from '../lib/state/config.state.svelte';
  const c = config;   // c.current is the reactive, bindable store value
</script>

<section class="config">
  <h2>Goal</h2>
  <!-- Explicit for/id associations used to ensure getByLabelText works reliably in testing-library -->
  <label for="min-will">Min will</label>
  <input id="min-will" type="number" min="0" max="5" bind:value={c.current.minWill} />
  <label for="min-chaos">Min chaos</label>
  <input id="min-chaos" type="number" min="0" max="5" bind:value={c.current.minChaos} />
  <label for="min-first">Min 1st node</label>
  <input id="min-first" type="number" min="0" max="5" bind:value={c.current.minFirst} />
  <label for="min-second">Min 2nd node</label>
  <input id="min-second" type="number" min="0" max="5" bind:value={c.current.minSecond} />
  <label for="min-side-coeff">Min side coeff</label>
  <input id="min-side-coeff" type="number" min="0" step="any" bind:value={c.current.minSideCoeff} />

  <h2>Grade</h2>
  <label for="rarity">Rarity</label>
  <select id="rarity" bind:value={c.current.rarityOverride}>
    <option value="auto">Auto (detected)</option>
    <option value="common">Common (5)</option>
    <option value="rare">Rare (7)</option>
    <option value="epic">Epic (9)</option>
  </select>
  <label for="relic-coeff">Relic coeff</label>
  <input id="relic-coeff" type="number" step="any" placeholder="fusion default"
    value={c.current.relicCoeff ?? ''} oninput={(e) => c.current.relicCoeff = e.currentTarget.value === '' ? null : +e.currentTarget.value} />
  <label for="ancient-coeff">Ancient coeff</label>
  <input id="ancient-coeff" type="number" step="any" placeholder="fusion default"
    value={c.current.ancientCoeff ?? ''} oninput={(e) => c.current.ancientCoeff = e.currentTarget.value === '' ? null : +e.currentTarget.value} />

  <details class="advanced">
    <summary>Advanced</summary>
    <label for="endgame-risk">Endgame risk</label>
    <input id="endgame-risk" type="number" step="any" placeholder="auto-gate"
      value={c.current.endgameRisk ?? ''} oninput={(e) => c.current.endgameRisk = e.currentTarget.value === '' ? null : +e.currentTarget.value} />
    <label for="relic-reroll-threshold">Relic reroll threshold</label>
    <input id="relic-reroll-threshold" type="number" min="0" max="1" step="any" bind:value={c.current.relicRerollThreshold} />
    <label for="force-reroll-no-progress">Force reroll no-progress</label>
    <input id="force-reroll-no-progress" type="number" min="0" step="any" bind:value={c.current.forceRerollNoProgress} />
    <label for="extra-ticket">Extra ticket</label>
    <select id="extra-ticket" value={String(c.current.extraTicket)} onchange={(e) => {
      const v = e.currentTarget.value; c.current.extraTicket = v === 'true' ? true : v === 'false' ? false : null;
    }}>
      <option value="null">Armed (off, enable on signal)</option>
      <option value="true">On</option>
      <option value="false">Off (hard)</option>
    </select>
    <label for="optimize">Optimize</label>
    <select id="optimize" bind:value={c.current.optimizeOverride}>
      <option value="auto">Auto (from effects)</option>
      <option value="dps">DPS</option>
      <option value="support">Support</option>
    </select>
    <label for="ignore-side-node-values"><input id="ignore-side-node-values" type="checkbox" bind:checked={c.current.ignoreSideNodeValues} /> Ignore side-node values</label>
    <label for="reset-override">Reset available</label>
    <select id="reset-override" bind:value={c.current.resetOverride}>
      <option value="auto">Auto (turn 1)</option>
      <option value="always">Always</option>
      <option value="never">Never</option>
    </select>
  </details>
</section>
