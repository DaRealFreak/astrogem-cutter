<script lang="ts">
  let { supported }: { supported: boolean } = $props();
</script>

{#if !supported}
  <div class="browser-guard" role="alert">
    This advisor needs a <strong>Chromium-based browser</strong> (Chrome, Edge, or Opera) —
    screen capture isn't available here. Open it in Chrome/Edge to use it.
  </div>
{/if}
