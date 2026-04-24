import { createMiddleware } from 'hono/factory';
import { timingSafeEqual } from 'node:crypto';

export const apiKeyAuth = createMiddleware(async (c, next) => {
  const expected = process.env.HWP_API_KEY;

  if (!expected) {
    console.warn('[auth] HWP_API_KEY not set — running in open mode');
    return next();
  }

  const key = c.req.header('X-Api-Key') ?? c.req.query('api_key');

  if (!key) {
    return c.json({ error: 'Unauthorized', code: 'INVALID_API_KEY' }, 401);
  }

  const a = Buffer.from(key);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return c.json({ error: 'Unauthorized', code: 'INVALID_API_KEY' }, 401);
  }

  return next();
});
