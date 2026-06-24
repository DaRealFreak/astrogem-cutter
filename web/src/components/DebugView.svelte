<script lang="ts">
  let { image }: { image: ImageBitmap | null } = $props();
  let canvas = $state<HTMLCanvasElement | null>(null);
  // DebugView owns the handed-off bitmaps: when `image` changes, draw the new
  // one and close the previously-held one; on destroy close the last one.
  // Exactly one owner closes each bitmap, so no draw-after-close and no leak.
  let prev: ImageBitmap | null = null;
  $effect(() => {
    const current = image;
    if (current && canvas) {
      canvas.width = current.width;
      canvas.height = current.height;
      canvas.getContext('2d')?.drawImage(current, 0, 0);
    }
    if (prev && prev !== current) prev.close();
    prev = current;
  });
  // Destroy-only cleanup: a bare $effect with a returned function would run its
  // cleanup before each re-run too, racing the body's close. This separate
  // effect has no reactive deps, so its cleanup runs only on unmount.
  $effect(() => () => { if (prev) { prev.close(); prev = null; } });
</script>
<canvas bind:this={canvas}></canvas>
