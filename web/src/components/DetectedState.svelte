<script lang="ts">
  import type { DetectionResult } from '../lib/cv/types';
  import { effectLabel } from '../lib/app/offerLabel';
  let { detection }: { detection: DetectionResult | null } = $props();
</script>

{#if detection}
  <dl class="detected">
    <div><dt>Gem</dt><dd>{detection.gemType ?? '—'} <span class="score">{detection.gemTypeScore.toFixed(2)}</span></dd></div>
    <div><dt>Will</dt><dd>{detection.willpower ?? '—'}</dd></div>
    <div><dt>Chaos</dt><dd>{detection.chaos ?? '—'}</dd></div>
    <div><dt>1st</dt><dd>{effectLabel(detection.firstEffect) || '—'} Lv{detection.firstLevel ?? '—'}</dd></div>
    <div><dt>2nd</dt><dd>{effectLabel(detection.secondEffect) || '—'} Lv{detection.secondLevel ?? '—'}</dd></div>
    <div><dt>Rerolls</dt><dd>{detection.rerolls ?? '—'}</dd></div>
    <div><dt>Step</dt><dd>{detection.currentStep ?? '—'}/{detection.totalSteps ?? '—'}</dd></div>
  </dl>
{/if}
