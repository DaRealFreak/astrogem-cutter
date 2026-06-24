import { defineConfig } from 'vitest/config';
import { resolve } from 'node:path';

// opencv-dependent test files run in a real browser; everything else in Node.
const BROWSER_TESTS = [
  'tests/cv/**/*.test.ts',
  'tests/vision/matcher.test.ts',
  'tests/vision/templates.test.ts',
  'tests/vision/recognizer.test.ts',
  'tests/vision/e2e.test.ts',
];

export default defineConfig({
  test: {
    projects: [
      {
        // NODE: Plan 1 engine + Plan 2 pure-logic (constants, parse, adapter-unit)
        test: {
          name: 'node',
          globals: true,
          environment: 'node',
          include: ['tests/**/*.test.ts'],
          exclude: [...BROWSER_TESTS, '**/node_modules/**'],
          // DP-table builds can take 10-20 s; raise the timeout from the vitest 3
          // default of 5 s to accommodate the slowest parity tests.
          testTimeout: 30_000,
        },
      },
      {
        // BROWSER: opencv-dependent vision tests, in headless Chromium
        // Note: do NOT exclude @techstark/opencv-js from optimizeDeps; Vite needs
        // to pre-bundle the UMD module to make it importable as ESM in the browser.
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
