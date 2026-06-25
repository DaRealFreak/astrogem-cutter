<script lang="ts">
  import { untrack } from 'svelte';
  import { CaptureController } from '../lib/cv/captureController';
  import { syncAdvice, type AdviceSink } from '../lib/app/adviceSync';
  import { isCompleteDetection } from '../lib/app/optimize';
  import { DetectionStabilizer, detectionSignature } from '../lib/app/detectionStability';
  import { config } from '../lib/state/config.state.svelte';
  import { advisor } from '../lib/state/advisor.state.svelte';
  import { turnLog } from '../lib/state/turnLog.state.svelte';
  import type { DetectionResult } from '../lib/cv/types';
  import ScreenshotUpload from './ScreenshotUpload.svelte';
  import DebugView from './DebugView.svelte';

  let { supported = true }: { supported?: boolean } = $props();

  let controller: CaptureController | null = null;
  // Detection ROI overlays on the screen mirror — on by default. The screen
  // itself always streams; this only toggles the annotation boxes.
  let drawOverlays = $state(true);
  let debugImage = $state<ImageBitmap | null>(null);
  // Debounces live frames so the advice + turn log only update on a settled
  // reading (the game animates ~0.2-0.4s after a turn flips, misreading offers
  // and side-node levels in between). Uploads bypass it (one-shot).
  const stabilizer = new DetectionStabilizer();

  // Routes advisory results from the pure orchestrator into the reactive stores.
  const sink: AdviceSink = {
    applyAdvice(det, output) {
      advisor.detection = det;
      advisor.output = output;
      advisor.waiting = false;
    },
    observeTurn(det, output) {
      turnLog.observe(det, output.action, output.pGoal, output.pRelic, output.pAncient, output.eValue);
    },
  };

  /** Update the advisor + turn log from a settled detection (a real turn). */
  function commit(det: DetectionResult) {
    syncAdvice(det, config.current, turnLog.resetObserved, true, sink);
  }

  // Re-score the last reading whenever the config changes (preset load, goal or
  // knob edit) so the odds + recommendation reflect the new goal without waiting
  // for the next frame. No turn-log entry — the reading didn't change, the goal
  // did. The recompute is synchronous and can rebuild the DP (tens of ms), so we
  // flip on a "recalculating" flag and defer via setTimeout: the indicator paints
  // before the main thread blocks, and rapid edits debounce to the last change.
  $effect(() => {
    JSON.stringify(config.current); // deep-track every config field
    if (!untrack(() => advisor.detection)) return; // nothing committed yet
    advisor.recomputing = true;
    const id = setTimeout(() => {
      const det = advisor.detection;
      if (det) syncAdvice(det, config.current, turnLog.resetObserved, false, sink);
      advisor.recomputing = false;
    }, 0);
    return () => clearTimeout(id);
  });

  function ensure(): CaptureController {
    if (controller) return controller;
    const c = new CaptureController();
    c.setDrawOverlays(drawOverlays); // honor the default-on UI state
    c.onStatus = (s) => { advisor.status = s; };
    c.onError = (e) => { advisor.error = e; advisor.status = 'idle'; };
    c.onDetection = (det, source) => {
      advisor.error = null;
      // Uploaded stills are one-shot — commit immediately, no debounce.
      if (source === 'image') {
        stabilizer.reset();
        if (det) commit(det);
        else advisor.waiting = true;
        return;
      }
      // Live frames: only commit once the reading has settled (anti-flicker).
      // While unsettled we keep showing the last committed advice rather than
      // flickering through transient animation-frame misreads.
      if (!det || !isCompleteDetection(det)) {
        stabilizer.reset();
        if (!advisor.output) advisor.waiting = true;
        return;
      }
      if (stabilizer.push(detectionSignature(det))) commit(det);
    };
    c.onDebug = (img) => { debugImage = img; };
    controller = c;
    return c;
  }
  async function start() { advisor.error = null; await ensure().startCapture(); }
  function stop() { controller?.stopCapture(); }
  function toggleOverlays() { drawOverlays = ensure().toggleOverlays(); }
</script>

<div class="capture-controls">
  <div class="debug-screen">
    {#if debugImage}
      <DebugView image={debugImage} />
    {:else}
      <p class="debug-hint">Share your screen (or upload a screenshot below) to see what's detected.</p>
    {/if}
  </div>
  <div class="capture-bar">
    {#if advisor.status === 'recording'}
      <button onclick={stop}>Stop</button>
    {:else}
      <button onclick={start} disabled={!supported || advisor.status === 'loading'}>Share screen</button>
    {/if}
    <span class="status">Status: {advisor.status}</span>
    <label class="debug-toggle"><input type="checkbox" checked={drawOverlays} onchange={toggleOverlays} /> overlays</label>
    {#if advisor.error}<span class="error">{advisor.error}</span>{/if}
    <ScreenshotUpload onfile={(b) => ensure().analyzeImage(b)} />
  </div>
</div>
