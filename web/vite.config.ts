import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Pages project base path. Worker is an ES-module worker (import/export inside it).
export default defineConfig({
  base: '/AstrogemCutter/',
  plugins: [svelte()],
  worker: { format: 'es' },
});
