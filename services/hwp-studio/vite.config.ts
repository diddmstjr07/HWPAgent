import { defineConfig } from 'vite';
import { resolve } from 'path';
import { readFileSync } from 'fs';

const pkg = JSON.parse(readFileSync(resolve(__dirname, 'package.json'), 'utf-8'));

export default defineConfig({
  base: '/static/hwp-studio/',
  build: {
    outDir: '../../static/hwp-studio',
    emptyOutDir: true,
  },
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@wasm': resolve(__dirname, '..', 'hwp-node', 'node_modules', '@rhwp', 'core'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 7700,
    allowedHosts: true,
    fs: {
      allow: ['..'],
    },
  },
});
