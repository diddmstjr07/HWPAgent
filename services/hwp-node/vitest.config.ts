import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    setupFiles: ['./test/setup.ts'],
    testTimeout: 30_000,
    pool: 'forks',
    fileParallelism: false,
  },
});
