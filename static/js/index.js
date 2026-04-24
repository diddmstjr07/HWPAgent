document.addEventListener('DOMContentLoaded', () => {
    console.log("HELLO FROM INDEX.JS! If you see this, the script is running.");
    // ============================================================
    // 0. 설정 및 상수
    // ============================================================
    const DEBUG_MODE = true; // [디버깅용] true면 콘솔에 데이터 수신 로그를 출력합니다.
    
    const API_ENDPOINTS = {
        CHAT: '/api/chat-stream',
        DOC: '/api/generate-stream',
        AUTO: '/api/interact',
        IMAGE: '/api/search-images',
        TEMPLATE: '/api/template/upload',
        // v2 HWP endpoints (Node 서버 프록시)
        HWP_UPLOAD: '/api/v2/hwp/sessions',  // POST: file → session_id
        HWP_RENDER: '/api/v2/hwp/sessions/{sessionId}/pages/{pageIndex}',  // GET: SVG
        HWP_EDIT: '/api/v2/hwp/sessions/{sessionId}/edit',  // POST: operation
        HWP_EXPORT: '/api/v2/hwp/sessions/{sessionId}/export',  // GET: download
        HWP_DELETE: '/api/v2/hwp/sessions/{sessionId}',  // DELETE
        HWP_HEALTH: '/api/v2/hwp/health',  // GET
        // Legacy endpoints (deprecated)
        EDIT_HTML: '/api/edit-html', // DEPRECATED
        EDIT_FRAGMENT: '/api/edit-fragment', // DEPRECATED
        TEMPLATES: '/api/templates',
        TEMPLATE_SELECT: '/api/template/select'
    };
    const supportsSrcdoc = 'srcdoc' in document.createElement('iframe');
    const THEME_STORAGE_KEY = 'docAgentTheme';
    const THEME_COLORS = {
        light: '#F8FAFC',
        dark: '#0B0F17'
    };
    const CANVAS_WIDTH_STORAGE_KEY = 'docAgentCanvasWidth';

    // DOM 요소 캐싱 (에러 방지를 위해 Optional Chaining 사용)
    const els = {
        // Views
        homeView: document.getElementById('homeView'),
        resultView: document.getElementById('resultView'),
        chatStream: document.getElementById('chatStream'),
        docPaper: document.getElementById('paperArea'),
        docFrame: document.getElementById('docFrame'),
        docContent: document.getElementById('docContent'),
        docTitle: document.getElementById('docTitle'),
        scrollContainer: document.getElementById('scrollContainer'),
        sectionFillPanel: document.getElementById('sectionFillPanel'),

        // Inputs & Buttons
        userRequest: document.getElementById('userRequest'),
        btnSend: document.getElementById('btnSend'),
        iconSend: document.getElementById('iconSend'),
        spinnerSend: document.getElementById('spinnerSend'),
        btnAttach: document.getElementById('btnAttach'),
        attachMenu: document.getElementById('attachMenu'),
        editorToolbar: document.getElementById('editorToolbar'),
        templateNameBadge: document.getElementById('templateNameBadge'),
        editModeBadge: document.getElementById('editModeBadge'),
        fillModeBadge: document.getElementById('fillModeBadge'),
        selectionPreview: document.getElementById('selectionPreview'),
        clearSelectionBtn: document.getElementById('clearSelectionBtn'),
        editTargetPanel: document.getElementById('editTargetPanel'),
        editTargetSelect: document.getElementById('editTargetSelect'),
        editTargetInput: document.getElementById('editTargetInput'),
        editTargetApply: document.getElementById('editTargetApply'),
        inlineEditBubble: document.getElementById('inlineEditBubble'),
        inlineEditInput: document.getElementById('inlineEditInput'),
        inlineEditSubmit: document.getElementById('inlineEditSubmit'),
        inlineEditClose: document.getElementById('inlineEditClose'),
        editCover: document.getElementById('editCover'),
        canvasOverlay: document.getElementById('canvasOverlay'),
        canvasPanel: document.querySelector('.canvas-panel'),
        canvasResizeHandle: document.getElementById('canvasResizeHandle'),
        canvasBody: document.getElementById('canvasBody'),
        btnCanvasClose: document.getElementById('btnCanvasClose'),
        
        // Toggles & Sidebar
        btnDocMode: document.querySelector('.toggle-btn'), // 헤더의 문서모드 토글
        sidebar: document.getElementById('sidebar'),
        sidebarOverlay: document.getElementById('sidebarOverlay'),
        workspaceList: document.getElementById('workspaceList'),
        btnMenu: document.getElementById('btnMenu'),
        btnDesktopSidebarToggle: document.getElementById('btnDesktopSidebarToggle'),
        
        // Modals
        modalAuth: document.getElementById('modalAuth'),
        modalLogin: document.getElementById('modalLogin'),
        modalProfile: document.getElementById('modalProfile'),
        profileModalBox: document.getElementById('profileModalBox'),
        modalCalendar: document.getElementById('modalCalendar'),
        modalTemplate: document.getElementById('modalTemplate'),
        modalDownload: document.getElementById('modalDownload'),
        templateList: document.getElementById('templateList'),
        templateSearch: document.getElementById('templateSearch'),
        templateEmpty: document.getElementById('templateEmpty'),
        btnCloseTemplate: document.getElementById('closeTemplateModal'),
        btnDownloadConfirm: document.getElementById('btnDownloadConfirm'),
        btnDownloadCancel: document.getElementById('btnDownloadCancel'),
        btnDownloadClose: document.getElementById('closeDownloadModal'),
        btnOpenAuth: document.getElementById('btnOpenAuth'),
        btnAuthToggle: document.getElementById('btnAuthToggle'),
        closeProfile: document.getElementById('closeProfile'),
        profileAvatar: document.getElementById('profileAvatar'),
        profileName: document.getElementById('profileName'),
        profileEmail: document.getElementById('profileEmail'),
        profileProvider: document.getElementById('profileProvider'),
        profileLogin: document.getElementById('profileLogin'),
        profileLogout: document.getElementById('profileLogout'),
        
        // Riro Inputs
        riroSchool: document.getElementById('riroSchool'),
        riroId: document.getElementById('riroId'),
        riroPw: document.getElementById('riroPw'),
        btnLoginAction: document.getElementById('btnLoginAction'),

        // Auth Inputs
        authName: document.getElementById('authName'),
        authEmail: document.getElementById('authEmail'),
        authPassword: document.getElementById('authPassword'),
        btnAuthLogin: document.getElementById('btnAuthLogin'),
        btnAuthRegister: document.getElementById('btnAuthRegister'),
        btnAuthGoogle: document.getElementById('btnAuthGoogle'),
        authStatus: document.getElementById('authStatus'),
        userNameLabel: document.getElementById('userNameLabel'),
        userEmailLabel: document.getElementById('userEmailLabel'),
        userAvatar: document.getElementById('userAvatar'),
        userProfile: document.getElementById('userProfile'),
        
        // New Chat Button
        btnNewChat: document.getElementById('btnNewChat'),
        
        // Etc
        toast: document.getElementById('toast'),
    };

    // 상태 관리 (State)
    const state = {
        isGenerating: false,
        docMode: false, // false: 채팅모드, true: 문서모드 - Now implies if docContent has an active template
        chatHistory: [], // { role: 'user' | 'ai', text: '...' }
        streamingBuffer: '', // 현재 받아오고 있는 텍스트 (raw text before display)
        document: { title: '', content: '' }, // raw text for doc mode
        templateHtml: '', // NEW: Store the current HTML content of the document
        templateName: '', // NEW: Name of the loaded template
        templateFilePath: '', // NEW: path of the loaded template file
        templateId: '', // NEW: asset base id for template HTML
        imagesNeeded: [],
        template: null, // OLD: For raw text template, use templateHtml now
        templateCatalog: [],
        templateCatalogLoaded: false,
        templateSource: null,
        templateMode: null,
        templateSections: [],
        templateSectionSignature: '',
        templateAnalysis: null,
        templateFillFields: [],
        fillSessionActive: false,
        fillIntakeBusy: false,
        fillEssentialFields: [],
        fillRemainingFields: [],
        fillVerificationPending: false,
        fillDetectedFields: [],
        fillQueue: [],
        fillActiveField: '',
        fillAnswers: {},
        selectedSnippet: '',
        selectedBlocks: [],
        selectedSectionTitle: '',
        selectedBlock: null,
        selectedRange: null,
        editCoverActive: false,
        editCoverLocked: false,
        canvasOpen: false,
        canvasDismissed: false,
        canvasRestoreParent: null,
        canvasRestoreNext: null,
        canvasUserWidth: null,
        canvasResizing: false,
        canvasResizeStartX: 0,
        canvasResizeStartWidth: 0,
        canvasResizePointerId: null,
        frameHtml: '',
        frameDocumentRef: null,
        frameResizeObserver: null,
        frameBlobUrl: null,
        selectionChangeTimer: null,
        riroEvents: [],
        riroLoggedIn: false,
        user: null,
        authChecked: false,
        // New for typewriter effect in chat mode
        displayedChatContent: '',
        chatTypingTimeoutId: null,
        // New for typewriter effect in document mode (now for chat output only)
        displayedDocContent: '', 
        docTypingTimeoutId: null,
        // Chat History
        currentSessionId: null
    };

    const theme = {
        meta: document.querySelector('meta[name="theme-color"]'),
        toggles: Array.from(document.querySelectorAll('[data-theme-toggle]')),
        icons: Array.from(document.querySelectorAll('[data-theme-icon]'))
    };

    const applyTheme = (themeName, { persist = true } = {}) => {
        const resolved = themeName === 'dark' ? 'dark' : 'light';
        document.body.dataset.theme = resolved;
        document.documentElement.style.colorScheme = resolved;
        if (theme.meta) theme.meta.setAttribute('content', THEME_COLORS[resolved]);
        theme.toggles.forEach((btn) => {
            btn.setAttribute('aria-pressed', resolved === 'dark' ? 'true' : 'false');
        });
        theme.icons.forEach((icon) => {
            icon.classList.toggle('bi-sun', resolved === 'dark');
            icon.classList.toggle('bi-moon-stars', resolved !== 'dark');
        });
        if (persist) localStorage.setItem(THEME_STORAGE_KEY, resolved);
    };

    const toggleTheme = () => {
        const current = document.body.dataset.theme === 'dark' ? 'dark' : 'light';
        applyTheme(current === 'dark' ? 'light' : 'dark');
    };

    const initTheme = () => {
        const stored = localStorage.getItem(THEME_STORAGE_KEY);
        const hasStored = stored === 'dark' || stored === 'light';
        if (hasStored) {
            applyTheme(stored, { persist: true });
            return;
        }
        applyTheme('light', { persist: false });
    };

    const getPremiumState = () => {
        const hostname = window.location.hostname.toLowerCase();
        const email = (state.user?.email || '').toLowerCase();
        const matchesDomain = hostname === 'okgwa.hs.jne.kr' || hostname.endsWith('.okgwa.hs.jne.kr');
        const matchesEmail = email.endsWith('@okgwa.hs.jne.kr');
        const tierValue = String(state.user?.tier || state.user?.plan || state.user?.subscription || '').toLowerCase();
        const hasPremiumFlag = state.user?.is_premium === true;
        const hasTier = ['premium', 'plus', 'pro'].includes(tierValue);
        const isPremium = hasPremiumFlag || hasTier || matchesDomain || matchesEmail;

        return { matchesDomain, matchesEmail, isPremium };
    };

    const applyAccountUIState = () => {
        const { matchesDomain, matchesEmail, isPremium } = getPremiumState();
        const shouldHideUpgrade = matchesDomain || matchesEmail;

        document.querySelectorAll('[data-upgrade-item]').forEach((item) => {
            item.classList.toggle('hidden', shouldHideUpgrade);
            item.setAttribute('aria-hidden', shouldHideUpgrade ? 'true' : 'false');
        });

        document.querySelectorAll('[data-premium-badge]').forEach((badge) => {
            badge.classList.toggle('hidden', !isPremium);
            badge.setAttribute('aria-hidden', isPremium ? 'false' : 'true');
        });
    };

    // ============================================================ 
    // 1. 핵심 로직: 화면 렌더링 (View)
    // ============================================================ 

    // 마크다운 변환기 (에러 방지 래퍼)
    const parseMarkdown = (text) => {
        if (!text) return '';
        try {
            // 1. 최신 marked.parse() 시도
            if (window.marked && typeof window.marked.parse === 'function') {
                const result = window.marked.parse(text);
                // 동기적으로 문자열이 반환된 경우만 사용
                if (typeof result === 'string') return result;
            }
            // 2. 구버전 marked() 함수 시도
            if (typeof window.marked === 'function') {
                return window.marked(text);
            }
        } catch (e) { 
            console.warn('Marked lib parsing error:', e); 
        }
        
        // Fallback: HTML 이스케이프 후 줄바꿈 처리
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\n/g, '<br>');
    };

    const safeJsonParse = (text) => {
        if (!text) return null;
        try {
            return JSON.parse(text);
        } catch {
            return null;
        }
    };

    const parseJsonResponse = async (response) => {
        const text = await response.text();
        const data = safeJsonParse(text);
        if (data) return data;
        if (!text) return { success: false, error: `HTTP ${response.status}` };
        return { success: false, error: text };
    };

    const postFormDataViaXHR = (url, formData) =>
        new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url, true);
            xhr.responseType = 'text';
            xhr.onload = () => {
                const data = safeJsonParse(xhr.responseText || '');
                resolve({
                    ok: xhr.status >= 200 && xhr.status < 300,
                    status: xhr.status,
                    data: data || { success: false, error: xhr.responseText || `HTTP ${xhr.status}` }
                });
            };
            xhr.onerror = () => reject(new TypeError('Failed to fetch'));
            xhr.send(formData);
        });

    // Safari/모바일에서 fetch FormData 업로드가 실패하는 경우 XHR로 폴백
    const postFormData = async (url, formData) => {
        try {
            const response = await fetch(url, { method: 'POST', body: formData });
            const data = await parseJsonResponse(response);
            return { ok: response.ok, status: response.status, data };
        } catch (err) {
            const message = String(err && err.message ? err.message : '');
            if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {
                return await postFormDataViaXHR(url, formData);
            }
            throw err;
        }
    };

    // 수식 렌더링 (KaTeX)
    const renderMath = (rootElement) => {
        if (!rootElement || !window.renderMathInElement) return;
        try {
            window.renderMathInElement(rootElement, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false }
                ],
                throwOnError: false
            });
        } catch (e) { /* ignore */ }
    };

    const getFrameDocument = () => {
        if (!els.docFrame) return null;
        return els.docFrame.contentDocument;
    };

    const getFrameWindow = () => {
        if (!els.docFrame) return null;
        return els.docFrame.contentWindow;
    };

    const getDocRoot = () => {
        const doc = getFrameDocument();
        return doc ? doc.body : null;
    };

    const getFrameSelection = () => {
        const win = getFrameWindow();
        return win ? win.getSelection() : null;
    };

    const getTemplateBaseHref = () => {
        if (!state.templateId) return '/';
        const safeId = encodeURIComponent(state.templateId);
        return `/api/template/asset/${safeId}/`;
    };

    const serializeFrameHtml = () => {
        const doc = getFrameDocument();
        if (!doc) return state.templateHtml;
        const styles = Array.from(doc.head.querySelectorAll('style, link[rel="stylesheet"]'))
            .filter((style) => style.id !== 'hwp-editor-overlay')
            .map((style) => style.outerHTML)
            .join('\n');
        return `${styles}${doc.body.innerHTML}`;
    };

    const getAbsoluteTemplateBaseHref = () => {
        const relative = getTemplateBaseHref();
        if (!relative) return '';
        try {
            return new URL(relative, window.location.href).toString();
        } catch (e) {
            return relative;
        }
    };

    const getExportHtmlFromFrame = () => {
        const doc = getFrameDocument();
        if (!doc || !doc.body) return state.templateHtml;
        const clone = doc.body.cloneNode(true);
        clone.querySelectorAll('.selected-block, .edit-erase-span, .edit-erase-block, .doc-fill-flash')
            .forEach((el) => el.classList.remove('selected-block', 'edit-erase-span', 'edit-erase-block', 'doc-fill-flash'));
        return clone.innerHTML.trim();
    };

    const getExportHtmlDocument = () => {
        const doc = getFrameDocument();
        if (!doc) return state.templateHtml;
        const styles = Array.from(doc.head.querySelectorAll('style, link[rel="stylesheet"]'))
            .filter((style) => style.id !== 'hwp-editor-overlay')
            .map((style) => style.outerHTML)
            .join('\n');
        const body = getExportHtmlFromFrame();
        const baseHref = getAbsoluteTemplateBaseHref();
        const baseTag = baseHref ? `<base href="${baseHref}">` : '';
        return `<!DOCTYPE html><html><head><meta charset="utf-8">${baseTag}${styles}</head><body>${body}</body></html>`;
    };

    const syncTemplateHtmlFromFrame = () => {
        const html = serializeFrameHtml();
        state.templateHtml = html;
        state.frameHtml = html;
    };

    const getFrameScale = (doc = getFrameDocument()) => {
        if (!doc || !doc.body) return 1;
        const raw = parseFloat(doc.body.dataset.hwpScale || '1');
        return Number.isFinite(raw) && raw > 0 ? raw : 1;
    };

    const clearFrameScale = (doc) => {
        if (!doc || !doc.body) return;
        if (!doc.body.dataset.hwpScale) return;
        doc.body.style.transform = '';
        doc.body.style.transformOrigin = '';
        doc.body.style.width = '';
        delete doc.body.dataset.hwpScale;
    };

    const getFrameContentWidth = (doc) => {
        if (!doc) return 0;
        const candidate = doc.querySelector('.Section, .Paper, .hwp-doc');
        if (candidate) {
            const width = candidate.scrollWidth || candidate.getBoundingClientRect().width;
            if (width) return width;
        }
        return Math.max(
            doc.documentElement ? doc.documentElement.scrollWidth : 0,
            doc.body ? doc.body.scrollWidth : 0
        );
    };

    const applyFrameScale = () => {
        const doc = getFrameDocument();
        if (!doc || !doc.body || !els.docFrame) return;
        const isCompact = window.matchMedia
            ? window.matchMedia('(max-width: 768px)').matches
            : window.innerWidth <= 768;
        if (!isCompact) {
            clearFrameScale(doc);
            return;
        }

        const frameWidth = els.docFrame.clientWidth;
        if (!frameWidth) return;
        const contentWidth = getFrameContentWidth(doc);
        if (!contentWidth) return;

        const scale = Math.min(1, frameWidth / contentWidth);
        if (scale >= 0.98) {
            clearFrameScale(doc);
            return;
        }

        doc.body.dataset.hwpScale = String(scale);
        doc.body.style.transformOrigin = 'top left';
        doc.body.style.transform = `scale(${scale})`;
        doc.body.style.width = `${contentWidth}px`;
    };

    const syncFrameHeight = () => {
        if (!els.docFrame) return;
        const doc = getFrameDocument();
        if (!doc) return;
        let height = Math.max(
            doc.documentElement.scrollHeight,
            doc.body ? doc.body.scrollHeight : 0
        );
        const scale = getFrameScale(doc);
        if (scale !== 1) height = Math.ceil(height * scale);
        if (state.canvasOpen && els.canvasBody) {
            const canvasHeight = els.canvasBody.clientHeight;
            if (canvasHeight) height = Math.max(height, canvasHeight);
        }
        if (height) {
            els.docFrame.style.height = `${height}px`;
        }
    };

    const syncFrameLayout = () => {
        applyFrameScale();
        syncFrameHeight();
    };

    const getCanvasLayoutMetrics = () => {
        const isMobile = window.matchMedia
            ? window.matchMedia('(max-width: 768px)').matches
            : window.innerWidth <= 768;
        const mainContent = document.querySelector('.main-content');
        const mainRect = mainContent ? mainContent.getBoundingClientRect() : null;
        const viewportWidth = Math.max(
            window.innerWidth || 0,
            document.documentElement ? document.documentElement.clientWidth : 0
        );
        const mainWidth = mainRect ? Math.round(mainRect.width) : viewportWidth;
        const computedMax = (() => {
            if (!els.resultView) return 850;
            const maxWidth = window.getComputedStyle(els.resultView).maxWidth;
            const parsed = parseFloat(maxWidth);
            return Number.isFinite(parsed) ? parsed : 850;
        })();
        const minChat = 560;
        const targetRatio = 0.6;
        const gutter = mainWidth < 1100 ? 20 : 32;
        const minCanvas = Math.min(240, Math.round(mainWidth * 0.24));
        const maxCanvas = Math.min(viewportWidth * 0.52, 820, mainWidth);
        const maxChat = Math.min(computedMax, mainWidth);
        const minSideBySide = minChat + minCanvas + gutter;
        const overlayMode = isMobile || mainWidth < minSideBySide;

        return {
            isMobile,
            mainWidth,
            viewportWidth,
            computedMax,
            minChat,
            targetRatio,
            gutter,
            minCanvas,
            maxCanvas,
            maxChat,
            overlayMode
        };
    };

    const clampCanvasWidth = (width, metrics) => {
        const maxCanvasByChat = Math.max(
            metrics.minCanvas,
            metrics.mainWidth - metrics.minChat - metrics.gutter
        );
        const maxAllowed = Math.min(metrics.maxCanvas, maxCanvasByChat);
        return Math.max(metrics.minCanvas, Math.min(maxAllowed, width));
    };

    const loadCanvasUserWidth = () => {
        const raw = localStorage.getItem(CANVAS_WIDTH_STORAGE_KEY);
        const parsed = raw ? parseFloat(raw) : NaN;
        if (!Number.isFinite(parsed) || parsed <= 0) return null;
        return parsed;
    };

    const persistCanvasUserWidth = (width) => {
        if (!Number.isFinite(width) || width <= 0) return;
        localStorage.setItem(CANVAS_WIDTH_STORAGE_KEY, String(Math.round(width)));
    };

    const updateCanvasLayoutVars = () => {
        if (!document.body) return;
        const metrics = getCanvasLayoutMetrics();
        const {
            overlayMode,
            mainWidth,
            maxChat,
            minChat,
            targetRatio,
            gutter,
            minCanvas,
            maxCanvas
        } = metrics;
        let canvasWidth = maxCanvas;

        if (!overlayMode) {
            if (Number.isFinite(state.canvasUserWidth)) {
                canvasWidth = clampCanvasWidth(state.canvasUserWidth, metrics);
            } else {
                let desiredChatWidth = Math.min(
                    maxChat,
                    Math.max(minChat, Math.round(mainWidth * targetRatio))
                );
                desiredChatWidth = Math.min(desiredChatWidth, mainWidth - minCanvas - gutter);
                canvasWidth = mainWidth - desiredChatWidth - gutter;
                canvasWidth = Math.max(minCanvas, Math.min(maxCanvas, canvasWidth));
            }
        } else {
            canvasWidth = Math.min(maxCanvas, Math.max(minCanvas, Math.round(mainWidth * 0.6)));
        }

        if (!Number.isFinite(canvasWidth) || canvasWidth <= 0) {
            canvasWidth = Math.min(maxCanvas, mainWidth);
        }

        const reserveWidth = overlayMode ? 0 : canvasWidth;
        document.body.dataset.canvasMode = overlayMode ? 'overlay' : 'side';
        document.body.style.setProperty('--canvas-panel-width', `${Math.round(canvasWidth)}px`);
        document.body.style.setProperty('--canvas-reserve-width', `${Math.round(reserveWidth)}px`);
    };

    const startCanvasResize = (event) => {
        if (!els.canvasPanel || !state.canvasOpen) return;
        if (event.button !== undefined && event.button !== 0) return;
        const metrics = getCanvasLayoutMetrics();
        if (metrics.overlayMode) return;
        event.preventDefault();
        state.canvasResizing = true;
        state.canvasResizePointerId = typeof event.pointerId === 'number' ? event.pointerId : null;
        state.canvasResizeStartX = event.clientX;
        state.canvasResizeStartWidth = els.canvasPanel.getBoundingClientRect().width;
        document.body.classList.add('canvas-resizing');
        if (event.target && typeof event.target.setPointerCapture === 'function' && state.canvasResizePointerId !== null) {
            event.target.setPointerCapture(state.canvasResizePointerId);
        }
    };

    const updateCanvasResize = (event) => {
        if (!state.canvasResizing) return;
        if (state.canvasResizePointerId !== null && event.pointerId !== state.canvasResizePointerId) return;
        const metrics = getCanvasLayoutMetrics();
        if (metrics.overlayMode) return;
        const delta = state.canvasResizeStartX - event.clientX;
        const desiredWidth = state.canvasResizeStartWidth + delta;
        const clampedWidth = clampCanvasWidth(desiredWidth, metrics);
        if (!Number.isFinite(clampedWidth)) return;
        state.canvasUserWidth = clampedWidth;
        document.body.style.setProperty('--canvas-panel-width', `${Math.round(clampedWidth)}px`);
        document.body.style.setProperty('--canvas-reserve-width', `${Math.round(clampedWidth)}px`);
    };

    const endCanvasResize = (event) => {
        if (!state.canvasResizing) return;
        if (event && state.canvasResizePointerId !== null && event.pointerId !== state.canvasResizePointerId) return;
        state.canvasResizing = false;
        state.canvasResizePointerId = null;
        document.body.classList.remove('canvas-resizing');
        if (Number.isFinite(state.canvasUserWidth)) {
            persistCanvasUserWidth(state.canvasUserWidth);
        }
        updateCanvasLayoutVars();
    };

    const attachFrameListeners = () => {
        const doc = getFrameDocument();
        if (!doc || state.frameDocumentRef === doc) return;
        state.frameDocumentRef = doc;

        doc.addEventListener('mouseup', handleDocSelection);
        doc.addEventListener('keyup', handleDocSelection);
        doc.addEventListener('scroll', () => {
            dismissEditCover();
            clearSelectedSnippet();
        }, { passive: true });
        doc.addEventListener('mousedown', () => clearSelectedSnippet());
        doc.addEventListener('selectionchange', () => {
            if (state.selectionChangeTimer) {
                clearTimeout(state.selectionChangeTimer);
            }
            state.selectionChangeTimer = setTimeout(() => {
                state.selectionChangeTimer = null;
                handleDocSelection();
            }, 80);
        });

        if (state.frameResizeObserver) {
            state.frameResizeObserver.disconnect();
            state.frameResizeObserver = null;
        }
        if (window.ResizeObserver && doc.body) {
            state.frameResizeObserver = new ResizeObserver(() => syncFrameHeight());
            state.frameResizeObserver.observe(doc.body);
        }

        Array.from(doc.images || []).forEach((img) => {
            img.addEventListener('load', syncFrameHeight);
            img.addEventListener('error', syncFrameHeight);
        });
        syncFrameLayout();
    };

    const createCanvasMessageRow = (msg) => {
        const div = document.createElement('div');
        div.className = 'message-row canvas-row';

        const avatar = document.createElement('div');
        avatar.className = 'role-avatar ai';
        avatar.innerHTML = '<i class="bi bi-window"></i>';

        const content = document.createElement('div');
        content.className = 'message-content';

        const name = document.createElement('div');
        name.className = 'message-name';
        name.textContent = 'Canvas';

        const card = document.createElement('div');
        card.className = 'canvas-message-card';
        card.dataset.action = 'open-canvas';
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');

        const kicker = document.createElement('div');
        kicker.className = 'canvas-card-kicker';
        kicker.textContent = 'Canvas Snapshot';

        const title = document.createElement('div');
        title.className = 'canvas-card-title';
        title.textContent = msg.title || '문서';

        const summary = document.createElement('div');
        summary.className = 'canvas-card-summary';
        summary.textContent = msg.summary || '내용 미리보기 없음';

        const cta = document.createElement('div');
        cta.className = 'canvas-card-cta';
        cta.textContent = '클릭하여 Canvas 열기';

        card.append(kicker, title, summary, cta);
        content.append(name, card);
        div.append(avatar, content);
        return div;
    };

    const createVerificationRow = (msg) => {
        const div = document.createElement('div');
        div.className = 'message-row';

        const avatar = document.createElement('div');
        avatar.className = 'role-avatar ai';
        avatar.innerHTML = '<i class="bi bi-stars"></i>';

        const content = document.createElement('div');
        content.className = 'message-content';

        const name = document.createElement('div');
        name.className = 'message-name';
        name.textContent = 'AI Agent';

        const card = document.createElement('div');
        card.className = 'verification-card';

        const title = document.createElement('div');
        title.className = 'verification-title';
        const count = Array.isArray(msg.fields) ? msg.fields.length : 0;
        title.textContent = `학생 작성 항목 확인 (${count}개)`;

        const list = document.createElement('ul');
        list.className = 'verification-list';
        if (Array.isArray(msg.fields)) {
            msg.fields.forEach((field) => {
                const item = document.createElement('li');
                item.textContent = field;
                list.appendChild(item);
            });
        }

        const note = document.createElement('div');
        note.className = 'verification-note';
        note.textContent = '확인 후 기본 정보만 질문하고, 나머지는 AI가 자동 작성합니다. 제외/추가는 입력창에 "제외: ..." 또는 "추가: ..."로 입력하세요.';

        const actions = document.createElement('div');
        actions.className = 'verification-actions';

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'verification-btn primary';
        confirmBtn.dataset.action = 'verification-confirm';
        confirmBtn.textContent = '확인';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'verification-btn ghost';
        cancelBtn.dataset.action = 'verification-cancel';
        cancelBtn.textContent = '취소';

        actions.append(confirmBtn, cancelBtn);
        card.append(title, list, note, actions);
        content.append(name, card);
        div.append(avatar, content);
        return div;
    };

    // [New] 채팅 메시지 DOM 생성 헬퍼
    const createMessageRow = (roleOrMsg, text, isStreaming = false) => {
        const msg = typeof roleOrMsg === 'object' ? roleOrMsg : { role: roleOrMsg, text };
        if (msg.type === 'canvas') {
            return createCanvasMessageRow(msg);
        }
        if (msg.type === 'verification') {
            return createVerificationRow(msg);
        }
        const role = msg.role;
        const bodyText = msg.text || '';
        const isUser = role === 'user';
        const div = document.createElement('div');
        div.className = 'message-row';
        if (isStreaming) div.classList.add('streaming-row');
        
        const avatarHtml = isUser 
            ? '<div class="role-avatar user"><i class="bi bi-person"></i></div>' 
            : '<div class="role-avatar ai"><i class="bi bi-stars"></i></div>';
            
        const contentHtml = isStreaming && !bodyText 
            ? `<div class="message-content streaming">
                 <div class="message-name">AI Agent</div>
                 <div class="loading-bubble">
                   <div class="loading-line"></div>
                   <div class="loading-line short"></div>
                 </div>
               </div>`
            : `<div class="message-content">
                 <div class="message-name">${isUser ? 'You' : 'AI Agent'}</div>
                 <div class="markdown-body">${parseMarkdown(bodyText)}</div>
               </div>`;

        div.innerHTML = avatarHtml + contentHtml;
        return div;
    };

    const openCanvasOverlay = (force = false) => {
        if (!els.canvasOverlay || !els.canvasBody || !els.docPaper) return;
        if (state.canvasOpen) return;
        if (state.canvasDismissed && !force) return;

        if (!state.canvasRestoreParent) {
            state.canvasRestoreParent = els.docPaper.parentNode;
            state.canvasRestoreNext = els.docPaper.nextSibling;
        }

        els.canvasBody.appendChild(els.docPaper);
        els.docPaper.style.display = 'block';
        els.canvasOverlay.classList.remove('hidden');
        els.canvasOverlay.classList.add('active');
        document.body.classList.add('canvas-open');
        state.canvasOpen = true;
        state.canvasDismissed = false;
        updateCanvasLayoutVars();
        requestAnimationFrame(() => syncFrameLayout());
    };

    const closeCanvasOverlay = (dismiss = false) => {
        if (!els.canvasOverlay || !els.docPaper) return;
        endCanvasResize();
        if (state.canvasOpen) {
            if (state.canvasRestoreParent) {
                state.canvasRestoreParent.insertBefore(els.docPaper, state.canvasRestoreNext);
            }
            els.canvasOverlay.classList.remove('active');
            els.canvasOverlay.classList.add('hidden');
            document.body.classList.remove('canvas-open');
            state.canvasOpen = false;
            updateCanvasLayoutVars();
        }

        if (dismiss) {
            state.canvasDismissed = true;
            if (els.docPaper) els.docPaper.style.display = 'none';
            if (els.docFrame) els.docFrame.classList.add('hidden');
            if (els.docContent) els.docContent.classList.add('hidden');
        }
        state.editCoverLocked = false;
        hideEditCover();
        clearSelectedSnippet();
    };

    const updateUI = () => {
        try {
            // [View Toggle] 콘텐츠가 있으면 홈 화면 숨기고 결과 화면 표시
            const templateActive = !!state.templateName || !!state.templateFilePath || !!state.templateHtml;
            if (templateActive) state.docMode = true;
            if (els.scrollContainer) els.scrollContainer.classList.toggle('template-mode', templateActive);
            if (els.resultView) els.resultView.classList.toggle('template-mode', templateActive);
            if (els.docPaper) els.docPaper.classList.toggle('template-mode', templateActive);
            updateTemplateControls();

            const hasContent = state.chatHistory.length > 0 || state.isGenerating || state.docMode;
            if (els.homeView) els.homeView.style.display = hasContent ? 'none' : 'block';
            if (els.resultView) els.resultView.style.display = hasContent ? 'flex' : 'none';

            // Document Title Update
            if (els.docTitle) {
                els.docTitle.textContent = state.templateName || state.document.title || '새 문서';
            }

            if (templateActive) {
                openCanvasOverlay();
            } else {
                state.canvasDismissed = false;
                closeCanvasOverlay(false);
            }

            const hideDoc = templateActive && state.canvasDismissed && !state.canvasOpen;
            if (state.docMode) {
                if (els.chatStream) els.chatStream.style.display = 'flex'; // Chat visible
                if (els.docPaper) {
                    els.docPaper.style.display = hideDoc ? 'none' : 'block';
                    els.docPaper.classList.add('active');
                }
                
                if (templateActive) {
                    if (els.docFrame) els.docFrame.classList.toggle('hidden', hideDoc);
                    if (els.docContent) els.docContent.classList.add('hidden');
                    if (state.templateHtml && state.templateHtml !== state.frameHtml) {
                        renderTemplateFrame(state.templateHtml);
                    }
                } else {
                    if (els.docFrame) els.docFrame.classList.add('hidden');
                    if (els.docContent) {
                        els.docContent.classList.remove('hidden');
                        if (!state.isGenerating && !state.document.content) {
                            // Clear content if no template and not generating
                            els.docContent.innerHTML = '';
                        }
                    }
                }

            } else { // No template HTML loaded, default chat behavior
                if (els.docPaper) els.docPaper.style.display = 'none';
                if (els.chatStream) els.chatStream.style.display = 'flex';
                if (els.docFrame) els.docFrame.classList.add('hidden');
            }
            
            // Handle chat stream updates (always visible in the original UI)
            const container = els.chatStream;
            const historyCount = state.chatHistory.length;
            
            // 1. 기존 메시지 동기화 (이미 그려진 것은 건너뜀)
            const renderedRows = container.querySelectorAll('.message-row:not(.streaming-row)');
            
            for (let i = renderedRows.length; i < historyCount; i++) {
                const msg = state.chatHistory[i];
                const row = createMessageRow(msg);
                const streamingRow = container.querySelector('.streaming-row');
                if (streamingRow) {
                    container.insertBefore(row, streamingRow);
                } else {
                    container.appendChild(row);
                }
                renderMath(row);
            }

            // 2. 스트리밍 메시지 처리 (Typewriter effect)
            let streamingRow = container.querySelector('.streaming-row');
            
            if (state.isGenerating || state.streamingBuffer) {
                if (!streamingRow) {
                    streamingRow = createMessageRow('ai', '', true); // 로딩 상태로 생성
                    container.appendChild(streamingRow);
                    scrollToBottom();
                }
                
                // Typewriter effect for chat mode
                if (state.streamingBuffer.length > state.displayedChatContent.length) {
                    if (!state.chatTypingTimeoutId) {
                        state.chatTypingTimeoutId = setTimeout(() => {
                            const charsToAdd = Math.min(5, state.streamingBuffer.length - state.displayedChatContent.length); // Adjust typing speed
                            state.displayedChatContent += state.streamingBuffer.substring(state.displayedChatContent.length, state.displayedChatContent.length + charsToAdd);
                            
                            const contentDiv = streamingRow.querySelector('.message-content');
                            if (contentDiv.classList.contains('streaming')) {
                                contentDiv.classList.remove('streaming');
                                contentDiv.innerHTML = `<div class="message-name">AI Agent</div><div class="markdown-body"></div>`;
                            }
                            const body = contentDiv.querySelector('.markdown-body');
                            if (body) {
                                body.innerHTML = parseMarkdown(state.displayedChatContent);
                                renderMath(body);
                            }
                            scrollToBottom();
                            state.chatTypingTimeoutId = null; // Reset to allow next frame to trigger
                            if (state.isGenerating || state.displayedChatContent.length < state.streamingBuffer.length) {
                                requestAnimationFrame(updateUI); // Continue updating if more content or still generating
                            }
                        }, 50); // Typing speed
                    }
                } else if (!state.isGenerating && state.displayedChatContent.length === state.streamingBuffer.length && state.streamingBuffer) {
                    // Stream finished, ensure final parse for chat mode
                    const contentDiv = streamingRow.querySelector('.message-content');
                    if (contentDiv.classList.contains('streaming')) {
                        contentDiv.classList.remove('streaming');
                        contentDiv.innerHTML = `<div class="message-name">AI Agent</div><div class="markdown-body"></div>`;
                    }
                    const body = contentDiv.querySelector('.markdown-body');
                    if (body) {
                        body.innerHTML = parseMarkdown(state.streamingBuffer);
                        renderMath(body);
                    }
                    scrollToBottom();
                }
            } else {
                // 스트리밍 종료
                if (streamingRow) {
                    streamingRow.remove();
                }
            }
        } catch (e) {
            console.error('[UpdateUI Error]', e);
            if (els.chatStream) {
                 els.chatStream.innerHTML += `<div style="color:red; padding:10px;">UI Rendering Error: ${e.message}</div>`;
            }
        }
    };

    const scrollToBottom = () => {
        if (els.scrollContainer) {
            els.scrollContainer.scrollTo({ top: els.scrollContainer.scrollHeight, behavior: 'smooth' });
        }
    };

    const clearChatStream = () => {
        if (!els.chatStream) return;
        els.chatStream.innerHTML = '';
    };

    // ============================================================
    // 2. 핵심 로직: 데이터 통신 (Streaming)
    // ============================================================

    const handleGenerate = async () => {
        const prompt = els.userRequest.value.trim();
        if (!prompt || state.isGenerating) return;
        hideInlineEditBubble();

        if (state.fillVerificationPending) {
            if (state.fillIntakeBusy) return;
            state.fillIntakeBusy = true;
            state.chatHistory.push({ role: 'user', text: prompt });
            try {
                await saveChatSession();

                els.userRequest.value = '';
                els.userRequest.style.height = 'auto';

                const response = handleFillVerificationResponse(prompt);
                if (!response.handled) {
                    state.fillIntakeBusy = false;
                    return;
                }

                if (!response.proceed) {
                    updateUI();
                    scrollToBottom();
                    await saveChatSession();
                    return;
                }

                state.fillVerificationPending = false;
                const analysis = state.templateAnalysis
                    ? { ...state.templateAnalysis, fields: state.fillDetectedFields }
                    : { fields: state.fillDetectedFields, sections: [] };
                const started = await startTemplateFillIntake(analysis);
                if (!started) {
                    updateUI();
                    scrollToBottom();
                    await saveChatSession();
                    return;
                }

                if (response.treatAsAnswer) {
                    const shouldRunFill = advanceFillIntake(prompt);
                    updateUI();
                    scrollToBottom();
                    await saveChatSession();

                    if (!shouldRunFill) return;

                    const fillPrompt = buildFillPromptFromAnswers(state.fillAnswers, state.fillRemainingFields);
                    state.templateMode = 'fill';
                    state.isGenerating = true;
                    setLoadingState(true);
                    updateUI();
                    try {
                        await runTemplateFillSequence(fillPrompt);
                    } catch (error) {
                        console.error(error);
                        showToast(`생성 중 오류 발생: ${error.message}`, 'error');
                        state.chatHistory.push({ role: 'ai', text: `템플릿 처리 중 오류 발생: ${error.message}` });
                    } finally {
                        state.isGenerating = false;
                        setLoadingState(false);
                        state.fillAnswers = {};
                        state.fillRemainingFields = [];
                        state.fillEssentialFields = [];
                        updateUI();
                        await saveChatSession();
                    }
                    return;
                }

                updateUI();
                scrollToBottom();
                await saveChatSession();
                return;
            } finally {
                state.fillIntakeBusy = false;
            }
        }

        if (state.fillSessionActive) {
            if (state.fillIntakeBusy) return;
            state.fillIntakeBusy = true;
            state.chatHistory.push({ role: 'user', text: prompt });
            try {
                await saveChatSession();

                els.userRequest.value = '';
                els.userRequest.style.height = 'auto';

                const shouldRunFill = advanceFillIntake(prompt);
                updateUI();
                scrollToBottom();
                await saveChatSession();

                if (!shouldRunFill) return;

                const fillPrompt = buildFillPromptFromAnswers(state.fillAnswers, state.fillRemainingFields);
                state.templateMode = 'fill';
                state.isGenerating = true;
                setLoadingState(true);
                updateUI();
                try {
                    await runTemplateFillSequence(fillPrompt);
                } catch (error) {
                    console.error(error);
                    showToast(`생성 중 오류 발생: ${error.message}`, 'error');
                    state.chatHistory.push({ role: 'ai', text: `템플릿 처리 중 오류 발생: ${error.message}` });
                } finally {
                    state.isGenerating = false;
                    setLoadingState(false);
                    state.fillAnswers = {};
                    state.fillRemainingFields = [];
                    state.fillEssentialFields = [];
                    updateUI();
                    await saveChatSession();
                }
                return;
            } finally {
                state.fillIntakeBusy = false;
            }
        }

        // 1. 초기화 및 UI 준비
        state.isGenerating = true;
        state.streamingBuffer = ''; // 버퍼 초기화
        state.document = { title: '', content: '' }; // 문서 내용 초기화 (only for old doc generation, not for template html) 
        
        // Reset typewriter state
        state.displayedChatContent = '';
        if (state.chatTypingTimeoutId) clearTimeout(state.chatTypingTimeoutId);
        state.chatTypingTimeoutId = null;
        state.displayedDocContent = '';
        if (state.docTypingTimeoutId) clearTimeout(state.docTypingTimeoutId);
        state.docTypingTimeoutId = null;
        
        // 사용자의 입력은 항상 채팅 기록에 남김 (문서 모드여도 로그 역할)
        state.chatHistory.push({ role: 'user', text: prompt });
        
        // [New] Create/Update session immediately to show in sidebar
        await saveChatSession();

        els.userRequest.value = ''; // 입력창 비우기
        els.userRequest.style.height = 'auto'; // 높이 리셋
        setLoadingState(true); // 버튼 로딩
        updateUI(); // 로딩 UI 표시 (이 시점에서는 아직 모드 변경/문서 초기화 안 함) 

        const templateActive = !!state.templateName || !!state.templateFilePath || !!state.templateHtml;
        const hasEditSelection = !!state.selectedSnippet
            || !!state.selectedSectionTitle
            || !!state.selectedBlock
            || (state.selectedBlocks && state.selectedBlocks.length > 0);
        if (!(templateActive && hasEditSelection)) {
            scrollToBottom(); // Always scroll down after user input
        }
        if (templateActive) {
            try {
                if (!state.templateMode) {
                    state.templateMode = 'edit';
                }
                if (state.templateMode === 'fill') {
                    await runTemplateFillSequence(prompt);
                } else {
                    await runTemplateEdit(prompt);
                }
            } catch (error) {
                console.error(error);
                showToast(`생성 중 오류 발생: ${error.message}`, 'error');
                state.chatHistory.push({ role: 'ai', text: `템플릿 처리 중 오류 발생: ${error.message}` });
            } finally {
                state.isGenerating = false;
                setLoadingState(false);

                if (state.chatTypingTimeoutId) clearTimeout(state.chatTypingTimeoutId);
                state.chatTypingTimeoutId = null;
                if (state.docTypingTimeoutId) clearTimeout(state.docTypingTimeoutId);
                state.docTypingTimeoutId = null;

                updateUI();
                await saveChatSession();
            }
            return;
        }

        try {
            let endpoint = API_ENDPOINTS.AUTO; // Default to auto intent classification
            
            if (DEBUG_MODE) console.log(`[Request] ${endpoint} -> ${prompt}`);

            const previousHistory = state.chatHistory.slice(0, -1);
            const requestBody = JSON.stringify({
                request: prompt,
                template: state.templateHtml || '',
                history: previousHistory
            });

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: requestBody
            });

            if (!response.ok) throw new Error(`Server Error: ${response.status}`);
            if (!response.body) throw new Error('ReadableStream not supported');

            // 2. 스트림 읽기 (Robust Parsing)
            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            let hasDocumentModeChanged = false; // Flag to track if mode changed during stream

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                buffer += chunk;

                // SSE 데이터 파싱
                const lines = buffer.split(/\r?\n/);
                buffer = lines.pop(); 

                for (const line of lines) {
                    const cleanLine = line.trim();
                    if (!cleanLine.startsWith('data:')) continue;

                    let data;
                    try {
                        const jsonStr = cleanLine.substring(5).trim();
                        if (!jsonStr) continue;
                        
                        data = JSON.parse(jsonStr);
                    } catch (e) {
                        if (DEBUG_MODE) console.error('Stream Parse Error:', e, cleanLine);
                        continue; // Skip malformed lines
                    }

                    // Handle /api/edit-html responses
                    if (data.type === 'mode') {
                        // 서버의 의도 파악 결과에 따라 모드 전환
                        if (data.mode === 'document') {
                            // If docMode is set by intent, it means we are generating NEW content, not editing existing.
                            state.docMode = true; 
                            hasDocumentModeChanged = true;
                            console.log('[Auto Mode] Switched to Document Mode');
                        } else if (data.mode === 'chat') {
                            state.docMode = false;
                            hasDocumentModeChanged = true;
                            console.log('[Auto Mode] Switched to Chat Mode');
                        }
                        updateUI(); // 모드 변경 반영
                    }
                    else if (data.chunk || (data.type === 'token' && data.content)) {
                        const content = data.chunk || data.content;
                        
                        // 모드에 따라 데이터 저장 위치 분기
                        if (state.docMode && !state.templateHtml) { // If docMode and no existing template (generating new doc)
                            state.document.content += content;
                        } else { // Chat mode or editing a template via chat messages
                            state.streamingBuffer += content;
                        }
                        
                        requestAnimationFrame(updateUI); // Only chat part needs typewriter, docContent will be full replacement
                    } 
                    else if (data.type === 'image_keyword') {
                        state.generatedImageKeyword = data.keyword;
                        console.log('Image Generation Triggered:', data.keyword);
                    } else if (data.type === 'error') {
                        console.error('Stream Error:', data.message);
                        state.streamingBuffer += `\n\n[Error: ${data.message}]`;
                        requestAnimationFrame(updateUI);
                    }
                }
            }

            // 3. 완료 처리
            if (state.docMode && !state.templateHtml) { // Original doc generation mode
                if (state.document.content) {
                    const parsed = _parseGeneratedContent(state.document.content); // Helper function from original logic
                    state.document.title = parsed.title;
                    state.document.content = parsed.body;
                    state.imagesNeeded = parsed.images_needed;
                    
                    els.docTitle.textContent = state.document.title;
                    els.docContent.innerHTML = parseMarkdown(state.document.content);
                    renderMath(els.docContent);
                    state.chatHistory.push({ role: 'ai', text: `새로운 문서가 생성되었습니다.` });
                }
            } else if (state.streamingBuffer) { // Original chat mode
                state.chatHistory.push({ role: 'ai', text: state.streamingBuffer });
                state.streamingBuffer = '';
            }

        } catch (error) {
            console.error(error);
            
            const isQuotaError = error.message.includes('Quota Exceeded') || error.message.includes('한도 초과');
            
            if (!isQuotaError) {
                showToast('생성 중 오류 발생: ' + error.message, 'error');
            }

            const errorHtml = `<div style="color: #EF4444; font-weight: 600; font-size: 0.9rem; padding: 8px 10px; background: rgba(254, 226, 226, 0.5); border: 1px solid #FECACA; border-radius: 8px; margin-top: 8px;">
                <i class="bi bi-exclamation-triangle-fill" style="margin-right: 6px;"></i>
                ${error.message}
            </div>`;

            if (state.docMode && !state.templateHtml) { // Original doc generation
                state.document.content += `\n\n${errorHtml}`;
            } else { // Original chat mode
                state.chatHistory.push({ role: 'ai', text: errorHtml });
            }
        } finally {
            state.isGenerating = false;
            setLoadingState(false);
            
            if (state.chatTypingTimeoutId) clearTimeout(state.chatTypingTimeoutId);
            state.chatTypingTimeoutId = null;
            if (state.docTypingTimeoutId) clearTimeout(state.docTypingTimeoutId);
            state.docTypingTimeoutId = null;

            updateUI(); // Final UI update
            
            // If we generated a new document, resolve images.
            // For HTML editing, images would already be in the HTML.
            if (state.docMode && !state.templateHtml) resolveImages();
            
            await saveChatSession();
        }
    };

    // Placeholder for _parseGeneratedContent from previous docgen logic
    function _parseGeneratedContent(content) {
        const gen_img_pattern = /.*\[gen_img\].*?(.*?).*\[\/gen_img\].*/g;
        const image_keywords = [];
        let match;
        while ((match = gen_img_pattern.exec(content)) !== null) {
            image_keywords.push(match[1]);
        }
        
        let title = '';
        let body = content;

        const lines = content.split('\n');
        for (const line of lines) {
            const stripped = line.trim();
            const title_match = stripped.match(/^(?:.*제목\s*:\s*)(.*)/);
            if (title_match) {
                title = title_match[1].replace(/(\*\*|__)/g, '');
                body = content.substring(content.indexOf(line) + line.length).trim();
                break;
            }
        }

        if (!title && lines.length > 0) {
            title = lines[0].replace(/#+\s*/g, '').trim().substring(0, 50);
        }
        if (!body) {
            body = content;
        }

        return {
            title: title || '새 문서',
            body: body,
            images_needed: image_keywords,
            tables_needed: [] // Not implemented for simple markdown
        };
    }

    // ============================================================
    // 2.5. Download Logic
    // ============================================================

    const getSelectedDownloadFormat = () => {
        const inputs = document.querySelectorAll('input[name="downloadFormat"]');
        for (const input of inputs) {
            if (input.checked) return input.value;
        }
        return 'hwp';
    };

    const setSelectedDownloadFormat = (value) => {
        const inputs = document.querySelectorAll('input[name="downloadFormat"]');
        let matched = false;
        inputs.forEach((input) => {
            const isMatch = input.value === value;
            input.checked = isMatch;
            if (isMatch) matched = true;
        });
        if (!matched && inputs.length) {
            inputs[0].checked = true;
        }
    };

    const openDownloadModal = (defaultFormat = 'hwp') => {
        if (!els.modalDownload) return;
        setSelectedDownloadFormat(defaultFormat);
        els.modalDownload.style.display = 'flex';
        setTimeout(() => els.modalDownload.classList.add('show'), 10);
    };

    const closeDownloadModal = () => {
        if (!els.modalDownload) return;
        els.modalDownload.classList.remove('show');
        setTimeout(() => {
            if (els.modalDownload) els.modalDownload.style.display = 'none';
        }, 200);
    };

    const performDownload = async (formatOverride) => {
        const isTemplateDoc = !!state.templateName || !!state.templateHtml;
        if (isTemplateDoc && getFrameDocument()) {
            syncTemplateHtmlFromFrame();
        }
        const content = isTemplateDoc ? getExportHtmlDocument() : state.document.content;
        const title = isTemplateDoc ? (state.templateName || '문서') : (state.document.title || '새 문서');
        const format = formatOverride || (isTemplateDoc ? 'pdf' : 'hwp');

        if (!content) {
            showToast('저장할 문서 내용이 없습니다.', 'error');
            return;
        }

        const btnSide = document.getElementById('btnDownloadSide');
        const btnMobile = document.getElementById('btnDownloadMobile');

        const originalSideText = btnSide ? btnSide.innerHTML : '';
        if (btnSide) btnSide.innerHTML = '<div class="spinner"></div> 저장 중...';
        if (btnMobile) btnMobile.style.opacity = '0.5';

        try {
            const payload = {
                title: title,
                content: content,
                format: format,
                content_type: isTemplateDoc ? 'html' : 'text'
            };

            if (!isTemplateDoc) {
                payload.images_needed = state.imagesNeeded || [];
                payload.image_urls = collectRenderedImages();
            }

            const response = await fetch('/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (data.success) {
                showToast('파일이 생성되었습니다. 다운로드를 시작합니다.', 'success');
                const filename = data.file_path.split('/').pop(); 
                window.location.href = `/api/download/${encodeURIComponent(filename)}`;
            } else {
                throw new Error(data.error || '저장 실패');
            }

        } catch (e) {
            console.error(e);
            showToast(`저장 중 오류가 발생했습니다: ${e.message}`, 'error');
        } finally {
            if (btnSide) btnSide.innerHTML = originalSideText || '<i class="bi bi-download"></i> 문서 저장';
            if (btnMobile) btnMobile.style.opacity = '1';
        }
    };

    const handleDownload = async () => {
        const isTemplateDoc = !!state.templateName || !!state.templateHtml;
        if (isTemplateDoc) {
            if (els.modalDownload) {
                openDownloadModal('hwp');
                return;
            }
            await performDownload('hwp');
            return;
        }
        await performDownload('hwp');
    };

    // 화면에 렌더링된 이미지 정보 수집 (선택적)
    const collectRenderedImages = () => {
        const images = [];
        if (!els.docContent) return images;
        
        // 1. 로드된 이미지들
        els.docContent.querySelectorAll('.img-placeholder-box.loaded img').forEach(img => {
            const container = img.closest('.img-placeholder-box');
            const keyword = container ? container.dataset.keyword : 'image';
            images.push({
                keyword: keyword,
                url: img.src
            });
        });
        return images;
    };

    // ============================================================
    // 2.6. File Upload Logic
    // ============================================================

    // ============================================================
    // 2.6. File Upload Logic
    // ============================================================
    
    // Helper to manage analysis badge state
    const updateAnalysisBadge = (show, type = 'loading', message = '문서 분석 중...') => {
        const overlay = document.getElementById('analysisOverlay');
        if (!overlay) return;

        const typingIndicator = overlay.querySelector('.typing-indicator');
        const statusIconContainer = overlay.querySelector('.status-icon-container'); // Get new container
        const statusText = overlay.querySelector('.status-text');

        // Reset state classes
        overlay.classList.remove('analysis-success', 'analysis-error');
        statusIconContainer.innerHTML = ''; // Clear icon container

        if (show) {
            overlay.classList.remove('hidden');
            statusText.textContent = message;

            if (type === 'loading') {
                typingIndicator.style.display = 'flex';
                statusIconContainer.style.display = 'none';
            } else if (type === 'success') {
                overlay.classList.add('analysis-success');
                typingIndicator.style.display = 'none';
                statusIconContainer.innerHTML = '<i class="bi bi-check-circle-fill"></i>';
                statusIconContainer.style.display = 'block';
            } else if (type === 'error') {
                overlay.classList.add('analysis-error');
                typingIndicator.style.display = 'none';
                statusIconContainer.innerHTML = '<i class="bi bi-x-circle-fill"></i>';
                statusIconContainer.style.display = 'block';
            }
        } else {
            overlay.classList.add('hidden');
            // Reset to loading state for next time it appears
            typingIndicator.style.display = 'flex';
            statusIconContainer.style.display = 'none';
            statusIconContainer.innerHTML = ''; 
            statusText.textContent = '문서 분석 중...';
        }
    };

    const handleFileUpload = async (file) => {
        if (!file) return;

        resetChatSession({ clearTemplate: true });

        // Show analysis badge with loading state
        updateAnalysisBadge(true, 'loading', '문서 분석 중...');

        const formData = new FormData();
        const isHwp = file.name.toLowerCase().endsWith('.hwp') || file.name.toLowerCase().endsWith('.hwpx');
        const endpoint = isHwp ? API_ENDPOINTS.HWP_UPLOAD : API_ENDPOINTS.TEMPLATE;

        if (isHwp) {
            formData.append('file', file);
            try {
                const { data } = await postFormData(endpoint, formData);
                const payload = data || {};

                if (payload.success) {
                    let v2Html = '<div style="display:flex; flex-direction:column; align-items:center; background:#f0f0f0; padding:20px; min-height:100vh; overflow-y:auto;">';
                    for (let i = 0; i < payload.pageCount; i++) {
                        v2Html += `<img src="${API_ENDPOINTS.HWP_RENDER.replace('{sessionId}', payload.sessionId).replace('{pageIndex}', i)}" style="width:100%; max-width:800px; margin-bottom:20px; box-shadow:0 2px 10px rgba(0,0,0,0.1); background:white; display:block;" />`;
                    }
                    v2Html += '</div>';

                    state.templateHtml = v2Html;
                    state.templateName = payload.fileName;
                    state.templateFilePath = '';
                    state.templateId = payload.sessionId;
                    state.templateSource = 'upload';
                    state.canvasDismissed = false;
                    state.docMode = true;
                    
                    renderTemplateFrame(state.templateHtml);
                    if (els.docTitle) {
                        els.docTitle.textContent = payload.fileName;
                    }

                    // UI 업데이트
                    updateFileBadge(true, payload.fileName);
                    updateAnalysisBadge(false); 
                    if (els.attachMenu) els.attachMenu.classList.remove('open');

                    state.chatHistory.push({ role: 'ai', text: `"${payload.fileName}" 템플릿을 불러왔습니다. 이제 문서에 대한 변경을 요청할 수 있습니다.` });
                    updateUI();
                    scrollToBottom();
                } else {
                    throw new Error(payload.error || '업로드 실패');
                }
            } catch (e) {
                console.error(e);
                showToast(`HWP 파일 업로드 실패: ${e.message}`, 'error');
                clearFileSelection();
                updateAnalysisBadge(true, 'error', `분석 실패: ${e.message}`);
                setTimeout(() => updateAnalysisBadge(false), 3000);
            }
        } else {
            formData.append('template', file);
            try {
                const { data } = await postFormData(endpoint, formData);
                const payload = data || {};

                if (payload.success) {
                    // NEW: Use template_html directly
                    state.templateHtml = payload.template_html || (payload.template_text ? parseMarkdown(payload.template_text) : '');
                    state.templateName = payload.template_name;
                    state.templateFilePath = payload.template_file;
                    state.templateId = payload.template_id || '';
                    state.templateSource = 'upload';
                    state.canvasDismissed = false;
                    state.docMode = true;
                    const analysis = applyTemplateAnalysis(state.templateHtml);
                    
                    renderTemplateFrame(state.templateHtml);
                    if (els.docTitle) {
                        els.docTitle.textContent = payload.template_name;
                    }

                    // UI 업데이트
                    updateFileBadge(true, payload.template_name);
                    
                    // 분석 완료 메시지 없이 바로 숨김 (요청 사항 반영)
                    updateAnalysisBadge(false); 
                    
                    // 메뉴 닫기
                    if (els.attachMenu) els.attachMenu.classList.remove('open');

                    // Add message to chat stream
                    const startedFill = analysis && analysis.mode === 'fill'
                        ? startTemplateFillVerification(analysis)
                        : false;
                    if (!startedFill) {
                        const modeMessage = analysis && analysis.mode === 'fill'
                            ? '양식을 채우기 위한 정보를 입력해주세요.'
                            : '이제 문서에 대한 변경을 요청할 수 있습니다.';
                        state.chatHistory.push({ role: 'ai', text: `"${payload.template_name}" 템플릿을 불러왔습니다. ${modeMessage}` });
                    }
                    updateUI();
                    scrollToBottom();
                } else {
                    throw new Error(payload.error || '업로드 실패');
                }
            } catch (e) {
                console.error(e);
                showToast(`파일 업로드 실패: ${e.message}`, 'error');
                clearFileSelection();
                // Show error on badge and hide after delay (Error message still needed)
                updateAnalysisBadge(true, 'error', `분석 실패: ${e.message}`);
                setTimeout(() => updateAnalysisBadge(false), 3000); // Hide after 3 seconds
            }
        }
    };

    const clearFileSelection = () => {
        // Clear template-related state
        state.templateHtml = '';
        state.templateName = '';
        state.templateFilePath = '';
        state.templateId = '';
        state.template = null; // Also clear old template state
        state.templateSource = null;
        state.templateMode = null;
        state.templateSections = [];
        state.templateSectionSignature = '';
        state.templateAnalysis = null;
        state.templateFillFields = [];
        state.fillSessionActive = false;
        state.fillIntakeBusy = false;
        state.fillEssentialFields = [];
        state.fillRemainingFields = [];
        state.fillVerificationPending = false;
        state.fillDetectedFields = [];
        state.fillQueue = [];
        state.fillActiveField = '';
        state.fillAnswers = {};
        state.selectedSnippet = '';
        state.selectedSectionTitle = '';
        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            state.selectedBlocks.forEach((block) => block.classList.remove('selected-block'));
        }
        state.selectedBlocks = [];
        if (state.selectedBlock) {
            state.selectedBlock.classList.remove('selected-block');
        }
        state.selectedBlock = null;
        state.selectedRange = null;
        hideEditCover();
        state.docMode = false;
        state.frameHtml = '';
        state.frameDocumentRef = null;
        if (state.frameResizeObserver) {
            state.frameResizeObserver.disconnect();
            state.frameResizeObserver = null;
        }
        state.canvasDismissed = false;
        closeCanvasOverlay(false);

        if (els.docContent) els.docContent.innerHTML = '';
        if (els.docFrame) {
            els.docFrame.srcdoc = '';
            els.docFrame.classList.add('hidden');
        }
        revokeFrameBlobUrl();
        if (els.docTitle) els.docTitle.textContent = '문서 제목';
        if (els.editTargetInput) els.editTargetInput.value = '';
        if (els.editTargetSelect) els.editTargetSelect.value = '';
        hideInlineEditBubble();
        updateSelectionPreview();
        if (els.sectionFillPanel) els.sectionFillPanel.classList.add('hidden');

        updateFileBadge(false);
        updateTemplateControls();
        const fileInput = document.getElementById('fileInput');
        if (fileInput) fileInput.value = ''; // Reset input
        updateUI();
    };

    const updateFileBadge = (show, name='') => {
        const badge = document.getElementById('fileBadge');
        const nameEl = document.getElementById('fileName');
        if (!badge || !nameEl) return;

        if (show) {
            nameEl.textContent = name;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
            nameEl.textContent = '';
        }
    };

    // ============================================================
    // 2.7. Template Catalog Logic
    // ============================================================

    const renderTemplateCatalog = (items) => {
        if (!els.templateList) return;
        els.templateList.innerHTML = '';

        if (!items || items.length === 0) {
            if (els.templateEmpty) els.templateEmpty.classList.remove('hidden');
            return;
        }
        if (els.templateEmpty) els.templateEmpty.classList.add('hidden');

        items.forEach((item) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'template-card';
            card.innerHTML = `
                <div class="template-card-header">
                    <div class="template-card-title">${item.name}</div>
                    <span class="template-badge ${item.type}">${item.type === 'preset' ? 'preset' : (item.extension || 'file')}</span>
                </div>
                <div class="template-card-desc">${item.type === 'preset' ? '기본 양식' : '로컬 파일 양식'}</div>
            `;
            card.addEventListener('click', () => selectTemplateFromCatalog(item));
            els.templateList.appendChild(card);
        });
    };

    const loadTemplateCatalog = async (force = false) => {
        if (state.templateCatalogLoaded && !force) return;
        try {
            const response = await fetch(API_ENDPOINTS.TEMPLATES);
            const data = await response.json();
            if (!data.success) throw new Error(data.error || '템플릿 목록 로드 실패');
            state.templateCatalog = data.templates || [];
            state.templateCatalogLoaded = true;
            renderTemplateCatalog(state.templateCatalog);
        } catch (e) {
            console.error(e);
            renderTemplateCatalog([]);
        }
    };

    const filterTemplateCatalog = (query) => {
        const keyword = (query || '').trim().toLowerCase();
        if (!keyword) {
            renderTemplateCatalog(state.templateCatalog);
            return;
        }
        const filtered = state.templateCatalog.filter((item) => {
            return (item.name || '').toLowerCase().includes(keyword);
        });
        renderTemplateCatalog(filtered);
    };

    const openTemplateModal = async () => {
        if (!els.modalTemplate) return;
        els.modalTemplate.classList.add('show');
        els.modalTemplate.style.display = 'flex';
        await loadTemplateCatalog();
        if (els.templateSearch) els.templateSearch.focus();
    };

    const closeTemplateModal = () => {
        if (!els.modalTemplate) return;
        els.modalTemplate.classList.remove('show');
        setTimeout(() => {
            if (els.modalTemplate) els.modalTemplate.style.display = 'none';
        }, 200);
    };

    const selectTemplateFromCatalog = async (item) => {
        if (!item) return;

        resetChatSession({ clearTemplate: true });

        updateAnalysisBadge(true, 'loading', '템플릿 불러오는 중...');

        try {
            const response = await fetch(API_ENDPOINTS.TEMPLATE_SELECT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    template_id: item.id,
                    template_type: item.type
                })
            });
            const data = await response.json();
            if (!data.success) throw new Error(data.error || '템플릿 로드 실패');

            const html = data.template_html
                || (data.template_markdown ? parseMarkdown(data.template_markdown) : '')
                || (data.template_text ? parseMarkdown(data.template_text) : '');

            state.templateHtml = html;
            state.templateName = data.template_name || item.name;
            state.templateFilePath = data.template_file || '';
            state.templateId = data.template_id || '';
            state.templateSource = data.template_type || item.type;
            state.canvasDismissed = false;
            state.docMode = true;
            const analysis = applyTemplateAnalysis(state.templateHtml);

            renderTemplateFrame(state.templateHtml);
            if (els.docTitle) els.docTitle.textContent = state.templateName || '문서';

            updateFileBadge(true, state.templateName);
            updateAnalysisBadge(false);
            closeTemplateModal();

                const startedFill = analysis && analysis.mode === 'fill'
                    ? startTemplateFillVerification(analysis)
                    : false;
            if (!startedFill) {
                const modeMessage = analysis && analysis.mode === 'fill'
                    ? '양식을 채우기 위한 정보를 입력해주세요.'
                    : '이제 문서에 대한 변경을 요청할 수 있습니다.';
                state.chatHistory.push({ role: 'ai', text: `"${state.templateName}" 템플릿을 불러왔습니다. ${modeMessage}` });
            }
            updateUI();
            scrollToBottom();
        } catch (e) {
            console.error(e);
            showToast(`템플릿 로드 실패: ${e.message}`, 'error');
            updateAnalysisBadge(true, 'error', `분석 실패: ${e.message}`);
            setTimeout(() => updateAnalysisBadge(false), 3000);
        }
    };

    // ============================================================
    // 2.8. Template Mode Logic (Fill vs Edit)
    // ============================================================

    const PLACEHOLDER_PATTERN = /(작성|입력|기입|선택|예시)(?=$|\s|[:：])|OO|○|□|■|△|▲|▽|▼|__+|\.{3,}|·{2,}|ㆍ{2,}|\[\s*\]|\(\s*\)/g;
    const ESSENTIAL_FIELD_KEYWORDS = [
        '학번',
        '이름',
        '성명',
        '학교',
        '학년',
        '반',
        '번호',
        '연락처',
        '전화',
        '이메일',
        '주소',
        '소속',
        '학과',
        '전공',
        '지도교사',
        '담당',
        '제출자',
        '작성자',
        '진로',
        '관심'
    ];
    const MAX_ESSENTIAL_FIELDS = 6;

    const extractSectionsFromDoc = (doc) => {
        if (!doc) return [];
        const unique = new Set();
        const results = [];
        const pushUnique = (text) => {
            const trimmed = (text || '').trim();
            if (!trimmed || unique.has(trimmed)) return;
            unique.add(trimmed);
            results.push(trimmed);
        };

        const headings = Array.from(doc.querySelectorAll('h1, h2, h3')).map((el) => el.textContent.trim());
        headings.forEach(pushUnique);

        if (results.length < 3) {
            const pattern = /^(?:\d+\.\s*|\d+\)\s*|[가-힣]\.\s*|제\s*\d+\s*장|[IVX]+\.\s*)/;
            const paragraphs = Array.from(doc.querySelectorAll('p')).map((el) => el.textContent.trim());
            paragraphs.forEach((text) => {
                if (pattern.test(text) && text.length <= 40) {
                    pushUnique(text);
                }
            });
        }

        return results.slice(0, 12);
    };

    const extractSectionsFromHtml = (html) => {
        if (!html) return [];
        try {
            const doc = new DOMParser().parseFromString(html, 'text/html');
            return extractSectionsFromDoc(doc);
        } catch (e) {
            return [];
        }
    };

    const sanitizeCellText = (value) => {
        return (value || '')
            .replace(PLACEHOLDER_PATTERN, '')
            .replace(/[·•ㆍ]+/g, ' ')
            .replace(/[_\.]{2,}/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    };

    const hasPlaceholderTokens = (value) => {
        const raw = value || '';
        PLACEHOLDER_PATTERN.lastIndex = 0;
        return PLACEHOLDER_PATTERN.test(raw);
    };

    const normalizeLabelText = (label) => {
        const raw = (label || '').replace(/\s+/g, ' ').trim();
        if (!raw) return '';
        const cleaned = raw
            .replace(/[:：]\s*$/, '')
            .replace(/[()\[\]]/g, '')
            .trim();
        if (!cleaned || cleaned.length > 60) return '';
        const placeholderRemoved = sanitizeCellText(cleaned);
        if (!placeholderRemoved) return '';
        return cleaned;
    };

    const normalizeFieldLabel = (label) => {
        return normalizeLabelText(label);
    };

    const getCellInfo = (cell) => {
        const raw = (cell.textContent || '').replace(/\s+/g, ' ').trim();
        const cleaned = sanitizeCellText(raw);
        const hasText = cleaned.length > 0;
        const hasPlaceholder = hasPlaceholderTokens(raw);
        const hasMedia = !!cell.querySelector('img, svg, canvas');
        const hasInput = !!cell.querySelector('input, textarea, select');
        const isEmpty = (!hasText || hasPlaceholder) && !hasMedia && !hasInput;
        return { raw, cleaned, hasText, hasPlaceholder, isEmpty };
    };

    const extractFieldPromptsFromDoc = (doc) => {
        const fields = [];
        const seen = new Set();
        let emptyCount = 0;
        let filledCount = 0;

        const pushField = (label) => {
            const cleaned = normalizeFieldLabel(label);
            if (!cleaned || seen.has(cleaned)) return;
            seen.add(cleaned);
            fields.push(cleaned);
        };

        Array.from(doc.querySelectorAll('table')).forEach((table) => {
            const columnLabels = [];
            const rows = Array.from(table.querySelectorAll('tr'));
            rows.forEach((row) => {
                const cells = Array.from(row.children).filter((el) => el.matches('td, th'));
                if (!cells.length) return;
                const infos = cells.map((cell) => getCellInfo(cell));
                const labelTexts = cells.map((cell) => normalizeLabelText(cell.textContent));
                const rowHasLabel = infos.some((info) => info.hasText || info.hasPlaceholder);
                if (!rowHasLabel) return;

                infos.forEach((info, i) => {
                    const labelText = labelTexts[i];
                    if (labelText && cells[i].tagName.toLowerCase() === 'th') {
                        columnLabels[i] = labelText;
                    }
                });

                const rowLabelIndex = labelTexts.findIndex((text, idx) => text && idx === 0);
                const rowLabel = rowLabelIndex === 0 ? labelTexts[0] : '';

                infos.forEach((info, i) => {
                    const cell = cells[i];
                    const labelText = labelTexts[i];
                    const isHeader = cell.tagName.toLowerCase() === 'th' && labelText;
                    const isLabelCell = isHeader || (i === 0 && labelText && cells.length > 1);
                    if (isLabelCell) return;

                    if (info.isEmpty) {
                        emptyCount += 1;
                        let label = '';
                        for (let j = i - 1; j >= 0; j -= 1) {
                            if (labelTexts[j]) {
                                label = labelTexts[j];
                                break;
                            }
                        }
                        if (!label && columnLabels[i]) {
                            label = columnLabels[i];
                        }
                        if (!label && rowLabel) {
                            label = rowLabel;
                        }
                        if (label) {
                            pushField(label);
                        }
                    } else if (info.hasText && !info.hasPlaceholder) {
                        filledCount += 1;
                    }
                });
            });
        });

        Array.from(doc.querySelectorAll('input, textarea, select')).forEach((el) => {
            const placeholder = (el.getAttribute('placeholder') || '').trim();
            if (placeholder) pushField(placeholder);
            emptyCount += 1;
        });

        Array.from(doc.querySelectorAll('p, li, div')).forEach((el) => {
            const raw = (el.textContent || '').replace(/\s+/g, ' ').trim();
            if (!raw || raw.length > 120) return;
            if (!hasPlaceholderTokens(raw)) return;
            const match = raw.match(/^\s*(.+?)\s*[:：]\s*(.+)$/);
            if (!match) return;
            const label = normalizeFieldLabel(match[1]);
            if (label) pushField(label);
        });

        return {
            fields,
            stats: {
                emptyCount,
                filledCount,
                totalCount: emptyCount + filledCount
            }
        };
    };

    const analyzeTemplateHtml = (html) => {
        const text = (html || '')
            .replace(/<style[\s\S]*?<\/style>/gi, ' ')
            .replace(/<[^>]+>/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();

        let doc = null;
        try {
            doc = new DOMParser().parseFromString(html || '', 'text/html');
        } catch (e) {
            doc = null;
        }

        const placeholders = text.match(PLACEHOLDER_PATTERN) || [];
        const placeholderChars = placeholders.reduce((sum, token) => sum + token.length, 0);
        const placeholderRatio = placeholderChars / Math.max(1, text.length);
        const sections = doc ? extractSectionsFromDoc(doc) : extractSectionsFromHtml(html);
        const fieldAnalysis = doc ? extractFieldPromptsFromDoc(doc) : { fields: [], stats: { emptyCount: 0, filledCount: 0, totalCount: 0 } };

        const isSparse = text.length < 450;
        const hasPlaceholderSignal = placeholders.length >= 2 || placeholderRatio > 0.04;
        const totalFields = fieldAnalysis.stats.totalCount;
        const emptyRatio = totalFields ? fieldAnalysis.stats.emptyCount / totalFields : 0;
        const hasFieldSignals = totalFields >= 3;
        const isMostlyEmpty = hasFieldSignals && (emptyRatio >= 0.45 || fieldAnalysis.stats.emptyCount >= 6);
        const isMostlyFilled = hasFieldSignals && emptyRatio <= 0.12 && fieldAnalysis.stats.filledCount >= 3;

        const isLikelyTemplate = hasPlaceholderSignal || isMostlyEmpty || (isSparse && placeholders.length > 0);
        const isLikelyFilled = (text.length > 1200 && placeholderRatio < 0.015) || isMostlyFilled;
        const mode = isLikelyFilled ? 'edit' : (isLikelyTemplate ? 'fill' : 'edit');

        return {
            mode,
            sections,
            fields: fieldAnalysis.fields,
            fieldStats: fieldAnalysis.stats
        };
    };

    const updateTemplateControls = () => {
        const templateActive = !!state.templateName || !!state.templateFilePath || !!state.templateHtml;

        if (els.editorToolbar) {
            els.editorToolbar.classList.toggle('hidden', !templateActive);
        }
        if (els.editTargetPanel) {
            els.editTargetPanel.classList.toggle('hidden', !(templateActive && state.templateMode === 'edit'));
        }
        if (!templateActive || state.templateMode !== 'edit') {
            hideInlineEditBubble();
        }
        if (els.templateNameBadge) {
            els.templateNameBadge.textContent = state.templateName || '템플릿';
        }
        if (els.editModeBadge) {
            els.editModeBadge.classList.toggle('hidden', !(templateActive && state.templateMode === 'edit'));
        }
        if (els.fillModeBadge) {
            els.fillModeBadge.classList.toggle('hidden', !(templateActive && state.templateMode === 'fill'));
        }
        if (els.clearSelectionBtn) {
            const hasSelection = !!state.selectedSnippet || !!state.selectedSectionTitle;
            els.clearSelectionBtn.classList.toggle('hidden', !hasSelection);
            els.clearSelectionBtn.disabled = !hasSelection;
        }
        updateSelectionPreview();

        if (els.sectionFillPanel && (!templateActive || state.templateMode !== 'fill')) {
            els.sectionFillPanel.classList.add('hidden');
        }
    };

    const renderEditTargetOptions = () => {
        if (!els.editTargetSelect) return;
        const currentValue = els.editTargetSelect.value;
        const sections = Array.isArray(state.templateSections) ? state.templateSections : [];

        els.editTargetSelect.innerHTML = '';
        const appendOption = (value, label) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            els.editTargetSelect.appendChild(option);
        };

        appendOption('', '선택한 텍스트');
        appendOption('__full__', '전체 문서');
        sections.forEach((section) => {
            const trimmed = (section || '').trim();
            if (trimmed) appendOption(trimmed, trimmed);
        });

        const preferredValue = state.selectedSectionTitle
            ? (state.selectedSectionTitle === '전체 문서' ? '__full__' : state.selectedSectionTitle)
            : currentValue;
        const hasPreferred = Array.from(els.editTargetSelect.options).some((option) => option.value === preferredValue);
        els.editTargetSelect.value = hasPreferred ? preferredValue : '';
    };

    const applyTemplateAnalysis = (html, overrideMode = null) => {
        if (!html) {
            state.templateMode = null;
            state.templateSections = [];
            state.templateSectionSignature = '';
            state.templateAnalysis = null;
            state.templateFillFields = [];
            state.fillSessionActive = false;
            state.fillIntakeBusy = false;
            state.fillEssentialFields = [];
            state.fillRemainingFields = [];
            state.fillVerificationPending = false;
            state.fillDetectedFields = [];
            state.fillQueue = [];
            state.fillActiveField = '';
            state.fillAnswers = {};
            updateTemplateControls();
            return;
        }

        const analysis = analyzeTemplateHtml(html);
        state.templateAnalysis = analysis;
        state.templateMode = overrideMode || analysis.mode;
        state.templateSections = analysis.sections;
        state.templateFillFields = analysis.fields || [];
        state.fillSessionActive = false;
        state.fillIntakeBusy = false;
        state.fillEssentialFields = [];
        state.fillRemainingFields = [];
        state.fillVerificationPending = false;
        state.fillDetectedFields = [];
        state.fillQueue = [];
        state.fillActiveField = '';
        state.fillAnswers = {};
        state.selectedSnippet = '';
        state.selectedSectionTitle = '';
        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            state.selectedBlocks.forEach((block) => block.classList.remove('selected-block'));
        }
        state.selectedBlocks = [];
        state.selectedRange = null;
        if (state.selectedBlock) {
            state.selectedBlock.classList.remove('selected-block');
        }
        state.selectedBlock = null;
        hideEditCover();
        updateSelectionPreview();
        if (els.sectionFillPanel) els.sectionFillPanel.classList.add('hidden');
        renderEditTargetOptions();
        updateTemplateControls();
        return analysis;
    };

    const splitFillFields = (analysis) => {
        const fields = Array.isArray(analysis?.fields) ? analysis.fields : [];
        const sections = Array.isArray(analysis?.sections) ? analysis.sections : [];
        const combined = fields.length > 0 ? fields : sections;
        if (combined.length === 0) {
            return { essential: [], remaining: [] };
        }
        const essential = [];
        const remaining = [];
        combined.forEach((field) => {
            const trimmed = (field || '').trim();
            if (!trimmed) return;
            const isEssential = ESSENTIAL_FIELD_KEYWORDS.some((keyword) => trimmed.includes(keyword));
            if (isEssential) {
                essential.push(trimmed);
            } else {
                remaining.push(trimmed);
            }
        });

        if (essential.length === 0) {
            const fallbackCount = Math.min(3, combined.length);
            const fallback = combined.slice(0, fallbackCount).map((item) => (item || '').trim()).filter(Boolean);
            return {
                essential: fallback,
                remaining: combined.slice(fallbackCount).map((item) => (item || '').trim()).filter(Boolean)
            };
        }

        if (essential.length > MAX_ESSENTIAL_FIELDS) {
            const trimmedEssential = essential.slice(0, MAX_ESSENTIAL_FIELDS);
            const overflow = essential.slice(MAX_ESSENTIAL_FIELDS);
            return {
                essential: trimmedEssential,
                remaining: remaining.concat(overflow)
            };
        }

        return { essential, remaining };
    };

    const startTemplateFillIntake = async (analysis) => {
        const { essential, remaining } = splitFillFields(analysis);
        if (essential.length === 0) return false;
        state.fillSessionActive = true;
        state.fillIntakeBusy = false;
        state.templateMode = 'fill';
        state.fillAnswers = {};
        state.fillEssentialFields = essential;
        state.fillRemainingFields = remaining;
        state.fillVerificationPending = false;
        if (!state.fillDetectedFields || state.fillDetectedFields.length === 0) {
            const fallback = Array.isArray(analysis?.fields) && analysis.fields.length > 0
                ? analysis.fields
                : (Array.isArray(analysis?.sections) ? analysis.sections : []);
            state.fillDetectedFields = fallback.map((item) => (item || '').trim()).filter(Boolean);
        }
        state.fillActiveField = essential[0];
        state.fillQueue = essential.slice(1);
        const guideMessage = await fetchFillGuideMessage({
            fields: state.fillDetectedFields,
            firstField: state.fillActiveField,
            total: state.fillDetectedFields.length || essential.length
        });
        state.chatHistory.push({
            role: 'ai',
            text: guideMessage
        });
        return true;
    };

    const buildFillPromptFromAnswers = (answers, remainingFields = []) => {
        const lines = Object.entries(answers).map(([key, value]) => `- ${key}: ${value}`);
        const remainingList = remainingFields.filter(Boolean);
        if (remainingList.length > 0) {
            lines.push(`- 위 정보를 바탕으로 나머지 항목(${remainingList.join(', ')})은 자연스럽게 추론해 작성하세요.`);
        } else {
            lines.push('- 위 정보를 바탕으로 남아 있는 모든 빈 항목을 자연스럽게 작성하세요.');
        }
        return `다음 정보를 반영해 양식을 완성하세요.\n${lines.join('\n')}`.trim();
    };

    async function fetchFillGuideMessage({ fields, firstField, total }) {
        const fallback = `업로드된 문서가 비어 있는 양식으로 감지되었습니다. 기본 정보만 먼저 알려주세요. (총 ${total}개)\n첫 번째: ${firstField}\n나머지 항목은 AI가 자동으로 작성합니다.`;
        const recentHistory = (state.chatHistory || [])
            .filter((msg) => msg && (msg.role === 'user' || msg.role === 'ai'))
            .filter((msg) => !msg.type && typeof msg.text === 'string' && msg.text.trim())
            .slice(-6)
            .map((msg) => ({ role: msg.role, text: msg.text }));
        try {
            const response = await fetch('/api/template/fill-guide', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fields,
                    first_field: firstField,
                    total,
                    history: recentHistory
                })
            });
            const data = await response.json();
            if (response.ok && data.success && data.message) {
                return data.message;
            }
        } catch (e) {
            console.error(e);
        }
        return fallback;
    }

    const normalizeFieldListInput = (raw) => {
        return (raw || '')
            .split(/[,，\n]/)
            .map((item) => item.trim())
            .filter(Boolean);
    };

    const startTemplateFillVerification = (analysis) => {
        const fields = Array.isArray(analysis?.fields) ? analysis.fields : [];
        const sections = Array.isArray(analysis?.sections) ? analysis.sections : [];
        const combined = fields.length > 0 ? fields : sections;
        if (combined.length === 0) return false;
        state.fillVerificationPending = true;
        const seen = new Set();
        state.fillDetectedFields = combined
            .map((item) => (item || '').trim())
            .filter((item) => {
                if (!item || seen.has(item)) return false;
                seen.add(item);
                return true;
            });
        state.templateMode = 'fill';
        state.chatHistory.push({
            role: 'ai',
            type: 'verification',
            fields: state.fillDetectedFields
        });
        return true;
    };

    const handleFillVerificationResponse = (response) => {
        const raw = (response || '').trim();
        const lower = raw.toLowerCase();
        if (!raw) return { handled: false };

        const isConfirm = /^(확인|시작|네|응|ok|okay|yes)$/i.test(raw);
        const isCancel = /^(취소|중단|그만|아니|아니오|no)$/i.test(raw);

        if (isCancel) {
            state.fillVerificationPending = false;
            state.fillDetectedFields = [];
            state.templateMode = 'edit';
            state.chatHistory.push({ role: 'ai', text: '작성 검증을 취소했습니다. 필요한 수정 사항을 직접 요청해 주세요.' });
            return { handled: true, proceed: false };
        }

        if (lower.startsWith('제외:')) {
            const items = normalizeFieldListInput(raw.replace(/^제외:/i, ''));
            if (items.length === 0) {
                state.chatHistory.push({ role: 'ai', text: '제외할 항목을 알려주세요. 예: 제외: 이름, 학번' });
                return { handled: true, proceed: false };
            }
            state.fillDetectedFields = state.fillDetectedFields.filter((item) => !items.some((remove) => item.includes(remove)));
            if (state.fillDetectedFields.length === 0) {
                state.chatHistory.push({
                    role: 'ai',
                    text: '모든 항목이 제외되었습니다. 추가할 항목이 있으면 "추가: ..."로 알려주세요. 계속 진행을 원하면 "확인"이라고 입력해 주세요.'
                });
                return { handled: true, proceed: false };
            }
            const listText = state.fillDetectedFields.map((item, idx) => `${idx + 1}. ${item}`).join('\n');
            state.chatHistory.push({
                role: 'ai',
                text: `제외 항목을 반영했습니다. 최종 목록:\n${listText}\n\n맞다면 '확인'이라고 입력해 주세요.`
            });
            return { handled: true, proceed: false };
        }

        if (lower.startsWith('추가:')) {
            const items = normalizeFieldListInput(raw.replace(/^추가:/i, ''));
            if (items.length === 0) {
                state.chatHistory.push({ role: 'ai', text: '추가할 항목을 알려주세요. 예: 추가: 연구 주제, 지도교사' });
                return { handled: true, proceed: false };
            }
            items.forEach((item) => {
                if (!state.fillDetectedFields.some((existing) => existing === item)) {
                    state.fillDetectedFields.push(item);
                }
            });
            const listText = state.fillDetectedFields.map((item, idx) => `${idx + 1}. ${item}`).join('\n');
            state.chatHistory.push({
                role: 'ai',
                text: `추가 항목을 반영했습니다. 최종 목록:\n${listText}\n\n맞다면 '확인'이라고 입력해 주세요.`
            });
            return { handled: true, proceed: false };
        }

        if (isConfirm) {
            return { handled: true, proceed: true, treatAsAnswer: false };
        }

        return { handled: true, proceed: true, treatAsAnswer: true };
    };

    const advanceFillIntake = (answer) => {
        if (!state.fillSessionActive || !state.fillActiveField) return false;
        const trimmed = (answer || '').trim();
        if (trimmed) {
            state.fillAnswers[state.fillActiveField] = trimmed;
        }
        if (state.fillQueue.length > 0) {
            state.fillActiveField = state.fillQueue.shift();
            state.chatHistory.push({
                role: 'ai',
                text: `다음 항목을 알려주세요: ${state.fillActiveField}`
            });
            return false;
        }
        state.fillSessionActive = false;
        state.fillActiveField = '';
        state.fillQueue = [];
        return true;
    };

    let sectionFillMap = new Map();

    const renderSectionFillPanel = (sections) => {
        if (!els.sectionFillPanel) return;
        els.sectionFillPanel.innerHTML = '';
        sectionFillMap = new Map();

        sections.forEach((section) => {
            const item = document.createElement('div');
            item.className = 'section-fill-item';
            item.dataset.section = section;
            item.innerHTML = `
                <div>${section}</div>
                <div class="section-fill-status">대기</div>
            `;
            els.sectionFillPanel.appendChild(item);
            sectionFillMap.set(section, item);
        });

        els.sectionFillPanel.classList.remove('hidden');
    };

    const updateSectionFillStatus = (section, status) => {
        const item = sectionFillMap.get(section);
        if (!item) return;
        const statusEl = item.querySelector('.section-fill-status');
        if (!statusEl) return;

        item.classList.remove('active');
        statusEl.classList.remove('active', 'done', 'error');

        if (status === 'active') {
            item.classList.add('active');
            statusEl.textContent = '작성 중';
            statusEl.classList.add('active');
        } else if (status === 'done') {
            statusEl.textContent = '완료';
            statusEl.classList.add('done');
        } else if (status === 'error') {
            statusEl.textContent = '오류';
            statusEl.classList.add('error');
        } else {
            statusEl.textContent = '대기';
        }
    };

    const streamHtmlEdit = async ({ html, instruction, onChunk }) => {
        const response = await fetch(API_ENDPOINTS.EDIT_HTML, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ html, instruction })
        });

        if (!response.ok) throw new Error(`Server Error: ${response.status}`);
        if (!response.body) throw new Error('ReadableStream not supported');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let htmlBuffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split(/\r?\n/);
            buffer = lines.pop();

            for (const line of lines) {
                const cleanLine = line.trim();
                if (!cleanLine.startsWith('data:')) continue;
                const jsonStr = cleanLine.substring(5).trim();
                if (!jsonStr) continue;

                let data;
                try {
                    data = JSON.parse(jsonStr);
                } catch (e) {
                    continue;
                }

                if (data.error) {
                    throw new Error(data.error);
                }
                if (data.chunk) {
                    htmlBuffer += data.chunk;
                    if (onChunk) onChunk(htmlBuffer);
                }
            }
        }

        return normalizeGeneratedHtml(htmlBuffer);
    };

    const streamHtmlFragmentEdit = async ({ fragment, instruction, onChunk }) => {
        const response = await fetch(API_ENDPOINTS.EDIT_FRAGMENT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fragment, instruction })
        });

        if (!response.ok) throw new Error(`Server Error: ${response.status}`);
        if (!response.body) throw new Error('ReadableStream not supported');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let htmlBuffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split(/\r?\n/);
            buffer = lines.pop();

            for (const line of lines) {
                const cleanLine = line.trim();
                if (!cleanLine.startsWith('data:')) continue;
                const jsonStr = cleanLine.substring(5).trim();
                if (!jsonStr) continue;

                let data;
                try {
                    data = JSON.parse(jsonStr);
                } catch (e) {
                    continue;
                }

                if (data.error) {
                    throw new Error(data.error);
                }
                if (data.chunk) {
                    htmlBuffer += data.chunk;
                    if (onChunk) onChunk(htmlBuffer);
                }
            }
        }

        return normalizeGeneratedHtml(htmlBuffer);
    };

    const stripCodeFences = (input) => {
        const trimmed = (input || '').trim();
        if (!trimmed) return '';
        const fenced = trimmed.match(/^```(?:html|xml)?\s*([\s\S]*?)```$/i);
        if (fenced) return (fenced[1] || '').trim();
        return trimmed;
    };

    const extractHtmlEnvelope = (input) => {
        const text = (input || '').trim();
        if (!text) return '';
        const lower = text.toLowerCase();
        const htmlStart = lower.indexOf('<html');
        const htmlEnd = lower.lastIndexOf('</html>');
        if (htmlStart !== -1 && htmlEnd !== -1 && htmlEnd > htmlStart) {
            return text.slice(htmlStart, htmlEnd + 7).trim();
        }
        const bodyStart = lower.indexOf('<body');
        const bodyEnd = lower.lastIndexOf('</body>');
        if (bodyStart !== -1 && bodyEnd !== -1 && bodyEnd > bodyStart) {
            return text.slice(bodyStart, bodyEnd + 7).trim();
        }
        return text;
    };

    const decodeHtmlEntities = (input) => {
        const text = input || '';
        if (!text) return '';
        const textarea = document.createElement('textarea');
        textarea.innerHTML = text;
        return textarea.value;
    };

    const normalizeGeneratedHtml = (input) => {
        let result = stripCodeFences(input);
        result = extractHtmlEnvelope(result);
        const hasTag = /<\w+[\s>]/.test(result);
        if (!hasTag && /&lt;|&gt;|&amp;/.test(result)) {
            result = decodeHtmlEntities(result);
        }
        return (result || '').trim();
    };

    const splitHtmlStyles = (html) => {
        const normalized = normalizeGeneratedHtml(html);
        const styleMatches = normalized.match(/<style[\s\S]*?<\/style>/gi) || [];
        const styleBlock = styleMatches.join('\n');
        const body = normalized.replace(/<style[\s\S]*?<\/style>/gi, '').trim();
        return { styleBlock, body };
    };

    const extractBodyHtml = (html) => {
        const trimmed = normalizeGeneratedHtml(html);
        if (!trimmed) return '';
        if (!/<(?:html|body)[\s>]/i.test(trimmed) && !/<!doctype/i.test(trimmed)) {
            return trimmed;
        }
        try {
            const doc = new DOMParser().parseFromString(trimmed, 'text/html');
            if (doc && doc.body) {
                const bodyHtml = doc.body.innerHTML.trim();
                return bodyHtml || trimmed;
            }
        } catch (e) {
            return trimmed;
        }
        return trimmed;
    };

    const getHtmlMetrics = (html) => {
        const normalized = extractBodyHtml(html);
        if (!normalized) {
            return { normalized: '', textLength: 0, mediaCount: 0, flags: null };
        }
        try {
            const doc = new DOMParser().parseFromString(normalized, 'text/html');
            const body = doc.body;
            if (!body) {
                return { normalized, textLength: 0, mediaCount: 0, flags: null };
            }
            const textLength = (body.textContent || '').replace(/\s+/g, '').length;
            const mediaCount = body.querySelectorAll('img, svg, canvas, iframe').length;
            const flags = {
                hasSection: !!body.querySelector('.Section, .Paper, .hwp-doc'),
                hasTable: !!body.querySelector('table')
            };
            const elementCount = body.querySelectorAll('*').length;
            return { normalized, textLength, mediaCount, elementCount, flags };
        } catch (e) {
            return {
                normalized,
                textLength: normalized.replace(/\s+/g, '').length,
                mediaCount: 0,
                elementCount: /<\w+[\s>]/.test(normalized) ? 1 : 0,
                flags: null
            };
        }
    };

    const validateRenderedUpdate = (originalHtml, updatedHtml, options = {}) => {
        const { enforceStructure = false } = options;
        const original = getHtmlMetrics(originalHtml);
        const updated = getHtmlMetrics(updatedHtml);
        if (!updated.normalized) return { ok: false, normalized: '' };
        if (updated.textLength === 0 && updated.mediaCount === 0) {
            return { ok: false, normalized: updated.normalized };
        }
        if (original.textLength > 0 && updated.textLength === 0 && updated.mediaCount === 0) {
            return { ok: false, normalized: updated.normalized };
        }
        if (enforceStructure && original.flags && updated.flags) {
            if (original.elementCount > 0 && updated.elementCount === 0) {
                return { ok: false, normalized: updated.normalized };
            }
            if (original.flags.hasSection && !updated.flags.hasSection) {
                return { ok: false, normalized: updated.normalized };
            }
            if (original.flags.hasTable && !updated.flags.hasTable) {
                return { ok: false, normalized: updated.normalized };
            }
        }
        return { ok: true, normalized: updated.normalized };
    };

    const BLOCK_LEVEL_TAGS = new Set([
        'P', 'DIV', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER',
        'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
        'UL', 'OL', 'LI', 'DL', 'DT', 'DD',
        'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'TD', 'TH',
        'BLOCKQUOTE', 'PRE', 'HR'
    ]);

    const isInlineHtml = (html) => {
        const normalized = extractBodyHtml(html);
        if (!normalized) return true;
        try {
            const doc = new DOMParser().parseFromString(normalized, 'text/html');
            const body = doc.body;
            if (!body) return true;
            return !Array.from(body.querySelectorAll('*')).some((node) => BLOCK_LEVEL_TAGS.has(node.tagName));
        } catch (e) {
            return true;
        }
    };

    const mergeElementAttributes = (source, target) => {
        if (!source || !target) return;
        Array.from(source.attributes).forEach((attr) => {
            if (attr.name === 'class' && target.classList) {
                const merged = new Set([
                    ...source.classList,
                    ...target.classList
                ]);
                target.setAttribute('class', Array.from(merged).join(' '));
                return;
            }
            if (!target.hasAttribute(attr.name)) {
                target.setAttribute(attr.name, attr.value);
            }
        });
    };

    const PRESERVE_CONTAINER_TAGS = new Set(['TD', 'TH', 'TR', 'TBODY', 'THEAD', 'TFOOT', 'TABLE']);

    const normalizeFragmentForReplacement = (block, html) => {
        const normalized = extractBodyHtml(html);
        if (!block) return { html: normalized, innerOnly: false, innerHtml: '' };
        const doc = block.ownerDocument || document;
        const temp = doc.createElement('div');
        temp.innerHTML = normalized;
        const firstEl = temp.firstElementChild;
        const tag = block.tagName;

        if (PRESERVE_CONTAINER_TAGS.has(tag)) {
            const candidate = temp.querySelector(tag.toLowerCase());
            const inner = candidate ? candidate.innerHTML : normalized;
            return { html: normalized, innerOnly: true, innerHtml: inner };
        }

        if (firstEl && firstEl.tagName === tag) {
            mergeElementAttributes(block, firstEl);
            return { html: temp.innerHTML, innerOnly: false, innerHtml: '' };
        }

        if (temp.childElementCount === 1 && firstEl) {
            const inner = firstEl.innerHTML;
            return { html: normalized, innerOnly: true, innerHtml: inner };
        }

        if (temp.childElementCount === 0) {
            return { html: normalized, innerOnly: true, innerHtml: normalized };
        }

        return { html: normalized, innerOnly: false, innerHtml: '' };
    };

    const getPreviewHtmlForBlock = (block, html) => {
        const normalized = extractBodyHtml(html);
        if (!block || !normalized) return null;
        const doc = block.ownerDocument || document;
        const temp = doc.createElement('div');
        temp.innerHTML = normalized;
        const firstEl = temp.firstElementChild;
        if (PRESERVE_CONTAINER_TAGS.has(block.tagName)) {
            const candidate = temp.querySelector(block.tagName.toLowerCase());
            return candidate ? candidate.innerHTML : null;
        }
        if (firstEl && firstEl.tagName === block.tagName) {
            return firstEl.innerHTML;
        }
        if (!firstEl) return normalized;
        return null;
    };

    const cleanupEraseSpans = (root) => {
        if (!root) return;
        const spans = Array.from(root.querySelectorAll('.edit-erase-span'));
        spans.forEach((span) => {
            const parent = span.parentNode;
            if (!parent) return;
            const fragment = span.ownerDocument.createDocumentFragment();
            while (span.firstChild) {
                fragment.appendChild(span.firstChild);
            }
            parent.replaceChild(fragment, span);
        });
    };

    const replaceRangeWithHtml = (range, html) => {
        if (!range) return false;
        const container = range.commonAncestorContainer;
        const doc = container && container.ownerDocument ? container.ownerDocument : document;
        if (!doc || !doc.contains(container)) return false;

        const normalized = extractBodyHtml(html);
        if (!normalized) return false;

        const block = getBlockElement(container);
        const temp = doc.createElement('div');
        temp.innerHTML = normalized;

        let replacement = normalized;
        if (block) {
            const blockTag = block.tagName.toLowerCase();
            const candidate = temp.querySelector(blockTag);
            if (candidate) {
                replacement = candidate.innerHTML;
            } else if (temp.childElementCount === 1 && temp.firstElementChild) {
                replacement = temp.firstElementChild.innerHTML;
            }
        }

        const wrap = doc.createElement('div');
        wrap.innerHTML = replacement;
        const fragment = doc.createDocumentFragment();
        while (wrap.firstChild) {
            fragment.appendChild(wrap.firstChild);
        }

        const safeRange = range.cloneRange();
        safeRange.deleteContents();
        safeRange.insertNode(fragment);
        return true;
    };

    const getRangeFragmentHtml = (range) => {
        if (!range) return '';
        const doc = range.startContainer && range.startContainer.ownerDocument
            ? range.startContainer.ownerDocument
            : document;
        const wrapper = doc.createElement('div');
        const cloned = range.cloneContents();
        wrapper.appendChild(cloned);
        return wrapper.innerHTML || '';
    };

    const getInlineSelectionInfo = () => {
        if (!state.selectedRange || !state.selectedBlock) return null;
        const startBlock = getBlockElement(state.selectedRange.startContainer);
        const endBlock = getBlockElement(state.selectedRange.endContainer);
        if (!startBlock || !endBlock || startBlock !== endBlock) return null;
        const fragmentHtml = getRangeFragmentHtml(state.selectedRange);
        if (!fragmentHtml) return null;
        return {
            range: state.selectedRange,
            block: startBlock,
            fragmentHtml
        };
    };

    const buildFrameOverlayStyles = () => {
        return `
<style id="hwp-editor-overlay">
  .fill-content {
    text-align: justify !important;
    line-height: 1.6 !important;
    margin: 0 !important;
  }
  .fill-content span {
    font-family: inherit;
    font-size: inherit;
  }
  .Paper {
    border: none !important;
    box-shadow: none !important;
  }
  .HeaderPageFooter {
    margin-top: 0 !important;
    padding-top: 0 !important;
  }
  .HeaderPageFooter .Page {
    padding-top: 0 !important;
  }
  .edit-erase-span {
    display: inline-block;
    position: relative;
    background: rgba(226, 232, 240, 0.6);
    border-radius: 6px;
    padding: 0 2px;
    animation: erase-out 0.45s ease forwards;
  }
  .edit-erase-block {
    position: relative;
    animation: erase-out 0.45s ease forwards;
  }
  .selected-block {
    outline: 2px solid rgba(14, 165, 233, 0.35);
    background: rgba(14, 165, 233, 0.06);
    border-radius: 6px;
  }
  @keyframes erase-out {
    0% { opacity: 1; filter: blur(0); transform: translateY(0); }
    100% { opacity: 0; filter: blur(4px); transform: translateY(-4px); }
  }
  .doc-fill-flash {
    animation: fill-flash 0.6s ease;
  }
  @keyframes fill-flash {
    0% { background: rgba(14, 165, 233, 0.08); }
    100% { background: transparent; }
  }
</style>`;
    };

    const buildFrameHtml = (html, baseHref = '/') => {
        if (!html) return '';
        const cleanedHtml = html;
        const overlayStyle = buildFrameOverlayStyles();
        const normalizedBase = baseHref ? (baseHref.endsWith('/') ? baseHref : `${baseHref}/`) : '/';
        const baseTag = `<base href="${normalizedBase}">`;
        const hasHtmlTag = /<html[\s>]/i.test(cleanedHtml);
        if (hasHtmlTag) {
            let result = cleanedHtml;
            if (!/<head[\s>]/i.test(result)) {
                result = result.replace(/<html[^>]*>/i, (match) => `${match}<head>${baseTag}${overlayStyle}</head>`);
            }
            if (!/<base\s/i.test(result)) {
                result = result.replace(/<head[^>]*>/i, (match) => `${match}${baseTag}`);
            }
            if (!/hwp-editor-overlay/.test(result)) {
                result = result.replace(/<head[^>]*>/i, (match) => `${match}${overlayStyle}`);
            }
            return result;
        }

        const { styleBlock, body } = splitHtmlStyles(cleanedHtml);
        return `<!DOCTYPE html><html><head><meta charset="utf-8">${baseTag}${styleBlock || ''}${overlayStyle}</head><body>${body || ''}</body></html>`;
    };

    const revokeFrameBlobUrl = () => {
        if (state.frameBlobUrl) {
            URL.revokeObjectURL(state.frameBlobUrl);
            state.frameBlobUrl = null;
        }
    };

    const renderTemplateFrame = (html) => {
        if (!els.docFrame) return;
        const frameHtml = buildFrameHtml(html, getTemplateBaseHref());
        state.frameHtml = html;
        revokeFrameBlobUrl();
        if (supportsSrcdoc) {
            els.docFrame.removeAttribute('src');
            els.docFrame.srcdoc = frameHtml;
        } else {
            const blob = new Blob([frameHtml], { type: 'text/html' });
            const url = URL.createObjectURL(blob);
            state.frameBlobUrl = url;
            els.docFrame.src = url;
        }
        hideInlineEditBubble();
    };

    const buildEditInstruction = (prompt, snippet, sectionTitle) => {
        const parts = [];
        const isFullDoc = sectionTitle === '전체 문서';
        if (sectionTitle && !isFullDoc) {
            parts.push(`수정 대상 섹션: ${sectionTitle}`);
        }
        if (snippet) parts.push(`선택한 원문: """${snippet}"""`);
        parts.push(`요청: ${prompt}`);
        if (snippet || (sectionTitle && !isFullDoc)) {
            parts.push('해당 부분만 수정하고 나머지는 유지하세요.');
        }
        return parts.join('\n');
    };

    function normalizeSnippet(snippet) {
        return (snippet || '').replace(/\s+/g, ' ').trim();
    }

    function normalizeSectionKey(text) {
        return (text || '')
            .replace(/\s+/g, '')
            .replace(/[^0-9a-zA-Z가-힣]/g, '')
            .toLowerCase();
    }

    const STREAM_UPDATE_INTERVAL = 120;

    function getCanvasSummary(html) {
        const text = (html || '')
            .replace(/<style[\s\S]*?<\/style>/gi, ' ')
            .replace(/<[^>]+>/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        if (!text) return '';
        const limit = 140;
        return text.length > limit ? `${text.slice(0, limit)}…` : text;
    }

    function updateBlockFromFragment(block, html) {
        if (!block || !block.isConnected) return;
        if ((state.templateMode === 'fill' || state.fillSessionActive) && block.matches('td, th')) {
            const applied = applyFillContentToCell(block, html);
            if (applied) {
                syncFrameHeight();
                return;
            }
        }
        const doc = block.ownerDocument || document;
        const { ok } = validateRenderedUpdate(block.outerHTML || '', html);
        if (!ok) return;
        const previewHtml = getPreviewHtmlForBlock(block, html);
        if (previewHtml === null) return;
        block.innerHTML = previewHtml;
    }

    function updateFrameBodyFromStream(html) {
        const doc = getFrameDocument();
        if (!doc || !doc.body) return;
        const { body } = splitHtmlStyles(html);
        const baseHtml = doc.body.innerHTML || '';
        const { ok, normalized } = validateRenderedUpdate(baseHtml, body || html || '', { enforceStructure: true });
        if (!ok) return;
        doc.body.innerHTML = normalized;
        syncFrameHeight();
    }

    function getInlineBubbleRect() {
        if (!els.inlineEditBubble || els.inlineEditBubble.classList.contains('hidden')) return null;
        const rect = els.inlineEditBubble.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;
        return rect;
    }

    function getSelectionViewportRect() {
        if (!els.docFrame) return null;
        const frameRect = els.docFrame.getBoundingClientRect();
        const rects = [];

        const pushRect = (rect) => {
            if (!rect || (!rect.width && !rect.height)) return;
            rects.push(rect);
        };

        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            state.selectedBlocks.forEach((block) => pushRect(block.getBoundingClientRect()));
        } else if (state.selectedBlock) {
            pushRect(state.selectedBlock.getBoundingClientRect());
        } else if (state.selectedRange) {
            let rangeRect = state.selectedRange.getBoundingClientRect();
            if (!rangeRect.width && !rangeRect.height) {
                const clientRects = state.selectedRange.getClientRects();
                if (clientRects.length > 0) rangeRect = clientRects[0];
            }
            pushRect(rangeRect);
        }

        if (rects.length === 0) return null;

        let minLeft = Infinity;
        let minTop = Infinity;
        let maxRight = -Infinity;
        let maxBottom = -Infinity;
        rects.forEach((rect) => {
            minLeft = Math.min(minLeft, rect.left);
            minTop = Math.min(minTop, rect.top);
            maxRight = Math.max(maxRight, rect.right);
            maxBottom = Math.max(maxBottom, rect.bottom);
        });

        const padding = 6;
        const left = frameRect.left + minLeft - padding;
        const top = frameRect.top + minTop - padding;
        const right = frameRect.left + maxRight + padding;
        const bottom = frameRect.top + maxBottom + padding;

        return {
            left,
            top,
            width: Math.max(24, right - left),
            height: Math.max(24, bottom - top)
        };
    }

    function hideEditCover() {
        if (!els.editCover) return;
        els.editCover.classList.add('hidden');
        els.editCover.classList.remove('active', 'done');
        els.editCover.style.left = '';
        els.editCover.style.top = '';
        els.editCover.style.width = '';
        els.editCover.style.height = '';
        els.editCover.style.opacity = '';
        els.editCover.style.transform = '';
        els.editCover.style.transition = '';
        state.editCoverActive = false;
        state.editCoverLocked = false;
    }

    function dismissEditCover() {
        if (!state.editCoverActive) return;
        state.editCoverLocked = false;
        hideEditCover();
    }

    function startEditCoverAnimation(originRect = null) {
        if (!els.editCover) return;
        const targetRect = getSelectionViewportRect();
        if (!targetRect) return;

        const fallbackWidth = Math.min(targetRect.width, 160);
        const startRect = originRect || {
            left: targetRect.left,
            top: targetRect.top - 28,
            width: Math.max(80, fallbackWidth),
            height: 10
        };

        const cover = els.editCover;
        cover.classList.remove('hidden', 'done');
        cover.classList.remove('active');
        cover.style.transition = 'none';
        cover.style.left = `${startRect.left}px`;
        cover.style.top = `${startRect.top}px`;
        cover.style.width = `${startRect.width}px`;
        cover.style.height = `${startRect.height}px`;
        cover.style.opacity = '0.6';
        cover.style.transform = 'translateY(-8px) scale(0.98)';
        cover.getBoundingClientRect();
        cover.style.transition = '';

        state.editCoverActive = true;
        state.editCoverLocked = true;

        requestAnimationFrame(() => {
            cover.classList.add('active');
            cover.style.left = `${targetRect.left}px`;
            cover.style.top = `${targetRect.top}px`;
            cover.style.width = `${targetRect.width}px`;
            cover.style.height = `${targetRect.height}px`;
            cover.style.opacity = '1';
            cover.style.transform = 'translateY(0) scale(1)';
        });
    }

    function finishEditCoverAnimation() {
        if (!els.editCover || !state.editCoverActive) return;
        els.editCover.classList.add('done');
        els.editCover.classList.remove('active');
        state.editCoverLocked = false;
        setTimeout(() => {
            if (!state.editCoverLocked) hideEditCover();
        }, 260);
    }

    function updateSelectionPreview() {
        if (!els.selectionPreview) return;
        const snippet = state.selectedSnippet;
        const sectionTitle = state.selectedSectionTitle;
        if (!snippet && !sectionTitle) {
            els.selectionPreview.classList.add('hidden');
            els.selectionPreview.textContent = '';
            return;
        }
        const snippetPreview = snippet ? (snippet.length > 180 ? `${snippet.slice(0, 180)}...` : snippet) : '';
        let label = '';
        if (sectionTitle) {
            label = sectionTitle === '전체 문서' ? '전체 문서' : `섹션: ${sectionTitle}`;
        }
        if (snippetPreview) {
            label = label ? `${label} · ${snippetPreview}` : snippetPreview;
        }
        els.selectionPreview.textContent = `선택됨: ${label}`;
        els.selectionPreview.classList.remove('hidden');
    }

    function setSelectedSnippet(snippet) {
        const normalized = normalizeSnippet(snippet);
        state.selectedSnippet = normalized;

        updateSelectionPreview();
        updateTemplateControls();
    }

    function clearSelectedSnippet() {
        state.selectedSnippet = '';
        state.selectedSectionTitle = '';
        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            state.selectedBlocks.forEach((block) => block.classList.remove('selected-block'));
        }
        state.selectedBlocks = [];
        if (state.selectedBlock) {
            state.selectedBlock.classList.remove('selected-block');
        }
        state.selectedBlock = null;
        state.selectedRange = null;
        const selection = getFrameSelection();
        if (selection) selection.removeAllRanges();
        cleanupEraseSpans(getDocRoot());
        if (els.editTargetInput) els.editTargetInput.value = '';
        if (els.editTargetSelect) els.editTargetSelect.value = '';
        hideInlineEditBubble();
        if (!state.editCoverLocked) hideEditCover();
        updateSelectionPreview();
        updateTemplateControls();
    }


    function hideInlineEditBubble() {
        if (!els.inlineEditBubble) return;
        els.inlineEditBubble.classList.add('hidden');
        els.inlineEditBubble.style.visibility = '';
        if (els.inlineEditInput) els.inlineEditInput.value = '';
    }

    function positionInlineEditBubble(rect) {
        if (!els.inlineEditBubble || !els.docFrame || !rect) return;
        const bubble = els.inlineEditBubble;
        const frameRect = els.docFrame.getBoundingClientRect();
        const anchorX = frameRect.left + rect.left + rect.width / 2;
        const anchorY = frameRect.top + rect.top;

        bubble.classList.remove('hidden');
        bubble.style.visibility = 'hidden';
        bubble.style.left = '0px';
        bubble.style.top = '0px';

        requestAnimationFrame(() => {
            const bubbleRect = bubble.getBoundingClientRect();
            const padding = 12;
            const left = Math.min(
                Math.max(padding, anchorX - bubbleRect.width / 2),
                window.innerWidth - bubbleRect.width - padding
            );
            const top = Math.max(padding, anchorY - bubbleRect.height - 12);
            bubble.style.left = `${left}px`;
            bubble.style.top = `${top}px`;
            bubble.style.visibility = 'visible';
        });
    }

    function showInlineEditBubble(rect) {
        positionInlineEditBubble(rect);
        if (els.inlineEditInput) {
            els.inlineEditInput.focus();
        }
    }

    function setSelectedBlocks(blocks, sectionTitle) {
        if (!blocks || blocks.length === 0) return;
        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            state.selectedBlocks.forEach((block) => block.classList.remove('selected-block'));
        }
        state.selectedBlocks = blocks;
        state.selectedSectionTitle = sectionTitle || '';
        state.selectedRange = null;
        if (state.selectedBlock) {
            state.selectedBlock.classList.remove('selected-block');
        }
        state.selectedBlock = null;
        const selection = getFrameSelection();
        if (selection) selection.removeAllRanges();
        blocks.forEach((block) => block.classList.add('selected-block'));
        hideInlineEditBubble();
        updateSelectionPreview();
        updateTemplateControls();
    }

    function startEraseAnimation() {
        const docRoot = getDocRoot();
        if (!docRoot) return null;
        cleanupEraseSpans(docRoot);
        const block = state.selectedBlock;
        if (block && block.isConnected) {
            block.classList.add('edit-erase-block');
            return block;
        }
        return null;
    }

    function getBlockElement(node) {
        if (!node) return null;
        const element = node.nodeType === 1 ? node : node.parentElement;
        if (!element) return null;
        return element.closest('p, li, td, th, h1, h2, h3, div');
    }

    function replaceNodeWithHtml(targetNode, html) {
        if (!targetNode || !targetNode.parentNode) return;
        const doc = targetNode.ownerDocument || document;
        const temp = doc.createElement('div');
        temp.innerHTML = html;
        const fragment = doc.createDocumentFragment();
        while (temp.firstChild) {
            fragment.appendChild(temp.firstChild);
        }
        targetNode.replaceWith(fragment);
    }

    function replaceBlocksWithHtml(blocks, html) {
        if (!blocks || blocks.length === 0) return;
        const firstBlock = blocks[0];
        if (!firstBlock || !firstBlock.parentNode) return;

        const doc = firstBlock.ownerDocument || document;
        const normalized = normalizeFragmentForReplacement(firstBlock, html);
        if (normalized.innerOnly) {
            firstBlock.innerHTML = normalized.innerHtml;
            blocks.slice(1).forEach((block) => block.remove());
            return;
        }

        const temp = doc.createElement('div');
        temp.innerHTML = normalized.html;

        const fragment = doc.createDocumentFragment();
        while (temp.firstChild) {
            fragment.appendChild(temp.firstChild);
        }
        if (!fragment.childNodes.length) return;
        firstBlock.parentNode.insertBefore(fragment, firstBlock);
        blocks.forEach((block) => block.remove());
    }

    function extractFragmentFromBlock(block) {
        if (!block) return '';
        return block.outerHTML || '';
    }

    function getSelectedFragment() {
        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            return state.selectedBlocks.map((block) => block.outerHTML || '').join('\n');
        }
        if (state.selectedBlock && state.selectedBlock.isConnected) {
            return extractFragmentFromBlock(state.selectedBlock);
        }
        return '';
    }

    function collectSiblingBlocks(startBlock, maxBlocks = 6) {
        const blocks = [];
        let current = startBlock;
        while (current && blocks.length < maxBlocks) {
            blocks.push(current);
            const next = current.nextElementSibling;
            if (!next || next.matches('h1, h2, h3')) break;
            current = next;
        }
        return blocks;
    }

    function limitBlocksByLength(blocks, maxChars = 12000) {
        let total = 0;
        const limited = [];
        for (const block of blocks) {
            const html = block.outerHTML || '';
            if (limited.length > 0 && total + html.length > maxChars) break;
            limited.push(block);
            total += html.length;
        }
        return limited;
    }

    function findSectionAnchor(sectionTitle) {
        const docRoot = getDocRoot();
        if (!docRoot) return null;
        const normalizedTitle = normalizeSectionKey(sectionTitle);
        if (!normalizedTitle) return null;

        const headingCandidates = Array.from(docRoot.querySelectorAll('h1, h2, h3'));
        for (const el of headingCandidates) {
            const text = normalizeSectionKey(el.textContent);
            if (text && (text === normalizedTitle || text.includes(normalizedTitle) || normalizedTitle.includes(text))) {
                return el;
            }
        }

        const candidates = Array.from(docRoot.querySelectorAll('p, li, td, th, div'));
        for (const el of candidates) {
            const raw = (el.textContent || '').trim();
            if (raw.length > 140) continue;
            const text = normalizeSectionKey(raw);
            if (text && (text === normalizedTitle || text.includes(normalizedTitle) || normalizedTitle.includes(text))) {
                return el;
            }
        }
        return null;
    }

    function pickSectionBlock(anchor) {
        const docRoot = getDocRoot();
        if (!anchor) return null;
        const cell = anchor.closest('td, th');
        if (cell && docRoot && docRoot.contains(cell)) return cell;

        const table = anchor.closest('table');
        if (table && docRoot && docRoot.contains(table)) return table;

        const block = anchor.closest('p, li, div, h1, h2, h3');
        if (block && docRoot && block !== docRoot) return block;
        return anchor;
    }

    function getSectionBlocks(sectionTitle) {
        if (!getDocRoot()) return { blocks: [], fragment: '' };
        const anchor = findSectionAnchor(sectionTitle);
        if (!anchor) return { blocks: [], fragment: '' };

        const baseBlock = pickSectionBlock(anchor);
        if (!baseBlock) return { blocks: [], fragment: '' };

        let blocks = [];
        if (baseBlock.matches('table, td, th')) {
            blocks = [baseBlock];
        } else {
            blocks = collectSiblingBlocks(baseBlock, 6);
        }
        blocks = limitBlocksByLength(blocks, 12000);
        if (blocks.length === 0) return { blocks: [], fragment: '' };
        const fragment = blocks.map((block) => block.outerHTML).join('\n');
        return { blocks, fragment };
    }

    function isEmptyCellBlock(cell) {
        if (!cell) return false;
        const info = getCellInfo(cell);
        return info.isEmpty;
    }

    function isLabelCellBlock(cell) {
        if (!cell) return false;
        const row = cell.closest('tr');
        if (!row) return false;
        const cells = Array.from(row.children).filter((el) => el.matches('td, th'));
        const index = cells.indexOf(cell);
        if (index < 0) return false;
        const labelText = normalizeLabelText(cell.textContent);
        if (!labelText) return false;
        if (cell.tagName.toLowerCase() === 'th') return true;
        return index === 0 && cells.length > 1;
    }

    function findAdjacentEmptyCell(labelCell) {
        if (!labelCell) return null;
        const row = labelCell.closest('tr');
        if (!row) return null;
        const cells = Array.from(row.children).filter((el) => el.matches('td, th'));
        const index = cells.indexOf(labelCell);
        if (index >= 0) {
            for (let i = index + 1; i < cells.length; i += 1) {
                if (isEmptyCellBlock(cells[i])) return cells[i];
            }
            for (let i = 0; i < index; i += 1) {
                if (isEmptyCellBlock(cells[i])) return cells[i];
            }
        }
        let nextRow = row.nextElementSibling;
        while (nextRow) {
            const nextCells = Array.from(nextRow.children).filter((el) => el.matches('td, th'));
            if (index >= 0 && nextCells[index] && isEmptyCellBlock(nextCells[index])) {
                return nextCells[index];
            }
            nextRow = nextRow.nextElementSibling;
        }
        return null;
    }

    function buildFillCellMap(docRoot) {
        const map = new Map();
        if (!docRoot) return map;

        const addCell = (key, cell) => {
            if (!key || !cell) return;
            if (!map.has(key)) map.set(key, cell);
        };

        Array.from(docRoot.querySelectorAll('table')).forEach((table) => {
            const columnLabels = [];
            const rows = Array.from(table.querySelectorAll('tr'));
            rows.forEach((row) => {
                const cells = Array.from(row.children).filter((el) => el.matches('td, th'));
                if (!cells.length) return;
                const infos = cells.map((cell) => getCellInfo(cell));
                const labelTexts = cells.map((cell) => normalizeLabelText(cell.textContent));

                labelTexts.forEach((labelText, idx) => {
                    if (labelText && cells[idx].tagName.toLowerCase() === 'th') {
                        columnLabels[idx] = labelText;
                    }
                });

                const rowLabel = labelTexts[0] || '';

                cells.forEach((cell, i) => {
                    const info = infos[i];
                    const labelText = labelTexts[i];
                    const isHeader = cell.tagName.toLowerCase() === 'th' && labelText;
                    const isLabelCell = isHeader || (i === 0 && labelText && cells.length > 1);
                    if (isLabelCell) return;
                    if (!info.isEmpty) return;

                    let label = '';
                    for (let j = i - 1; j >= 0; j -= 1) {
                        if (labelTexts[j]) {
                            label = labelTexts[j];
                            break;
                        }
                    }
                    if (!label && columnLabels[i]) {
                        label = columnLabels[i];
                    }
                    if (!label && rowLabel && i > 0) {
                        label = rowLabel;
                    }
                    if (!label) return;

                    const key = normalizeSectionKey(label);
                    const cleanedKey = normalizeSectionKey(sanitizeCellText(label));
                    addCell(key, cell);
                    if (cleanedKey && cleanedKey !== key) {
                        addCell(cleanedKey, cell);
                    }
                });
            });
        });

        return map;
    }

    function findFillTargetForField(sectionTitle) {
        const docRoot = getDocRoot();
        if (!docRoot) return getSectionBlocks(sectionTitle);
        const normalizedTitle = normalizeSectionKey(sectionTitle);
        if (!normalizedTitle) return getSectionBlocks(sectionTitle);

        const fillMap = buildFillCellMap(docRoot);
        const fallbackKey = normalizeSectionKey(sanitizeCellText(sectionTitle));
        const mappedCell = fillMap.get(normalizedTitle) || (fallbackKey ? fillMap.get(fallbackKey) : null);
        if (mappedCell) {
            return { blocks: [mappedCell], fragment: mappedCell.outerHTML };
        }

        const cells = Array.from(docRoot.querySelectorAll('td, th'));
        let matchedLabel = null;
        let matchedLength = Infinity;

        cells.forEach((cell) => {
            const labelText = normalizeLabelText(cell.textContent);
            if (!labelText) return;
            if (labelText.length > 160) return;
            const cellKey = normalizeSectionKey(labelText);
            if (!cellKey) return;
            if (cellKey === normalizedTitle || cellKey.includes(normalizedTitle) || normalizedTitle.includes(cellKey)) {
                if (labelText.length < matchedLength) {
                    matchedLabel = cell;
                    matchedLength = labelText.length;
                }
                if (cellKey === normalizedTitle) {
                    matchedLength = labelText.length;
                }
            }
        });

        if (matchedLabel) {
            const fillCell = findAdjacentEmptyCell(matchedLabel);
            if (fillCell) {
                return { blocks: [fillCell], fragment: fillCell.outerHTML };
            }
            return { blocks: [], fragment: '', skip: true };
        }

        const fallback = getSectionBlocks(sectionTitle);
        if (fallback.blocks.length === 1 && fallback.blocks[0].matches('td, th')) {
            const fallbackCell = fallback.blocks[0];
            if (isLabelCellBlock(fallbackCell) && !isEmptyCellBlock(fallbackCell)) {
                const fillCell = findAdjacentEmptyCell(fallbackCell);
                if (fillCell) {
                    return { blocks: [fillCell], fragment: fillCell.outerHTML };
                }
                return { blocks: [], fragment: '', skip: true };
            }
        }
        return fallback;
    }

    function extractFillLines(html, doc) {
        const normalized = extractBodyHtml(html) || html || '';
        const temp = doc.createElement('div');
        temp.innerHTML = normalized;
        Array.from(temp.querySelectorAll('br')).forEach((br) => br.replaceWith('\n'));
        const blocks = Array.from(temp.querySelectorAll('p, div, li'));
        const lines = [];
        if (blocks.length > 0) {
            blocks.forEach((el) => {
                const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
                if (text) lines.push(text);
            });
        } else {
            const text = (temp.textContent || '').replace(/\s+/g, ' ').trim();
            if (text) {
                text.split(/\n+/).forEach((line) => {
                    const trimmed = line.trim();
                    if (trimmed) lines.push(trimmed);
                });
            }
        }
        return lines;
    }

    function applyFillContentToCell(cell, html) {
        if (!cell) return false;
        if (isLabelCellBlock(cell) && !isEmptyCellBlock(cell)) {
            return false;
        }
        const doc = cell.ownerDocument || document;
        const lines = extractFillLines(html, doc);
        if (lines.length === 0) return false;
        let target = cell.querySelector('p, div');
        if (!target) {
            target = doc.createElement('p');
            target.className = 'Normal';
            cell.innerHTML = '';
            cell.appendChild(target);
        }
        target.classList.add('fill-content');
        target.innerHTML = '';
        const span = doc.createElement('span');
        span.className = 'lang-ko';
        lines.forEach((line, idx) => {
            if (idx > 0) span.appendChild(doc.createElement('br'));
            span.appendChild(doc.createTextNode(line));
        });
        target.appendChild(span);
        return true;
    }

    function buildSnippetFromBlocks(blocks) {
        if (!blocks || blocks.length === 0) return '';
        const text = blocks.map((block) => block.textContent || '').join(' ');
        const normalized = normalizeSnippet(text);
        return normalized.length > 800 ? normalized.slice(0, 800) : normalized;
    }

    function setFullDocTarget() {
        clearSelectedSnippet();
        state.selectedSectionTitle = '전체 문서';
        updateSelectionPreview();
        updateTemplateControls();
        if (els.editTargetSelect) els.editTargetSelect.value = '__full__';
        if (els.editTargetInput) els.editTargetInput.value = '';
    }

    function applyEditTargetSelection() {
        const inputValue = els.editTargetInput ? els.editTargetInput.value.trim() : '';
        const selectValue = els.editTargetSelect ? els.editTargetSelect.value : '';
        const targetValue = inputValue || selectValue;
        if (!targetValue) {
            const hasManualSelection = !!state.selectedSnippet || !!state.selectedBlock;
            if (state.selectedBlocks && state.selectedBlocks.length > 0) {
                state.selectedBlocks.forEach((block) => block.classList.remove('selected-block'));
            }
            state.selectedBlocks = [];
            state.selectedSectionTitle = '';
            if (!hasManualSelection) {
                state.selectedSnippet = '';
                if (state.selectedBlock) {
                    state.selectedBlock.classList.remove('selected-block');
                }
                state.selectedBlock = null;
                hideInlineEditBubble();
            }
            updateSelectionPreview();
            updateTemplateControls();
            return;
        }
        state.templateMode = 'edit';
        if (targetValue === '__full__') {
            setFullDocTarget();
            return;
        }

        const { blocks } = getSectionBlocks(targetValue);
        if (!blocks || blocks.length === 0) {
            showToast(`"${targetValue}" 섹션을 찾지 못했습니다.`, 'error');
            return;
        }

        state.selectedSnippet = buildSnippetFromBlocks(blocks);
        setSelectedBlocks(blocks, targetValue);
        if (els.editTargetSelect) els.editTargetSelect.value = targetValue;
        if (els.editTargetInput) els.editTargetInput.value = '';
    }

    function applyEraseAnimationToBlocks(blocks) {
        if (!blocks || blocks.length === 0) return;
        blocks.forEach((block) => {
            if (block && block.classList) {
                block.classList.add('edit-erase-block');
            }
        });
    }

    function clearEraseAnimation(blocks) {
        if (!blocks || blocks.length === 0) return;
        blocks.forEach((block) => {
            if (block && block.classList) {
                block.classList.remove('edit-erase-block');
            }
        });
    }

    function flashDocContent() {
        const docRoot = getDocRoot();
        if (!docRoot) return;
        docRoot.classList.add('doc-fill-flash');
        setTimeout(() => {
            docRoot.classList.remove('doc-fill-flash');
        }, 650);
    }

    const handleDocSelection = () => {
        const docRoot = getDocRoot();
        if (!docRoot || !state.templateHtml) return;
        if (state.templateMode === 'fill' || state.fillSessionActive || state.fillVerificationPending) return;
        const selection = getFrameSelection();
        if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;

        const range = selection.getRangeAt(0);
        const container = range.commonAncestorContainer;
        const containerEl = container.nodeType === 3 ? container.parentElement : container;
        if (!containerEl || !docRoot.contains(containerEl)) return;

        const selectedText = normalizeSnippet(selection.toString());
        if (selectedText.length < 2) return;

        const clipped = selectedText.length > 800 ? selectedText.slice(0, 800) : selectedText;
        state.templateMode = 'edit';
        state.selectedSectionTitle = '';
        if (state.selectedBlocks && state.selectedBlocks.length > 0) {
            state.selectedBlocks.forEach((block) => block.classList.remove('selected-block'));
        }
        state.selectedBlocks = [];
        if (els.editTargetSelect) els.editTargetSelect.value = '';
        if (els.editTargetInput) els.editTargetInput.value = '';
        state.selectedRange = range.cloneRange();
        if (state.selectedBlock) {
            state.selectedBlock.classList.remove('selected-block');
        }
        const blockEl = getBlockElement(range.startContainer) || getBlockElement(range.commonAncestorContainer);
        if (blockEl && blockEl !== docRoot) {
            state.selectedBlock = blockEl;
            state.selectedBlock.classList.add('selected-block');
        }
        setSelectedSnippet(clipped);
        const rect = range.getBoundingClientRect();
        const fallbackRect = range.getClientRects().length ? range.getClientRects()[0] : null;
        showInlineEditBubble(rect && rect.width ? rect : fallbackRect);
    };

    const runTemplateEdit = async (prompt) => {
        const snippet = state.selectedSnippet;
        const instruction = buildEditInstruction(prompt, snippet, state.selectedSectionTitle);
        const baseHtml = state.templateHtml;

        const fragmentHtml = getSelectedFragment();

        if (fragmentHtml) {
            const inlineInfo = getInlineSelectionInfo();
            const hasSelectedBlocks = state.selectedBlocks && state.selectedBlocks.length > 0;
            const hasInlineSelection = !hasSelectedBlocks && !!inlineInfo;
            const fragmentSource = hasInlineSelection ? inlineInfo.fragmentHtml : fragmentHtml;
            const editInstruction = hasInlineSelection
                ? `${instruction}\n추가 규칙: 선택된 범위에 삽입 가능한 인라인 HTML만 반환하세요. <p>, <div>, <table> 같은 블록 태그는 금지합니다.`
                : instruction;
            if (hasSelectedBlocks) {
                applyEraseAnimationToBlocks(state.selectedBlocks);
            } else {
                startEraseAnimation();
            }
            await new Promise((resolve) => setTimeout(resolve, 250));
            if (hasSelectedBlocks) {
                clearEraseAnimation(state.selectedBlocks);
            } else if (state.selectedBlock) {
                clearEraseAnimation([state.selectedBlock]);
            }
            let updatedFragment = '';
            try {
                let lastStreamAt = 0;
                const previewBlock = hasSelectedBlocks ? state.selectedBlocks[0] : state.selectedBlock;
                updatedFragment = await streamHtmlFragmentEdit({
                    fragment: fragmentSource,
                    instruction: editInstruction,
                    onChunk: (partial) => {
                        if (!previewBlock || hasInlineSelection) return;
                        const now = Date.now();
                        if (now - lastStreamAt < STREAM_UPDATE_INTERVAL) return;
                        lastStreamAt = now;
                        updateBlockFromFragment(previewBlock, partial);
                        syncFrameHeight();
                    }
                });
            } catch (error) {
                if (hasSelectedBlocks) {
                    replaceBlocksWithHtml(state.selectedBlocks, fragmentHtml);
                } else if (state.selectedBlock) {
                    replaceBlocksWithHtml([state.selectedBlock], fragmentHtml);
                }
                throw error;
            }

            const fragmentCheck = validateRenderedUpdate(fragmentSource, updatedFragment);
            if (!fragmentCheck.ok) {
                if (hasSelectedBlocks) {
                    replaceBlocksWithHtml(state.selectedBlocks, fragmentHtml);
                } else if (state.selectedBlock) {
                    replaceBlocksWithHtml([state.selectedBlock], fragmentHtml);
                }
                throw new Error('편집 결과가 비어 있습니다.');
            }

            if (hasInlineSelection) {
                if (isInlineHtml(fragmentCheck.normalized)) {
                    const applied = replaceRangeWithHtml(inlineInfo.range, fragmentCheck.normalized);
                    if (!applied) {
                        replaceBlocksWithHtml([inlineInfo.block], fragmentHtml);
                        throw new Error('선택 영역 편집을 적용하지 못했습니다.');
                    }
                } else {
                    replaceBlocksWithHtml([inlineInfo.block], fragmentCheck.normalized);
                }
            } else if (hasSelectedBlocks) {
                replaceBlocksWithHtml(state.selectedBlocks, fragmentCheck.normalized);
            } else if (state.selectedBlock) {
                replaceBlocksWithHtml([state.selectedBlock], fragmentCheck.normalized);
            }
            flashDocContent();
            syncTemplateHtmlFromFrame();
            syncFrameHeight();
        } else {
            const { styleBlock, body } = splitHtmlStyles(baseHtml);
            const updatedBody = await streamHtmlEdit({
                html: body || baseHtml,
                instruction,
                onChunk: (() => {
                    let lastStreamAt = 0;
                    return (partial) => {
                        const now = Date.now();
                        if (now - lastStreamAt < STREAM_UPDATE_INTERVAL) return;
                        lastStreamAt = now;
                        updateFrameBodyFromStream(partial);
                    };
                })()
            });

            const bodyCheck = validateRenderedUpdate(baseHtml, updatedBody, { enforceStructure: true });
            if (!bodyCheck.ok) {
                state.templateHtml = baseHtml;
                renderTemplateFrame(baseHtml);
                throw new Error('편집 결과가 비어 있습니다.');
            }

            let mergedHtml = bodyCheck.normalized;
            if (styleBlock && !bodyCheck.normalized.includes('<style')) {
                mergedHtml = `${styleBlock}\n${bodyCheck.normalized}`;
            }

            state.templateHtml = mergedHtml;
            renderTemplateFrame(mergedHtml);
        }

        state.chatHistory.push({ role: 'ai', text: '문서가 업데이트되었습니다.' });
        clearSelectedSnippet();
    };

    const runInlineEdit = async () => {
        if (!els.inlineEditInput) return;
        const prompt = els.inlineEditInput.value.trim();
        if (!prompt) {
            showToast('수정 내용을 입력해주세요.', 'error');
            return;
        }
        const hasSelection = !!state.selectedSnippet
            || (state.selectedBlocks && state.selectedBlocks.length > 0)
            || !!state.selectedSectionTitle;
        if (!hasSelection) {
            showToast('수정할 부분을 먼저 선택해주세요.', 'error');
            return;
        }

        if (state.isGenerating) return;
        const bubbleRect = getInlineBubbleRect();
        startEditCoverAnimation(bubbleRect);
        hideInlineEditBubble();
        state.templateMode = 'edit';
        state.isGenerating = true;
        setLoadingState(true);
        state.chatHistory.push({ role: 'user', text: prompt });
        updateUI();
        if (!getSelectionViewportRect()) {
            scrollToBottom();
        }

        try {
            await runTemplateEdit(prompt);
        } catch (error) {
            console.error(error);
            showToast(`생성 중 오류 발생: ${error.message}`, 'error');
            state.chatHistory.push({ role: 'ai', text: `템플릿 처리 중 오류 발생: ${error.message}` });
        } finally {
            finishEditCoverAnimation();
            state.isGenerating = false;
            setLoadingState(false);
            updateUI();
            await saveChatSession();
        }
    };

    const runTemplateFillSequence = async (prompt) => {
        const buildChatContextSnippet = () => {
            const maxMessages = 8;
            const maxChars = 1200;
            const skipPattern = /양식 작성 시작|양식 작성이 완료되었습니다|업로드된 문서가 비어 있는/;
            const messages = (state.chatHistory || [])
                .filter((msg) => msg && (msg.role === 'user' || msg.role === 'ai'))
                .filter((msg) => !msg.type && typeof msg.text === 'string' && msg.text.trim())
                .map((msg) => ({
                    role: msg.role,
                    text: msg.text.replace(/\s+/g, ' ').trim()
                }))
                .filter((msg) => !skipPattern.test(msg.text));

            const recent = messages.slice(-maxMessages);
            let output = '';
            for (const msg of recent) {
                const label = msg.role === 'user' ? '사용자' : 'AI';
                let line = `[${label}] ${msg.text}`;
                if (line.length > 400) {
                    line = `${line.slice(0, 400)}...`;
                }
                if (output.length + line.length + 1 > maxChars) break;
                output += (output ? '\n' : '') + line;
            }
            return output;
        };

        const historyContext = buildChatContextSnippet();
        const enrichedPrompt = historyContext
            ? `이전 대화 기록을 참고하여 작성하세요.\n${historyContext}\n\n${prompt}`
            : prompt;
        const sections = (() => {
            if (Array.isArray(state.fillDetectedFields) && state.fillDetectedFields.length > 0) {
                return state.fillDetectedFields;
            }
            if (Array.isArray(state.templateFillFields) && state.templateFillFields.length > 0) {
                return state.templateFillFields;
            }
            if (Array.isArray(state.templateSections) && state.templateSections.length > 0) {
                return state.templateSections;
            }
            return ['전체'];
        })();
        renderSectionFillPanel(sections);

        let currentHtml = state.templateHtml;
        state.chatHistory.push({ role: 'ai', text: '양식 작성 시작. 파트별로 내용을 채우겠습니다.' });

        const canResolveAny = sections.some((section) => {
            const target = findFillTargetForField(section);
            return (target.blocks && target.blocks.length > 0) || target.skip;
        });
        const hasFieldSections = Array.isArray(state.fillDetectedFields) && state.fillDetectedFields.length > 0;
        const onlyFullDoc = sections.length === 1 && sections[0] === '전체';

        if (!canResolveAny && hasFieldSections && !onlyFullDoc) {
            sections.forEach((section) => updateSectionFillStatus(section, 'error'));
            state.chatHistory.push({ role: 'ai', text: '작성할 위치를 찾지 못했습니다. 양식 구조를 다시 확인해주세요.' });
            state.templateMode = 'edit';
            renderEditTargetOptions();
            updateTemplateControls();
            if (els.sectionFillPanel) {
                setTimeout(() => els.sectionFillPanel.classList.add('hidden'), 1200);
            }
            return;
        }

        if (!canResolveAny || onlyFullDoc) {
            const sectionLabel = sections[0] || '전체';
            updateSectionFillStatus(sectionLabel, 'active');
            const instruction = `사용자 요청: ${enrichedPrompt}\n전체 양식을 빠짐없이 채워 넣고, 기존 구조는 유지하세요.`;
            const { styleBlock, body } = splitHtmlStyles(currentHtml);
            const updatedBody = await streamHtmlEdit({
                html: body || currentHtml,
                instruction,
                onChunk: (() => {
                    let lastStreamAt = 0;
                    return (partial) => {
                        const now = Date.now();
                        if (now - lastStreamAt < STREAM_UPDATE_INTERVAL) return;
                        lastStreamAt = now;
                        updateFrameBodyFromStream(partial);
                    };
                })()
            });
            const bodyCheck = validateRenderedUpdate(currentHtml, updatedBody, { enforceStructure: true });
            if (!bodyCheck.ok) {
                updateSectionFillStatus(sectionLabel, 'error');
                throw new Error('전체 작성 결과가 비어 있습니다.');
            }
            let mergedHtml = bodyCheck.normalized;
            if (styleBlock && !bodyCheck.normalized.includes('<style')) {
                mergedHtml = `${styleBlock}\n${bodyCheck.normalized}`;
            }
            currentHtml = mergedHtml;
            state.templateHtml = mergedHtml;
            renderTemplateFrame(mergedHtml);
            sections.forEach((section) => updateSectionFillStatus(section, 'done'));
        } else {
            for (const section of sections) {
                updateSectionFillStatus(section, 'active');
                const instruction = `사용자 요청: ${enrichedPrompt}\n다음 섹션(${section})에 해당하는 부분만 채워 넣고, 다른 부분은 유지하세요.`;

                const { blocks, fragment, skip } = findFillTargetForField(section);
                if (skip) {
                    updateSectionFillStatus(section, 'done');
                    continue;
                }
                if (!fragment || !blocks || blocks.length === 0) {
                    updateSectionFillStatus(section, 'error');
                    continue;
                }

                applyEraseAnimationToBlocks(blocks);
                await new Promise((resolve) => setTimeout(resolve, 250));
                clearEraseAnimation(blocks);

                let updatedFragment = '';
                try {
                    let lastStreamAt = 0;
                    const previewBlock = blocks[0];
                    updatedFragment = await streamHtmlFragmentEdit({
                        fragment,
                        instruction,
                        onChunk: (partial) => {
                            if (!previewBlock) return;
                            const now = Date.now();
                            if (now - lastStreamAt < STREAM_UPDATE_INTERVAL) return;
                            lastStreamAt = now;
                            updateBlockFromFragment(previewBlock, partial);
                            syncFrameHeight();
                        }
                    });
                } catch (error) {
                    replaceBlocksWithHtml(blocks, fragment);
                    updateSectionFillStatus(section, 'error');
                    throw error;
                }

                const fragmentCheck = validateRenderedUpdate(fragment, updatedFragment);
                if (!fragmentCheck.ok) {
                    replaceBlocksWithHtml(blocks, fragment);
                    updateSectionFillStatus(section, 'error');
                    throw new Error(`"${section}" 섹션 작성 결과가 비어 있습니다.`);
                }
                if (blocks.length === 1 && blocks[0].matches('td, th')) {
                    const applied = applyFillContentToCell(blocks[0], fragmentCheck.normalized);
                    if (!applied) {
                        replaceBlocksWithHtml(blocks, fragmentCheck.normalized);
                    }
                } else {
                    replaceBlocksWithHtml(blocks, fragmentCheck.normalized);
                }
                flashDocContent();
                syncTemplateHtmlFromFrame();
                currentHtml = state.templateHtml;
                syncFrameHeight();
                updateSectionFillStatus(section, 'done');
            }
        }

        state.templateMode = 'edit';
        renderEditTargetOptions();
        updateTemplateControls();

        if (els.sectionFillPanel) {
            setTimeout(() => els.sectionFillPanel.classList.add('hidden'), 1200);
        }

        state.chatHistory.push({ role: 'ai', text: '양식 작성이 완료되었습니다.' });
        await handleDownload();
    };

    // ============================================================
    // 3. 보조 기능 (이미지, UI 상태 등)
    // ============================================================

    const updateSendButtonState = (isLoading = state.isGenerating) => {
        if (!els.btnSend) return;
        const hasInput = !!(els.userRequest && els.userRequest.value.trim());
        const loading = !!isLoading;

        els.btnSend.classList.toggle('active', hasInput && !loading);
        els.btnSend.classList.toggle('loading', loading);
        els.btnSend.disabled = !hasInput && !loading;
        els.btnSend.setAttribute('aria-busy', loading ? 'true' : 'false');
        els.btnSend.setAttribute('aria-disabled', (!hasInput || loading) ? 'true' : 'false');

        if (els.iconSend) els.iconSend.classList.toggle('hidden', loading);
        if (els.spinnerSend) els.spinnerSend.classList.toggle('hidden', !loading);
    };

    const setLoadingState = (loading) => {
        updateSendButtonState(loading);
    };

    const showToast = (msg, type='info') => {
        if (!els.toast) return;
        els.toast.textContent = msg;
        els.toast.className = 'toast show ' + type; // CSS 가정
        els.toast.style.opacity = '1';
        setTimeout(() => { els.toast.style.opacity = '0'; }, 3000);
    };

    // ============================================================
    // 인증 상태 관리
    // ============================================================

    const resolveProviderLabel = (user) => {
        if (!user || !user.id) return 'Guest';
        const id = String(user.id);
        if (id.startsWith('google_')) return 'Google 계정';
        if (id.startsWith('kakao_')) return 'Kakao 계정';
        if (id.startsWith('naver_')) return 'Naver 계정';
        if (id.startsWith('admin_')) return 'Admin 계정';
        if (id.startsWith('demo_')) return 'Demo 계정';
        if (id.startsWith('user_')) return 'Local 계정';
        return '계정';
    };

    const renderUserProfile = () => {
        const name = state.user?.name || 'Guest';
        const email = state.user?.email || '로그인 필요';
        const initial = (name || email || 'G').trim().charAt(0).toUpperCase() || 'G';
        const picture = state.user?.picture || '';
        const providerLabel = resolveProviderLabel(state.user);
        const { isPremium } = getPremiumState();

        if (els.userNameLabel) els.userNameLabel.textContent = name;
        if (els.userEmailLabel) els.userEmailLabel.textContent = email;
        if (els.userAvatar) {
            if (picture) {
                els.userAvatar.classList.add('has-photo');
                els.userAvatar.style.backgroundImage = `url("${picture}")`;
                els.userAvatar.textContent = '';
            } else {
                els.userAvatar.classList.remove('has-photo');
                els.userAvatar.style.backgroundImage = '';
                els.userAvatar.textContent = initial;
            }
        }
        if (els.profileName) els.profileName.textContent = name;
        if (els.profileEmail) els.profileEmail.textContent = email;
        if (els.profileProvider) {
            if (isPremium) {
                els.profileProvider.textContent = '프리미엄 계정';
                els.profileProvider.classList.add('profile-provider--premium');
            } else {
                els.profileProvider.textContent = providerLabel;
                els.profileProvider.classList.remove('profile-provider--premium');
            }
        }
        if (els.profileAvatar) {
            if (picture) {
                els.profileAvatar.classList.add('has-photo');
                els.profileAvatar.style.backgroundImage = `url("${picture}")`;
                els.profileAvatar.textContent = '';
            } else {
                els.profileAvatar.classList.remove('has-photo');
                els.profileAvatar.style.backgroundImage = '';
                els.profileAvatar.textContent = initial;
            }
        }
        if (els.profileLogin) {
            els.profileLogin.style.display = state.user ? 'none' : 'flex';
        }
        if (els.profileLogout) {
            els.profileLogout.style.display = state.user ? 'flex' : 'none';
        }

        if (els.btnAuthToggle) {
            els.btnAuthToggle.innerHTML = state.user
                ? '<i class="bi bi-box-arrow-right"></i>'
                : '<i class="bi bi-box-arrow-in-right"></i>';
            els.btnAuthToggle.title = state.user ? '로그아웃' : '로그인';
        }

        // Toggle Login Button visibility
        if (els.btnOpenAuth) {
            els.btnOpenAuth.style.display = state.user ? 'none' : 'flex';
        }

        applyAccountUIState();
    };

    const getSafeNextPath = () => {
        const next = window.location.pathname + window.location.search;
        if (!next.startsWith('/') || next.startsWith('//')) return '/';
        return next;
    };

    const withNextParam = (base) => {
        const next = getSafeNextPath();
        const joiner = base.includes('?') ? '&' : '?';
        return `${base}${joiner}next=${encodeURIComponent(next)}`;
    };

    const updateAuthLinks = () => {
        if (els.btnAuthGoogle) {
            els.btnAuthGoogle.href = withNextParam('/api/auth/social/google');
        }
    };

    const setAuthStatus = (msg, type='muted') => {
        if (!els.authStatus) return;
        const colors = {
            error: '#f87171',
            success: '#10B981',
            muted: '#94A3B8'
        };
        els.authStatus.textContent = msg;
        els.authStatus.style.color = colors[type] || colors.muted;
    };

    const setAuthLoading = (loading) => {
        [els.btnAuthLogin, els.btnAuthRegister].forEach(btn => {
            if (!btn) return;
            if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent;
            btn.disabled = loading;
            btn.textContent = loading ? '처리 중...' : btn.dataset.originalText;
        });
    };

    const openAuthModal = () => {
        if (!els.modalAuth) return;
        els.modalAuth.style.display = 'flex';
        setTimeout(() => els.modalAuth.classList.add('show'), 10);
    };

    const closeAuthModal = () => {
        if (!els.modalAuth) return;
        els.modalAuth.classList.remove('show');
        setTimeout(() => els.modalAuth.style.display = 'none', 200);
    };

    const openProfileModal = () => {
        if (!els.modalProfile || !els.profileModalBox) return;
        renderUserProfile();
        els.modalProfile.style.display = 'flex';

        const anchor = els.userProfile;
        const modalBox = els.profileModalBox;
        const gap = 12;

        let top = (window.innerHeight - modalBox.offsetHeight) / 2;
        let left = (window.innerWidth - modalBox.offsetWidth) / 2;
        let origin = '50% 50%';

        if (anchor) {
            const rect = anchor.getBoundingClientRect();
            const modalRect = modalBox.getBoundingClientRect();
            left = rect.right - modalRect.width;
            top = rect.top - modalRect.height - gap;
            let placeBelow = false;
            if (top < 12) {
                top = rect.bottom + gap;
                placeBelow = true;
            }
            const maxLeft = window.innerWidth - modalRect.width - 12;
            const maxTop = window.innerHeight - modalRect.height - 12;
            left = Math.min(Math.max(left, 12), Math.max(12, maxLeft));
            top = Math.min(Math.max(top, 12), Math.max(12, maxTop));
            origin = placeBelow ? '50% 0%' : '50% 100%';
        }

        modalBox.style.left = `${left}px`;
        modalBox.style.top = `${top}px`;
        modalBox.style.transformOrigin = origin;

        setTimeout(() => els.modalProfile.classList.add('show'), 10);
    };

    const closeProfileModal = () => {
        if (!els.modalProfile) return;
        els.modalProfile.classList.remove('show');
        setTimeout(() => els.modalProfile.style.display = 'none', 200);
    };

    const fetchAuthMe = async () => {
        try {
            const res = await fetch('/api/auth/me');
            const data = await res.json();
            state.user = data && data.authenticated ? data.user : null;
        } catch (e) {
            console.warn('Auth check failed', e);
            state.user = null;
        } finally {
            state.authChecked = true;
            renderUserProfile();
            loadChatSessions();
        }
    };

    const readAuthForm = () => ({
        name: els.authName?.value.trim() || '',
        email: els.authEmail?.value.trim(),
        password: els.authPassword?.value || ''
    });

    const handleAuthLogin = async () => {
        const { email, password } = readAuthForm();
        if (!email || !password) {
            setAuthStatus('이메일과 비밀번호를 입력하세요.', 'error');
            return;
        }
        setAuthLoading(true);
        setAuthStatus('로그인 중...', 'muted');
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || '로그인 실패');
            state.user = data.user;
            renderUserProfile();
            setAuthStatus('로그인 완료!', 'success');
            showToast('로그인되었습니다.', 'success');
            closeAuthModal();
        } catch (e) {
            console.error(e);
            setAuthStatus(e.message, 'error');
            showToast(e.message, 'error');
        } finally {
            setAuthLoading(false);
        }
    };

    const handleAuthRegister = async () => {
        const { name, email, password } = readAuthForm();
        if (!email || !password) {
            setAuthStatus('이메일과 비밀번호를 입력하세요.', 'error');
            return;
        }
        setAuthLoading(true);
        setAuthStatus('계정을 생성하는 중...', 'muted');
        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, email, password })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || '회원가입 실패');
            state.user = data.user;
            renderUserProfile();
            setAuthStatus('가입이 완료되었습니다.', 'success');
            showToast('로그인되었습니다.', 'success');
            closeAuthModal();
        } catch (e) {
            console.error(e);
            setAuthStatus(e.message, 'error');
            showToast(e.message, 'error');
        } finally {
            setAuthLoading(false);
        }
    };

    const handleAuthLogout = async () => {
        try {
            await fetch('/api/auth/logout', { method: 'POST' });
        } catch (e) {
            console.warn('Logout failed', e);
        }
        state.user = null;
        renderUserProfile();
        showToast('로그아웃되었습니다.', 'success');
    };

    // 이미지 단일 로드 처리 (재시도 지원)
    const loadImage = async (box) => {
        if (box.classList.contains('loaded') || box.classList.contains('loading')) return;
        
        const keyword = box.dataset.keyword;
        box.classList.add('loading');
        // 로딩 중 UI
        box.innerHTML = `<div class="spinner"></div><span>"${keyword}" 생성 중...</span>`;

        try {
            const res = await fetch(API_ENDPOINTS.IMAGE, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ query: keyword, count: 1 })
            });
            const data = await res.json();
            
            if (data.images && data.images.length > 0) {
                const imgUrl = data.images[0].url || data.images[0].data;
                // 이미지 로드 성공
                box.innerHTML = `<img src="${imgUrl}" alt="${keyword}" style="width:100%; border-radius:8px; box-shadow:0 4px 12px rgba(0,0,0,0.1); display:block;">`;
                box.classList.remove('loading');
                box.classList.add('loaded');
            } else {
                throw new Error('이미지를 찾을 수 없습니다.');
            }
        } catch (e) {
            console.error(e);
            box.classList.remove('loading');
            // 에러 UI: 물음표 아이콘 + 재시도 버튼
            box.innerHTML = `
                <div style="display:flex; flex-direction:column; align-items:center; gap:10px; color:#64748B; padding:10px;">
                    <i class="bi bi-question-circle-fill" style="font-size:2rem; color:#CBD5E1;"></i>
                    <div style="font-size:0.9rem;">이미지 생성에 실패했습니다.</div>
                    <button class="btn-retry-img" style="
                        padding: 8px 16px; 
                        border: 1px solid #E2E8F0; 
                        border-radius: 8px; 
                        background: #fff; 
                        color: #0F172A; 
                        cursor: pointer; 
                        font-size: 0.85rem; 
                        font-weight: 600; 
                        display: flex; 
                        align-items: center; 
                        gap: 6px;
                        transition: all 0.2s;
                        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
                    ">
                        <i class="bi bi-arrow-clockwise"></i> 다시 시도
                    </button>
                </div>
            `;
            
            // 재시도 버튼 이벤트 연결
            const btn = box.querySelector('.btn-retry-img');
            if(btn) {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation(); 
                    loadImage(box); // 재귀 호출로 다시 시도
                });
                // 버튼 호버 효과 (JS로 간단히 처리하거나 CSS 클래스로 할 수도 있음)
                btn.addEventListener('mouseenter', () => btn.style.background = '#F8FAFC');
                btn.addEventListener('mouseleave', () => btn.style.background = '#fff');
            }
        }
    };

    // 이미지 플레이스홀더 처리 (Loop)
    const resolveImages = async () => {
        if (!els.docContent) return;
        const placeholders = els.docContent.querySelectorAll('.img-placeholder-box');
        
        for (const box of placeholders) {
            // 이미 로드되었거나 로딩 중이면 패스. 
            // 단, 에러 상태(재시도 버튼 있음)인 경우는 사용자가 누르길 기다림 (자동 재시도 X)
            if (box.classList.contains('loaded') || box.classList.contains('loading')) continue;
            
            // 에러 UI가 이미 그려져 있는 경우도 패스 (중복 호출 방지)
            if (box.querySelector('.btn-retry-img')) continue;

            loadImage(box);
        }
    };

    // ============================================================
    // 3.5. RiroSchool Logic
    // ============================================================

    const normalizeRiroEvents = (raw) => {
        if (!raw) return [];
        let events = [];
        if (Array.isArray(raw)) {
            events = raw;
        } else if (typeof raw === 'object') {
            Object.entries(raw).forEach(([date, value]) => {
                if (Array.isArray(value)) {
                    value.forEach(item => {
                        if (!item) return;
                        events.push({ ...(item || {}), date: item.date || date });
                    });
                } else if (value && typeof value === 'object') {
                    events.push({ ...value, date: value.date || date });
                }
            });
        }
        events = events.map(evt => ({
            ...evt,
            date: evt.date || evt.raw_date || '',
            type: evt.type || 'assignment'
        }));
        try {
            events.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
        } catch (e) { /* ignore */ }
        return events;
    };

    const saveRiroEvents = (events, forceLoggedIn = false) => {
        state.riroEvents = events;
        state.riroLoggedIn = forceLoggedIn || events.length > 0 || state.riroLoggedIn;
        localStorage.setItem('riro_events', JSON.stringify(events));
        localStorage.setItem('riro_logged_in', state.riroLoggedIn ? 'true' : 'false');
    };

    const loadRiroFromStorage = () => {
        try {
            const stored = localStorage.getItem('riro_events');
            const parsed = stored ? JSON.parse(stored) : [];
            const wasLogged = localStorage.getItem('riro_logged_in') === 'true';
            saveRiroEvents(normalizeRiroEvents(parsed), wasLogged);
        } catch (e) {
            console.warn('Failed to load Riro events from storage', e);
            saveRiroEvents([]);
        }
    };

    const buildRiroSummary = (events) => {
        if (!events || events.length === 0) return '리로스쿨 일정이 없습니다.';
        const lines = events.slice(0, 5).map(evt => {
            const guide = evt.guide ? ` — ${evt.guide.slice(0, 120)}${evt.guide.length > 120 ? '...' : ''}` : '';
            return `- ${evt.date || '날짜 미정'}: ${evt.title}${guide}`;
        });
        return [
            `✅ **리로스쿨 연동 완료!** 총 ${events.length}개의 수행평가/일정을 가져왔어요.`,
            ...lines,
            '',
            "이 정보를 참고해 일정 관리나 학습 계획을 물어보면 바로 답해줄게요."
        ].join('\n');
    };

    const renderCalendar = () => {
        const calendarEl = document.getElementById('calendarView');
        if (!calendarEl || typeof FullCalendar === 'undefined') return;

        const cached = localStorage.getItem('riro_events');
        const fallback = cached ? normalizeRiroEvents(JSON.parse(cached)) : [];
        const events = (state.riroEvents && state.riroEvents.length > 0)
            ? state.riroEvents
            : fallback;

        if (!events.length) {
            calendarEl.innerHTML = '<div style="padding:12px; color:#64748B;">리로스쿨에서 불러온 일정이 없습니다.</div>';
            return;
        }

        calendarEl.innerHTML = '';

        // FullCalendar 포맷으로 변환
        const fcEvents = events.map(evt => {
            let color = '#3788d8'; // 기본 파란색
            if (evt.type === 'assignment') color = '#e11d48'; // 과제: 빨간색
            if (evt.type === 'notice') color = '#059669'; // 공지: 초록색
            
            return {
                title: `[${evt.type === 'assignment' ? '과제' : '공지'}] ${evt.title}`,
                start: evt.date, // YYYY-MM-DD
                backgroundColor: color,
                borderColor: color,
                extendedProps: {
                    original: evt
                }
            };
        });

        const calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,listMonth'
            },
            events: fcEvents,
            height: 'auto',
            locale: 'ko',
            eventClick: function(info) {
                const props = info.event.extendedProps.original;
                const guideText = props.guide || props.guide_text || props.description || '';
                const chatNote = `📌 **${props.title}** (${props.date || '날짜 미정'})\n${guideText || '제출 안내가 없습니다.'}`;
                state.chatHistory.push({ role: 'ai', text: chatNote });
                state.docMode = false;
                updateUI();
                showToast('채팅에 수행평가 정보를 추가했어요.', 'success');
                if (els.modalCalendar) {
                    els.modalCalendar.classList.remove('show');
                    setTimeout(() => { els.modalCalendar.style.display = 'none'; }, 200);
                }
            }
        });
        calendar.render();
    };

    const handleRiroLogin = async () => {
        const school = els.riroSchool?.value.trim();
        const username = els.riroId?.value.trim();
        const password = els.riroPw?.value.trim();
        
        if (!school || !username || !password) {
            showToast('학교, 아이디, 비밀번호를 모두 입력해주세요.', 'error');
            return;
        }
        
        const btn = els.btnLoginAction;
        const originalText = btn.textContent;
        btn.textContent = '로그인 중...';
        btn.disabled = true;
        
        try {
            const response = await fetch('/api/riroschool/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ school, username, password, grade: '1', year: '2025' })
            });
            const data = await response.json();
            
            if (data.success) {
                const normalizedEvents = normalizeRiroEvents(data.events || data.events_by_date);
                saveRiroEvents(normalizedEvents, true);
                showToast('리로스쿨 연동 성공!', 'success');
                
                if (normalizedEvents.length) {
                    renderCalendar(); // 캘린더 갱신
                    state.chatHistory.push({ 
                        role: 'ai', 
                        text: buildRiroSummary(normalizedEvents)
                    });
                    updateUI();
                    
                    // 캘린더 모달 열기
                    if (els.modalCalendar) {
                        els.modalCalendar.style.display = 'flex';
                        setTimeout(() => {
                            els.modalCalendar.classList.add('show');
                            renderCalendar();
                        }, 10);
                    }
                } else {
                    state.chatHistory.push({
                        role: 'ai',
                        text: '리로스쿨 연동은 완료됐지만 가져올 수행평가 일정이 없습니다.'
                    });
                    updateUI();
                }

                // Close login modal
                if (els.modalLogin) {
                    els.modalLogin.classList.remove('show');
                    setTimeout(() => els.modalLogin.style.display='none', 300);
                }
            } else {
                throw new Error(data.error || '로그인 실패');
            }
        } catch (e) {
            showToast(e.message, 'error');
        } finally {
            btn.textContent = originalText;
            btn.disabled = false;
        }
    };

    // ============================================================
    // 3.6. Chat History Management
    // ============================================================

    const restoreSessionFromLocalStorage = async () => {
        localStorage.removeItem('lastLoadedSessionId');
        localStorage.removeItem('lastLoadedDocMode');
        state.currentSessionId = null;
        state.chatHistory = [];
        state.docMode = false;
        clearChatStream();
        updateUI();
        loadChatSessions();
    };

    const resetChatSession = ({ clearTemplate = false, closeSidebar = false } = {}) => {
        state.chatHistory = [];
        state.currentSessionId = null;
        state.document = { title: '', content: '' };
        state.docMode = false;
        state.streamingBuffer = '';
        state.displayedChatContent = '';
        state.displayedDocContent = '';
        if (state.chatTypingTimeoutId) clearTimeout(state.chatTypingTimeoutId);
        if (state.docTypingTimeoutId) clearTimeout(state.docTypingTimeoutId);
        state.chatTypingTimeoutId = null;
        state.docTypingTimeoutId = null;
        state.isGenerating = false;
        localStorage.removeItem('lastLoadedSessionId');
        localStorage.removeItem('lastLoadedDocMode');
        clearChatStream();

        if (clearTemplate) {
            clearFileSelection();
        } else {
            updateUI();
        }

        loadChatSessions();
        if (closeSidebar) toggleSidebar(false);
    };

    const loadChatSessions = async () => {
        // if (!state.user) return; // Allow guests
        try {
            const res = await fetch('/api/chat/sessions');
            const data = await res.json();
            
            if (data.success && els.workspaceList) {
                els.workspaceList.innerHTML = ''; // Clear list
                
                // Add "New Chat" button/item logic if needed, but sidebar has a dedicated button
                
                data.sessions.forEach(session => {
                    const div = document.createElement('div');
                    div.className = 'nav-item';
                    if (session.id === state.currentSessionId) div.classList.add('active'); 
                    
                    const title = session.title || '새로운 대화';
                    const displayTitle = title.length > 15 ? title.substring(0, 15) + '...' : title;
                    
                    div.innerHTML = `
                        <div class="session-item-content" style="display:flex; align-items:center; gap:12px; flex:1; overflow:hidden;">
                            <i class="bi bi-chat-left-text"></i>
                            <span style="overflow:hidden; text-overflow:ellipsis;">${displayTitle}</span>
                        </div>
                        <div style="display:flex; align-items:center; gap:4px;">
                            ${session.id === state.currentSessionId ? '<i class="bi bi-check" style="color:var(--accent-primary); font-size:1.1rem;"></i>' : ''}
                            <div class="btn-delete-session" style="padding:4px; border-radius:4px; color:#94A3B8; transition:all 0.2s; display:flex; align-items:center; justify-content:center;">
                                <i class="bi bi-trash" style="font-size:0.9rem;"></i>
                            </div>
                        </div>
                    `;
                    
                    // Main click (Load Session)
                    const contentArea = div.querySelector('.session-item-content');
                    contentArea.addEventListener('click', () => loadChatSession(session.id));
                    
                    // Delete click
                    const deleteBtn = div.querySelector('.btn-delete-session');
                    deleteBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if(confirm('정말 이 대화를 삭제하시겠습니까?')) {
                            handleDeleteSession(session.id);
                        }
                    });
                    
                    // Delete hover effect
                    deleteBtn.addEventListener('mouseenter', () => { deleteBtn.style.color = '#EF4444'; deleteBtn.style.background = 'rgba(239, 68, 68, 0.1)'; });
                    deleteBtn.addEventListener('mouseleave', () => { deleteBtn.style.color = '#94A3B8'; deleteBtn.style.background = 'transparent'; });

                    els.workspaceList.appendChild(div);
                });
            }
        } catch (e) {
            console.error('Failed to load chat sessions', e);
        }
    };

    const handleDeleteSession = async (sessionId) => {
        try {
            const res = await fetch(`/api/chat/sessions/${sessionId}`, {
                method: 'DELETE'
            });
            const data = await res.json();
            
            if (data.success) {
                showToast('대화가 삭제되었습니다.', 'success');
                if (state.currentSessionId === sessionId) {
                    // Reset if current session was deleted
                    state.chatHistory = [];
                    state.currentSessionId = null;
                    state.docMode = false;
                    updateUI();
                }
                loadChatSessions();
            } else {
                throw new Error(data.error || '삭제 실패');
            }
        } catch (e) {
            showToast(e.message, 'error');
        }
    };

    const loadChatSession = async (sessionId) => {
        try {
            // Reset current view
            state.chatHistory = [];
            state.docMode = false;
            clearChatStream();
            updateUI();
            
            const res = await fetch(`/api/chat/sessions/${sessionId}`);
            const data = await res.json();
            
            if (data.success && data.session) {
                state.currentSessionId = data.session.id;
                state.chatHistory = data.session.messages || [];
                clearChatStream();
                // Save this session as the last loaded one
                localStorage.setItem('lastLoadedSessionId', sessionId);
                localStorage.setItem('lastLoadedDocMode', state.docMode);
                
                updateUI();
                scrollToBottom();
                
                // Refresh list to show active state
                loadChatSessions();
                
                // Mobile: Close sidebar
                toggleSidebar(false);
            }
        } catch (e) {
            showToast('대화 기록을 불러오지 못했습니다.', 'error');
            localStorage.removeItem('lastLoadedSessionId'); // Clear invalid session
            localStorage.removeItem('lastLoadedDocMode');
        }
    };


    const saveChatSession = async () => {
        if (state.chatHistory.length === 0) return;
        
        try {
            if (state.currentSessionId) {
                // Update existing
                await fetch(`/api/chat/sessions/${state.currentSessionId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        messages: state.chatHistory
                    })
                });
                localStorage.setItem('lastLoadedSessionId', state.currentSessionId);
                localStorage.setItem('lastLoadedDocMode', state.docMode);
                // Reload list to update sorting/active state
                loadChatSessions();
            } else {
                // Create new
                // Use first user message as title
                const firstMsg = state.chatHistory.find(m => m.role === 'user');
                const title = firstMsg ? firstMsg.text.substring(0, 30) : '새로운 대화';
                
                const res = await fetch('/api/chat/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        title: title,
                        messages: state.chatHistory
                    })
                });
                const data = await res.json();
                if (data.success) {
                    console.log('New session created:', data.session.id);
                    state.currentSessionId = data.session.id;
                    localStorage.setItem('lastLoadedSessionId', state.currentSessionId);
                    localStorage.setItem('lastLoadedDocMode', state.docMode);
                    await loadChatSessions(); // Ensure list is refreshed
                }
            }
        } catch (e) {
            console.error('Failed to save chat session', e);
        }
    };

    // ============================================================
    // 4. 이벤트 리스너 바인딩
    // ============================================================

    // 입력창 엔터 & 클릭
    if (els.userRequest) {
        els.userRequest.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleGenerate();
            }
        });
        els.userRequest.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            updateSendButtonState();
        });
    }
    if (els.btnSend) els.btnSend.addEventListener('click', handleGenerate);
    updateSendButtonState();
    if (els.btnLoginAction) els.btnLoginAction.addEventListener('click', handleRiroLogin);
    if (els.btnAuthLogin) els.btnAuthLogin.addEventListener('click', handleAuthLogin);
    if (els.btnAuthRegister) els.btnAuthRegister.addEventListener('click', handleAuthRegister);
    if (els.btnOpenAuth) {
        els.btnOpenAuth.addEventListener('click', () => {
            window.location.href = withNextParam('/login');
        });
    }
    if (els.btnAuthToggle) {
        els.btnAuthToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (state.user) {
                handleAuthLogout();
            } else {
                window.location.href = withNextParam('/login');
            }
        });
    }
    if (els.userProfile) {
        els.userProfile.addEventListener('click', () => {
            openProfileModal();
        });
    }
    if (els.closeProfile) {
        els.closeProfile.addEventListener('click', closeProfileModal);
    }
    if (els.modalProfile) {
        els.modalProfile.addEventListener('click', (e) => {
            if (e.target === els.modalProfile) closeProfileModal();
        });
    }
    if (els.profileLogin) {
        els.profileLogin.addEventListener('click', () => {
            closeProfileModal();
            if (!state.user) {
                window.location.href = withNextParam('/login');
            }
        });
    }
    if (els.profileLogout) {
        els.profileLogout.addEventListener('click', async () => {
            await handleAuthLogout();
            closeProfileModal();
        });
    }
    const btnCloseAuth = document.getElementById('closeAuth');
    if (btnCloseAuth) btnCloseAuth.addEventListener('click', closeAuthModal);

    // New Chat Button
    if (els.btnNewChat) {
        els.btnNewChat.addEventListener('click', () => {
            resetChatSession({ clearTemplate: true, closeSidebar: true });
        });
    }

    // Download Buttons
    const btnDownloadSide = document.getElementById('btnDownloadSide');
    const btnDownloadMobile = document.getElementById('btnDownloadMobile');
    if (btnDownloadSide) btnDownloadSide.addEventListener('click', handleDownload);
    if (btnDownloadMobile) btnDownloadMobile.addEventListener('click', handleDownload);

    // 모드 토글 (Chat <-> Doc)
    if (els.btnDocMode) {
        els.btnDocMode.addEventListener('click', () => {
            state.docMode = !state.docMode;
            localStorage.setItem('lastLoadedDocMode', state.docMode); // Persist docMode
            els.btnDocMode.classList.toggle('on', state.docMode); // CSS 클래스 토글
            updateUI();
        });
    }

    // 파일 첨부 메뉴
    const btnUpload = document.getElementById('btnUploadTemplate');
    if (btnUpload) {
        btnUpload.innerHTML = '<i class="bi bi-upload"></i> 파일 업로드'; // 텍스트 변경
        btnUpload.addEventListener('click', (e) => {
            e.stopPropagation(); // 메뉴 닫기 방지 (파일 선택창이 뜨므로)
            const fileInput = document.getElementById('fileInput');
            if (fileInput) fileInput.click();
        });
    }

    const btnSelectTemplate = document.getElementById('btnSelectTemplate');
    if (btnSelectTemplate) {
        btnSelectTemplate.addEventListener('click', (e) => {
            e.stopPropagation();
            openTemplateModal();
            els.attachMenu?.classList.remove('open');
        });
    }

    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            handleFileUpload(file);
        });
    }

    if (els.docFrame) {
        els.docFrame.addEventListener('load', () => {
            attachFrameListeners();
        });
    }

    window.addEventListener('resize', () => {
        updateCanvasLayoutVars();
        if (!els.docFrame || !state.templateHtml) return;
        requestAnimationFrame(() => syncFrameLayout());
    });

    if (els.canvasBody) {
        els.canvasBody.addEventListener('scroll', () => {
            dismissEditCover();
            clearSelectedSnippet();
        }, { passive: true });
    }

    if (els.canvasResizeHandle) {
        els.canvasResizeHandle.addEventListener('pointerdown', startCanvasResize);
        els.canvasResizeHandle.addEventListener('keydown', (event) => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            const metrics = getCanvasLayoutMetrics();
            if (metrics.overlayMode) return;
            event.preventDefault();
            const step = event.shiftKey ? 64 : 24;
            const baseWidth = Number.isFinite(state.canvasUserWidth)
                ? state.canvasUserWidth
                : (els.canvasPanel ? els.canvasPanel.getBoundingClientRect().width : metrics.maxCanvas);
            const delta = event.key === 'ArrowLeft' ? step : -step;
            const nextWidth = clampCanvasWidth(baseWidth + delta, metrics);
            state.canvasUserWidth = nextWidth;
            persistCanvasUserWidth(nextWidth);
            updateCanvasLayoutVars();
        });
        window.addEventListener('pointermove', updateCanvasResize);
        window.addEventListener('pointerup', endCanvasResize);
        window.addEventListener('pointercancel', endCanvasResize);
        window.addEventListener('blur', () => endCanvasResize());
    }

    if (els.scrollContainer) {
        els.scrollContainer.addEventListener('scroll', () => {
            dismissEditCover();
        }, { passive: true });
    }

    if (els.btnCanvasClose) {
        els.btnCanvasClose.addEventListener('click', async () => {
            closeCanvasOverlay(true);
            const title = state.templateName || state.document.title || '문서';
            const summary = getCanvasSummary(state.templateHtml) || '내용 미리보기 없음';
            state.chatHistory.push({
                role: 'canvas',
                type: 'canvas',
                title,
                summary
            });
            updateUI();
            scrollToBottom();
            await saveChatSession();
        });
    }
    if (els.chatStream) {
        els.chatStream.addEventListener('click', (e) => {
            const verifyBtn = e.target.closest('[data-action="verification-confirm"], [data-action="verification-cancel"]');
            if (verifyBtn) {
                if (!els.userRequest) return;
                const action = verifyBtn.dataset.action;
                const value = action === 'verification-cancel' ? '취소' : '확인';
                if (state.isGenerating) return;
                els.userRequest.value = value;
                handleGenerate();
                return;
            }
            const card = e.target.closest('[data-action="open-canvas"]');
            if (!card) return;
            openCanvasOverlay(true);
            updateUI();
        });
        els.chatStream.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            const card = e.target.closest('[data-action="open-canvas"]');
            if (!card) return;
            e.preventDefault();
            openCanvasOverlay(true);
            updateUI();
        });
    }

    if (els.clearSelectionBtn) {
        els.clearSelectionBtn.addEventListener('click', (e) => {
            e.preventDefault();
            clearSelectedSnippet();
        });
    }

    if (els.editTargetApply) {
        els.editTargetApply.addEventListener('click', (e) => {
            e.preventDefault();
            applyEditTargetSelection();
        });
    }
    if (els.editTargetSelect) {
        els.editTargetSelect.addEventListener('change', () => {
            if (els.editTargetInput) els.editTargetInput.value = '';
            applyEditTargetSelection();
        });
    }
    if (els.editTargetInput) {
        els.editTargetInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                applyEditTargetSelection();
            }
        });
        els.editTargetInput.addEventListener('input', () => {
            if (els.editTargetInput.value.trim() && els.editTargetSelect) {
                els.editTargetSelect.value = '';
            }
        });
    }

    if (els.inlineEditSubmit) {
        els.inlineEditSubmit.addEventListener('click', (e) => {
            e.preventDefault();
            runInlineEdit();
        });
    }
    if (els.inlineEditInput) {
        els.inlineEditInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                runInlineEdit();
            } else if (e.key === 'Escape') {
                clearSelectedSnippet();
            }
        });
    }
    if (els.inlineEditClose) {
        els.inlineEditClose.addEventListener('click', (e) => {
            e.preventDefault();
            hideInlineEditBubble();
        });
    }

    if (els.scrollContainer) {
        els.scrollContainer.addEventListener('scroll', () => clearSelectedSnippet(), { passive: true });
    }

    document.addEventListener('mousedown', (e) => {
        if (!els.inlineEditBubble || els.inlineEditBubble.classList.contains('hidden')) return;
        if (!els.inlineEditBubble.contains(e.target)) {
            clearSelectedSnippet();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            clearSelectedSnippet();
        }
    });


    const btnRemoveFile = document.getElementById('btnRemoveFile');
    if (btnRemoveFile) {
        btnRemoveFile.addEventListener('click', (e) => {
            e.stopPropagation();
            clearFileSelection();
        });
    }

    if (els.btnAttach) {
        els.btnAttach.addEventListener('click', (e) => {
            e.stopPropagation();
            els.attachMenu?.classList.toggle('open');
        });
    }
    document.addEventListener('click', () => els.attachMenu?.classList.remove('open'));

    if (els.templateSearch) {
        els.templateSearch.addEventListener('input', (e) => {
            filterTemplateCatalog(e.target.value);
        });
    }
    if (els.btnCloseTemplate) {
        els.btnCloseTemplate.addEventListener('click', closeTemplateModal);
    }
    if (els.modalTemplate) {
        els.modalTemplate.addEventListener('click', (e) => {
            if (e.target === els.modalTemplate) closeTemplateModal();
        });
    }
    if (els.btnDownloadClose) {
        els.btnDownloadClose.addEventListener('click', closeDownloadModal);
    }
    if (els.btnDownloadCancel) {
        els.btnDownloadCancel.addEventListener('click', closeDownloadModal);
    }
    if (els.btnDownloadConfirm) {
        els.btnDownloadConfirm.addEventListener('click', async () => {
            const format = getSelectedDownloadFormat();
            closeDownloadModal();
            await performDownload(format);
        });
    }
    if (els.modalDownload) {
        els.modalDownload.addEventListener('click', (e) => {
            if (e.target === els.modalDownload) closeDownloadModal();
        });
    }

    // 리로스쿨 토글 버튼 (첨부 메뉴 안)
    const btnToggleRiro = document.getElementById('btnToggleRiro');
    if (btnToggleRiro) {
        btnToggleRiro.addEventListener('click', (e) => {
            e.stopPropagation();
            if (state.riroLoggedIn) {
                if (els.modalCalendar) {
                    els.modalCalendar.style.display = 'flex';
                    setTimeout(() => {
                        els.modalCalendar.classList.add('show');
                        renderCalendar();
                    }, 10);
                }
            } else if (els.modalLogin) {
                els.modalLogin.style.display = 'flex';
                setTimeout(() => els.modalLogin.classList.add('show'), 10);
            }
            els.attachMenu?.classList.remove('open');
        });
    }

    // 사이드바
    const toggleSidebar = (open) => {
        if(open) {
            els.sidebar.classList.add('open');
            els.sidebarOverlay.classList.add('open');
        } else {
            els.sidebar.classList.remove('open');
            els.sidebarOverlay.classList.remove('open');
        }
        updateCanvasLayoutVars();
    };
    els.btnMenu?.addEventListener('click', () => toggleSidebar(true));
    els.sidebarOverlay?.addEventListener('click', () => toggleSidebar(false));

    // Desktop Sidebar Toggle
    if (els.btnDesktopSidebarToggle) {
        els.btnDesktopSidebarToggle.addEventListener('click', () => {
            els.sidebar.classList.toggle('collapsed');
            updateCanvasLayoutVars();
        });
    }

    if (theme.toggles.length) {
        theme.toggles.forEach((btn) => {
            btn.addEventListener('click', toggleTheme);
        });
    }

    // 모달 (로그인, 캘린더 등 껍데기 동작만 연결)
    const setupModal = (btnId, modalId, closeId) => {
        const btn = document.getElementById(btnId);
        const modal = document.getElementById(modalId);
        const close = document.getElementById(closeId);
        if(btn && modal) {
            btn.addEventListener('click', () => { modal.classList.add('show'); modal.style.display='flex'; });
        }
        if(close && modal) {
            close.addEventListener('click', () => { modal.classList.remove('show'); setTimeout(()=>modal.style.display='none', 300); });
        }
    };
    setupModal('btnOpenLogin', 'modalLogin', 'closeLogin');
    
    // 캘린더 모달은 별도 처리 (렌더링 필요)
    const btnCalendar = document.getElementById('btnOpenCalendar');
    const modalCalendar = document.getElementById('modalCalendar');
    const closeCalendar = document.getElementById('closeCalendar');
    
    if (btnCalendar && modalCalendar) {
        btnCalendar.addEventListener('click', () => {
            modalCalendar.style.display = 'flex';
            setTimeout(() => {
                modalCalendar.classList.add('show');
                renderCalendar(); // 모달이 뜰 때 캘린더 다시 그리기 (사이즈 계산 위함)
            }, 10);
        });
    }
    if (closeCalendar && modalCalendar) {
        closeCalendar.addEventListener('click', () => {
            modalCalendar.classList.remove('show');
            setTimeout(() => modalCalendar.style.display = 'none', 300);
        });
    }

    // 초기 실행
    console.log('DOC Agent Initialized. Debug Mode:', DEBUG_MODE);
    state.canvasUserWidth = loadCanvasUserWidth();
    updateCanvasLayoutVars();
    initTheme();
    applyAccountUIState();
    renderUserProfile();
    updateAuthLinks();
    fetchAuthMe().then(() => {
        restoreSessionFromLocalStorage();
    });
    loadRiroFromStorage();
    // updateUI(); // Initial UI update is now handled by restoreSessionFromLocalStorage or its fallback
});
