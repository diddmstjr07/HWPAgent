import { HwpDocument } from '@rhwp/core';
import { readFileSync } from 'node:fs';
import { existsSync } from 'node:fs';
import { resolve, relative } from 'node:path';
import type { HwpDocWrapper, CharProps, ParaProps } from './hwp-helper.js';

// ---- Op types (discriminated union) ----
export type Op =
  // Write operations
  | { kind: 'insert_text'; sec: number; para: number; offset: number; text: string }
  | {
      kind: 'insert_image'; sec: number; para: number; offset: number;
      /** base64 인코딩된 이미지 바이트 (PNG/JPG 등) */
      dataBase64: string;
      /** 원본 픽셀 크기. 문서 안 표시 크기 계산의 기준이 된다. */
      naturalWidthPx: number; naturalHeightPx: number;
      /** 문서에 놓일 너비(mm). 높이는 비율대로 계산한다. 생략 시 120mm. */
      widthMm?: number;
      ext?: string; description?: string;
    }
  | { kind: 'delete_text'; sec: number; para: number; offset: number; length: number }
  | { kind: 'replace_text'; sec: number; para: number; offset: number; length: number; newText: string }
  | { kind: 'split_paragraph'; sec: number; para: number; offset: number }
  | { kind: 'set_char_format'; sec: number; para: number; start: number; end: number; props: CharProps }
  | { kind: 'set_para_format'; sec: number; para: number; props: ParaProps }
  | { kind: 'set_char_format_in_cell'; sec: number; para: number; controlIdx: number; cellIdx: number; cellPara: number; start: number; end: number; props: CharProps }
  | { kind: 'set_para_format_in_cell'; sec: number; para: number; controlIdx: number; cellIdx: number; cellPara: number; props: ParaProps }
  | { kind: 'set_field'; fieldName: string; value: string }
  | { kind: 'search_replace_all'; query: string; replacement: string; caseSensitive?: boolean }
  | { kind: 'create_table'; sec: number; para: number; offset: number; rows: number; cols: number; cells?: string[][] }
  | { kind: 'insert_text_in_cell'; sec: number; para: number; controlIdx: number; cellIdx: number; cellPara: number; offset: number; text: string }
  | { kind: 'delete_text_in_cell'; sec: number; para: number; controlIdx: number; cellIdx: number; cellPara: number; offset: number; length: number }
  | { kind: 'insert_table_row'; sec: number; para: number; controlIdx: number; rowIdx: number; below?: boolean }
  | { kind: 'insert_table_column'; sec: number; para: number; controlIdx: number; colIdx: number; right?: boolean }
  | { kind: 'delete_table_row'; sec: number; para: number; controlIdx: number; rowIdx: number }
  | { kind: 'delete_table_column'; sec: number; para: number; controlIdx: number; colIdx: number }
  | { kind: 'set_table_properties'; sec: number; para: number; controlIdx: number; props: Record<string, unknown> }
  | { kind: 'set_cell_properties'; sec: number; para: number; controlIdx: number; cellIdx: number; props: Record<string, unknown> }
  | {
      kind: 'paste_reference_component';
      sourcePath?: string;
      component?: 'attachment_header_bar' | 'contact_box' | 'press_header';
      sourceSec?: number;
      sourcePara?: number;
      sourceControlIdx?: number;
      sec: number;
      para: number;
      offset: number;
      replacements?: Array<{ cellIdx: number; text: string }>;
    }
  | { kind: 'call_hwp_function'; method: string; args?: unknown[]; affectsDocument?: boolean }
  // Read-only operations
  | { kind: 'get_paragraph_text'; sec: number; para: number }
  | { kind: 'search_text'; query: string; caseSensitive?: boolean }
  | { kind: 'get_table_info'; sec: number; para: number; controlIdx: number }
  | { kind: 'get_text_in_cell'; sec: number; para: number; controlIdx: number; cellIdx: number; cellPara?: number; offset?: number; count?: number }
  | { kind: 'get_hwp_function_catalog' }
  | { kind: 'search_deep'; query: string; caseSensitive?: boolean };

export interface OpResult {
  affectedPages: number[];
  // Read-only ops can return data here.
  data?: unknown;
}

// Discriminate read vs write for AI agent.
export const READ_OPS: ReadonlyArray<Op['kind']> = [
  'get_paragraph_text',
  'search_text',
  'get_table_info',
  'get_text_in_cell',
  'get_hwp_function_catalog',
  'search_deep',
];
export const WRITE_OPS: ReadonlyArray<Op['kind']> = [
  'insert_text',
  'insert_image',
  'delete_text',
  'replace_text',
  'split_paragraph',
  'set_char_format',
  'set_para_format',
  'set_char_format_in_cell',
  'set_para_format_in_cell',
  'set_field',
  'search_replace_all',
  'create_table',
  'insert_text_in_cell',
  'delete_text_in_cell',
  'insert_table_row',
  'insert_table_column',
  'delete_table_row',
  'delete_table_column',
  'set_table_properties',
  'set_cell_properties',
  'paste_reference_component',
  'call_hwp_function',
];

export function isReadOp(op: Op): boolean {
  return READ_OPS.includes(op.kind);
}

export class OpError extends Error {
  constructor(
    public op: Op,
    public stage: 'validate' | 'execute' | 'postprocess',
    message: string,
    public cause?: unknown,
  ) {
    super(`[${op.kind}/${stage}] ${message}`);
    this.name = 'OpError';
  }
}

interface SearchHit {
  found: boolean;
  sec?: number;
  para?: number;
  sectionIndex?: number;
  paragraphIndex?: number;
  charOffset?: number;
  offset?: number;
  length?: number;
}

interface FieldLocation {
  sec: number;
  para: number;
  ctrlIdx?: number;
  offset?: number;
}

interface FieldInfo {
  name: string;
  fieldType: string;
  currentValue?: unknown;
  value?: unknown;
  location?: FieldLocation;
}

interface DeepSearchMatch {
  type: 'paragraph' | 'field' | 'cell';
  text: string;
  normalizedText?: string;
  sec?: number;
  para?: number;
  offset?: number;
  length?: number;
  fieldName?: string;
  fieldType?: string;
  location?: FieldLocation;
  controlIdx?: number;
  cellIdx?: number;
  row?: number;
  col?: number;
}

function parseJson<T>(op: Op, stage: 'execute' | 'postprocess', value: string, label: string): T {
  try {
    return JSON.parse(value) as T;
  } catch (e) {
    throw new OpError(op, stage, `Failed to parse ${label}: ${value.slice(0, 200)}`, e);
  }
}

function normalizeHit(op: Op, hit: SearchHit): { sec: number; para: number; offset: number; length: number } {
  const sec = hit.sec ?? hit.sectionIndex;
  const para = hit.para ?? hit.paragraphIndex;
  const offset = hit.charOffset ?? hit.offset;
  if (sec === undefined || para === undefined || offset === undefined) {
    throw new OpError(op, 'postprocess', `searchText returned unexpected shape: ${JSON.stringify(hit)}`);
  }
  return { sec, para, offset, length: hit.length ?? 0 };
}

function normalizeSearchText(value: string, caseSensitive: boolean): string {
  const compact = String(value || '').replace(/\s+/g, '');
  return caseSensitive ? compact : compact.toLocaleLowerCase();
}

function includesQuery(value: string, query: string, caseSensitive: boolean): boolean {
  const haystack = normalizeSearchText(value, caseSensitive);
  const needle = normalizeSearchText(query, caseSensitive);
  return !!needle && haystack.includes(needle);
}

export function applyOp(doc: HwpDocWrapper, op: Op): OpResult {
  try {
    switch (op.kind) {
      case 'insert_text':
        return opInsertText(doc, op);
      case 'insert_image':
        return opInsertImage(doc, op);
      case 'delete_text':
        return opDeleteText(doc, op);
      case 'replace_text':
        return opReplaceText(doc, op);
      case 'split_paragraph':
        return opSplitParagraph(doc, op);
      case 'set_char_format':
        return opSetCharFormat(doc, op);
      case 'set_para_format':
        return opSetParaFormat(doc, op);
      case 'set_char_format_in_cell':
        return opSetCharFormatInCell(doc, op);
      case 'set_para_format_in_cell':
        return opSetParaFormatInCell(doc, op);
      case 'set_field':
        return opSetField(doc, op);
      case 'search_replace_all':
        return opSearchReplaceAll(doc, op);
      case 'create_table':
        return opCreateTable(doc, op);
      case 'insert_text_in_cell':
        return opInsertTextInCell(doc, op);
      case 'delete_text_in_cell':
        return opDeleteTextInCell(doc, op);
      case 'insert_table_row':
        return opInsertTableRow(doc, op);
      case 'insert_table_column':
        return opInsertTableColumn(doc, op);
      case 'delete_table_row':
        return opDeleteTableRow(doc, op);
      case 'delete_table_column':
        return opDeleteTableColumn(doc, op);
      case 'set_table_properties':
        return opSetTableProperties(doc, op);
      case 'set_cell_properties':
        return opSetCellProperties(doc, op);
      case 'paste_reference_component':
        return opPasteReferenceComponent(doc, op);
      case 'call_hwp_function':
        return opCallHwpFunction(doc, op);
      case 'get_paragraph_text':
        return opGetParagraphText(doc, op);
      case 'search_text':
        return opSearchText(doc, op);
      case 'get_table_info':
        return opGetTableInfo(doc, op);
      case 'get_text_in_cell':
        return opGetTextInCell(doc, op);
      case 'get_hwp_function_catalog':
        return opGetHwpFunctionCatalog(doc);
      case 'search_deep':
        return opSearchDeep(doc, op);
      default: {
        const _exhaustive: never = op;
        throw new Error(`Unknown op: ${JSON.stringify(_exhaustive)}`);
      }
    }
  } catch (err) {
    if (err instanceof OpError) throw err;
    const message = err instanceof Error ? err.message : typeof err === 'string' ? err : String(err);
    throw new OpError(op, 'execute', message, err);
  }
}

interface CreateTableResult {
  ok?: boolean;
  paraIdx?: number;
  controlIdx?: number;
}

function clampTableSize(value: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(1, Math.min(20, Math.trunc(value)));
}

// ---- insert_text ----
// 핵심: rhwp는 \n을 단락 분리로 해석하지 않는다. 여러 줄을 넣으려면
// insert_text 후 split_paragraph를 명시적으로 호출해야 한다.
function opInsertText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'insert_text' }>): OpResult {
  doc.insertText(op.sec, op.para, op.offset, op.text);
  return { affectedPages: [op.sec] }; // TODO: 실제 페이지 계산은 STEP 5 렌더러에서
}

// ---- insert_image ----
// HWPUNIT은 1/7200 inch. 1mm = 7200 / 25.4 ≈ 283.465 HWPUNIT.
const HWPUNIT_PER_MM = 7200 / 25.4;
// A4 본문 폭(여백 제외)을 넘는 그림은 페이지를 깨뜨린다.
const MAX_IMAGE_WIDTH_MM = 160;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

function opInsertImage(doc: HwpDocWrapper, op: Extract<Op, { kind: 'insert_image' }>): OpResult {
  let bytes: Buffer;
  try {
    bytes = Buffer.from(op.dataBase64, 'base64');
  } catch {
    throw new OpError(op, 'validate', 'dataBase64 is not valid base64');
  }
  if (!bytes.length) throw new OpError(op, 'validate', 'image data is empty');
  if (bytes.length > MAX_IMAGE_BYTES) {
    throw new OpError(op, 'validate', `image too large: ${bytes.length} bytes`);
  }
  const naturalW = Math.max(1, Math.floor(op.naturalWidthPx));
  const naturalH = Math.max(1, Math.floor(op.naturalHeightPx));

  let widthMm = Math.min(Math.max(op.widthMm ?? 120, 10), MAX_IMAGE_WIDTH_MM);
  // 세로로 긴 그림이 페이지를 넘치지 않게 높이도 제한한다. 비율은 유지한다.
  const MAX_IMAGE_HEIGHT_MM = 200;
  if (widthMm * (naturalH / naturalW) > MAX_IMAGE_HEIGHT_MM) {
    widthMm = MAX_IMAGE_HEIGHT_MM * (naturalW / naturalH);
  }
  const width = Math.round(widthMm * HWPUNIT_PER_MM);
  const height = Math.round(width * (naturalH / naturalW));

  const raw = doc.insertPicture(
    op.sec, op.para, op.offset, new Uint8Array(bytes),
    width, height, naturalW, naturalH,
    (op.ext ?? 'png').toLowerCase(), op.description ?? '',
  );
  const result = parseJson<{ ok?: boolean }>(op, 'execute', raw, 'insertPicture result');
  if (!result.ok) {
    throw new OpError(op, 'postprocess', `insertPicture returned unexpected shape: ${raw}`);
  }
  return { affectedPages: [op.sec] };
}

// ---- create_table ----
function opCreateTable(doc: HwpDocWrapper, op: Extract<Op, { kind: 'create_table' }>): OpResult {
  const rows = clampTableSize(op.rows, 3);
  const cols = clampTableSize(op.cols, 3);
  const created = parseJson<CreateTableResult>(op, 'execute', doc.createTable(op.sec, op.para, op.offset, rows, cols), 'createTable result');
  if (!created.ok || created.paraIdx === undefined || created.controlIdx === undefined) {
    throw new OpError(op, 'postprocess', `createTable returned unexpected shape: ${JSON.stringify(created)}`);
  }

  const cells = op.cells ?? [];
  for (let row = 0; row < Math.min(rows, cells.length); row++) {
    const rowValues = cells[row] ?? [];
    for (let col = 0; col < Math.min(cols, rowValues.length); col++) {
      const text = String(rowValues[col] ?? '');
      if (!text) continue;
      doc.insertTextInCell(op.sec, created.paraIdx, created.controlIdx, row * cols + col, 0, 0, text);
    }
  }

  return {
    affectedPages: [op.sec],
    data: { rows, cols, paraIdx: created.paraIdx, controlIdx: created.controlIdx },
  };
}

function opInsertTextInCell(doc: HwpDocWrapper, op: Extract<Op, { kind: 'insert_text_in_cell' }>): OpResult {
  doc.insertTextInCell(op.sec, op.para, op.controlIdx, op.cellIdx, op.cellPara, op.offset, op.text);
  return { affectedPages: [op.sec] };
}

function opDeleteTextInCell(doc: HwpDocWrapper, op: Extract<Op, { kind: 'delete_text_in_cell' }>): OpResult {
  doc.deleteTextInCell(op.sec, op.para, op.controlIdx, op.cellIdx, op.cellPara, op.offset, op.length);
  return { affectedPages: [op.sec] };
}

function opInsertTableRow(doc: HwpDocWrapper, op: Extract<Op, { kind: 'insert_table_row' }>): OpResult {
  const data = parseJson<Record<string, unknown>>(op, 'execute', doc.insertTableRow(op.sec, op.para, op.controlIdx, op.rowIdx, op.below ?? true), 'insertTableRow result');
  return { affectedPages: [op.sec], data };
}

function opInsertTableColumn(doc: HwpDocWrapper, op: Extract<Op, { kind: 'insert_table_column' }>): OpResult {
  const data = parseJson<Record<string, unknown>>(op, 'execute', doc.insertTableColumn(op.sec, op.para, op.controlIdx, op.colIdx, op.right ?? true), 'insertTableColumn result');
  return { affectedPages: [op.sec], data };
}

function opDeleteTableRow(doc: HwpDocWrapper, op: Extract<Op, { kind: 'delete_table_row' }>): OpResult {
  const data = parseJson<Record<string, unknown>>(op, 'execute', doc.deleteTableRow(op.sec, op.para, op.controlIdx, op.rowIdx), 'deleteTableRow result');
  return { affectedPages: [op.sec], data };
}

function opDeleteTableColumn(doc: HwpDocWrapper, op: Extract<Op, { kind: 'delete_table_column' }>): OpResult {
  const data = parseJson<Record<string, unknown>>(op, 'execute', doc.deleteTableColumn(op.sec, op.para, op.controlIdx, op.colIdx), 'deleteTableColumn result');
  return { affectedPages: [op.sec], data };
}

function opSetTableProperties(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_table_properties' }>): OpResult {
  const data = parseJson<Record<string, unknown>>(op, 'execute', doc.setTableProperties(op.sec, op.para, op.controlIdx, op.props), 'setTableProperties result');
  return { affectedPages: [op.sec], data };
}

function opSetCellProperties(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_cell_properties' }>): OpResult {
  const data = parseJson<Record<string, unknown>>(op, 'execute', doc.setCellProperties(op.sec, op.para, op.controlIdx, op.cellIdx, op.props), 'setCellProperties result');
  return { affectedPages: [op.sec], data };
}

const REFERENCE_COMPONENTS: Record<string, { sourcePath: string; sourceSec: number; sourcePara: number; sourceControlIdx: number }> = {
  attachment_header_bar: {
    sourcePath: 'data/hwp_corpus/kma_press/040_ATC202601191001531_9c0b8bfe-ddbb-4800-933c-a41f63c63f6e.hwp',
    sourceSec: 0,
    sourcePara: 29,
    sourceControlIdx: 0,
  },
  contact_box: {
    sourcePath: 'data/hwp_corpus/kma_press/001_ATC202604021618462_541a4117-3530-4c59-adaf-e57521d60f7e.hwp',
    sourceSec: 0,
    sourcePara: 75,
    sourceControlIdx: 0,
  },
  press_header: {
    sourcePath: 'data/hwp_corpus/kma_press/001_ATC202604021618462_541a4117-3530-4c59-adaf-e57521d60f7e.hwp',
    sourceSec: 0,
    sourcePara: 0,
    sourceControlIdx: 3,
  },
};

function resolveReferencePath(pathValue: string): string {
  const cwd = process.cwd();
  const root = existsSync(resolve(cwd, 'data/hwp_corpus')) ? cwd : resolve(cwd, '../..');
  const absolute = resolve(root, pathValue);
  const rel = relative(root, absolute);
  if (rel.startsWith('..') || rel.startsWith('/') || !rel.startsWith('data/hwp_corpus/')) {
    throw new Error(`Reference path is outside allowed corpus: ${pathValue}`);
  }
  return absolute;
}

function findPastedTable(doc: HwpDocWrapper, paraStart: number, expectedCells?: number): { paraIdx: number; controlIdx: number } | null {
  for (let para = Math.max(0, paraStart - 1); para <= paraStart + 2; para++) {
    for (let controlIdx = 0; controlIdx < 20; controlIdx++) {
      try {
        const dim = JSON.parse(doc.getTableDimensions(0, para, controlIdx)) as { cellCount?: number };
        if (!Number.isFinite(Number(dim.cellCount))) continue;
        if (!expectedCells || Number(dim.cellCount) === expectedCells) {
          return { paraIdx: para, controlIdx };
        }
      } catch {
        // not a table/control
      }
    }
  }
  return null;
}

function assertSafeRoundTripGeometry(doc: HwpDocWrapper, op: Op): void {
  let reloaded: HwpDocument | null = null;
  try {
    const bytes = doc.raw.exportHwp();
    reloaded = new HwpDocument(bytes);
    const pageCount = typeof (reloaded as any).pageCount === 'function' ? (reloaded as any).pageCount() : 0;
    const pageInfo = JSON.parse(reloaded.getPageInfo(0)) as { width?: unknown; height?: unknown };
    const width = Number(pageInfo.width);
    const height = Number(pageInfo.height);
    if (!Number.isFinite(pageCount) || pageCount < 1 || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      throw new OpError(
        op,
        'postprocess',
        `Reference component corrupts exported page geometry: pageCount=${pageCount}, width=${pageInfo.width}, height=${pageInfo.height}`,
      );
    }
  } finally {
    try { reloaded?.free(); } catch {}
  }
}

function opPasteReferenceComponent(doc: HwpDocWrapper, op: Extract<Op, { kind: 'paste_reference_component' }>): OpResult {
  const preset = op.component ? REFERENCE_COMPONENTS[op.component] : undefined;
  const sourcePath = op.sourcePath ?? preset?.sourcePath;
  const sourceSec = op.sourceSec ?? preset?.sourceSec;
  const sourcePara = op.sourcePara ?? preset?.sourcePara;
  const sourceControlIdx = op.sourceControlIdx ?? preset?.sourceControlIdx;
  if (!sourcePath || sourceSec === undefined || sourcePara === undefined || sourceControlIdx === undefined) {
    throw new OpError(op, 'validate', 'Missing reference component source');
  }

  const bytes = readFileSync(resolveReferencePath(sourcePath));
  const source = new HwpDocument(new Uint8Array(bytes));
  let html = '';
  let sourceCellCount: number | undefined;
  try {
    html = source.exportControlHtml(sourceSec, sourcePara, sourceControlIdx);
    try {
      const dim = JSON.parse(source.getTableDimensions(sourceSec, sourcePara, sourceControlIdx)) as { cellCount?: number };
      sourceCellCount = Number(dim.cellCount);
    } catch {
      sourceCellCount = undefined;
    }
  } finally {
    try { source.free(); } catch {}
  }

  const pasted = parseJson<Record<string, unknown>>(op, 'execute', doc.raw.pasteHtml(op.sec, op.para, op.offset, html), 'pasteHtml result');
  const paraIdx = Number(pasted.paraIdx ?? op.para);
  const table = findPastedTable(doc, paraIdx, sourceCellCount);
  const replacements = op.replacements ?? [];
  if (table) {
    for (const replacement of replacements) {
      const cellIdx = Number(replacement.cellIdx);
      if (!Number.isFinite(cellIdx)) continue;
      const text = String(replacement.text ?? '');
      const before = doc.getTextInCell(op.sec, table.paraIdx, table.controlIdx, cellIdx, 0, 0, 100_000);
      if (before.length > 0) {
        doc.deleteTextInCell(op.sec, table.paraIdx, table.controlIdx, cellIdx, 0, 0, before.length);
      }
      if (text) {
        doc.insertTextInCell(op.sec, table.paraIdx, table.controlIdx, cellIdx, 0, 0, text);
      }
    }
  }

  assertSafeRoundTripGeometry(doc, op);

  return {
    affectedPages: [op.sec],
    data: {
      ok: true,
      component: op.component ?? null,
      sourcePath,
      pasted,
      table,
      replacedCells: replacements.length,
    },
  };
}

function isLikelyReadOnlyRawFunction(method: string): boolean {
  return /^(get|find|search|render|export|measure|hitTest|logicalToTextOffset|pageCount|clipboardHas|has|evaluate)/.test(method);
}

function opCallHwpFunction(doc: HwpDocWrapper, op: Extract<Op, { kind: 'call_hwp_function' }>): OpResult {
  const data = doc.callRawFunction(op.method, op.args ?? []);
  const changed = op.affectsDocument ?? !isLikelyReadOnlyRawFunction(op.method);
  return { affectedPages: changed ? [0] : [], data: { method: op.method, result: data } };
}

// ---- delete_text ----
// 핵심: 삭제 범위는 단일 문단 내부로 제한한다. 문단 병합/다중 문단 삭제는 별도 연산으로 확장한다.
function opDeleteText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'delete_text' }>): OpResult {
  doc.deleteText(op.sec, op.para, op.offset, op.length);
  return { affectedPages: [op.sec] };
}

// ---- replace_text ----
// 핵심: 전역 replaceAll은 save/reload 시 원복되는 버그가 있어서 사용 금지.
// 여기서는 단일 위치 치환만. 전역 치환은 search_replace_all에서 loop로 구현.
function opReplaceText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'replace_text' }>): OpResult {
  doc.replaceText(op.sec, op.para, op.offset, op.length, op.newText);
  return { affectedPages: [op.sec] };
}

// ---- split_paragraph ----
// 핵심: 단락 분리는 오직 이 메서드로만. insertText의 \n은 동작 안 함.
function opSplitParagraph(doc: HwpDocWrapper, op: Extract<Op, { kind: 'split_paragraph' }>): OpResult {
  doc.splitParagraph(op.sec, op.para, op.offset);
  return { affectedPages: [op.sec] };
}

// ---- set_char_format ----
// 핵심 (프로젝트에서 가장 중요한 패턴):
// fontFamily 문자열만 주면 save/reload 시 "맑은 고딕"으로 리셋되는 버그 존재.
// 반드시 findOrCreateFontId로 ID를 얻어 fontId + fontIds[7]로 지정해야 한다.
// 이 함수는 props.fontName이 주어지면 자동으로 fontId 변환을 수행한다.
function opSetCharFormat(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_char_format' }>): OpResult {
  const before = doc.getText(op.sec, op.para, 0, 100_000);
  const props: CharProps = { ...op.props };

  if (props.fontName && !props.fontId) {
    const fontId = doc.findOrCreateFontId(props.fontName);
    props.fontId = fontId;
    props.fontIds = [fontId, fontId, fontId, fontId, fontId, fontId, fontId];
    delete props.fontName;
  }

  doc.setCharFormat(op.sec, op.para, op.start, op.end, props);
  const after = doc.getText(op.sec, op.para, 0, 100_000);
  if (after !== before) {
    throw new OpError(op, 'postprocess', 'Character formatting changed paragraph text; operation was rejected');
  }
  return { affectedPages: [op.sec] };
}

// ---- set_para_format ----
// 핵심: 문단 단위 속성만 처리한다. 셀/머리말/꼬리말 내부 문단은 별도 op로 확장한다.
function opSetParaFormat(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_para_format' }>): OpResult {
  const before = doc.getText(op.sec, op.para, 0, 100_000);
  doc.setParaFormat(op.sec, op.para, op.props);
  const after = doc.getText(op.sec, op.para, 0, 100_000);
  if (after !== before) {
    throw new OpError(op, 'postprocess', 'Paragraph formatting changed paragraph text; operation was rejected');
  }
  return { affectedPages: [op.sec] };
}

function normalizeCharPropsForFonts(doc: HwpDocWrapper, props: CharProps): CharProps {
  const next: CharProps = { ...props };
  if (next.fontName && !next.fontId) {
    const fontId = doc.findOrCreateFontId(next.fontName);
    next.fontId = fontId;
    next.fontIds = [fontId, fontId, fontId, fontId, fontId, fontId, fontId];
    delete next.fontName;
  }
  return next;
}

function opSetCharFormatInCell(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_char_format_in_cell' }>): OpResult {
  const props = normalizeCharPropsForFonts(doc, op.props);
  doc.setCharFormatInCell(op.sec, op.para, op.controlIdx, op.cellIdx, op.cellPara, op.start, op.end, props);
  return { affectedPages: [op.sec] };
}

function opSetParaFormatInCell(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_para_format_in_cell' }>): OpResult {
  doc.setParaFormatInCell(op.sec, op.para, op.controlIdx, op.cellIdx, op.cellPara, op.props);
  return { affectedPages: [op.sec] };
}

// ---- set_field ----
// 핵심: 필드 타입마다 다른 경로.
// - edit/checkBtn/radioBtn/comboBox: setFormValue로 영속 저장
// - clickhere: setFieldValueByName은 세션 내에서만 유효, 저장 후 풀림.
//   그래서 location 찾아서 직접 insertText로 우회.
function opSetField(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_field' }>): OpResult {
  const fields = parseJson<FieldInfo[]>(op, 'execute', doc.getFieldList(), 'field list');
  const field = fields.find((f) => f.name === op.fieldName);
  if (!field) {
    throw new OpError(
      op,
      'validate',
      `Field "${op.fieldName}" not found. Available: ${fields.map((f) => f.name).join(', ')}`,
    );
  }

  if (['edit', 'checkBtn', 'radioBtn', 'comboBox'].includes(field.fieldType)) {
    if (!field.location || field.location.ctrlIdx === undefined) {
      throw new OpError(op, 'validate', `Field "${op.fieldName}" lacks location data`);
    }
    const valueJson = JSON.stringify(field.fieldType === 'edit' ? op.value : { value: op.value });
    doc.setFormValue(field.location.sec, field.location.para, field.location.ctrlIdx, valueJson);
  } else if (field.fieldType === 'clickhere') {
    if (!field.location) {
      throw new OpError(op, 'validate', `clickhere field "${op.fieldName}" lacks location`);
    }
    const offset = field.location.offset ?? 0;
    doc.insertText(field.location.sec, field.location.para, offset, op.value);
  } else {
    doc.setFieldValueByName(op.fieldName, op.value);
  }

  return { affectedPages: [field.location?.sec ?? 0] };
}

// ---- search_replace_all ----
// 핵심: rhwp의 replaceAll은 save/reload 시 원복되는 버그가 있음.
// 여기서는 searchText를 반복 호출해서 replaceText로 교체하는 방식으로 영속 치환 구현.
function opSearchReplaceAll(doc: HwpDocWrapper, op: Extract<Op, { kind: 'search_replace_all' }>): OpResult {
  const caseSensitive = op.caseSensitive ?? false;
  const affectedSections = new Set<number>();
  let count = 0;
  const maxIterations = 10000;

  let fromSec = 0;
  let fromPara = 0;
  let fromChar = 0;
  const seen = new Set<string>();

  while (count < maxIterations) {
    const hit = parseJson<SearchHit>(
      op,
      'execute',
      doc.searchText(op.query, fromSec, fromPara, fromChar, true, caseSensitive),
      'search result',
    );
    if (!hit.found) break;

    const loc = normalizeHit(op, hit);
    const key = `${loc.sec}:${loc.para}:${loc.offset}`;
    if (seen.has(key)) break;
    seen.add(key);
    doc.replaceText(loc.sec, loc.para, loc.offset, hit.length ?? op.query.length, op.replacement);
    affectedSections.add(loc.sec);
    count++;

    fromSec = loc.sec;
    fromPara = loc.para;
    fromChar = loc.offset + op.replacement.length;
  }

  return {
    affectedPages: Array.from(affectedSections),
    data: { replacedCount: count },
  };
}

// ---- get_paragraph_text (read-only) ----
// 핵심: rhwp는 단락 길이 API를 따로 노출하지 않으므로 충분히 큰 범위를 읽는다.
function opGetParagraphText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'get_paragraph_text' }>): OpResult {
  const text = doc.getText(op.sec, op.para, 0, 100_000);
  return { affectedPages: [], data: { text } };
}

function opGetTableInfo(doc: HwpDocWrapper, op: Extract<Op, { kind: 'get_table_info' }>): OpResult {
  const dimensions = parseJson<Record<string, unknown>>(op, 'execute', doc.getTableDimensions(op.sec, op.para, op.controlIdx), 'table dimensions');
  const properties = parseJson<Record<string, unknown>>(op, 'execute', doc.getTableProperties(op.sec, op.para, op.controlIdx), 'table properties');
  return { affectedPages: [], data: { sec: op.sec, para: op.para, controlIdx: op.controlIdx, dimensions, properties } };
}

function opGetTextInCell(doc: HwpDocWrapper, op: Extract<Op, { kind: 'get_text_in_cell' }>): OpResult {
  const text = doc.getTextInCell(op.sec, op.para, op.controlIdx, op.cellIdx, op.cellPara ?? 0, op.offset ?? 0, op.count ?? 100_000);
  return { affectedPages: [], data: { text } };
}

function opGetHwpFunctionCatalog(doc: HwpDocWrapper): OpResult {
  return { affectedPages: [], data: { functions: doc.listRawFunctions() } };
}

function opSearchDeep(doc: HwpDocWrapper, op: Extract<Op, { kind: 'search_deep' }>): OpResult {
  const caseSensitive = op.caseSensitive ?? false;
  const matches: DeepSearchMatch[] = [];
  const maxMatches = 80;

  const sectionCount = doc.getSectionCount();
  for (let sec = 0; sec < sectionCount && matches.length < maxMatches; sec++) {
    const paraCount = doc.getParagraphCount(sec);
    for (let para = 0; para < paraCount && matches.length < maxMatches; para++) {
      const text = doc.getText(sec, para, 0, 100_000);
      if (includesQuery(text, op.query, caseSensitive)) {
        matches.push({
          type: 'paragraph',
          sec,
          para,
          text: text.slice(0, 300),
          normalizedText: normalizeSearchText(text, caseSensitive).slice(0, 300),
          offset: text.indexOf(op.query),
          length: op.query.length,
        });
      }

      for (let controlIdx = 0; controlIdx < 20 && matches.length < maxMatches; controlIdx++) {
        let dimensions: { rowCount?: number; colCount?: number; cellCount?: number };
        try {
          dimensions = parseJson(op, 'execute', doc.getTableDimensions(sec, para, controlIdx), 'table dimensions');
        } catch {
          continue;
        }
        const colCount = Number(dimensions.colCount || 0);
        const cellCount = Number(dimensions.cellCount || 0);
        for (let cellIdx = 0; cellIdx < cellCount && matches.length < maxMatches; cellIdx++) {
          let cellText = '';
          try {
            cellText = doc.getTextInCell(sec, para, controlIdx, cellIdx, 0, 0, 100_000);
          } catch {
            continue;
          }
          if (includesQuery(cellText, op.query, caseSensitive)) {
            matches.push({
              type: 'cell',
              sec,
              para,
              controlIdx,
              cellIdx,
              row: colCount ? Math.floor(cellIdx / colCount) : undefined,
              col: colCount ? cellIdx % colCount : undefined,
              text: cellText.slice(0, 300),
              normalizedText: normalizeSearchText(cellText, caseSensitive).slice(0, 300),
              offset: cellText.indexOf(op.query),
              length: op.query.length,
            });
          }
        }
      }
    }
  }

  const fields = parseJson<FieldInfo[]>(op, 'execute', doc.getFieldList(), 'field list');
  for (const field of fields) {
    const currentValue = field.currentValue ?? field.value ?? '';
    const fieldText = `${field.name || ''} ${field.fieldType || ''} ${String(currentValue)}`;
    if (includesQuery(fieldText, op.query, caseSensitive)) {
      matches.push({
        type: 'field',
        text: fieldText.slice(0, 300),
        normalizedText: normalizeSearchText(fieldText, caseSensitive).slice(0, 300),
        fieldName: field.name,
        fieldType: field.fieldType,
        location: field.location,
      });
    }
  }

  return { affectedPages: [], data: { matches, count: matches.length } };
}

// ---- search_text (read-only) ----
// 핵심: searchText 반환 JSON은 @rhwp/core 0.7.3 기준 {found, sec, para, charOffset, length}.
function opSearchText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'search_text' }>): OpResult {
  const caseSensitive = op.caseSensitive ?? false;
  const matches: Array<{ sec: number; para: number; offset: number; length: number }> = [];

  let fromSec = 0;
  let fromPara = 0;
  let fromChar = 0;
  const maxIterations = 10000;
  const seen = new Set<string>();

  for (let i = 0; i < maxIterations; i++) {
    const hit = parseJson<SearchHit>(
      op,
      'execute',
      doc.searchText(op.query, fromSec, fromPara, fromChar, true, caseSensitive),
      'search result',
    );
    if (!hit.found) break;

    const loc = normalizeHit(op, hit);
    const key = `${loc.sec}:${loc.para}:${loc.offset}`;
    if (seen.has(key)) break;
    seen.add(key);
    matches.push(loc);
    fromSec = loc.sec;
    fromPara = loc.para;
    fromChar = loc.offset + (loc.length || op.query.length);
  }

  return { affectedPages: [], data: { matches, count: matches.length } };
}
