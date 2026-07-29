/* 생성된 문서를 미리보던 캔버스·iframe·본문 렌더링. 진짜 HWP 경로가 아니라
   HTML을 그려 보여주던 것이라 2026-07-29에 걷어냈다.
   원래 위치: static/js/index.js 354~1037행 */

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