(function () {
  const endpoint = (template, sessionId) => template.replace('{sessionId}', encodeURIComponent(sessionId));

  const CHATS_KEY = 'hwpAgentChats';
  const META_KEY = 'hwpV2Session';
  const IDB_NAME = 'hwpAgentDocs';
  const IDB_STORE = 'bytes';

  const safeParse = (raw) => {
    try { return JSON.parse(raw); } catch { return null; }
  };

  const loadAllChats = () => {
    return safeParse(localStorage.getItem(CHATS_KEY)) || {};
  };
  const trimChats = (obj, maxSessions = 20, maxMessages = 200) => {
    const entries = Object.entries(obj).sort((a, b) => (b[1].updatedAt || 0) - (a[1].updatedAt || 0));
    const out = {};
    for (const [k, v] of entries.slice(0, maxSessions)) {
      out[k] = { ...v, messages: (v.messages || []).slice(-maxMessages) };
    }
    return out;
  };
  const saveAllChats = (obj) => {
    try {
      localStorage.setItem(CHATS_KEY, JSON.stringify(trimChats(obj)));
      window.dispatchEvent(new CustomEvent('hwp-vibe-sessions-updated'));
    } catch {}
  };
  const persistMeta = (meta) => {
    try { localStorage.setItem(META_KEY, JSON.stringify(meta)); } catch {}
  };
  const readMeta = () => safeParse(localStorage.getItem(META_KEY));
  const clearMeta = () => { try { localStorage.removeItem(META_KEY); } catch {} };

  let idbPromise = null;
  const openIdb = () => {
    if (idbPromise) return idbPromise;
    idbPromise = new Promise((resolve, reject) => {
      if (typeof indexedDB === 'undefined') return reject(new Error('indexedDB unavailable'));
      const req = indexedDB.open(IDB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(IDB_STORE)) db.createObjectStore(IDB_STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return idbPromise;
  };
  const idbWith = async (mode, fn) => {
    const db = await openIdb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, mode);
      const store = tx.objectStore(IDB_STORE);
      let result;
      Promise.resolve(fn(store, (v) => { result = v; }))
        .then(() => { tx.oncomplete = () => resolve(result); tx.onerror = () => reject(tx.error); })
        .catch(reject);
    });
  };
  const idbPut = (key, blob) => idbWith('readwrite', (store) => store.put(blob, key));
  const idbGet = (key) => idbWith('readonly', (store, set) => new Promise((res, rej) => {
    const r = store.get(key); r.onsuccess = () => { set(r.result); res(); }; r.onerror = () => rej(r.error);
  }));
  const idbDelete = (key) => idbWith('readwrite', (store) => store.delete(key));

  const persistAPI = {
    META_KEY, CHATS_KEY,
    readMeta, persistMeta, clearMeta,
    loadAllChats, saveAllChats,
    idbPut, idbGet, idbDelete,
    rekeyChat(oldId, newId) {
      const all = loadAllChats();
      if (all[oldId]) {
        all[newId] = { ...all[oldId], sessionId: newId, updatedAt: Date.now() };
        delete all[oldId];
        saveAllChats(all);
      }
    },
    async rekeyBytes(oldId, newId) {
      try {
        const blob = await idbGet(oldId);
        if (blob) {
          await idbPut(newId, blob);
          await idbDelete(oldId);
        }
      } catch {}
    },
    listSessions() {
      const all = loadAllChats();
      return Object.values(all).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    },
  };
  if (typeof window !== 'undefined') window.HwpVibePersist = persistAPI;

  class HwpStudioHost {
    constructor(options) {
      this.options = options || {};
      this.mount = this.options.mount;
      this.sessionId = this.options.sessionId;
      this.pageCount = this.options.pageCount || 0;
      this.fileName = this.options.fileName || 'document.hwp';
      this.endpoints = this.options.endpoints || {};
      this.iframe = null;
      this.agentEl = null;
      this.logEl = null;
      this.inputEl = null;
      this.sendBtn = null;
      this.history = [];
      this.busy = false;
      this.agentCollapsed = false;
      this.agentDrag = null;
      this.agentSuppressClick = false;
      this.agentTransitionTimer = null;
      this.liveRefreshPromise = null;
      this.liveRefreshQueued = false;
      this.lastLiveRefreshAt = 0;
      this.refreshSerial = 0;
      this.messageHandler = this.handleMessage.bind(this);
    }

    render() {
      if (!this.mount || !this.sessionId) return;

      const exportUrl = endpoint(this.endpoints.export || '/api/v2/hwp/sessions/{sessionId}/export', this.sessionId);
      const syncUrl = endpoint(this.endpoints.import || '/api/v2/hwp/sessions/{sessionId}/import', this.sessionId);
      const params = new URLSearchParams({
        url: exportUrl,
        syncUrl,
        filename: this.fileName,
        embedded: '1',
      });

      this.mount.innerHTML = `
        <div class="hwp-studio-host">
          <iframe
            class="hwp-studio-frame"
            title="HWP Studio Editor"
            src="/static/hwp-studio/index.html?${params.toString()}"
            allow="clipboard-read; clipboard-write"
          ></iframe>
        </div>
      `;
      this.mountAgentBesideScrollContainer();
      this.iframe = this.mount.querySelector('.hwp-studio-frame');
      this.logEl = this.agentEl?.querySelector('[data-role="log"]') || null;
      this.inputEl = this.agentEl?.querySelector('[data-role="input"]') || null;
      this.sendBtn = this.agentEl?.querySelector('[data-role="send"]') || null;
      this.statusEl = this.agentEl?.querySelector('[data-role="status"]') || null;
      this.bindAgentUi();
      window.addEventListener('message', this.messageHandler);
      this.injectStyles();

      persistMeta({
        sessionId: this.sessionId,
        fileName: this.fileName,
        pageCount: this.pageCount,
        updatedAt: Date.now(),
      });
      this.restoreLogFromStorage();
      this.cacheCurrentBytes();
    }

    mountAgentBesideScrollContainer() {
      document.querySelector('.hwp-studio-agent')?.remove();
      const host = this.mount.querySelector('.hwp-studio-host');
      if (!host) return;

      const aside = document.createElement('aside');
      aside.className = 'hwp-studio-agent';
      aside.innerHTML = `
        <button type="button" class="hwp-agent-rail" data-action="toggle-agent" title="AI 도구 열기" aria-label="AI 도구 열기">
          <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
            <defs>
              <linearGradient id="hwpAgentRailGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#4F46E5"/>
                <stop offset="100%" stop-color="#7C3AED"/>
              </linearGradient>
            </defs>
            <g fill="url(#hwpAgentRailGrad)" transform="translate(0 8)">
              <path d="M11.34 6.78a.7.7 0 0 1 1.32 0l1.08 2.9a2.76 2.76 0 0 0 1.62 1.62l2.9 1.08a.7.7 0 0 1 0 1.32l-2.9 1.08a2.76 2.76 0 0 0-1.62 1.62l-1.08 2.9a.7.7 0 0 1-1.32 0l-1.08-2.9a2.76 2.76 0 0 0-1.62-1.62l-2.9-1.08a.7.7 0 0 1 0-1.32l2.9-1.08a2.76 2.76 0 0 0 1.62-1.62l1.08-2.9z"/>
              <path d="M6.56 5.12a.34.34 0 0 1 .64 0l.32.86c.1.27.31.48.58.58l.86.32a.34.34 0 0 1 0 .64l-.86.32c-.27.1-.48.31-.58.58l-.32.86a.34.34 0 0 1-.64 0l-.32-.86a.96.96 0 0 0-.58-.58l-.86-.32a.34.34 0 0 1 0-.64l.86-.32c.27-.1.48-.31.58-.58l.32-.86z"/>
              <path d="M16.8 5.12a.34.34 0 0 1 .64 0l.32.86c.1.27.31.48.58.58l.86.32a.34.34 0 0 1 0 .64l-.86.32c-.27.1-.48.31-.58.58l-.32.86a.34.34 0 0 1-.64 0l-.32-.86a.96.96 0 0 0-.58-.58l-.86-.32a.34.34 0 0 1 0-.64l.86-.32c.27-.1.48-.31.58-.58l.32-.86z"/>
            </g>
          </svg>
        </button>
        <header class="hwp-agent-menubar" data-drag-handle="agent">
          <span class="hwp-agent-grabber" aria-hidden="true"></span>
          <div class="hwp-agent-navrow">
            <button type="button" class="hwp-agent-icon-btn" data-action="toggle-agent" title="AI 도구 닫기" aria-label="닫기">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M15 6l-6 6 6 6"/>
              </svg>
            </button>
            <div class="hwp-agent-titleblock">
              <div class="hwp-agent-menu-title">AI 도구</div>
              <div class="hwp-agent-status" data-role="status">대기</div>
            </div>
            <button type="button" class="hwp-agent-icon-btn hwp-agent-menu-btn" data-action="sync" title="서버 동기화" aria-label="동기화">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M21 12a9 9 0 1 1-3.2-6.9"/>
                <path d="M21 4v5h-5"/>
              </svg>
            </button>
          </div>
        </header>
        <div class="hwp-agent-toolbar" role="toolbar" aria-label="빠른 작업">
          <button type="button" class="hwp-agent-chip" data-action="focus-input" title="편집 요청">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M12 20h9"/>
              <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
            </svg>
            <span>요청</span>
          </button>
          <button type="button" class="hwp-agent-chip" data-action="sync" title="현재 문서 동기화">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M19 12a7 7 0 1 1-2.5-5.4"/>
              <path d="M19 5v4h-4"/>
            </svg>
            <span>동기화</span>
          </button>
          <button type="button" class="hwp-agent-chip" data-action="clear-log" title="대화 기록 지우기">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 6h18"/>
              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            </svg>
            <span>비우기</span>
          </button>
        </div>
        <div class="hwp-agent-log" data-role="log">
          <div class="hwp-agent-empty">
            <div class="hwp-agent-empty-title">Agent 편집 대기</div>
            <div class="hwp-agent-empty-text">현재 Canvas 문서를 서버 세션과 맞춘 뒤 도구를 실행합니다.</div>
          </div>
        </div>
        <form class="hwp-agent-form" data-role="form">
          <div class="hwp-agent-composer">
            <textarea id="hwpAgentInput" class="hwp-agent-input" data-role="input" rows="1" placeholder="메시지를 입력하세요"></textarea>
            <button type="submit" class="hwp-agent-send" data-role="send" aria-label="전송">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M12 19V5"/>
                <path d="M5 12l7-7 7 7"/>
              </svg>
            </button>
          </div>
        </form>
      `;
      host.appendChild(aside);
      this.agentEl = aside;
    }

    bindAgentUi() {
      const form = this.agentEl?.querySelector('[data-role="form"]');
      form?.addEventListener('submit', (event) => {
        event.preventDefault();
        this.sendAgentRequest();
      });
      const input = this.agentEl?.querySelector('[data-role="input"]');
      if (input) {
        const autosize = () => {
          input.style.height = 'auto';
          const max = 132;
          input.style.height = `${Math.min(input.scrollHeight, max)}px`;
        };
        input.addEventListener('input', autosize);
        input.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form?.dispatchEvent(new Event('submit', { cancelable: true }));
          }
        });
        requestAnimationFrame(autosize);
      }
      this.agentEl?.querySelector('[data-action="sync"]')?.addEventListener('click', async () => {
        this.setStatus('동기화 중');
        this.addLog('system', '현재 Canvas 문서를 서버 세션에 동기화합니다.');
        try {
          await this.request('syncSession');
          this.addLog('system', '동기화 완료');
          this.setStatus('동기화 완료');
        } catch (error) {
          this.addLog('error', this.cleanError(error));
          this.setStatus('오류');
        }
      });
      this.agentEl?.querySelectorAll('[data-action="sync"]').forEach((button) => {
        if (button.dataset.boundSync === '1') return;
        button.dataset.boundSync = '1';
        button.addEventListener('click', async () => {
          if (button.matches('.hwp-agent-menu-btn')) return;
          this.setStatus('동기화 중');
          this.addLog('system', '현재 Canvas 문서를 서버 세션에 동기화합니다.');
          try {
            await this.request('syncSession');
            this.addLog('system', '동기화 완료');
            this.setStatus('동기화 완료');
          } catch (error) {
            this.addLog('error', this.cleanError(error));
            this.setStatus('오류');
          }
        });
      });
      this.agentEl?.querySelector('[data-action="focus-input"]')?.addEventListener('click', () => {
        this.inputEl?.focus();
      });
      this.agentEl?.querySelectorAll('[data-action="clear-log"]').forEach((button) => {
        button.addEventListener('click', () => {
          if (this.logEl) {
            this.logEl.innerHTML = `
              <div class="hwp-agent-empty">
                <div class="hwp-agent-empty-title">Agent 편집 대기</div>
                <div class="hwp-agent-empty-text">현재 Canvas 문서를 서버 세션과 맞춘 뒤 도구를 실행합니다.</div>
              </div>
            `;
          }
        });
      });
      this.agentEl?.querySelectorAll('[data-action="toggle-agent"]').forEach((button) => {
        button.addEventListener('click', (event) => {
          if (this.agentSuppressClick) {
            event.preventDefault();
            event.stopPropagation();
            this.agentSuppressClick = false;
            return;
          }
          this.toggleAgent();
        });
      });
      if (this.inputEl) {
        const autoGrow = () => {
          this.inputEl.style.height = 'auto';
          const maxHeight = 140;
          const next = Math.min(this.inputEl.scrollHeight, maxHeight);
          this.inputEl.style.height = `${next}px`;
        };
        this.inputEl.addEventListener('input', autoGrow);
        this.inputEl.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form?.requestSubmit?.();
          }
        });
        autoGrow();
      }
      this.setupAgentDrag();
    }

    setupAgentDrag() {
      const handle = this.agentEl?.querySelector('[data-drag-handle="agent"]');
      const rail = this.agentEl?.querySelector('.hwp-agent-rail');
      if (!this.agentEl) return;

      const startDrag = (event, surface, options = {}) => {
        if (options.expandedOnly && this.agentCollapsed) return;
        if (options.collapsedOnly && !this.agentCollapsed) return;
        if (event.button !== 0) return;
        if (!options.allowButtonTarget && event.target.closest('button, input, textarea, select, a')) return;

        const panelRect = this.agentEl.getBoundingClientRect();
        this.agentDrag = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          startLeft: panelRect.left,
          startTop: panelRect.top,
          viewportWidth: window.innerWidth,
          viewportHeight: window.innerHeight,
          panelWidth: panelRect.width,
          panelHeight: panelRect.height,
          moved: false,
        };
        this.agentEl.classList.add('is-dragging');
        surface.setPointerCapture?.(event.pointerId);
        event.preventDefault();
      };

      const moveDrag = (event) => {
        if (!this.agentDrag || event.pointerId !== this.agentDrag.pointerId || !this.agentEl) return;
        const nextLeft = this.agentDrag.startLeft + event.clientX - this.agentDrag.startX;
        const nextTop = this.agentDrag.startTop + event.clientY - this.agentDrag.startY;
        const movedDistance = Math.hypot(event.clientX - this.agentDrag.startX, event.clientY - this.agentDrag.startY);
        if (movedDistance > 4) this.agentDrag.moved = true;
        const maxLeft = Math.max(0, window.innerWidth - this.agentDrag.panelWidth - 8);
        const maxTop = Math.max(0, window.innerHeight - this.agentDrag.panelHeight - 8);
        const left = Math.max(8, Math.min(nextLeft, maxLeft));
        const top = Math.max(8, Math.min(nextTop, maxTop));
        this.agentEl.style.left = `${Math.round(left)}px`;
        this.agentEl.style.top = `${Math.round(top)}px`;
        this.agentEl.style.right = 'auto';
        this.agentEl.style.bottom = 'auto';
        this.agentEl.classList.add('is-floating-moved');
      };

      const endDrag = (event) => {
        if (!this.agentDrag || event.pointerId !== this.agentDrag.pointerId) return;
        const moved = this.agentDrag.moved;
        this.agentDrag = null;
        this.agentEl?.classList.remove('is-dragging');
        event.currentTarget?.releasePointerCapture?.(event.pointerId);
        if (moved) {
          this.agentSuppressClick = true;
          window.setTimeout(() => {
            this.agentSuppressClick = false;
          }, 0);
        }
      };

      const bindSurface = (surface, options) => {
        if (!surface) return;
        surface.addEventListener('pointerdown', (event) => startDrag(event, surface, options));
        surface.addEventListener('pointermove', moveDrag);
        surface.addEventListener('pointerup', endDrag);
        surface.addEventListener('pointercancel', endDrag);
      };

      bindSurface(handle, { expandedOnly: true });
      bindSurface(rail, { collapsedOnly: true, allowButtonTarget: true });
    }

    toggleAgent(forceCollapsed) {
      const next = typeof forceCollapsed === 'boolean' ? forceCollapsed : !this.agentCollapsed;
      this.agentCollapsed = next;
      if (this.agentTransitionTimer) window.clearTimeout(this.agentTransitionTimer);
      this.agentEl?.classList.remove('is-transitioning');
      void this.agentEl?.offsetWidth;
      this.agentEl?.classList.toggle('is-collapsed', next);
      this.agentEl?.classList.add('is-transitioning');
      this.agentTransitionTimer = window.setTimeout(() => {
        this.agentEl?.classList.remove('is-transitioning');
        this.agentTransitionTimer = null;
      }, 360);
      this.mount?.querySelector('.hwp-studio-host')?.classList.toggle('agent-collapsed', next);
      this.agentEl?.querySelectorAll('[data-action="toggle-agent"]').forEach((button) => {
        button.setAttribute('aria-expanded', next ? 'false' : 'true');
        button.setAttribute('title', next ? 'AI 도구 열기' : 'AI 도구 닫기');
      });
      window.setTimeout(() => {
        this.iframe?.contentWindow?.dispatchEvent(new Event('resize'));
      }, 80);
    }

    injectStyles() {
      if (document.getElementById('hwp-studio-host-styles')) return;
      const style = document.createElement('style');
      style.id = 'hwp-studio-host-styles';
      style.textContent = `
        .hwp-studio-host {
          position: relative;
          width: 100%;
          height: 100%;
          min-height: calc(100vh - 24px);
          background: #e8edf3;
          border: 0;
          border-radius: 0;
          overflow: hidden;
        }
        .hwp-studio-frame {
          display: block;
          width: 100%;
          height: 100%;
          border: 0;
          background: #fff;
        }
        body.hwp-vibe-active #vibeRoot {
          width: 100%;
          height: 100%;
          margin: 0;
        }
        body.hwp-vibe-active .main-content {
          display: flex;
          flex-direction: column;
          min-height: 0;
        }
        body.hwp-vibe-active #scrollContainer {
          display: flex;
          flex-direction: column;
          min-height: 0;
        }
        body.hwp-vibe-active #resultView {
          display: flex;
          flex-direction: column;
          min-height: 0;
        }
        body.hwp-vibe-active #paperArea {
          min-width: 0;
          min-height: 0;
        }
        body.hwp-vibe-active .mobile-header,
        body.hwp-vibe-active .input-region {
          display: none !important;
        }
        body.hwp-vibe-active .paper-sheet,
        body.hwp-vibe-active .paper-sheet.active,
        body.hwp-vibe-active .paper-sheet.vibe-active {
          width: 100% !important;
          max-width: none !important;
          height: 100% !important;
          min-height: 0 !important;
          margin: 0 !important;
          padding: 0 !important;
          border: 0 !important;
          border-radius: 0 !important;
          box-shadow: none !important;
          background: transparent !important;
        }
        body.hwp-vibe-active .scroll-container,
        body.hwp-vibe-active .doc-viewer {
          padding: 0 !important;
          height: 100% !important;
          min-height: 0 !important;
        }
        body.hwp-vibe-active .main-content::before {
          display: none !important;
        }
        .hwp-studio-agent {
          position: fixed;
          top: 148px;
          right: 28px;
          bottom: auto;
          width: 360px;
          min-width: 320px;
          max-width: min(420px, calc(100vw - 32px));
          height: min(680px, calc(100vh - 188px));
          display: grid;
          grid-template-rows: auto auto minmax(0, 1fr) auto;
          min-height: 0;
          border: 1px solid rgba(255, 255, 255, .74);
          border-radius: 32px;
          background:
            radial-gradient(circle at 20% 10%, rgba(255,255,255,.96), rgba(255,255,255,0) 32%),
            linear-gradient(155deg, rgba(255,255,255,.88), rgba(246,248,252,.82));
          backdrop-filter: blur(32px) saturate(1.08);
          -webkit-backdrop-filter: blur(32px) saturate(1.08);
          color: #1f2933;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          z-index: 240;
          box-shadow:
            0 20px 40px -20px rgba(15, 23, 42, .16),
            0 12px 36px -18px rgba(79, 70, 229, .16),
            0 0 0 1px rgba(255,255,255,.38) inset;
          overflow: hidden;
          transform-origin: 50% 100%;
          will-change: transform, opacity, filter;
          animation: hwp-agent-genie-in .5s cubic-bezier(.16,.84,.28,1) both;
          transition: width .16s ease, min-width .16s ease, max-width .16s ease, opacity .16s ease, box-shadow .16s ease, transform .16s ease;
        }
        .hwp-studio-agent::before {
          content: '';
          position: absolute;
          inset: 0;
          border-radius: inherit;
          background:
            linear-gradient(120deg, rgba(255,255,255,.58), rgba(255,255,255,0) 42%, rgba(255,255,255,.38) 62%, rgba(255,255,255,0));
          opacity: .62;
          pointer-events: none;
          mix-blend-mode: screen;
        }
        .hwp-studio-agent > * {
          position: relative;
          z-index: 1;
        }
        @keyframes hwp-agent-genie-in {
          0% {
            opacity: 0;
            filter: blur(8px);
            transform: translateY(56px) scaleX(.18) scaleY(.1) skewX(6deg);
          }
          55% {
            opacity: 1;
            filter: blur(2px);
            transform: translateY(-4px) scaleX(.94) scaleY(1.04) skewX(-2deg);
          }
          100% {
            opacity: 1;
            filter: blur(0);
            transform: translateY(0) scaleX(1) scaleY(1) skewX(0deg);
          }
        }
        .hwp-studio-agent.is-dragging {
          transition: none;
          opacity: .98;
          user-select: none;
          cursor: grabbing;
          box-shadow:
            0 26px 54px -20px rgba(15, 23, 42, .24),
            0 18px 46px -24px rgba(79, 70, 229, .18);
        }
        .hwp-studio-agent.is-floating-moved {
          transform: translateY(-2px);
          box-shadow:
            0 24px 58px -24px rgba(15, 23, 42, .22),
            0 18px 44px -28px rgba(79, 70, 229, .18);
        }
        .hwp-studio-agent.is-transitioning:not(.is-collapsed) {
          animation: hwp-agent-genie-in .34s cubic-bezier(.16,.84,.28,1) both;
        }
        .hwp-studio-agent.is-collapsed {
          width: 52px !important;
          min-width: 52px !important;
          max-width: 52px !important;
          height: 52px !important;
          padding: 0;
          border-radius: 18px;
          border: 1px solid #E2E8F0;
          background: linear-gradient(135deg, #fff, #F8FAFC);
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
          box-shadow: 0 20px 40px -10px rgba(79, 70, 229, .15);
          transition:
            width .24s cubic-bezier(.2,.8,.2,1),
            min-width .24s cubic-bezier(.2,.8,.2,1),
            max-width .24s cubic-bezier(.2,.8,.2,1),
            height .24s cubic-bezier(.2,.8,.2,1),
            border-radius .24s ease,
            box-shadow .24s ease,
            background .24s ease;
        }
        .hwp-studio-agent.is-collapsed::before {
          display: none;
        }
        .hwp-studio-agent.is-transitioning.is-collapsed {
          animation: hwp-agent-button-in .24s cubic-bezier(.2,.8,.2,1) both;
        }
        .hwp-studio-agent.is-collapsed .hwp-agent-menubar,
        .hwp-studio-agent.is-collapsed .hwp-agent-toolbar,
        .hwp-studio-agent.is-collapsed .hwp-agent-log,
        .hwp-studio-agent.is-collapsed .hwp-agent-form {
          display: none;
        }
        .hwp-agent-rail {
          display: none;
          width: 100%;
          height: 100%;
          padding: 0;
          margin: 0;
          border: 0;
          border-radius: inherit;
          background: transparent;
          color: #4F46E5;
          cursor: pointer;
          align-items: center;
          justify-content: center;
          place-items: center;
          line-height: 0;
          transition: transform .18s ease, filter .18s ease;
        }
        .hwp-agent-rail svg {
          display: block;
          width: 26px;
          height: 26px;
          overflow: visible;
          filter: drop-shadow(0 6px 14px rgba(79, 70, 229, .22));
          transition: transform .25s cubic-bezier(.22,.94,.32,1.05);
        }
        .hwp-agent-rail:hover svg {
          transform: scale(1.06) rotate(-4deg);
        }
        .hwp-agent-rail:active svg {
          transform: scale(.94);
        }
        .hwp-studio-agent.is-collapsed .hwp-agent-rail {
          display: grid;
          animation: hwp-agent-logo-pop .2s ease-out both;
        }
        @keyframes hwp-agent-logo-pop {
          0% { opacity: 0; transform: scale(.86); }
          100% { opacity: 1; transform: scale(1); }
        }
        @keyframes hwp-agent-button-in {
          0% { opacity: .88; transform: scale(.96); }
          100% { opacity: 1; transform: scale(1); }
        }
        .hwp-agent-menubar {
          display: flex;
          flex-direction: column;
          align-items: stretch;
          min-width: 0;
          padding: 8px 10px 10px;
          background: transparent;
          font-size: 13px;
          cursor: grab;
          user-select: none;
        }
        .hwp-studio-agent.is-dragging .hwp-agent-menubar {
          cursor: grabbing;
        }
        .hwp-agent-grabber {
          align-self: center;
          width: 38px;
          height: 5px;
          margin-bottom: 8px;
          border-radius: 999px;
          background: rgba(60, 67, 82, .22);
          flex: 0 0 auto;
        }
        .hwp-agent-navrow {
          display: grid;
          grid-template-columns: 36px 1fr 36px;
          align-items: center;
          gap: 8px;
          min-width: 0;
        }
        .hwp-agent-titleblock {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-width: 0;
          line-height: 1.15;
          gap: 1px;
        }
        .hwp-agent-menu-title {
          font-size: 15px;
          font-weight: 600;
          letter-spacing: -0.01em;
          color: #1f2933;
          text-align: center;
          max-width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .hwp-agent-status {
          font-size: 11px;
          color: #8a93a4;
          text-align: center;
          max-width: 100%;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .hwp-agent-icon-btn {
          width: 36px;
          height: 36px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 0;
          border: 0;
          border-radius: 999px;
          background: rgba(255, 255, 255, .72);
          box-shadow:
            inset 0 0 0 1px rgba(15, 23, 42, .06),
            0 1px 2px rgba(15, 23, 42, .06);
          color: #344054;
          cursor: pointer;
          transition: background .16s ease, transform .12s ease, color .16s ease, box-shadow .16s ease;
        }
        .hwp-agent-icon-btn:hover {
          background: rgba(255, 255, 255, .96);
          color: #111827;
        }
        .hwp-agent-icon-btn:active {
          transform: scale(.94);
        }
        .hwp-agent-toolbar {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          min-width: 0;
          padding: 4px 12px 10px;
          background: transparent;
        }
        .hwp-agent-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          height: 28px;
          padding: 0 12px;
          border: 0;
          border-radius: 999px;
          background: rgba(255, 255, 255, .72);
          box-shadow: inset 0 0 0 1px rgba(15, 23, 42, .06);
          color: #455468;
          font-size: 12px;
          font-weight: 500;
          letter-spacing: -0.01em;
          cursor: pointer;
          transition: background .14s ease, color .14s ease, transform .12s ease;
        }
        .hwp-agent-chip:hover {
          background: rgba(255, 255, 255, .98);
          color: #111827;
        }
        .hwp-agent-chip:active {
          transform: scale(.97);
        }
        .hwp-agent-chip svg {
          opacity: .75;
        }
        .hwp-agent-log {
          min-height: 0;
          overflow: auto;
          padding: 8px 14px 12px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          background: transparent;
          scroll-behavior: smooth;
        }
        .hwp-agent-log::-webkit-scrollbar { width: 6px; }
        .hwp-agent-log::-webkit-scrollbar-thumb {
          background: rgba(15, 23, 42, .12);
          border-radius: 999px;
        }
        .hwp-agent-empty {
          align-self: center;
          margin: 24px auto;
          max-width: 84%;
          background: rgba(255, 255, 255, .68);
          color: #1f2933;
          padding: 14px 18px;
          font-size: 12px;
          line-height: 1.55;
          border-radius: 20px;
          box-shadow: inset 0 0 0 1px rgba(15, 23, 42, .05);
          text-align: center;
        }
        .hwp-agent-empty-title {
          font-weight: 600;
          margin-bottom: 4px;
          letter-spacing: -0.01em;
        }
        .hwp-agent-empty-text {
          color: #667085;
        }
        .hwp-agent-msg {
          display: inline-flex;
          flex-direction: column;
          max-width: 78%;
          padding: 9px 14px;
          font-size: 13px;
          line-height: 1.45;
          letter-spacing: -0.005em;
          white-space: pre-wrap;
          overflow-wrap: anywhere;
          border: 0;
          box-shadow: none;
        }
        .hwp-agent-msg.assistant {
          align-self: flex-start;
          background: rgba(242, 244, 247, .96);
          color: #1f2933;
          border-radius: 22px 22px 22px 6px;
          margin-right: auto;
        }
        .hwp-agent-msg.assistant + .hwp-agent-msg.assistant {
          border-top-left-radius: 6px;
          margin-top: -2px;
        }
        .hwp-agent-msg.user {
          align-self: flex-end;
          background: linear-gradient(180deg, rgba(95, 99, 255, .96), rgba(62, 78, 255, .98));
          color: #fff;
          border-radius: 22px 22px 6px 22px;
          margin-left: auto;
        }
        .hwp-agent-msg.user + .hwp-agent-msg.user {
          border-top-right-radius: 6px;
          margin-top: -2px;
        }
        .hwp-agent-msg.tool {
          align-self: center;
          background: transparent;
          color: #8a93a4;
          font-size: 11px;
          font-weight: 500;
          padding: 4px 10px;
          margin: 2px 0;
        }
        .hwp-agent-msg.error {
          align-self: center;
          background: rgba(255, 235, 235, .96);
          color: #9a1f1f;
          border-radius: 999px;
          font-size: 11px;
          padding: 6px 14px;
        }
        .hwp-agent-msg.system {
          align-self: center;
          background: transparent;
          color: #8a93a4;
          font-size: 11px;
          padding: 2px 10px;
        }
        .hwp-agent-form {
          padding: 8px 12px 12px;
          background: transparent;
        }
        .hwp-agent-composer {
          display: flex;
          align-items: flex-end;
          gap: 6px;
          padding: 6px 6px 6px 16px;
          background: rgba(255, 255, 255, .82);
          border-radius: 26px;
          box-shadow:
            inset 0 0 0 1px rgba(15, 23, 42, .08),
            0 4px 14px rgba(15, 23, 42, .06);
          transition: box-shadow .18s ease;
        }
        .hwp-agent-composer:focus-within {
          box-shadow:
            inset 0 0 0 1.5px rgba(95, 99, 255, .65),
            0 6px 18px rgba(74, 105, 255, .14);
        }
        .hwp-agent-input {
          flex: 1 1 auto;
          width: 100%;
          resize: none;
          min-height: 36px;
          max-height: 140px;
          border: 0;
          outline: none;
          padding: 8px 0;
          background: transparent;
          font: inherit;
          font-size: 14px;
          line-height: 1.45;
          letter-spacing: -0.005em;
          color: #1f2933;
        }
        .hwp-agent-input::placeholder {
          color: #9aa3b3;
        }
        .hwp-agent-send {
          flex: 0 0 auto;
          width: 36px;
          height: 36px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 0;
          border: 0;
          border-radius: 999px;
          background: linear-gradient(180deg, rgba(95, 99, 255, 1), rgba(62, 78, 255, 1));
          color: #fff;
          cursor: pointer;
          box-shadow: 0 6px 14px rgba(74, 105, 255, .28);
          transition: transform .14s ease, box-shadow .16s ease, opacity .16s ease;
        }
        .hwp-agent-send:hover {
          transform: translateY(-1px);
          box-shadow: 0 10px 22px rgba(74, 105, 255, .32);
        }
        .hwp-agent-send:active {
          transform: scale(.94);
        }
        .hwp-agent-send:disabled,
        .hwp-agent-chip:disabled,
        .hwp-agent-icon-btn:disabled {
          opacity: .45;
          cursor: not-allowed;
          transform: none;
          box-shadow: inset 0 0 0 1px rgba(15, 23, 42, .06);
        }
        body[data-theme="dark"] .hwp-studio-host {
          background: #020617;
        }
        body[data-theme="dark"] .hwp-studio-agent {
          background:
            radial-gradient(circle at 20% 10%, rgba(40,52,72,.72), rgba(20,26,38,0) 32%),
            linear-gradient(155deg, rgba(22,28,40,.92), rgba(14,20,32,.92));
          color: #e2e8f0;
          border-color: rgba(255,255,255,.08);
        }
        body[data-theme="dark"] .hwp-agent-menubar,
        body[data-theme="dark"] .hwp-agent-toolbar,
        body[data-theme="dark"] .hwp-agent-form {
          background: transparent;
        }
        body[data-theme="dark"] .hwp-agent-grabber {
          background: rgba(255, 255, 255, .22);
        }
        body[data-theme="dark"] .hwp-agent-menu-title {
          color: #e6ebf3;
        }
        body[data-theme="dark"] .hwp-agent-status {
          color: #94a3b8;
        }
        body[data-theme="dark"] .hwp-agent-icon-btn,
        body[data-theme="dark"] .hwp-agent-chip {
          background: rgba(255, 255, 255, .06);
          color: #cbd5e1;
          box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .08);
        }
        body[data-theme="dark"] .hwp-agent-icon-btn:hover,
        body[data-theme="dark"] .hwp-agent-chip:hover {
          background: rgba(255, 255, 255, .12);
          color: #f1f5f9;
        }
        body[data-theme="dark"] .hwp-agent-empty {
          background: rgba(255, 255, 255, .04);
          color: #cbd5e1;
          box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .06);
        }
        body[data-theme="dark"] .hwp-agent-msg.assistant {
          background: rgba(255, 255, 255, .06);
          color: #e2e8f0;
        }
        body[data-theme="dark"] .hwp-agent-msg.tool,
        body[data-theme="dark"] .hwp-agent-msg.system {
          color: #94a3b8;
        }
        body[data-theme="dark"] .hwp-agent-composer {
          background: rgba(255, 255, 255, .06);
          box-shadow:
            inset 0 0 0 1px rgba(255, 255, 255, .08),
            0 4px 14px rgba(0, 0, 0, .3);
        }
        body[data-theme="dark"] .hwp-agent-composer:focus-within {
          box-shadow:
            inset 0 0 0 1.5px rgba(120, 130, 255, .8),
            0 6px 18px rgba(74, 105, 255, .22);
        }
        body[data-theme="dark"] .hwp-agent-input {
          background: transparent;
          color: #e2e8f0;
        }
        body[data-theme="dark"] .hwp-agent-input::placeholder {
          color: #64748b;
        }
        @media (max-width: 768px) {
          .hwp-studio-agent {
            top: 112px;
            left: 10px;
            right: 10px;
            bottom: auto;
            width: auto;
            min-width: 0;
            max-width: none;
            height: min(420px, calc(100% - 136px));
          }
        }
        @media (max-width: 1080px) {
          .hwp-studio-agent {
            width: 340px;
            min-width: 300px;
          }
          .hwp-studio-agent.is-collapsed {
            width: 48px !important;
            min-width: 48px !important;
            max-width: 48px !important;
            height: 48px !important;
            border-radius: 16px;
          }
        }
        @media (max-width: 900px) {
          .hwp-studio-agent {
            width: 320px;
            min-width: 300px;
            height: min(560px, calc(100% - 170px));
          }
          .hwp-studio-agent.is-collapsed {
            left: auto;
            width: 44px !important;
            min-width: 44px !important;
            max-width: 44px !important;
            height: 44px !important;
            border-radius: 15px;
          }
          .hwp-agent-rail svg {
            width: 23px;
            height: 23px;
          }
        }
      `;
      document.head.appendChild(style);
    }

    setBusy(next) {
      this.busy = next;
      if (this.sendBtn) this.sendBtn.disabled = next;
      if (this.inputEl) this.inputEl.disabled = next;
      this.agentEl?.querySelectorAll('[data-action="sync"], [data-action="focus-input"], [data-action="clear-log"]').forEach((button) => {
        button.disabled = next;
      });
    }

    setStatus(text) {
      if (this.statusEl) this.statusEl.textContent = text;
    }

    cleanError(error) {
      return error instanceof Error ? error.message : String(error || '알 수 없는 오류');
    }

    addLog(kind, text, opts = {}) {
      if (!this.logEl) return null;
      this.logEl.querySelector('.hwp-agent-empty')?.remove();
      const item = document.createElement('div');
      item.className = `hwp-agent-msg ${kind}`;
      item.textContent = text;
      this.logEl.appendChild(item);
      this.logEl.scrollTop = this.logEl.scrollHeight;
      if (!opts.silent) this.persistLogEntry(kind, text);
      return item;
    }

    persistLogEntry(kind, text) {
      if (!this.sessionId) return;
      const all = loadAllChats();
      const entry = all[this.sessionId] || {
        sessionId: this.sessionId,
        fileName: this.fileName,
        pageCount: this.pageCount,
        messages: [],
      };
      entry.messages.push({ kind, text: String(text || ''), ts: Date.now() });
      entry.fileName = this.fileName;
      entry.pageCount = this.pageCount;
      entry.updatedAt = Date.now();
      all[this.sessionId] = entry;
      saveAllChats(all);
    }

    restoreLogFromStorage() {
      if (!this.sessionId || !this.logEl) return false;
      const all = loadAllChats();
      const entry = all[this.sessionId];
      if (!entry || !Array.isArray(entry.messages) || !entry.messages.length) return false;
      this.logEl.innerHTML = '';
      for (const msg of entry.messages) {
        if (!msg) continue;
        const k = String(msg.kind || '');
        const t = String(msg.text || '');
        if (!k || !t) continue;
        this.addLog(k, t, { silent: true });
      }
      this.history = entry.messages
        .filter((m) => m && (m.kind === 'user' || m.kind === 'assistant'))
        .map((m) => ({ role: m.kind, text: String(m.text || '') }));
      return true;
    }

    async cacheCurrentBytes() {
      if (!this.sessionId) return;
      try {
        const exportUrl = endpoint(this.endpoints.export || '/api/v2/hwp/sessions/{sessionId}/export', this.sessionId);
        const response = await fetch(exportUrl);
        if (!response.ok) return;
        const blob = await response.blob();
        if (!blob || !blob.size) return;
        await idbPut(this.sessionId, blob);
        persistMeta({
          sessionId: this.sessionId,
          fileName: this.fileName,
          pageCount: this.pageCount,
          updatedAt: Date.now(),
        });
      } catch (error) {
        console.warn('[HwpStudioHost] cacheCurrentBytes failed', error);
      }
    }

    appendLog(target, text) {
      if (!target || !text) return;
      target.textContent += text;
      if (this.logEl) this.logEl.scrollTop = this.logEl.scrollHeight;
    }

    parseSseChunk(buffer, onEvent) {
      let rest = buffer;
      let idx = rest.indexOf('\n\n');
      while (idx >= 0) {
        const raw = rest.slice(0, idx);
        rest = rest.slice(idx + 2);
        const data = raw
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (data) {
          try {
            onEvent(JSON.parse(data));
          } catch (error) {
            console.warn('[HwpStudioHost] invalid SSE event:', data, error);
          }
        }
        idx = rest.indexOf('\n\n');
      }
      return rest;
    }

    async sendAgentRequest() {
      if (this.busy || !this.inputEl) return;
      const message = this.inputEl.value.trim();
      if (!message) return;

      this.inputEl.value = '';
      this.addLog('user', message);
      const answer = this.addLog('assistant', '', { silent: true });
      let changed = false;
      this.setBusy(true);
      this.setStatus('Agent 실행 중');

      try {
        this.setStatus('동기화 중');
        await this.request('syncSession');
        this.setStatus('요청 전송');
        const chatUrl = endpoint(this.endpoints.chat || '/api/v2/hwp/sessions/{sessionId}/chat', this.sessionId);
        const response = await fetch(chatUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, history: this.history.slice(-8) }),
        });
        if (!response.ok || !response.body) {
          throw new Error(await response.text().catch(() => `HTTP ${response.status}`));
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        const onEvent = (event) => {
          if (event.type === 'text') {
            this.appendLog(answer, event.delta || '');
          } else if (event.type === 'status') {
            this.setStatus(event.text || event.phase || '도구 실행 준비');
            this.addLog('tool', event.text || event.phase || '도구 실행 준비');
        } else if (event.type === 'tool_start') {
            this.setStatus(`${event.name || 'tool'} 실행`);
            this.addLog('tool', `${event.name || 'tool'} 실행`);
          } else if (event.type === 'tool_result') {
            changed = true;
            const affected = Array.isArray(event.affected) && event.affected.length ? ` · ${event.affected.length}쪽 갱신` : '';
            this.setStatus(`${event.name || 'tool'} 완료`);
            this.addLog('tool', `${event.name || 'tool'} 완료${affected}`);
            if (event.live || (Array.isArray(event.affected) && event.affected.length)) {
              this.scheduleLiveRefresh();
            }
          } else if (event.type === 'tool_error' || event.type === 'error') {
            this.setStatus('오류');
            this.addLog('error', event.error || 'Agent 실행 오류');
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer = this.parseSseChunk(buffer + decoder.decode(value, { stream: true }), onEvent);
        }
        if (buffer.trim()) this.parseSseChunk(`${buffer}\n\n`, onEvent);

        const finalText = answer?.textContent || '';
        this.persistLogEntry('assistant', finalText);
        this.history.push({ role: 'user', text: message }, { role: 'assistant', text: finalText });
        if (changed) {
          this.setStatus('Canvas 갱신');
          this.addLog('system', 'Agent 변경사항을 Canvas에 반영합니다.');
          await this.flushLiveRefresh();
          await this.refreshAfterAgent({ forceReload: true });
          await this.cacheCurrentBytes();
        }
        this.setStatus('완료');
      } catch (error) {
        this.addLog('error', this.cleanError(error));
        this.setStatus('오류');
      } finally {
        this.setBusy(false);
      }
    }

    handleMessage(event) {
      const data = event.data || {};
      if (data.type !== 'rhwp-studio-event') return;
      if (data.event === 'session-synced' && typeof this.options.onSynced === 'function') {
        this.options.onSynced();
      }
      if (data.event === 'session-synced') {
        this.cacheCurrentBytes();
      }
      if (data.event === 'session-sync-error') {
        console.warn('[HwpStudioHost] session sync failed:', data.error);
      }
    }

    request(method, params = {}) {
      return new Promise((resolve, reject) => {
        if (!this.iframe?.contentWindow) {
          reject(new Error('HWP Studio iframe is not ready'));
          return;
        }

        const id = `hwp-studio-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        let timeoutId = null;
        const cleanup = () => {
          if (timeoutId) window.clearTimeout(timeoutId);
          window.removeEventListener('message', onMessage);
        };
        const onMessage = (event) => {
          const data = event.data || {};
          if (data.type !== 'rhwp-response' || data.id !== id) return;
          cleanup();
          if (data.error) {
            reject(new Error(data.error));
          } else {
            resolve(data.result);
          }
        };
        window.addEventListener('message', onMessage);
        timeoutId = window.setTimeout(() => {
          cleanup();
          reject(new Error(`${method} timed out`));
        }, 30000);
        this.iframe.contentWindow.postMessage({ type: 'rhwp-request', id, method, params }, '*');
      });
    }

    async scheduleLiveRefresh() {
      this.liveRefreshQueued = true;
      if (this.liveRefreshPromise) return this.liveRefreshPromise;

      this.liveRefreshPromise = (async () => {
        while (this.liveRefreshQueued) {
          this.liveRefreshQueued = false;
          const elapsed = Date.now() - this.lastLiveRefreshAt;
          if (elapsed < 350) {
            await new Promise((resolve) => setTimeout(resolve, 350 - elapsed));
          }
          await this.refreshAfterAgent({ live: true });
          this.lastLiveRefreshAt = Date.now();
        }
      })().catch((error) => {
        console.warn('[HwpStudioHost] live refresh failed:', error);
      }).finally(() => {
        this.liveRefreshPromise = null;
      });

      return this.liveRefreshPromise;
    }

    async flushLiveRefresh() {
      if (this.liveRefreshPromise) {
        await this.liveRefreshPromise;
      }
    }

    async refreshAfterAgent(options = {}) {
      if (!this.iframe) return;
      const exportUrl = endpoint(this.endpoints.export || '/api/v2/hwp/sessions/{sessionId}/export', this.sessionId);
      const hardReload = () => {
        this.refreshSerial += 1;
        const url = new URL(this.iframe.src, window.location.href);
        url.searchParams.set('url', `${exportUrl}?t=${Date.now()}`);
        url.searchParams.set('filename', this.fileName);
        this.iframe.src = url.toString();
      };

      if (options.forceReload) {
        hardReload();
        return;
      }

      const serial = ++this.refreshSerial;
      try {
        const response = await fetch(`${exportUrl}?t=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const bytes = Array.from(new Uint8Array(await response.arrayBuffer()));
        if (options.live && serial !== this.refreshSerial) return;
        const result = await this.request('loadFile', { data: bytes, fileName: this.fileName });
        const pageCount = Number(result?.pageCount || 0);
        if (pageCount <= 0) throw new Error('Canvas load returned an empty document');
      } catch (error) {
        if (options.live) throw error;
        hardReload();
      }
    }

    destroy() {
      window.removeEventListener('message', this.messageHandler);
      if (this.mount) this.mount.innerHTML = '';
      this.agentEl?.remove();
      this.agentEl = null;
      this.iframe = null;
    }
  }

  window.VibeEditor = {
    mount(options) {
      const editor = new HwpStudioHost(options);
      editor.render();
      return editor;
    },
  };
})();
