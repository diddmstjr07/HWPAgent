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
    const buf = await res.arrayBuffer();
    expect(buf.byteLength).toBeGreaterThan(0);
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
