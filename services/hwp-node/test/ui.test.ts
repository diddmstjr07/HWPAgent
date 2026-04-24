import { describe, it, expect } from 'vitest';
import { app } from '../src/server.js';

describe('UI routes', () => {
  it('GET / redirects to /ui/index.html', async () => {
    const res = await app.request('/');
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe('/ui/index.html');
  });

  it('GET /ui/index.html returns HTML', async () => {
    const res = await app.request('/ui/index.html');
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/html');
    const body = await res.text();
    expect(body).toContain('<html');
  });
});
