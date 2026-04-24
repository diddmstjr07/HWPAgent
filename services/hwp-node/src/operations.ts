import type { HwpDocWrapper, CharProps, ParaProps } from './hwp-helper.js';

// ---- Op types (discriminated union) ----
export type Op =
  // Write operations
  | { kind: 'insert_text'; sec: number; para: number; offset: number; text: string }
  | { kind: 'delete_text'; sec: number; para: number; offset: number; length: number }
  | { kind: 'replace_text'; sec: number; para: number; offset: number; length: number; newText: string }
  | { kind: 'split_paragraph'; sec: number; para: number; offset: number }
  | { kind: 'set_char_format'; sec: number; para: number; start: number; end: number; props: CharProps }
  | { kind: 'set_para_format'; sec: number; para: number; props: ParaProps }
  | { kind: 'set_field'; fieldName: string; value: string }
  | { kind: 'search_replace_all'; query: string; replacement: string; caseSensitive?: boolean }
  // Read-only operations
  | { kind: 'get_paragraph_text'; sec: number; para: number }
  | { kind: 'search_text'; query: string; caseSensitive?: boolean };

export interface OpResult {
  affectedPages: number[];
  // Read-only ops can return data here.
  data?: unknown;
}

// Discriminate read vs write for AI agent.
export const READ_OPS: ReadonlyArray<Op['kind']> = ['get_paragraph_text', 'search_text'];
export const WRITE_OPS: ReadonlyArray<Op['kind']> = [
  'insert_text',
  'delete_text',
  'replace_text',
  'split_paragraph',
  'set_char_format',
  'set_para_format',
  'set_field',
  'search_replace_all',
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
  location?: FieldLocation;
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

export function applyOp(doc: HwpDocWrapper, op: Op): OpResult {
  try {
    switch (op.kind) {
      case 'insert_text':
        return opInsertText(doc, op);
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
      case 'set_field':
        return opSetField(doc, op);
      case 'search_replace_all':
        return opSearchReplaceAll(doc, op);
      case 'get_paragraph_text':
        return opGetParagraphText(doc, op);
      case 'search_text':
        return opSearchText(doc, op);
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

// ---- insert_text ----
// 핵심: rhwp는 \n을 단락 분리로 해석하지 않는다. 여러 줄을 넣으려면
// insert_text 후 split_paragraph를 명시적으로 호출해야 한다.
function opInsertText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'insert_text' }>): OpResult {
  doc.insertText(op.sec, op.para, op.offset, op.text);
  return { affectedPages: [op.sec] }; // TODO: 실제 페이지 계산은 STEP 5 렌더러에서
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
  const props: CharProps = { ...op.props };

  if (props.fontName && !props.fontId) {
    const fontId = doc.findOrCreateFontId(props.fontName);
    props.fontId = fontId;
    props.fontIds = [fontId, fontId, fontId, fontId, fontId, fontId, fontId];
    delete props.fontName;
  }

  doc.setCharFormat(op.sec, op.para, op.start, op.end, props);
  return { affectedPages: [op.sec] };
}

// ---- set_para_format ----
// 핵심: 문단 단위 속성만 처리한다. 셀/머리말/꼬리말 내부 문단은 별도 op로 확장한다.
function opSetParaFormat(doc: HwpDocWrapper, op: Extract<Op, { kind: 'set_para_format' }>): OpResult {
  doc.setParaFormat(op.sec, op.para, op.props);
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

  while (count < maxIterations) {
    const hit = parseJson<SearchHit>(
      op,
      'execute',
      doc.searchText(op.query, fromSec, fromPara, fromChar, true, caseSensitive),
      'search result',
    );
    if (!hit.found) break;

    const loc = normalizeHit(op, hit);
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

// ---- search_text (read-only) ----
// 핵심: searchText 반환 JSON은 @rhwp/core 0.7.3 기준 {found, sec, para, charOffset, length}.
function opSearchText(doc: HwpDocWrapper, op: Extract<Op, { kind: 'search_text' }>): OpResult {
  const caseSensitive = op.caseSensitive ?? false;
  const matches: Array<{ sec: number; para: number; offset: number; length: number }> = [];

  let fromSec = 0;
  let fromPara = 0;
  let fromChar = 0;
  const maxIterations = 10000;

  for (let i = 0; i < maxIterations; i++) {
    const hit = parseJson<SearchHit>(
      op,
      'execute',
      doc.searchText(op.query, fromSec, fromPara, fromChar, true, caseSensitive),
      'search result',
    );
    if (!hit.found) break;

    const loc = normalizeHit(op, hit);
    matches.push(loc);
    fromSec = loc.sec;
    fromPara = loc.para;
    fromChar = loc.offset + (loc.length || op.query.length);
  }

  return { affectedPages: [], data: { matches, count: matches.length } };
}
