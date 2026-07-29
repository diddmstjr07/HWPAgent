import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { app } from '../src/server.js';
import { deleteSession } from '../src/session.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SAMPLES = resolve(__dirname, '../../../samples');

let sessionId: string;

async function upload(fileName: string): Promise<{ sessionId: string; pageCount: number }> {
  const bytes = await readFile(resolve(SAMPLES, fileName));
  const form = new FormData();
  form.append('file', new Blob([bytes], { type: 'application/octet-stream' }), fileName);
  const res = await app.request('/sessions', { method: 'POST', body: form });
  return res.json();
}

beforeAll(async () => {
  const body = await upload('text.hwp');
  sessionId = body.sessionId;
});

afterAll(() => {
  if (sessionId) deleteSession(sessionId);
});

describe('POST /sessions', () => {
  it('returns 201 with sessionId and pageCount', async () => {
    const body = await upload('text.hwp');
    expect(body.sessionId).toBeTruthy();
    expect(typeof body.sessionId).toBe('string');
    expect(typeof body.pageCount).toBe('number');
    expect(body.pageCount).toBeGreaterThan(0);
    deleteSession(body.sessionId);
  });
});

describe('GET /sessions/:id/pages/0', () => {
  it('returns 200 SVG with correct content-type', async () => {
    const res = await app.request(`/sessions/${sessionId}/pages/0`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('image/svg+xml');
    const body = await res.text();
    expect(body.trimStart().startsWith('<svg')).toBe(true);
  });
});

describe('overlay coordinate APIs', () => {
  it('returns page info for overlay sizing', async () => {
    const res = await app.request(`/sessions/${sessionId}/page-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pageIndex: 0 }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.pageIndex).toBe(0);
    expect(body.width).toBeGreaterThan(0);
    expect(body.height).toBeGreaterThan(0);
  });

  it('maps page coordinates to a document position', async () => {
    const res = await app.request(`/sessions/${sessionId}/hit-test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pageIndex: 0, x: 100, y: 100 }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('sectionIndex');
    expect(body).toHaveProperty('paragraphIndex');
    expect(body).toHaveProperty('charOffset');
  });

  it('returns cursor and selection rectangles', async () => {
    const cursorRes = await app.request(`/sessions/${sessionId}/cursor-rect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sectionIndex: 0, paragraphIndex: 0, charOffset: 0 }),
    });
    expect(cursorRes.status).toBe(200);
    const cursor = await cursorRes.json();
    expect(cursor.pageIndex).toBe(0);
    expect(cursor.height).toBeGreaterThan(0);

    const selectionRes = await app.request(`/sessions/${sessionId}/selection-rects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sectionIndex: 0, startParaIndex: 0, startCharOffset: 0, endParaIndex: 0, endCharOffset: 1 }),
    });
    expect(selectionRes.status).toBe(200);
    const selection = await selectionRes.json();
    expect(Array.isArray(selection)).toBe(true);
  });

  it('rejects invalid overlay requests', async () => {
    const res = await app.request(`/sessions/${sessionId}/hit-test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pageIndex: -1, x: 0, y: 0 }),
    });
    expect(res.status).toBe(400);
  });
});

describe('GET /sessions/:id/structure', () => {
  it('returns metadata, fields, and outline', async () => {
    const res = await app.request(`/sessions/${sessionId}/structure`);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.metadata.sectionCount).toBeGreaterThan(0);
    expect(body.metadata.pageCount).toBeGreaterThan(0);
    expect(Array.isArray(body.fields)).toBe(true);
    expect(Array.isArray(body.outline)).toBe(true);
    expect(body.outline.length).toBeGreaterThan(0);
    expect(body.outline[0]).toHaveProperty('sec');
    expect(body.outline[0]).toHaveProperty('para');
    expect(body.outline[0]).toHaveProperty('preview');
  });
});

describe('POST /sessions/:id/ops', () => {
  it('applies insert_text and returns affectedPages array', async () => {
    const res = await app.request(`/sessions/${sessionId}/ops`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind: 'insert_text',
        sec: 0,
        para: 0,
        offset: 0,
        text: '★',
      }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.affectedPages)).toBe(true);
  });
});

describe('GET /sessions/:id/pages/0 after edit', () => {
  it('re-rendered SVG contains the inserted marker', async () => {
    const res = await app.request(`/sessions/${sessionId}/pages/0`);
    expect(res.status).toBe(200);
    const svg = await res.text();
    expect(svg).toContain('★');
  });
});

describe('GET /sessions/:id/export', () => {
  it('returns 200 with octet-stream content-type', async () => {
    const res = await app.request(`/sessions/${sessionId}/export`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('application/octet-stream');
    expect(Number(res.headers.get('content-length'))).toBeGreaterThan(0);
    const buf = await res.arrayBuffer();
    expect(buf.byteLength).toBeGreaterThan(0);
    expect(buf.byteLength).toBe(Number(res.headers.get('content-length')));
  });

  it('supports non-ASCII filenames in Content-Disposition', async () => {
    const bytes = await readFile(resolve(SAMPLES, 'text.hwp'));
    const form = new FormData();
    form.append('file', new Blob([bytes], { type: 'application/octet-stream' }), '서식1_작품요약서.hwp');
    const uploadRes = await app.request('/sessions', { method: 'POST', body: form });
    const body = await uploadRes.json();

    const res = await app.request(`/sessions/${body.sessionId}/export`);
    expect(res.status).toBe(200);
    const disposition = res.headers.get('content-disposition') || '';
    expect(disposition).toContain('filename=');
    expect(disposition).toContain("filename*=UTF-8''");
    expect(decodeURIComponent(disposition.split("filename*=UTF-8''")[1])).toBe('서식1_작품요약서.hwp');
    deleteSession(body.sessionId);
  });
});

describe('DELETE /sessions/:id', () => {
  it('returns 204 then subsequent GET returns 404', async () => {
    const { sessionId: tmpId } = await upload('text.hwp');

    const delRes = await app.request(`/sessions/${tmpId}`, { method: 'DELETE' });
    expect(delRes.status).toBe(204);

    const getRes = await app.request(`/sessions/${tmpId}/pages/0`);
    expect(getRes.status).toBe(404);
    const body = await getRes.json();
    expect(body.code).toBe('SESSION_NOT_FOUND');
  });
});
