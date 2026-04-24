import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { app } from '../src/server.js';
import { deleteSession } from '../src/session.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SAMPLES = resolve(__dirname, '../../../samples');

const TEST_KEY = 'test-key-abc123';
let savedKey: string | undefined;

async function buildForm(): Promise<FormData> {
  const bytes = await readFile(resolve(SAMPLES, 'text.hwp'));
  const form = new FormData();
  form.append('file', new Blob([bytes], { type: 'application/octet-stream' }), 'text.hwp');
  return form;
}

beforeAll(() => {
  savedKey = process.env.HWP_API_KEY;
  process.env.HWP_API_KEY = TEST_KEY;
});

afterAll(() => {
  if (savedKey === undefined) {
    delete process.env.HWP_API_KEY;
  } else {
    process.env.HWP_API_KEY = savedKey;
  }
});

describe('API key authentication', () => {
  it('POST /sessions without key → 401 INVALID_API_KEY', async () => {
    const res = await app.request('/sessions', { method: 'POST', body: await buildForm() });
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.code).toBe('INVALID_API_KEY');
  });

  it('POST /sessions with wrong key → 401', async () => {
    const res = await app.request('/sessions', {
      method: 'POST',
      headers: { 'X-Api-Key': 'wrong-key' },
      body: await buildForm(),
    });
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.code).toBe('INVALID_API_KEY');
  });

  it('POST /sessions with correct key (header) → 201', async () => {
    const res = await app.request('/sessions', {
      method: 'POST',
      headers: { 'X-Api-Key': TEST_KEY },
      body: await buildForm(),
    });
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.sessionId).toBeTruthy();
    deleteSession(body.sessionId);
  });

  it('POST /sessions with correct key (query param) → 201', async () => {
    const res = await app.request(`/sessions?api_key=${TEST_KEY}`, {
      method: 'POST',
      body: await buildForm(),
    });
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.sessionId).toBeTruthy();
    deleteSession(body.sessionId);
  });

  it('HWP_API_KEY unset → open mode allows request (201)', async () => {
    delete process.env.HWP_API_KEY;
    try {
      const res = await app.request('/sessions', { method: 'POST', body: await buildForm() });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.sessionId).toBeTruthy();
      deleteSession(body.sessionId);
    } finally {
      process.env.HWP_API_KEY = TEST_KEY;
    }
  });
});
