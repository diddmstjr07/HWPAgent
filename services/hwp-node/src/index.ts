import 'dotenv/config';
import { serve } from '@hono/node-server';
import { app } from './server.js';

const PORT = Number(process.env.PORT ?? 3100);
serve({ fetch: app.fetch, port: PORT }, () => {
  console.log(`hwp-node listening on :${PORT}`);
});
