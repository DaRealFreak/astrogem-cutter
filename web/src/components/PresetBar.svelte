<script lang="ts">
  import { config } from '../lib/state/config.state.svelte';
  import { presets } from '../lib/state/presets.state.svelte';

  const names = $derived(presets.names());
  let selected = $state('');
  let nameInput = $state('');

  function loadPreset(name: string) {
    const p = presets.get(name);
    if (!p) return;
    // Deep, plain copy so editing the config later doesn't mutate the stored preset.
    config.current = JSON.parse(JSON.stringify(p));
    selected = name;
    nameInput = name;
  }
  function save() {
    const name = nameInput.trim();
    if (!name) return;
    presets.save(name, config.current); // upsert under the typed name
    selected = name;
  }
  function rename() {
    const next = nameInput.trim();
    if (!selected || !next || next === selected) return;
    presets.rename(selected, next);
    selected = next;
  }
  function remove() {
    if (!selected) return;
    presets.remove(selected);
    selected = '';
    nameInput = '';
  }
</script>

<fieldset class="config-section preset-bar">
  <div class="legend">Presets</div>
  <div class="field-row">
    <label for="preset-select" title="Load a saved preset into the settings below.">Load preset</label>
    <select id="preset-select" bind:value={selected} onchange={() => selected && loadPreset(selected)}>
      <option value="" disabled>Select…</option>
      {#each names as n (n)}<option value={n}>{n}</option>{/each}
    </select>
  </div>
  <input class="preset-name" type="text" placeholder="Preset name" bind:value={nameInput}
    aria-label="Preset name" />
  <div class="preset-actions">
    <button type="button" onclick={save} disabled={!nameInput.trim()}
      title="Save the current settings under this name (overwrites if it already exists).">Save</button>
    <button type="button" onclick={rename} disabled={!selected || !nameInput.trim() || nameInput.trim() === selected}
      title="Rename the loaded preset to the name above.">Rename</button>
    <button type="button" onclick={remove} disabled={!selected}
      title="Delete the loaded preset.">Delete</button>
  </div>
</fieldset>
