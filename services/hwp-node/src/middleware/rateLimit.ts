import { createMiddleware } from 'hono/factory';

// TODO: Implement sliding-window rate limiter for POST /sessions.
// Default: 20 requests per minute per IP.
// On exceed: 429 Too Many Requests + Retry-After header.
// Use a Map<ip, { count, windowStart }> with periodic cleanup.

export const sessionRateLimit = createMiddleware(async (_c, next) => {
  return next();
});
