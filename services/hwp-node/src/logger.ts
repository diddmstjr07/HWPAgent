export const logger = {
  info: (msg: string, meta?: unknown) => {
    console.log(`[${new Date().toISOString()}] INFO: ${msg}`, meta ?? '');
  },
  warn: (msg: string, meta?: unknown) => {
    console.warn(`[${new Date().toISOString()}] WARN: ${msg}`, meta ?? '');
  },
  error: (msg: string, err?: unknown) => {
    console.error(`[${new Date().toISOString()}] ERROR: ${msg}`, err ?? '');
  },
};
