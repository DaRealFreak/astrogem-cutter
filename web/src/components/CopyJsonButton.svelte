<script lang="ts">
  import { advisor } from '../lib/state/advisor.state.svelte';
  import { config } from '../lib/state/config.state.svelte';
  import { turnLog } from '../lib/state/turnLog.state.svelte';
  import { buildAdvisorSnapshot } from '../lib/app/snapshot';

  let copied = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function copy() {
    const det = advisor.detection, output = advisor.output;
    if (!det || !output) return;
    const snap = buildAdvisorSnapshot(det, config.current, output, turnLog.entries);
    try {
      await navigator.clipboard.writeText(JSON.stringify(snap, null, 2));
      copied = true;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => (copied = false), 1500);
    } catch {
      // Clipboard blocked (insecure context / permissions) — no flash, no throw.
    }
  }
</script>

<button class="copy-json" onclick={copy} disabled={!advisor.output}>
  {copied ? 'Copied!' : 'Copy JSON'}
</button>
