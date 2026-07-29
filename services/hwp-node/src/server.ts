import { Hono } from 'hono';
import { serveStatic } from '@hono/node-server/serve-static';
import { createBlankHwpDocument, openHwpFromBytes } from './hwp-helper.js';
import { getPageCount, getOrRenderPage } from './renderer.js';
import { createSession, getSession, deleteSession, invalidatePages } from './session.js';
import { applyOp, OpError } from './operations.js';
import { apiKeyAuth } from './middleware/auth.js';
import { serializeStructure, serializeWebDocument } from './serializer.js';
import { logger } from './logger.js';

export const app = new Hono();

function contentDispositionAttachment(fileName: string): string {
  const fallback =
    fileName
      .replace(/\\/g, '_')
      .replace(/"/g, '')
      .replace(/[^\x20-\x7E]/g, '_')
      .trim() || 'document.hwp';
  return `attachment; filename="${fallback}"; filename*=UTF-8''${encodeURIComponent(fileName)}`;
}

function parseRhwpJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`Invalid rhwp JSON response: ${value.slice(0, 200)}`);
  }
}

function finiteNumber(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

// Auth only on API routes — UI paths are public
app.use('/sessions', apiKeyAuth);
app.use('/sessions/*', apiKeyAuth);

// Static UI
app.get('/', (c) => c.redirect('/ui/index.html'));
app.use('/ui/*', serveStatic({
  root: './public',
  rewriteRequestPath: (p) => p.replace(/^\/ui/, ''),
}));

app.get('/health', (c) => c.json({ ok: true, service: 'hwp-node' }));
app.get('/version', (c) => c.json({ service: 'hwp-node', node: process.version }));

// POST /sessions/blank — create an editable blank HWP session
app.post('/sessions/blank', (c) => {
  const doc = createBlankHwpDocument();
  const session = createSession('새 문서.hwp', doc);
  const pageCount = getPageCount(doc);
  return c.json({ sessionId: session.id, pageCount, fileName: session.fileName }, 201);
});

// POST /sessions — multipart upload → new session
app.post('/sessions', async (c) => {
  let file: File | string | undefined;
  try {
    const body = await c.req.parseBody();
    file = body['file'];
  } catch {
    return c.json({ error: 'Failed to parse multipart body', code: 'INVALID_REQUEST' }, 400);
  }

  if (!file || !(file instanceof File)) {
    return c.json({ error: '"file" field (multipart) is required', code: 'INVALID_REQUEST' }, 400);
  }

  const bytes = new Uint8Array(await file.arrayBuffer());
  const doc = await openHwpFromBytes(bytes);
  const session = createSession(file.name || 'upload.hwp', doc);
  const pageCount = getPageCount(doc);
  return c.json({ sessionId: session.id, pageCount }, 201);
});

// PUT /sessions/:id/import — replace an existing session with edited HWP bytes.
app.put('/sessions/:id/import', async (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  let bytes: Uint8Array;
  try {
    bytes = new Uint8Array(await c.req.arrayBuffer());
  } catch {
    return c.json({ error: 'Failed to read request body', code: 'INVALID_REQUEST' }, 400);
  }

  if (!bytes.byteLength) {
    return c.json({ error: 'HWP bytes are required', code: 'INVALID_REQUEST' }, 400);
  }

  try {
    const nextDoc = await openHwpFromBytes(bytes);
    try {
      (session.doc.raw as any).free?.();
    } catch {
      // Replacing the session document should not fail because freeing the previous WASM object failed.
    }
    session.doc = nextDoc;
    session.renderCache.clear();
    session.lastAccess = Date.now();
    return c.json({ ok: true, pageCount: getPageCount(nextDoc) });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg || 'Failed to import HWP bytes', code: 'IMPORT_FAILED' }, 422);
  }
});

// DELETE /sessions/:id
app.delete('/sessions/:id', (c) => {
  const deleted = deleteSession(c.req.param('id'));
  if (!deleted) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }
  return new Response(null, { status: 204 });
});

// GET /sessions/:id/structure — metadata + fields + paragraph outline for AI tools
app.get('/sessions/:id/structure', (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  try {
    return c.json(serializeStructure(session.doc));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'STRUCTURE_ERROR' }, 500);
  }
});

// GET /sessions/:id/document — editable web document model
app.get('/sessions/:id/document', (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  try {
    return c.json(serializeWebDocument(session.doc));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'DOCUMENT_ERROR' }, 500);
  }
});

// GET /sessions/:id/pages/:pageIndex — SVG render (cache-first)
app.get('/sessions/:id/pages/:pageIndex', (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  const pageIndex = Number(c.req.param('pageIndex'));
  if (!Number.isInteger(pageIndex) || pageIndex < 0) {
    return c.json({ error: 'Invalid page index', code: 'INVALID_PAGE' }, 400);
  }

  try {
    const { svg } = getOrRenderPage(session, pageIndex);
    return c.body(svg, 200, { 'Content-Type': 'image/svg+xml; charset=utf-8' });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'RENDER_ERROR' }, 500);
  }
});

// POST /sessions/:id/page-info — page metrics for overlay coordinate mapping
app.post('/sessions/:id/page-info', async (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'Request body must be JSON', code: 'INVALID_REQUEST' }, 400);
  }

  const pageIndex = finiteNumber(body.pageIndex);
  if (pageIndex === null || !Number.isInteger(pageIndex) || pageIndex < 0) {
    return c.json({ error: 'Invalid page index', code: 'INVALID_PAGE' }, 400);
  }

  try {
    return c.json(parseRhwpJson(session.doc.getPageInfo(pageIndex)));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'PAGE_INFO_ERROR' }, 422);
  }
});

// POST /sessions/:id/hit-test — page coordinates to document position
app.post('/sessions/:id/hit-test', async (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'Request body must be JSON', code: 'INVALID_REQUEST' }, 400);
  }

  const pageIndex = finiteNumber(body.pageIndex);
  const x = finiteNumber(body.x);
  const y = finiteNumber(body.y);
  if (pageIndex === null || !Number.isInteger(pageIndex) || pageIndex < 0 || x === null || y === null) {
    return c.json({ error: 'Invalid hit-test coordinates', code: 'INVALID_REQUEST' }, 400);
  }

  try {
    return c.json(parseRhwpJson(session.doc.hitTest(pageIndex, x, y)));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'HIT_TEST_ERROR' }, 422);
  }
});

// POST /sessions/:id/cursor-rect — document position to page caret rectangle
app.post('/sessions/:id/cursor-rect', async (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'Request body must be JSON', code: 'INVALID_REQUEST' }, 400);
  }

  const sec = finiteNumber(body.sectionIndex ?? body.sec);
  const para = finiteNumber(body.paragraphIndex ?? body.para);
  const offset = finiteNumber(body.charOffset ?? body.offset);
  if (sec === null || para === null || offset === null) {
    return c.json({ error: 'Invalid cursor position', code: 'INVALID_REQUEST' }, 400);
  }

  try {
    if (body.parentParaIndex !== undefined) {
      const parentPara = finiteNumber(body.parentParaIndex);
      const controlIdx = finiteNumber(body.controlIndex);
      const cellIdx = finiteNumber(body.cellIndex);
      const cellPara = finiteNumber(body.cellParaIndex ?? body.cellPara);
      if (parentPara === null || controlIdx === null || cellIdx === null || cellPara === null) {
        return c.json({ error: 'Invalid cell cursor position', code: 'INVALID_REQUEST' }, 400);
      }
      return c.json(parseRhwpJson(session.doc.getCursorRectInCell(sec, parentPara, controlIdx, cellIdx, cellPara, offset)));
    }
    return c.json(parseRhwpJson(session.doc.getCursorRect(sec, para, offset)));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'CURSOR_RECT_ERROR' }, 422);
  }
});

// POST /sessions/:id/selection-rects — document range to overlay rectangles
app.post('/sessions/:id/selection-rects', async (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  let body: Record<string, unknown>;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'Request body must be JSON', code: 'INVALID_REQUEST' }, 400);
  }

  const sec = finiteNumber(body.sectionIndex ?? body.sec);
  const startPara = finiteNumber(body.startParaIndex ?? body.startPara);
  const startOffset = finiteNumber(body.startCharOffset ?? body.startOffset);
  const endPara = finiteNumber(body.endParaIndex ?? body.endPara);
  const endOffset = finiteNumber(body.endCharOffset ?? body.endOffset);
  if (sec === null || startPara === null || startOffset === null || endPara === null || endOffset === null) {
    return c.json({ error: 'Invalid selection range', code: 'INVALID_REQUEST' }, 400);
  }

  try {
    if (body.parentParaIndex !== undefined) {
      const parentPara = finiteNumber(body.parentParaIndex);
      const controlIdx = finiteNumber(body.controlIndex);
      const cellIdx = finiteNumber(body.cellIndex);
      if (parentPara === null || controlIdx === null || cellIdx === null) {
        return c.json({ error: 'Invalid cell selection range', code: 'INVALID_REQUEST' }, 400);
      }
      return c.json(parseRhwpJson(session.doc.getSelectionRectsInCell(
        sec,
        parentPara,
        controlIdx,
        cellIdx,
        startPara,
        startOffset,
        endPara,
        endOffset,
      )));
    }
    return c.json(parseRhwpJson(session.doc.getSelectionRects(sec, startPara, startOffset, endPara, endOffset)));
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg, code: 'SELECTION_RECTS_ERROR' }, 422);
  }
});

// POST /sessions/:id/ops — apply edit op + invalidate cache
app.post('/sessions/:id/ops', async (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  let op: unknown;
  try {
    op = await c.req.json();
  } catch {
    return c.json({ error: 'Request body must be JSON', code: 'INVALID_REQUEST' }, 400);
  }

  let before: Uint8Array<ArrayBuffer> | null = null;
  try {
    before = session.doc.exportBytes() as Uint8Array<ArrayBuffer>;
    const result = applyOp(session.doc, op as Parameters<typeof applyOp>[1]);
    invalidatePages(session, result.affectedPages);
    return c.json({ affectedPages: result.affectedPages, data: result.data ?? null });
  } catch (e) {
    try {
      if (before) {
        session.doc = await openHwpFromBytes(before);
        session.renderCache.clear();
      }
    } catch {
      // If rollback fails, surface the original operation error below.
    }
    const msg = e instanceof Error ? e.message : String(e);
    const code = e instanceof OpError ? 'OP_ERROR' : 'INTERNAL_ERROR';
    return c.json({ error: msg, code }, 422);
  }
});

// GET /sessions/:id/export — download current HWP bytes
app.get('/sessions/:id/export', (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }

  try {
    const bytes = session.doc.exportBytes() as Uint8Array<ArrayBuffer>;
    if (!bytes || bytes.byteLength === 0) {
      return c.json({ error: 'Export returned empty HWP bytes', code: 'EXPORT_EMPTY' }, 500);
    }

    const buffer = Buffer.from(bytes);
    return new Response(buffer, {
      status: 200,
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': contentDispositionAttachment(session.fileName),
        'Content-Length': String(buffer.byteLength),
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    logger.error('Failed to export HWP session', { sessionId: session.id, fileName: session.fileName, error: msg });
    return c.json({ error: msg || 'Failed to export HWP document', code: 'EXPORT_FAILED' }, 500);
  }
});

// GET /sessions/:id/export-hwpx — current document as HWPX (zip) bytes.
// 결정적 XML 편집(폰트 교체 등)을 위해 hwpx 형태로 내보낸다.
app.get('/sessions/:id/export-hwpx', (c) => {
  const session = getSession(c.req.param('id'));
  if (!session) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }
  try {
    const bytes = (session.doc.raw as any).exportHwpx() as Uint8Array;
    if (!bytes || bytes.byteLength === 0) {
      return c.json({ error: 'Export returned empty HWPX bytes', code: 'EXPORT_EMPTY' }, 500);
    }
    const buffer = Buffer.from(bytes);
    return new Response(buffer, {
      status: 200,
      headers: {
        'Content-Type': 'application/hwp+zip',
        'Content-Length': String(buffer.byteLength),
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    logger.error('Failed to export HWPX session', { sessionId: session.id, error: msg });
    return c.json({ error: msg || 'Failed to export HWPX document', code: 'EXPORT_FAILED' }, 500);
  }
});
