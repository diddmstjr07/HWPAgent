import './bootstrap.js';
import { HwpDocument } from '@rhwp/core';
import { readFile, writeFile } from 'node:fs/promises';

function normalizeError(e: unknown): Error {
  if (e instanceof Error) return e;
  if (typeof e === 'string') return new Error(e);
  return new Error(String(e));
}

export interface CharProps {
  fontId?: number;
  fontIds?: number[];
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

  insertText(sec: number, para: number, offset: number, text: string): void {
    try {
      this.raw.insertText(sec, para, offset, text);
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

  getText(sec: number, para: number, offset: number, count: number): string {
    try {
      return this.raw.getTextRange(sec, para, offset, count);
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

  async save(filePath: string): Promise<void> {
    try {
      const bytes = this.raw.exportHwp();
      await writeFile(filePath, Buffer.from(bytes));
    } catch (e) {
      throw normalizeError(e);
    }
  }

  exportBytes(): Uint8Array {
    try {
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
