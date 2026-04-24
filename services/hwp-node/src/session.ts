import { randomUUID } from 'node:crypto';
import type { HwpDocWrapper } from './hwp-helper.js';
import type { RenderedPage } from './renderer.js';

export interface Session {
  id: string;
  fileName: string;
  doc: HwpDocWrapper;
  renderCache: Map<number, RenderedPage>;
  lastAccess: number;
  createdAt: number;
}

const TTL_MS = 30 * 60 * 1000;
const SWEEP_INTERVAL_MS = 5 * 60 * 1000;

const sessions = new Map<string, Session>();

const sweepTimer: ReturnType<typeof setInterval> = setInterval(sweepExpiredSessions, SWEEP_INTERVAL_MS);
sweepTimer.unref();

export function createSession(fileName: string, doc: HwpDocWrapper): Session {
  const now = Date.now();
  const session: Session = {
    id: randomUUID(),
    fileName,
    doc,
    renderCache: new Map(),
    lastAccess: now,
    createdAt: now,
  };
  sessions.set(session.id, session);
  return session;
}

export function getSession(id: string): Session | null {
  const session = sessions.get(id);
  if (!session) return null;
  session.lastAccess = Date.now();
  return session;
}

export function deleteSession(id: string): boolean {
  const session = sessions.get(id);
  if (!session) return false;
  try {
    (session.doc.raw as any).free?.();
  } catch {
    // WASM free errors are non-fatal during cleanup
  }
  return sessions.delete(id);
}

export function invalidatePages(session: Session, pageIndexes: number[]): void {
  if (pageIndexes.length === 0) {
    session.renderCache.clear();
    return;
  }
  for (const idx of pageIndexes) {
    session.renderCache.delete(idx);
  }
}

export function sweepExpiredSessions(): number {
  const now = Date.now();
  let swept = 0;
  for (const [id, session] of sessions) {
    if (now - session.lastAccess > TTL_MS) {
      deleteSession(id);
      swept++;
    }
  }
  return swept;
}

export function sessionCount(): number {
  return sessions.size;
}
