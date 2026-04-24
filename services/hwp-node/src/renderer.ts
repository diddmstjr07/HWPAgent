import type { HwpDocWrapper } from './hwp-helper.js';
import type { Session } from './session.js';

export interface RenderedPage {
  svg: string;
  width: number;
  height: number;
}

export function renderPage(doc: HwpDocWrapper, pageIndex: number): RenderedPage {
  const svg = (doc.raw as any).renderPageSvg(pageIndex);
  if (typeof svg !== 'string') {
    throw new Error(`renderPageSvg returned ${typeof svg}, expected string`);
  }
  const viewBoxMatch = svg.match(/viewBox="([^"]+)"/);
  let width = 0;
  let height = 0;
  if (viewBoxMatch) {
    const parts = viewBoxMatch[1].split(/\s+/).map(Number);
    if (parts.length === 4) {
      width = parts[2];
      height = parts[3];
    }
  }
  return { svg, width, height };
}

export function getPageCount(doc: HwpDocWrapper): number {
  const raw = doc.raw as any;
  if (typeof raw.pageCount === 'function') return raw.pageCount();
  if (typeof raw.getPageCount === 'function') return raw.getPageCount();
  if (typeof raw.visiblePages === 'function') {
    const result = raw.visiblePages();
    if (result instanceof Uint32Array) return result.length;
    if (typeof result === 'string') {
      const arr = JSON.parse(result);
      return Array.isArray(arr) ? arr.length : 0;
    }
  }
  throw new Error('No page count method found on rhwp');
}

export function getOrRenderPage(session: Session, pageIndex: number): RenderedPage {
  const cached = session.renderCache.get(pageIndex);
  if (cached) return cached;
  const rendered = renderPage(session.doc, pageIndex);
  session.renderCache.set(pageIndex, rendered);
  return rendered;
}
