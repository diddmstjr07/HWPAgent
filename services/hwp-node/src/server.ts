import { Hono } from 'hono';
import { serveStatic } from '@hono/node-server/serve-static';
import { openHwpFromBytes } from './hwp-helper.js';
import { getPageCount, getOrRenderPage } from './renderer.js';
import { createSession, getSession, deleteSession, invalidatePages } from './session.js';
import { applyOp, OpError } from './operations.js';
import { apiKeyAuth } from './middleware/auth.js';

export const app = new Hono();

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

// DELETE /sessions/:id
app.delete('/sessions/:id', (c) => {
  const deleted = deleteSession(c.req.param('id'));
  if (!deleted) {
    return c.json({ error: 'Session not found', code: 'SESSION_NOT_FOUND' }, 404);
  }
  return new Response(null, { status: 204 });
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

  try {
    const result = applyOp(session.doc, op as Parameters<typeof applyOp>[1]);
    invalidatePages(session, result.affectedPages);
    return c.json({ affectedPages: result.affectedPages, data: result.data ?? null });
  } catch (e) {
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

  const bytes = session.doc.exportBytes() as Uint8Array<ArrayBuffer>;
  return c.body(bytes, 200, {
    'Content-Type': 'application/octet-stream',
    'Content-Disposition': `attachment; filename="${session.fileName}"`,
  });
});
