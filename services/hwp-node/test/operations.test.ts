import { describe, it, expect, beforeEach } from 'vitest';
import { openHwp, HwpDocWrapper } from '../src/hwp-helper.js';
import { applyOp, OpError } from '../src/operations.js';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SAMPLES = resolve(__dirname, '../../../samples');

describe('applyOp: write operations', () => {
  let doc: HwpDocWrapper;

  beforeEach(async () => {
    doc = await openHwp(`${SAMPLES}/text.hwp`);
  });

  it('insert_text adds text at position', () => {
    const before = doc.getText(0, 0, 0, 100);
    const result = applyOp(doc, {
      kind: 'insert_text',
      sec: 0,
      para: 0,
      offset: 0,
      text: 'PREFIX-',
    });
    const after = doc.getText(0, 0, 0, 100);
    expect(after.startsWith('PREFIX-')).toBe(true);
    expect(after).toBe(`PREFIX-${before}`);
    expect(result.affectedPages).toEqual([0]);
  });

  it('delete_text removes text', () => {
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'REMOVEME' });
    applyOp(doc, { kind: 'delete_text', sec: 0, para: 0, offset: 0, length: 8 });
    const text = doc.getText(0, 0, 0, 100);
    expect(text.startsWith('REMOVEME')).toBe(false);
  });

  it('replace_text swaps text at position', () => {
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'AAAAA' });
    applyOp(doc, { kind: 'replace_text', sec: 0, para: 0, offset: 0, length: 5, newText: 'BBBBB' });
    expect(doc.getText(0, 0, 0, 5)).toBe('BBBBB');
  });

  it('split_paragraph increases paragraph count', () => {
    const before = doc.getParagraphCount(0);
    applyOp(doc, { kind: 'split_paragraph', sec: 0, para: 0, offset: 0 });
    const after = doc.getParagraphCount(0);
    expect(after).toBe(before + 1);
  });

  it('set_char_format applies with fontName -> fontId conversion', () => {
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'TESTING' });
    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 0,
      start: 0,
      end: 7,
      props: { bold: true, fontSize: 1200, fontName: '함초롬바탕' },
    });
  });

  it('set_para_format changes alignment', () => {
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'TEST' });
    applyOp(doc, {
      kind: 'set_para_format',
      sec: 0,
      para: 0,
      props: { align: 'Center' },
    });
  });

  it('set_field throws for non-existent field', () => {
    expect(() =>
      applyOp(doc, {
        kind: 'set_field',
        fieldName: 'NO_SUCH_FIELD',
        value: 'x',
      }),
    ).toThrow(OpError);
  });

  it('search_replace_all replaces all occurrences', () => {
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'foo bar foo baz foo' });
    const result = applyOp(doc, {
      kind: 'search_replace_all',
      query: 'foo',
      replacement: 'XYZ',
    });
    expect((result.data as { replacedCount: number }).replacedCount).toBe(3);
    const after = doc.getText(0, 0, 0, 100);
    expect(after).toContain('XYZ bar XYZ baz XYZ');
    expect(after).not.toContain('foo');
  });
});

describe('applyOp: read operations', () => {
  it('get_paragraph_text returns text', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const result = applyOp(doc, { kind: 'get_paragraph_text', sec: 0, para: 0 });
    expect(typeof (result.data as { text: string }).text).toBe('string');
    expect((result.data as { text: string }).text.length).toBeGreaterThan(0);
    expect(result.affectedPages).toEqual([]);
  });

  it('search_text finds occurrences', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'UNIQUE_TOKEN' });
    const result = applyOp(doc, { kind: 'search_text', query: 'UNIQUE_TOKEN' });
    expect((result.data as { count: number }).count).toBeGreaterThanOrEqual(1);
  });
});

describe('applyOp: error handling', () => {
  it('wraps WASM errors in OpError', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    let caught: unknown;
    try {
      applyOp(doc, {
        kind: 'insert_text',
        sec: 999,
        para: 0,
        offset: 0,
        text: 'x',
      });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(OpError);
    expect((caught as OpError).op.kind).toBe('insert_text');
    expect((caught as OpError).stage).toBe('execute');
  });
});
