<script lang="ts">
  import { CaptureController } from '../lib/cv/captureController';
  import { computeAdvice } from '../lib/app/computeAdvice';
  import { config } from '../lib/state/config.state.svelte';
  import { advisor } from '../lib/state/advisor.state.svelte';
  import { turnLog } from '../lib/state/turnLog.state.svelte';
  import ScreenshotUpload from './ScreenshotUpload.svelte';
  import DebugView from './DebugView.svelte';

  let controller: CaptureController | null = null;
  let debugCanvas = $state<HTMLCanvasElement | null>(null);
  let drawDebug = $state(false);
  let debugImage = $state<ImageBitmap | null>(null);

  function ensure(): CaptureController {
    if (controller) return controller;
    const c = new CaptureController(debugCanvas);
    c.onStatus = (s) => { advisor.status = s; };
    c.onError = (e) => { advisor.error = e; advisor.status = 'idle'; };
    c.onDetection = (det) => {
      advisor.detection = det;
      advisor.error = null;
      if (!det) { advisor.waiting = true; return; }
      const { ready, output } = computeAdvice(det, config.current, turnLog.resetObserved);
      advisor.waiting = !ready;
      if (ready && output) {
        advisor.output = output;
        turnLog.observe(det, output.action, output.pGoal, output.eValue);
      }
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
    <button onclick={start} disabled={advisor.status === 'loading'}>Share screen</button>
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
