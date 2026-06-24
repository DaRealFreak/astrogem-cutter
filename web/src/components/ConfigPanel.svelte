<script lang="ts">
  import { config } from '../lib/state/config.state.svelte';
  const c = config;   // c.current is the reactive, bindable store value

  // When switching to combined mode, seed minWillChaosTotal from separate values if blank
  function handleGoalModeChange(mode: 'separate' | 'combined') {
    c.current.goalMode = mode;
    if (mode === 'combined' && c.current.minWillChaosTotal === undefined) {
      c.current.minWillChaosTotal = (c.current.minWill ?? 4) + (c.current.minChaos ?? 4);
    }
  }
</script>

<section class="config">
  <fieldset class="config-section">
    <legend>Goal</legend>

    <div class="field-row">
      <span class="field-label">Goal mode</span>
      <div class="segmented-toggle" role="group" aria-label="Goal mode">
        <button
          type="button"
          class:active={c.current.goalMode === 'separate'}
          onclick={() => handleGoalModeChange('separate')}
        >Separate</button>
        <button
          type="button"
          class:active={c.current.goalMode === 'combined'}
          onclick={() => handleGoalModeChange('combined')}
        >Combined</button>
      </div>
    </div>

    {#if c.current.goalMode !== 'combined'}
      <div class="field-row">
        <label for="min-will" title="Lowest willpower level (1–5) the finished gem must reach.">Min will</label>
        <input id="min-will" type="number" min="0" max="5" bind:value={c.current.minWill} />
      </div>
      <div class="field-row">
        <label for="min-chaos" title="Lowest chaos level (1–5) the finished gem must reach.">Min chaos</label>
        <input id="min-chaos" type="number" min="0" max="5" bind:value={c.current.minChaos} />
      </div>
    {:else}
      <div class="field-row">
        <label for="min-will-chaos-total" title="Lowest combined willpower + chaos the finished gem must reach (each caps at 5, so 10 max).">Min will+chaos</label>
        <input id="min-will-chaos-total" type="number" min="0" max="10" bind:value={c.current.minWillChaosTotal} />
      </div>
    {/if}

    <div class="field-row">
      <label for="min-first" title="Lowest level for the 1st side-node effect (0 = no constraint).">Min 1st node</label>
      <input id="min-first" type="number" min="0" max="5" bind:value={c.current.minFirst} />
    </div>
    <div class="field-row">
      <label for="min-second" title="Lowest level for the 2nd side-node effect (0 = no constraint).">Min 2nd node</label>
      <input id="min-second" type="number" min="0" max="5" bind:value={c.current.minSecond} />
    </div>
    <div class="field-row">
      <label for="min-side-coeff" title="Lowest coefficient-weighted side-node total (Σ effect coefficient × level). Use instead of per-node levels to value side nodes by worth.">Min side coeff</label>
      <input id="min-side-coeff" type="number" min="0" step="any" bind:value={c.current.minSideCoeff} />
    </div>
  </fieldset>

  <fieldset class="config-section">
    <legend>Grade</legend>

    <div class="field-row">
      <label for="rarity">Rarity</label>
      <select id="rarity" bind:value={c.current.rarityOverride}>
        <option value="auto">Auto (detected)</option>
        <option value="common">Common (5)</option>
        <option value="rare">Rare (7)</option>
        <option value="epic">Epic (9)</option>
      </select>
    </div>
    <div class="field-row">
      <label for="relic-coeff">Relic coeff</label>
      <input id="relic-coeff" type="number" step="any" placeholder="fusion default"
        value={c.current.relicCoeff ?? ''} oninput={(e) => c.current.relicCoeff = e.currentTarget.value === '' ? null : +e.currentTarget.value} />
    </div>
    <div class="field-row">
      <label for="ancient-coeff">Ancient coeff</label>
      <input id="ancient-coeff" type="number" step="any" placeholder="fusion default"
        value={c.current.ancientCoeff ?? ''} oninput={(e) => c.current.ancientCoeff = e.currentTarget.value === '' ? null : +e.currentTarget.value} />
    </div>
  </fieldset>

  <details class="config-section advanced">
    <summary>Advanced</summary>

    <div class="field-row">
      <label for="endgame-risk">Endgame risk</label>
      <input id="endgame-risk" type="number" step="any" placeholder="auto-gate"
        value={c.current.endgameRisk ?? ''} oninput={(e) => c.current.endgameRisk = e.currentTarget.value === '' ? null : +e.currentTarget.value} />
    </div>
    <div class="field-row">
      <label for="relic-reroll-threshold" title="Worthiness bar on P(relic+). Enables the extra reroll ticket once relic-grade odds cross it, and on a dead goal finishes the gem when odds fall below it. 0% disables both.">Relic reroll threshold</label>
      <div class="slider-field">
        <input id="relic-reroll-threshold" type="range" min="0" max="1" step="0.05" bind:value={c.current.relicRerollThreshold} />
        <span class="slider-value">{Math.round((c.current.relicRerollThreshold ?? 0) * 100)}%</span>
      </div>
    </div>
    <div class="field-row">
      <label for="force-reroll-no-progress">Force reroll no-progress</label>
      <input id="force-reroll-no-progress" type="number" min="0" step="any" bind:value={c.current.forceRerollNoProgress} />
    </div>
    <div class="field-row">
      <label for="extra-ticket">Extra ticket</label>
      <select id="extra-ticket" value={String(c.current.extraTicket)} onchange={(e) => {
        const v = e.currentTarget.value; c.current.extraTicket = v === 'true' ? true : v === 'false' ? false : null;
      }}>
        <option value="null">Armed (off, enable on signal)</option>
        <option value="true">On</option>
        <option value="false">Off (hard)</option>
      </select>
    </div>
    <div class="field-row">
      <label for="optimize">Optimize</label>
      <select id="optimize" bind:value={c.current.optimizeOverride}>
        <option value="auto">Auto (from effects)</option>
        <option value="dps">DPS</option>
        <option value="support">Support</option>
      </select>
    </div>
    <div class="field-row">
      <label for="ignore-side-node-values">Ignore side-node values</label>
      <input id="ignore-side-node-values" type="checkbox" bind:checked={c.current.ignoreSideNodeValues} />
    </div>
    <div class="field-row">
      <label for="reset-override">Reset available</label>
      <select id="reset-override" bind:value={c.current.resetOverride}>
        <option value="auto">Auto (turn 1)</option>
        <option value="always">Always</option>
        <option value="never">Never</option>
      </select>
    </div>
  </details>
</section>
