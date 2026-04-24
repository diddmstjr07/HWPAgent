// WARNING: This file MUST be imported before anything that touches @rhwp/core.
// Sets up measureTextWidth polyfill + loads WASM synchronously in Node.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';

declare global {
  // eslint-disable-next-line no-var
  var measureTextWidth: (font: string, text: string) => number;
}

// Naive polyfill — sufficient for editing/saving.
// For pixel-accurate rendering, replace with the `canvas` package.
globalThis.measureTextWidth = (_font: string, text: string): number => text.length * 7;

// Node-compatible WASM loading. Mirrors scripts/hwp-helper.mjs:
// path.resolve(scriptDir, '../node_modules/@rhwp/core/rhwp_bg.wasm')
const require = createRequire(import.meta.url);
const rhwpPkgPath = require.resolve('@rhwp/core/package.json');
const rhwpDir = dirname(rhwpPkgPath);
const wasmPath = resolve(rhwpDir, 'rhwp_bg.wasm');
const wasmBytes = readFileSync(wasmPath);

const { initSync } = await import('@rhwp/core');
initSync({ module: wasmBytes });

export {};
