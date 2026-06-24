<script lang="ts">
  let { onfile }: { onfile: (bitmap: ImageBitmap) => void } = $props();
  async function pick(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    if (file) onfile(await createImageBitmap(file));
  }
</script>
<label class="screenshot-upload">Test a screenshot <input type="file" accept="image/*" onchange={pick} /></label>
