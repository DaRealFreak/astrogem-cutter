<script lang="ts">
  import ConfigPanel from './components/ConfigPanel.svelte';
  import CaptureControls from './components/CaptureControls.svelte';
  import AdvisorPanel from './components/AdvisorPanel.svelte';
  import OfferTable from './components/OfferTable.svelte';
  import DetectedState from './components/DetectedState.svelte';
  import { advisor } from './lib/state/advisor.state.svelte';
</script>

<main class="app-shell">
  <aside class="app-config">
    <h1>Astrogem Advisor</h1>
    <ConfigPanel />
  </aside>
  <section class="app-main">
    <CaptureControls />
    <AdvisorPanel output={advisor.output} waiting={advisor.waiting} />
    {#if advisor.output}<OfferTable perOffer={advisor.output.perOffer} />{/if}
    <DetectedState detection={advisor.detection} />
  </section>
</main>
