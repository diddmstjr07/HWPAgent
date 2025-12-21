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
        TEMPLATE: '/api/template/upload'
    };

    // DOM 요소 캐싱 (에러 방지를 위해 Optional Chaining 사용)
    const els = {
        // Views
        homeView: document.getElementById('homeView'),
        resultView: document.getElementById('resultView'),
        chatStream: document.getElementById('chatStream'),
        docPaper: document.getElementById('paperArea'),
        docContent: document.getElementById('docContent'),
        docTitle: document.getElementById('docTitle'),
        scrollContainer: document.getElementById('scrollContainer'),

        // Inputs & Buttons
        userRequest: document.getElementById('userRequest'),
        btnSend: document.getElementById('btnSend'),
        iconSend: document.getElementById('iconSend'),
        spinnerSend: document.getElementById('spinnerSend'),
        btnAttach: document.getElementById('btnAttach'),
        attachMenu: document.getElementById('attachMenu'),
        
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
        modalCalendar: document.getElementById('modalCalendar'),
        btnOpenAuth: document.getElementById('btnOpenAuth'),
        btnAuthToggle: document.getElementById('btnAuthToggle'),
        
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
        authStatus: document.getElementById('authStatus'),
        userNameLabel: document.getElementById('userNameLabel'),
        userEmailLabel: document.getElementById('userEmailLabel'),
        userAvatar: document.getElementById('userAvatar'),
        
        // New Chat Button
        btnNewChat: document.getElementById('btnNewChat'),
        
        // Etc
        toast: document.getElementById('toast'),
    };

    // 상태 관리 (State)
    const state = {
        isGenerating: false,
        docMode: false, // false: 채팅모드, true: 문서모드
        chatHistory: [], // { role: 'user' | 'ai', text: '...' }
        streamingBuffer: '', // 현재 받아오고 있는 텍스트 (raw text before display)
        document: { title: '', content: '' }, // raw text for doc mode
        imagesNeeded: [],
        template: null,
        riroEvents: [],
        riroLoggedIn: false,
        user: null,
        authChecked: false,
        // New for typewriter effect in chat mode
        displayedChatContent: '',
        chatTypingTimeoutId: null,
        // New for typewriter effect in document mode
        displayedDocContent: '',
        docTypingTimeoutId: null,
        // Chat History
        currentSessionId: null
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

    // [New] 채팅 메시지 DOM 생성 헬퍼
    const createMessageRow = (role, text, isStreaming = false) => {
        const isUser = role === 'user';
        const div = document.createElement('div');
        div.className = 'message-row';
        if (isStreaming) div.classList.add('streaming-row');
        
        const avatarHtml = isUser 
            ? '<div class="role-avatar user"><i class="bi bi-person"></i></div>' 
            : '<div class="role-avatar ai"><i class="bi bi-stars"></i></div>';
            
        const contentHtml = isStreaming && !text 
            ? `<div class="message-content streaming">
                 <div class="message-name">AI Agent</div>
                 <div class="loading-bubble">
                   <div class="loading-line"></div>
                   <div class="loading-line short"></div>
                 </div>
               </div>`
            : `<div class="message-content">
                 <div class="message-name">${isUser ? 'You' : 'AI Agent'}</div>
                 <div class="markdown-body">${parseMarkdown(text)}</div>
               </div>`;

        div.innerHTML = avatarHtml + contentHtml;
        return div;
    };

    const updateUI = () => {
        try {
            // [View Toggle] 콘텐츠가 있으면 홈 화면 숨기고 결과 화면 표시
            const hasContent = state.chatHistory.length > 0 || state.isGenerating || state.docContent;
            if (els.homeView) els.homeView.style.display = hasContent ? 'none' : 'block';
            if (els.resultView) els.resultView.style.display = hasContent ? 'flex' : 'none';

            if (state.docMode) {
                // [문서 모드]
                if (els.chatStream) els.chatStream.style.display = 'none';
                if (els.docPaper) els.docPaper.style.display = 'block';

                // Typewriter effect for doc mode
                if (state.document.content.length > state.displayedDocContent.length) {
                    if (!state.docTypingTimeoutId) {
                        state.docTypingTimeoutId = setTimeout(() => {
                            const charsToAdd = Math.min(10, state.document.content.length - state.displayedDocContent.length); // Adjust typing speed
                            state.displayedDocContent += state.document.content.substring(state.displayedDocContent.length, state.displayedDocContent.length + charsToAdd);
                            els.docContent.innerHTML = parseMarkdown(state.displayedDocContent);
                            renderMath(els.docContent);
                            state.docTypingTimeoutId = null; // Reset to allow next frame to trigger
                            if (state.isGenerating || state.displayedDocContent.length < state.document.content.length) {
                                requestAnimationFrame(updateUI); // Continue updating if more content or still generating
                            }
                        }, 50); // Typing speed
                    }
                } else if (!state.isGenerating && state.displayedDocContent.length === state.document.content.length && state.document.content) {
                    // Stream finished, ensure final parse for doc mode
                    els.docContent.innerHTML = parseMarkdown(state.document.content);
                    renderMath(els.docContent);
                } else if (!state.document.content) {
                    els.docContent.innerHTML = ''; // Clear if no content
                }
            } else {
                // [채팅 모드] - 증분 업데이트 적용 (Flickering 방지)
                if (els.docPaper) els.docPaper.style.display = 'none';
                if (els.chatStream) els.chatStream.style.display = 'flex';

                const container = els.chatStream;
                const historyCount = state.chatHistory.length;
                
                // 1. 기존 메시지 동기화 (이미 그려진 것은 건너뜀)
                const renderedRows = container.querySelectorAll('.message-row:not(.streaming-row)');
                
                for (let i = renderedRows.length; i < historyCount; i++) {
                    const msg = state.chatHistory[i];
                    const row = createMessageRow(msg.role, msg.text);
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
            }
        } catch (e) {
            console.error('[UpdateUI Error]', e);
            if (els.chatStream && !state.docMode) {
                 els.chatStream.innerHTML += `<div style="color:red; padding:10px;">UI Rendering Error: ${e.message}</div>`;
            }
        }
    };

    const scrollToBottom = () => {
        if (els.scrollContainer) {
            els.scrollContainer.scrollTo({ top: els.scrollContainer.scrollHeight, behavior: 'smooth' });
        }
    };

    // ============================================================
    // 2. 핵심 로직: 데이터 통신 (Streaming)
    // ============================================================

    const handleGenerate = async () => {
        const prompt = els.userRequest.value.trim();
        if (!prompt || state.isGenerating) return;

        // 1. 초기화 및 UI 준비
        state.isGenerating = true;
        state.streamingBuffer = ''; // 버퍼 초기화
        state.document = { title: '', content: '' }; // 문서 내용 초기화
        
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
        
        // 채팅 모드였다면 스크롤 하단으로
        if (!state.docMode) scrollToBottom();

        // [New] Create/Update session immediately to show in sidebar
        await saveChatSession();

        try {
            // ★ 자동 모드 엔드포인트 사용
            const endpoint = API_ENDPOINTS.AUTO;
            
            if (DEBUG_MODE) console.log(`[Request] ${endpoint} -> ${prompt}`);

            // 현재 프롬프트(마지막 요소)를 제외한 이전 히스토리만 전송
            const previousHistory = state.chatHistory.slice(0, -1);

            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    request: prompt,
                    template: state.template ? state.template.text : '',
                    history: previousHistory
                })
            });

            if (!response.ok) throw new Error(`Server Error: ${response.status}`);
            if (!response.body) throw new Error('ReadableStream not supported');

            // 2. 스트림 읽기 (Robust Parsing)
            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

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

                    // [Server Protocol Compatibility]
                    // Server sends { chunk: "..." } OR { type: "token", content: "..." }
                    // Server also sends { type: "mode", mode: "document"|"chat" }
                    
                    if (data.type === 'mode') {
                        // 서버의 의도 파악 결과에 따라 모드 전환
                        if (data.mode === 'document') {
                            state.docMode = true;
                            console.log('[Auto Mode] Switched to Document Mode');
                        } else if (data.mode === 'chat') {
                            state.docMode = false;
                            console.log('[Auto Mode] Switched to Chat Mode');
                        }
                        updateUI(); // 모드 변경 반영
                    }
                    else if (data.chunk || (data.type === 'token' && data.content)) {
                        const content = data.chunk || data.content;
                        
                        // 모드에 따라 데이터 저장 위치 분기
                        if (state.docMode) {
                            state.document.content += content;
                        } else {
                            state.streamingBuffer += content;
                        }
                        
                        // 스트리밍 중에는 부분 업데이트만 수행
                        requestAnimationFrame(updateUI);
                    } 
                    else if (data.type === 'image_keyword') {
                        state.generatedImageKeyword = data.keyword;
                        console.log('Image Generation Triggered:', data.keyword);
                        // 이미지 생성 로직 호출 등...
                    } else if (data.type === 'error') {
                        console.error('Stream Error:', data.message);
                        state.streamingBuffer += `\n\n[Error: ${data.message}]`;
                        requestAnimationFrame(updateUI);
                    }
                }
            }

            // 3. 완료 처리
            if (!state.docMode && state.streamingBuffer) {
                state.chatHistory.push({ role: 'ai', text: state.streamingBuffer });
                state.streamingBuffer = '';
            }

        } catch (error) {
            console.error(error);
            
            // Check for Quota Exceeded error
            const isQuotaError = error.message.includes('Quota Exceeded') || error.message.includes('한도 초과');
            
            // Show toast only if it's NOT a quota error (per user request)
            if (!isQuotaError) {
                showToast('생성 중 오류 발생: ' + error.message, 'error');
            }

            // Styled error message (Red text)
            const errorHtml = `<div style="color: #EF4444; font-weight: 600; font-size: 0.9rem; padding: 8px 10px; background: rgba(254, 226, 226, 0.5); border: 1px solid #FECACA; border-radius: 8px; margin-top: 8px;">
                <i class="bi bi-exclamation-triangle-fill" style="margin-right: 6px;"></i>
                ${error.message}
            </div>`;

            if (state.docMode) {
                state.document.content += `\n\n${errorHtml}`;
            } else {
                state.chatHistory.push({ role: 'ai', text: errorHtml });
            }
        } finally {
            state.isGenerating = false;
            setLoadingState(false);
            
            // Clear any lingering typing timeouts
            if (state.chatTypingTimeoutId) clearTimeout(state.chatTypingTimeoutId);
            state.chatTypingTimeoutId = null;
            if (state.docTypingTimeoutId) clearTimeout(state.docTypingTimeoutId);
            state.docTypingTimeoutId = null;

            updateUI();
            
            // 문서 모드라면 이미지 로드 시도
            if (state.docMode) resolveImages();
            
            // Save chat history
            await saveChatSession();
        }
    };

    // ============================================================
    // 2.5. Download Logic
    // ============================================================

    const handleDownload = async () => {
        // 1. 문서 내용 확인
        const content = state.document.content;
        const title = state.document.title || '새 문서';
        
        if (!content) {
            showToast('저장할 문서 내용이 없습니다.', 'error');
            return;
        }

        const btnSide = document.getElementById('btnDownloadSide');
        const btnMobile = document.getElementById('btnDownloadMobile');
        
        // 로딩 표시
        const originalSideText = btnSide ? btnSide.innerHTML : '';
        if (btnSide) btnSide.innerHTML = '<div class="spinner"></div> 저장 중...';
        if (btnMobile) btnMobile.style.opacity = '0.5';

        try {
            // 2. 저장 요청
            const response = await fetch('/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    title: title, 
                    content: content,
                    format: 'hwp', // 기본값 HWP
                    images_needed: state.imagesNeeded || [],
                    // 이미지 URL 수집 (현재 렌더링된 이미지들)
                    image_urls: collectRenderedImages()
                })
            });

            const data = await response.json();
            
            if (data.success) {
                showToast('파일이 생성되었습니다. 다운로드를 시작합니다.', 'success');
                // 3. 다운로드 트리거
                const filename = data.file_path.split('/').pop(); 
                window.location.href = `/api/download/${encodeURIComponent(filename)}`;
            } else {
                throw new Error(data.error || '저장 실패');
            }

        } catch (e) {
            console.error(e);
            showToast(`저장 중 오류가 발생했습니다: ${e.message}`, 'error');
        } finally {
            // 버튼 복구
            if (btnSide) btnSide.innerHTML = originalSideText || '<i class="bi bi-download"></i> 문서 저장';
            if (btnMobile) btnMobile.style.opacity = '1';
        }
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

        // Show analysis badge with loading state
        updateAnalysisBadge(true, 'loading', '문서 분석 중...');

        const formData = new FormData();
        formData.append('template', file);

        try {
            const response = await fetch(API_ENDPOINTS.TEMPLATE, {
                method: 'POST',
                body: formData
            });
            const data = await response.json();

            if (data.success) {
                // 상태 업데이트
                state.template = {
                    name: data.template_name,
                    text: data.template_text,
                    id: data.template_id
                };
                
                // UI 업데이트
                updateFileBadge(true, data.template_name);
                // showToast(`'${data.template_name}' 업로드 완료!`, 'success'); // 사용자 요청에 따라 제거
                
                // 분석 완료 메시지 없이 바로 숨김 (요청 사항 반영)
                updateAnalysisBadge(false); 
                
                // 메뉴 닫기
                if (els.attachMenu) els.attachMenu.classList.remove('open');
            } else {
                throw new Error(data.error || '업로드 실패');
            }
        } catch (e) {
            console.error(e);
            showToast(`파일 업로드 실패: ${e.message}`, 'error');
            clearFileSelection();
            // Show error on badge and hide after delay (Error message still needed)
            updateAnalysisBadge(true, 'error', `분석 실패: ${e.message}`);
            setTimeout(() => updateAnalysisBadge(false), 3000); // Hide after 3 seconds
        }
    };

    const clearFileSelection = () => {
        state.template = null;
        updateFileBadge(false);
        const fileInput = document.getElementById('fileInput');
        if (fileInput) fileInput.value = ''; // Reset input
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
    // 3. 보조 기능 (이미지, UI 상태 등)
    // ============================================================

    const setLoadingState = (loading) => {
        if (!els.btnSend) return;
        if (loading) {
            els.btnSend.classList.add('active');
            els.iconSend.style.display = 'none';
            els.spinnerSend.style.display = 'block';
        } else {
            els.btnSend.classList.remove('active');
            els.iconSend.style.display = 'block';
            els.spinnerSend.style.display = 'none';
        }
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

    const renderUserProfile = () => {
        const name = state.user?.name || 'Guest';
        const email = state.user?.email || '로그인 필요';
        const initial = (name || email || 'G').trim().charAt(0).toUpperCase() || 'G';

        if (els.userNameLabel) els.userNameLabel.textContent = name;
        if (els.userEmailLabel) els.userEmailLabel.textContent = email;
        if (els.userAvatar) els.userAvatar.textContent = ''; // Removed initial text from avatar

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
        const lastLoadedSessionId = localStorage.getItem('lastLoadedSessionId');
        const lastLoadedDocMode = localStorage.getItem('lastLoadedDocMode') === 'true'; // Convert string to boolean
        
        if (lastLoadedSessionId) {
            console.log('Restoring session from localStorage:', lastLoadedSessionId);
            await loadChatSession(lastLoadedSessionId);
            state.docMode = lastLoadedDocMode; // Restore docMode
            els.btnDocMode?.classList.toggle('on', state.docMode);
        } else {
            // If no session to restore, ensure home view is shown if no other content
            updateUI();
        }
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
            updateUI();
            
            const res = await fetch(`/api/chat/sessions/${sessionId}`);
            const data = await res.json();
            
            if (data.success && data.session) {
                state.currentSessionId = data.session.id;
                state.chatHistory = data.session.messages || [];
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
        });
    }
    if (els.btnSend) els.btnSend.addEventListener('click', handleGenerate);
    if (els.btnLoginAction) els.btnLoginAction.addEventListener('click', handleRiroLogin);
    if (els.btnAuthLogin) els.btnAuthLogin.addEventListener('click', handleAuthLogin);
    if (els.btnAuthRegister) els.btnAuthRegister.addEventListener('click', handleAuthRegister);
    if (els.btnOpenAuth) {
        els.btnOpenAuth.addEventListener('click', () => {
            window.location.href = '/login';
        });
    }
    if (els.btnAuthToggle) {
        els.btnAuthToggle.addEventListener('click', () => {
            if (state.user) {
                handleAuthLogout();
            } else {
                window.location.href = '/login';
            }
        });
    }
    const btnCloseAuth = document.getElementById('closeAuth');
    if (btnCloseAuth) btnCloseAuth.addEventListener('click', closeAuthModal);

    // New Chat Button
    if (els.btnNewChat) {
        els.btnNewChat.addEventListener('click', () => {
            state.chatHistory = [];
            state.currentSessionId = null;
            state.document = { title: '', content: '' };
            state.docMode = false;
            state.streamingBuffer = '';
            state.displayedChatContent = '';
            
            localStorage.removeItem('lastLoadedSessionId');
            localStorage.removeItem('lastLoadedDocMode');
            
            updateUI();
            loadChatSessions(); // Clear active state
            toggleSidebar(false); // Close sidebar on mobile
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

    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            handleFileUpload(file);
        });
    }

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
    };
    els.btnMenu?.addEventListener('click', () => toggleSidebar(true));
    els.sidebarOverlay?.addEventListener('click', () => toggleSidebar(false));

    // Desktop Sidebar Toggle
    if (els.btnDesktopSidebarToggle) {
        els.btnDesktopSidebarToggle.addEventListener('click', () => {
            els.sidebar.classList.toggle('collapsed');
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
    renderUserProfile();
    fetchAuthMe().then(() => {
        restoreSessionFromLocalStorage();
    });
    loadRiroFromStorage();
    // updateUI(); // Initial UI update is now handled by restoreSessionFromLocalStorage or its fallback
});
