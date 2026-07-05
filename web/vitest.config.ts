import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'node:path';

// opencv-dependent test files run in a real browser; everything else in Node.
// parse.test.ts and adapter.test.ts were moved to Node after parse.ts/types.ts
// split removed the transitive opencv dependency from those modules.
const BROWSER_TESTS = [
  'tests/app/foundation.test.ts',
  'tests/cv/**/*.test.ts',
  'tests/vision/matcher.test.ts',
  'tests/vision/templates.test.ts',
  'tests/vision/recognizer.test.ts',
  'tests/vision/e2e.test.ts',
  'tests/components/**/*.test.ts',
  'tests/state/configPersist.test.ts',
];

export default defineConfig({
  test: {
    projects: [
      {
        // NODE: Plan 1 engine + Plan 2 opencv-free pure-logic (parse/adapter now
        // included here after the parse.ts/types.ts split severed their opencv dependency)
        test: {
          name: 'node',
          globals: true,
          environment: 'node',
          include: ['tests/**/*.test.ts'],
          exclude: [...BROWSER_TESTS, '**/node_modules/**'],
          // DP-table builds can take 20-60 s (the cost-saturation dimension
          // doubled every table's state space); raise the timeout from the
          // vitest 3 default of 5 s to accommodate the slowest parity tests
          // under full-suite parallel load.
          testTimeout: 120_000,
        },
      },
      {
        // BROWSER: opencv-dependent vision tests + Svelte component tests, in headless Chromium
        // Note: do NOT exclude @techstark/opencv-js from optimizeDeps; Vite needs
        // to pre-bundle the UMD module to make it importable as ESM in the browser.
        plugins: [svelte()],
        server: {
          host: '127.0.0.1',
          port: 51000,
          strictPort: false,
          fs: { allow: [resolve(__dirname, '..')] },
        },
        test: {
          name: 'browser',
          globals: true,
          include: BROWSER_TESTS,
          // e2e builds full engine contexts (DP tables) in the browser; allow
          // for the cost-saturation dimension's doubled build time.
          testTimeout: 180_000,
          browser: {
            enabled: true,
            provider: 'playwright',
            headless: true,
            // Override default port 63315 (falls in Windows Hyper-V excluded range)
            api: { port: 51000, strictPort: false, host: '127.0.0.1' },
            instances: [{ browser: 'chromium' }],
          },
        },
      },
    ],
  },
});
