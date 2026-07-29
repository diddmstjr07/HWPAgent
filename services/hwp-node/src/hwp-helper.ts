import './bootstrap.js';
import { HwpDocument } from '@rhwp/core';
import { readFile, writeFile } from 'node:fs/promises';

function normalizeError(e: unknown): Error {
  if (e instanceof Error) return e;
  if (typeof e === 'string') return new Error(e);
  return new Error(String(e));
}

function normalizeRawArg(value: unknown): unknown {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    if (typeof obj.__base64 === 'string') {
      return Uint8Array.from(Buffer.from(obj.__base64, 'base64'));
    }
  }
  return value;
}

function serializeRawResult(value: unknown): unknown {
  if (value instanceof Uint8Array) {
    return {
      type: 'Uint8Array',
      byteLength: value.byteLength,
      base64: Buffer.from(value).toString('base64'),
    };
  }
  return value;
}

export interface CharProps {
  fontId?: number;
  fontIds?: number[];
  fontName?: string;
  fontSize?: number;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  textColor?: number;
  [key: string]: unknown;
}

export interface ParaProps {
  align?: 'Left' | 'Center' | 'Right' | 'Justify' | 'Distribute';
  lineSpacing?: number;
  lineSpacingType?: 'Percent' | 'Fixed' | 'AtLeast' | 'BetweenLines';
  marginLeft?: number;
  marginRight?: number;
  spacingBefore?: number;
  spacingAfter?: number;
  indent?: number;
  [key: string]: unknown;
}

export class HwpDocWrapper {
  constructor(public raw: HwpDocument) {}

  listRawFunctions(): Array<{ name: string; arity: number }> {
    const proto = Object.getPrototypeOf(this.raw) as Record<string, unknown>;
    return Object.getOwnPropertyNames(proto)
      .filter((name) => name !== 'constructor' && typeof proto[name] === 'function')
      .sort()
      .map((name) => ({ name, arity: (proto[name] as Function).length }));
  }

  callRawFunction(method: string, args: unknown[]): unknown {
    if (method === 'free') {
      throw new Error('free is not callable through the agent tool gateway');
    }
    const fn = (this.raw as unknown as Record<string, unknown>)[method];
    if (typeof fn !== 'function') {
      throw new Error(`Unknown HWP function: ${method}`);
    }
    const normalizedArgs = args.map(normalizeRawArg);
    return serializeRawResult((fn as (...innerArgs: unknown[]) => unknown).apply(this.raw, normalizedArgs));
  }

  insertText(sec: number, para: number, offset: number, text: string): void {
    try {
      this.raw.insertText(sec, para, offset, text);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  deleteText(sec: number, para: number, offset: number, count: number): void {
    try {
      this.raw.deleteText(sec, para, offset, count);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  replaceText(sec: number, para: number, offset: number, length: number, newText: string): void {
    try {
      this.raw.replaceText(sec, para, offset, length, newText);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  splitParagraph(sec: number, para: number, offset: number): void {
    try {
      this.raw.splitParagraph(sec, para, offset);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  createTable(sec: number, para: number, offset: number, rows: number, cols: number): string {
    try {
      return this.raw.createTable(sec, para, offset, rows, cols);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  insertPicture(
    sec: number,
    para: number,
    offset: number,
    imageData: Uint8Array,
    width: number,
    height: number,
    naturalWidthPx: number,
    naturalHeightPx: number,
    extension: string,
    description: string,
  ): string {
    try {
      return this.raw.insertPicture(
        sec, para, offset, imageData, width, height,
        naturalWidthPx, naturalHeightPx, extension, description,
      );
    } catch (e) {
      throw normalizeError(e);
    }
  }

  insertTextInCell(
    sec: number,
    parentPara: number,
    controlIdx: number,
    cellIdx: number,
    cellPara: number,
    offset: number,
    text: string,
  ): string {
    try {
      return this.raw.insertTextInCell(sec, parentPara, controlIdx, cellIdx, cellPara, offset, text);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  deleteTextInCell(
    sec: number,
    parentPara: number,
    controlIdx: number,
    cellIdx: number,
    cellPara: number,
    offset: number,
    count: number,
  ): string {
    try {
      return this.raw.deleteTextInCell(sec, parentPara, controlIdx, cellIdx, cellPara, offset, count);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getTextInCell(sec: number, parentPara: number, controlIdx: number, cellIdx: number, cellPara: number, offset: number, count: number): string {
    try {
      return this.raw.getTextInCell(sec, parentPara, controlIdx, cellIdx, cellPara, offset, count);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getTableDimensions(sec: number, parentPara: number, controlIdx: number): string {
    try {
      return this.raw.getTableDimensions(sec, parentPara, controlIdx);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getTableProperties(sec: number, parentPara: number, controlIdx: number): string {
    try {
      return this.raw.getTableProperties(sec, parentPara, controlIdx);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setTableProperties(sec: number, parentPara: number, controlIdx: number, props: Record<string, unknown>): string {
    try {
      return this.raw.setTableProperties(sec, parentPara, controlIdx, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setCellProperties(sec: number, parentPara: number, controlIdx: number, cellIdx: number, props: Record<string, unknown>): string {
    try {
      return this.raw.setCellProperties(sec, parentPara, controlIdx, cellIdx, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  insertTableRow(sec: number, parentPara: number, controlIdx: number, rowIdx: number, below: boolean): string {
    try {
      return this.raw.insertTableRow(sec, parentPara, controlIdx, rowIdx, below);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  insertTableColumn(sec: number, parentPara: number, controlIdx: number, colIdx: number, right: boolean): string {
    try {
      return this.raw.insertTableColumn(sec, parentPara, controlIdx, colIdx, right);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  deleteTableRow(sec: number, parentPara: number, controlIdx: number, rowIdx: number): string {
    try {
      return this.raw.deleteTableRow(sec, parentPara, controlIdx, rowIdx);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  deleteTableColumn(sec: number, parentPara: number, controlIdx: number, colIdx: number): string {
    try {
      return this.raw.deleteTableColumn(sec, parentPara, controlIdx, colIdx);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setCharFormat(sec: number, para: number, start: number, end: number, props: CharProps): void {
    try {
      this.raw.applyCharFormat(sec, para, start, end, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setParaFormat(sec: number, para: number, props: ParaProps): void {
    try {
      this.raw.applyParaFormat(sec, para, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setCharFormatInCell(
    sec: number,
    parentPara: number,
    controlIdx: number,
    cellIdx: number,
    cellPara: number,
    start: number,
    end: number,
    props: CharProps,
  ): void {
    try {
      this.raw.applyCharFormatInCell(sec, parentPara, controlIdx, cellIdx, cellPara, start, end, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setParaFormatInCell(
    sec: number,
    parentPara: number,
    controlIdx: number,
    cellIdx: number,
    cellPara: number,
    props: ParaProps,
  ): void {
    try {
      this.raw.applyParaFormatInCell(sec, parentPara, controlIdx, cellIdx, cellPara, JSON.stringify(props));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  findOrCreateFontId(name: string): number {
    try {
      return this.raw.findOrCreateFontId(name);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getFieldList(): string {
    try {
      return this.raw.getFieldList();
    } catch (e) {
      throw normalizeError(e);
    }
  }

  searchText(
    query: string,
    fromSec: number,
    fromPara: number,
    fromChar: number,
    forward: boolean,
    caseSensitive: boolean,
  ): string {
    try {
      return this.raw.searchText(query, fromSec, fromPara, fromChar, forward, caseSensitive);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setFormValue(sec: number, para: number, ctrlIdx: number, valueJson: string): void {
    try {
      this.raw.setFormValue(sec, para, ctrlIdx, valueJson);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  setFieldValueByName(name: string, value: string): void {
    try {
      this.raw.setFieldValueByName(name, value);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getText(sec: number, para: number, offset: number, count: number): string {
    try {
      return this.raw.getTextRange(sec, para, offset, count);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getCharPropertiesAt(sec: number, para: number, offset: number): string {
    try {
      return this.raw.getCharPropertiesAt(sec, para, offset);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getParaPropertiesAt(sec: number, para: number): string {
    try {
      return this.raw.getParaPropertiesAt(sec, para);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getPageInfo(pageIndex: number): string {
    try {
      return this.raw.getPageInfo(pageIndex);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  hitTest(pageIndex: number, x: number, y: number): string {
    try {
      return this.raw.hitTest(pageIndex, x, y);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getCursorRect(sec: number, para: number, offset: number): string {
    try {
      return this.raw.getCursorRect(sec, para, offset);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getCursorRectInCell(
    sec: number,
    parentPara: number,
    controlIdx: number,
    cellIdx: number,
    cellPara: number,
    offset: number,
  ): string {
    try {
      return this.raw.getCursorRectInCell(sec, parentPara, controlIdx, cellIdx, cellPara, offset);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getSelectionRects(sec: number, startPara: number, startOffset: number, endPara: number, endOffset: number): string {
    try {
      return this.raw.getSelectionRects(sec, startPara, startOffset, endPara, endOffset);
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getSelectionRectsInCell(
    sec: number,
    parentPara: number,
    controlIdx: number,
    cellIdx: number,
    startCellPara: number,
    startOffset: number,
    endCellPara: number,
    endOffset: number,
  ): string {
    try {
      return this.raw.getSelectionRectsInCell(
        sec,
        parentPara,
        controlIdx,
        cellIdx,
        startCellPara,
        startOffset,
        endCellPara,
        endOffset,
      );
    } catch (e) {
      throw normalizeError(e);
    }
  }

  getSectionCount(): number {
    return this.raw.getSectionCount();
  }

  getParagraphCount(sec: number): number {
    return this.raw.getParagraphCount(sec);
  }

  getValidationWarnings(): unknown {
    try {
      const fn = (this.raw as unknown as { getValidationWarnings?: () => unknown }).getValidationWarnings;
      return typeof fn === 'function' ? fn.call(this.raw) : { count: 0, summary: [] };
    } catch (e) {
      throw normalizeError(e);
    }
  }

  reflowLinesegs(): number {
    try {
      const fn = (this.raw as unknown as { reflowLinesegs?: () => unknown }).reflowLinesegs;
      if (typeof fn !== 'function') return 0;
      const count = fn.call(this.raw);
      return Number.isFinite(Number(count)) ? Number(count) : 0;
    } catch (e) {
      throw normalizeError(e);
    }
  }

  normalizeForExport(): number {
    return this.reflowLinesegs();
  }

  async save(filePath: string): Promise<void> {
    try {
      this.normalizeForExport();
      const bytes = this.raw.exportHwp();
      await writeFile(filePath, Buffer.from(bytes));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  exportBytes(): Uint8Array {
    try {
      this.normalizeForExport();
      return this.raw.exportHwp();
    } catch (e) {
      throw normalizeError(e);
    }
  }
}

export async function openHwp(filePath: string): Promise<HwpDocWrapper> {
  const bytes = await readFile(filePath);
  const raw = new HwpDocument(new Uint8Array(bytes));
  return new HwpDocWrapper(raw);
}

export async function openHwpFromBytes(bytes: Uint8Array | Buffer): Promise<HwpDocWrapper> {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const raw = new HwpDocument(u8);
  return new HwpDocWrapper(raw);
}

export function createBlankHwpDocument(): HwpDocWrapper {
  const raw = HwpDocument.createEmpty();
  raw.createBlankDocument();
  raw.convertToEditable();
  raw.setFileName('새 문서.hwp');
  return new HwpDocWrapper(raw);
}
