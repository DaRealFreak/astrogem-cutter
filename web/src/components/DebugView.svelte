<script lang="ts">
  let { image }: { image: ImageBitmap | null } = $props();
  let canvas = $state<HTMLCanvasElement | null>(null);
  $effect(() => {
    if (image && canvas) {
      canvas.width = image.width;
      canvas.height = image.height;
      canvas.getContext('2d')?.drawImage(image, 0, 0);
    }
  });
</script>
<canvas bind:this={canvas}></canvas>
