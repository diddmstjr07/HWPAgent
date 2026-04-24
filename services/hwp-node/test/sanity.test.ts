import { describe, it, expect } from 'vitest';
import { openHwp } from '../src/hwp-helper.js';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SAMPLES = resolve(__dirname, '../../../samples');

describe('sanity: sample files open correctly', () => {
  it('text.hwp opens and has paragraphs', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    expect(doc.getSectionCount()).toBeGreaterThan(0);
    expect(doc.getParagraphCount(0)).toBeGreaterThan(0);
  });

  it('form.hwp opens', async () => {
    const doc = await openHwp(`${SAMPLES}/form.hwp`);
    expect(doc.getSectionCount()).toBe(1);
  });

  it('table.hwp opens', async () => {
    const doc = await openHwp(`${SAMPLES}/table.hwp`);
    expect(doc.getSectionCount()).toBe(1);
  });
});
