import { describe, it, expect, afterEach } from 'vitest';
import { openHwp } from '../src/hwp-helper.js';
import { renderPage, getPageCount, getOrRenderPage } from '../src/renderer.js';
import { createSession, getSession, deleteSession, invalidatePages } from '../src/session.js';
import { applyOp } from '../src/operations.js';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SAMPLES = resolve(__dirname, '../../../samples');

const createdSessions: string[] = [];

afterEach(() => {
  for (const id of createdSessions.splice(0)) {
    deleteSession(id);
  }
});

// ---- renderer unit tests ----

describe('renderer: renderPage', () => {
  it('returns valid SVG string with A4 dimensions', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const page = renderPage(doc, 0);

    expect(typeof page.svg).toBe('string');
    expect(page.svg.startsWith('<svg')).toBe(true);
    expect(page.width).toBeGreaterThan(700);
    expect(page.width).toBeLessThan(900);
    expect(page.height).toBeGreaterThan(1000);
    expect(page.height).toBeLessThan(1300);
  });

  it('SVG contains Korean characters from text.hwp', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const { svg } = renderPage(doc, 0);
    // SVG renders each glyph as a separate <text> element; check for individual chars
    expect(svg).toContain('샘');
    expect(svg).toContain('플');
  });

  it('getPageCount returns a positive integer', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const count = getPageCount(doc);
    expect(Number.isInteger(count)).toBe(true);
    expect(count).toBeGreaterThan(0);
  });
});

// ---- session unit tests ----

describe('session store', () => {
  it('createSession + getSession round-trip', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const session = createSession('text.hwp', doc);
    createdSessions.push(session.id);

    const retrieved = getSession(session.id);
    expect(retrieved).not.toBeNull();
    expect(retrieved!.id).toBe(session.id);
    expect(retrieved!.fileName).toBe('text.hwp');
  });

  it('getSession returns null for unknown id', () => {
    const result = getSession('00000000-0000-0000-0000-000000000000');
    expect(result).toBeNull();
  });

  it('invalidatePages([0]) removes only that page from cache', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const session = createSession('text.hwp', doc);
    createdSessions.push(session.id);

    // Populate cache for pages 0 and 1 (if they exist)
    const page0 = renderPage(doc, 0);
    session.renderCache.set(0, page0);
    session.renderCache.set(1, page0); // reuse for simplicity

    invalidatePages(session, [0]);

    expect(session.renderCache.has(0)).toBe(false);
    expect(session.renderCache.has(1)).toBe(true);
  });

  it('invalidatePages([]) clears entire cache', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const session = createSession('text.hwp', doc);
    createdSessions.push(session.id);

    const page0 = renderPage(doc, 0);
    session.renderCache.set(0, page0);
    session.renderCache.set(1, page0);
    session.renderCache.set(2, page0);

    invalidatePages(session, []);

    expect(session.renderCache.size).toBe(0);
  });
});

// ---- integration test ----

describe('renderer + session + ops integration', () => {
  it('edit op invalidates cache and re-render reflects new content', async () => {
    const doc = await openHwp(`${SAMPLES}/text.hwp`);
    const session = createSession('text.hwp', doc);
    createdSessions.push(session.id);

    // Initial render — populates cache
    const initial = getOrRenderPage(session, 0);
    expect(session.renderCache.has(0)).toBe(true);
    expect(initial.svg).not.toContain('★');

    // Apply edit: insert rare marker character
    const result = applyOp(session.doc, {
      kind: 'insert_text',
      sec: 0,
      para: 0,
      offset: 0,
      text: '★',
    });

    // Invalidate affected pages then re-render
    invalidatePages(session, result.affectedPages);
    expect(session.renderCache.has(0)).toBe(false);

    const updated = getOrRenderPage(session, 0);
    expect(updated.svg).toContain('★');
    expect(session.renderCache.has(0)).toBe(true);
  });
});
