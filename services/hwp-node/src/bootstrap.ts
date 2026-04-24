// WARNING: This file MUST be imported before anything that touches @rhwp/core.
// Sets up measureTextWidth polyfill + loads WASM synchronously in Node.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { createCanvas } from 'canvas';

declare global {
  // eslint-disable-next-line no-var
  var measureTextWidth: (font: string, text: string) => number;
}

// Canvas-backed font metrics for closer page preview layout.
const measureCanvas = createCanvas(1, 1);
const measureCtx = measureCanvas.getContext('2d');

globalThis.measureTextWidth = (font: string, text: string): number => {
  measureCtx.font = font || '12px sans-serif';
  return measureCtx.measureText(text).width;
};

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
