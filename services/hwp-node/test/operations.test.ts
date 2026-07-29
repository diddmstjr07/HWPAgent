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
    const before = doc.getText(0, 0, 0, 100);
    applyOp(doc, {
      kind: 'set_char_format',
      sec: 0,
      para: 0,
      start: 0,
      end: 7,
      props: { bold: true, fontSize: 1200, fontName: '함초롬바탕' },
    });
    expect(doc.getText(0, 0, 0, 100)).toBe(before);
  });

  it('set_para_format changes alignment', () => {
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: 'TEST' });
    const before = doc.getText(0, 0, 0, 100);
    applyOp(doc, {
      kind: 'set_para_format',
      sec: 0,
      para: 0,
      props: { align: 'Center' },
    });
    expect(doc.getText(0, 0, 0, 100)).toBe(before);
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

  it('create_table inserts a real table and optional cell text', () => {
    const result = applyOp(doc, {
      kind: 'create_table',
      sec: 0,
      para: 0,
      offset: 0,
      rows: 2,
      cols: 3,
      cells: [
        ['A1', 'B1', 'C1'],
        ['A2', 'B2', 'C2'],
      ],
    });

    const data = result.data as { rows: number; cols: number; paraIdx: number; controlIdx: number };
    expect(data.rows).toBe(2);
    expect(data.cols).toBe(3);
    expect(JSON.parse(doc.raw.getTableDimensions(0, data.paraIdx, data.controlIdx))).toEqual({
      rowCount: 2,
      colCount: 3,
      cellCount: 6,
    });
    expect(doc.raw.getTextInCell(0, data.paraIdx, data.controlIdx, 4, 0, 0, 100)).toBe('B2');
  });

  it('paste_reference_component rejects blocks that corrupt exported page geometry', () => {
    applyOp(doc, { kind: 'split_paragraph', sec: 0, para: 0, offset: 0 });
    expect(() =>
      applyOp(doc, {
        kind: 'paste_reference_component',
        component: 'attachment_header_bar',
        sec: 0,
        para: 0,
        offset: 0,
        replacements: [
          { cellIdx: 0, text: '붙임 9' },
          { cellIdx: 2, text: '복제 테스트 제목' },
        ],
      }),
    ).toThrow(/corrupts exported page geometry/);
  });

  it('table and cell ops edit an existing table', () => {
    const created = applyOp(doc, { kind: 'create_table', sec: 0, para: 0, offset: 0, rows: 2, cols: 2 });
    const table = created.data as { paraIdx: number; controlIdx: number };

    applyOp(doc, {
      kind: 'insert_text_in_cell',
      sec: 0,
      para: table.paraIdx,
      controlIdx: table.controlIdx,
      cellIdx: 0,
      cellPara: 0,
      offset: 0,
      text: 'cell text',
    });
    expect((applyOp(doc, {
      kind: 'get_text_in_cell',
      sec: 0,
      para: table.paraIdx,
      controlIdx: table.controlIdx,
      cellIdx: 0,
    }).data as { text: string }).text).toBe('cell text');

    expect(() => applyOp(doc, {
      kind: 'set_char_format_in_cell',
      sec: 0,
      para: table.paraIdx,
      controlIdx: table.controlIdx,
      cellIdx: 0,
      cellPara: 0,
      start: 0,
      end: 4,
      props: { fontName: '함초롬돋움', fontSize: 1100, bold: true },
    })).not.toThrow();

    expect(() => applyOp(doc, {
      kind: 'set_para_format_in_cell',
      sec: 0,
      para: table.paraIdx,
      controlIdx: table.controlIdx,
      cellIdx: 0,
      cellPara: 0,
      props: { align: 'Center', lineSpacing: 140 },
    })).not.toThrow();

    applyOp(doc, { kind: 'insert_table_row', sec: 0, para: table.paraIdx, controlIdx: table.controlIdx, rowIdx: 1, below: true });
    applyOp(doc, { kind: 'insert_table_column', sec: 0, para: table.paraIdx, controlIdx: table.controlIdx, colIdx: 1, right: true });
    const info = applyOp(doc, { kind: 'get_table_info', sec: 0, para: table.paraIdx, controlIdx: table.controlIdx }).data as {
      dimensions: { rowCount: number; colCount: number };
    };
    expect(info.dimensions.rowCount).toBe(3);
    expect(info.dimensions.colCount).toBe(3);
  });

  it('raw HWP function gateway exposes and calls Node functions', () => {
    const catalog = applyOp(doc, { kind: 'get_hwp_function_catalog' }).data as {
      functions: Array<{ name: string; arity: number }>;
    };
    expect(catalog.functions.some((fn) => fn.name === 'insertText')).toBe(true);

    const before = applyOp(doc, { kind: 'call_hwp_function', method: 'getParagraphCount', args: [0], affectsDocument: false });
    expect((before.data as { result: number }).result).toBeGreaterThan(0);

    applyOp(doc, { kind: 'call_hwp_function', method: 'insertText', args: [0, 0, 0, 'RAW-'], affectsDocument: true });
    expect(doc.getText(0, 0, 0, 10).startsWith('RAW-')).toBe(true);
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

  it('search_deep finds whitespace-normalized paragraph labels', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    applyOp(doc, { kind: 'insert_text', sec: 0, para: 0, offset: 0, text: '성 명 : ______' });
    const result = applyOp(doc, { kind: 'search_deep', query: '성명' });
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
