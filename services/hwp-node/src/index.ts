import './bootstrap.js';
import Fastify from 'fastify';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { logger } from './logger.js';

const require = createRequire(import.meta.url);
const pkg = JSON.parse(readFileSync('./package.json', 'utf-8')) as { version?: string };
const rhwpPkg = require('@rhwp/core/package.json') as { version: string };

const app = Fastify({ logger: false });

app.get('/health', async () => ({
  ok: true,
  service: 'hwp-node',
  version: pkg.version ?? '0.0.0',
  rhwp: rhwpPkg.version,
}));

app.get('/version', async () => ({
  service: 'hwp-node',
  version: pkg.version ?? '0.0.0',
  rhwp: rhwpPkg.version,
  node: process.version,
}));

const port = Number(process.env.PORT ?? 3100);
const host = process.env.HOST ?? '0.0.0.0';

try {
  await app.listen({ port, host });
  logger.info(`hwp-node listening on http://${host}:${port}`);
  logger.info(`@rhwp/core version: ${rhwpPkg.version}`);
} catch (err) {
  logger.error('Failed to start server', err);
  process.exit(1);
}
