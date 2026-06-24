<script lang="ts">
  import { CaptureController } from '../lib/cv/captureController';
  import { computeAdvice } from '../lib/app/computeAdvice';
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
  let debugCanvas = $state<HTMLCanvasElement | null>(null);
  let drawDebug = $state(false);
  let debugImage = $state<ImageBitmap | null>(null);
  // Debounces live frames so the advice + turn log only update on a settled
  // reading (the game animates ~0.2-0.4s after a turn flips, misreading offers
  // and side-node levels in between). Uploads bypass it (one-shot).
  const stabilizer = new DetectionStabilizer();

  /** Update the advisor + turn log from a settled detection. */
  function commit(det: DetectionResult) {
    const { ready, output } = computeAdvice(det, config.current, turnLog.resetObserved);
    if (ready && output) {
      advisor.detection = det;
      advisor.output = output;
      advisor.waiting = false;
      turnLog.observe(det, output.action, output.pGoal, output.eValue);
    }
  }

  function ensure(): CaptureController {
    if (controller) return controller;
    const c = new CaptureController(debugCanvas);
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
  function toggleDebug() { drawDebug = ensure().toggleDrawDebug(); }
</script>

<div class="capture-controls">
  {#if advisor.status === 'recording'}
    <button onclick={stop}>Stop</button>
  {:else}
    <button onclick={start} disabled={!supported || advisor.status === 'loading'}>Share screen</button>
  {/if}
  <span class="status">Status: {advisor.status}</span>
  <label><input type="checkbox" checked={drawDebug} onchange={toggleDebug} /> debug</label>
  {#if advisor.error}<span class="error">{advisor.error}</span>{/if}
  <canvas class="debug" bind:this={debugCanvas} hidden={!drawDebug}></canvas>
  {#if drawDebug}
    <ScreenshotUpload onfile={(b) => ensure().analyzeImage(b)} />
    <DebugView image={debugImage} />
  {/if}
</div>
