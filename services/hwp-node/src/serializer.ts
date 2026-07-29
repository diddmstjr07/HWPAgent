import type { HwpDocWrapper } from './hwp-helper.js';
import { getPageCount } from './renderer.js';

interface FieldLocation {
  sec?: number;
  para?: number;
  ctrlIdx?: number;
  offset?: number;
  [key: string]: unknown;
}

interface RawField {
  name?: string;
  fieldName?: string;
  fieldType?: string;
  type?: string;
  location?: FieldLocation;
  value?: unknown;
  currentValue?: unknown;
  [key: string]: unknown;
}

export interface SerializedField {
  name: string;
  fieldType: string;
  location: FieldLocation | null;
  currentValue: unknown;
}

export interface OutlineItem {
  sec: number;
  para: number;
  preview: string;
  length: number;
  style: unknown;
}

export interface SerializedTable {
  sec: number;
  para: number;
  controlIdx: number;
  rowCount: number;
  colCount: number;
  cellCount: number;
}

export interface DocumentStructure {
  metadata: {
    sectionCount: number;
    pageCount: number;
    sourceFormat: 'hwp';
  };
  fields: SerializedField[];
  outline: OutlineItem[];
  tables: SerializedTable[];
}

export interface WebParagraph {
  sec: number;
  para: number;
  text: string;
  length: number;
  style: unknown;
}

export interface WebTableCell {
  cellIdx: number;
  row: number;
  col: number;
  text: string;
  length: number;
}

export interface WebTable extends SerializedTable {
  cells: WebTableCell[];
}

export interface WebSection {
  sec: number;
  paragraphs: WebParagraph[];
  tables: WebTable[];
}

export interface WebDocument {
  metadata: DocumentStructure['metadata'];
  sections: WebSection[];
}

function safeJsonParse<T>(value: string, fallback: T): T {
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function normalizeField(field: RawField): SerializedField {
  const name = String(field.name ?? field.fieldName ?? '');
  const fieldType = String(field.fieldType ?? field.type ?? 'unknown');
  return {
    name,
    fieldType,
    location: field.location ?? null,
    currentValue: field.currentValue ?? field.value ?? null,
  };
}

function readParaStyle(doc: HwpDocWrapper, sec: number, para: number): unknown {
  try {
    const props = safeJsonParse<Record<string, unknown>>(doc.getParaPropertiesAt(sec, para), {});
    return {
      alignment: props.alignment ?? props.align ?? null,
      lineSpacing: props.lineSpacing ?? null,
      paraShapeId: props.paraShapeId ?? null,
    };
  } catch {
    return null;
  }
}

export function serializeStructure(doc: HwpDocWrapper): DocumentStructure {
  const sectionCount = doc.getSectionCount();
  const outline: OutlineItem[] = [];
  const tables: SerializedTable[] = [];

  for (let sec = 0; sec < sectionCount; sec++) {
    const paraCount = doc.getParagraphCount(sec);
    for (let para = 0; para < paraCount; para++) {
      const text = doc.getText(sec, para, 0, 100_000);
      const preview = text.replace(/\s+/g, ' ').trim().slice(0, 80);
      outline.push({
        sec,
        para,
        preview,
        length: text.length,
        style: readParaStyle(doc, sec, para),
      });

      for (let controlIdx = 0; controlIdx < 20; controlIdx++) {
        try {
          const dimensions = safeJsonParse<Record<string, unknown>>(doc.getTableDimensions(sec, para, controlIdx), {});
          const rowCount = Number(dimensions.rowCount);
          const colCount = Number(dimensions.colCount);
          const cellCount = Number(dimensions.cellCount);
          if (Number.isFinite(rowCount) && Number.isFinite(colCount) && Number.isFinite(cellCount)) {
            tables.push({ sec, para, controlIdx, rowCount, colCount, cellCount });
          }
        } catch {
          // Non-table controls or missing control indexes are expected while scanning.
        }
      }
    }
  }

  const rawFields = safeJsonParse<RawField[]>(doc.getFieldList(), []);
  const fields = rawFields.map(normalizeField).filter((field) => field.name);

  return {
    metadata: {
      sectionCount,
      pageCount: getPageCount(doc),
      sourceFormat: 'hwp',
    },
    fields,
    outline,
    tables,
  };
}

export function serializeWebDocument(doc: HwpDocWrapper): WebDocument {
  const sectionCount = doc.getSectionCount();
  const sections: WebSection[] = [];

  for (let sec = 0; sec < sectionCount; sec++) {
    const paragraphs: WebParagraph[] = [];
    const tables: WebTable[] = [];
    const paraCount = doc.getParagraphCount(sec);

    for (let para = 0; para < paraCount; para++) {
      const text = doc.getText(sec, para, 0, 100_000);
      paragraphs.push({
        sec,
        para,
        text,
        length: text.length,
        style: readParaStyle(doc, sec, para),
      });

      for (let controlIdx = 0; controlIdx < 20; controlIdx++) {
        try {
          const dimensions = safeJsonParse<Record<string, unknown>>(doc.getTableDimensions(sec, para, controlIdx), {});
          const rowCount = Number(dimensions.rowCount);
          const colCount = Number(dimensions.colCount);
          const cellCount = Number(dimensions.cellCount);
          if (!Number.isFinite(rowCount) || !Number.isFinite(colCount) || !Number.isFinite(cellCount)) {
            continue;
          }

          const cells: WebTableCell[] = [];
          for (let cellIdx = 0; cellIdx < cellCount; cellIdx++) {
            let cellText = '';
            try {
              cellText = doc.getTextInCell(sec, para, controlIdx, cellIdx, 0, 0, 100_000);
            } catch {
              cellText = '';
            }
            cells.push({
              cellIdx,
              row: colCount ? Math.floor(cellIdx / colCount) : 0,
              col: colCount ? cellIdx % colCount : cellIdx,
              text: cellText,
              length: cellText.length,
            });
          }

          tables.push({ sec, para, controlIdx, rowCount, colCount, cellCount, cells });
        } catch {
          // Non-table controls or missing control indexes are expected while scanning.
        }
      }
    }

    sections.push({ sec, paragraphs, tables });
  }

  return {
    metadata: {
      sectionCount,
      pageCount: getPageCount(doc),
      sourceFormat: 'hwp',
    },
    sections,
  };
}
