import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    // Run all tests in a single thread to avoid spawning many worker processes.
    // This is important for the opencv.js spike which loads a 10 MB WASM bundle.
    poolOptions: {
      threads: {
        singleThread: true,
      },
    },
    // Treat the large opencv.js WASM bundle as an external CJS module —
    // prevents vite-node from trying to esbuild-transform the 10 MB file.
    server: {
      deps: {
        external: ['@techstark/opencv-js'],
      },
    },
  },
});
