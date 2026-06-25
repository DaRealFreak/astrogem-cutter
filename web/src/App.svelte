<script lang="ts">
  import ConfigPanel from './components/ConfigPanel.svelte';
  import CaptureControls from './components/CaptureControls.svelte';
  import AdvisorPanel from './components/AdvisorPanel.svelte';
  import OfferTable from './components/OfferTable.svelte';
  import DetectedState from './components/DetectedState.svelte';
  import BrowserGuard from './components/BrowserGuard.svelte';
  import ActionMatrix from './components/ActionMatrix.svelte';
  import TurnLog from './components/TurnLog.svelte';
  import { advisor } from './lib/state/advisor.state.svelte';
  import { turnLog } from './lib/state/turnLog.state.svelte';
  import { isCaptureSupported } from './lib/app/captureSupport';

  const supported = isCaptureSupported();
</script>

<main class="app-shell">
  <aside class="app-config">
    <h1>Astrogem Cutter</h1>
    <ConfigPanel />
  </aside>
  <section class="app-main">
    <BrowserGuard {supported} />
    <div class="main-grid">
      <div class="main-left">
        <CaptureControls {supported} />
      </div>
      <div class="main-right">
        <AdvisorPanel output={advisor.output} waiting={advisor.waiting} recomputing={advisor.recomputing} />
        {#if advisor.output}
          <ActionMatrix actions={advisor.output.actions} recommended={advisor.output.action} ticket={advisor.output.ticket} />
        {/if}
        {#if advisor.output}<OfferTable perOffer={advisor.output.perOffer} detection={advisor.detection} />{/if}
        <DetectedState detection={advisor.detection} />
      </div>
    </div>
    <section class="turn-log-section">
      <h2 class="section-title">Turn log</h2>
      <TurnLog entries={turnLog.entries} />
    </section>
  </section>
</main>
