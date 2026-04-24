import './bootstrap.mjs';
import init, { initSync, HwpDocument } from '@rhwp/core';
import { readFile, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const wasmPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../node_modules/@rhwp/core/rhwp_bg.wasm'
);

let initPromise;

function normalizeError(e) {
  if (e instanceof Error) return e;
  if (typeof e === 'string') return new Error(e);
  return new Error(String(e));
}

async function ensureRhwpInit() {
  if (!initPromise) {
    initPromise = Promise.resolve(initSync({ module: readFileSync(wasmPath) }));
  }
  return initPromise;
}

class HwpDocWrapper {
  constructor(raw) {
    this.raw = raw;
  }

  insertText(sec, para, offset, text) {
    try {
      this.raw.insertText(sec, para, offset, text);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setCharFormat(sec, para, start, end, props) {
    try {
      this.raw.applyCharFormat(sec, para, start, end, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setParaFormat(sec, para, props) {
    try {
      this.raw.applyParaFormat(sec, para, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getText(sec, para, offset, count) {
    try {
      return this.raw.getTextRange(sec, para, offset, count);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  async save(filePath) {
    try {
      const bytes = this.raw.exportHwp();
      await writeFile(filePath, Buffer.from(bytes));
    } catch (e) {
      throw normalizeError(e);
    }
  }
}

export async function openHwp(filePath) {
  await ensureRhwpInit();
  const bytes = await readFile(filePath);
  return new HwpDocWrapper(new HwpDocument(new Uint8Array(bytes)));
}
