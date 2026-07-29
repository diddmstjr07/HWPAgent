/* 레거시 문서 생성 채팅의 대화 저장·복원. 지금은 사이드바 목록을 history.js가,
   설계·실험 대화를 guide.js가 다룬다. 2026-07-29 제거.
   원래 위치: static/js/index.js (정리 중) 1120~1339행 */

    // ============================================================
    // 3.6. Chat History Management
    // ============================================================

    const restoreSessionFromLocalStorage = async () => {
        localStorage.removeItem('lastLoadedSessionId');
        localStorage.removeItem('lastLoadedDocMode');
        state.currentSessionId = null;
        state.chatHistory = [];
        state.docMode = false;
        // 설계·실험 채팅(guide.js)이 이미 화면을 그렸으면 건드리지 않는다.
        // 이 파일(223KB)은 파싱이 늦어서 guide.js보다 나중에 초기화되는데,
        // 여기서 스트림을 비우면 /welcome을 마치고 온 학생이 빈 채팅을 보게 된다
        // (실제로 그랬다). guide.js의 메시지는 .message-row로 구분된다.
        if (els.chatStream && els.chatStream.querySelector('.message-row')) {
            loadChatSessions();
            return;
        }
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
                // 사이드바 HISTORY(history.js)도 지금 열린 대화를 따라와야 한다.
                window.dispatchEvent(new CustomEvent('history:refresh'));

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
        // 새 대화가 생기거나 제목이 바뀌면 사이드바 HISTORY도 다시 그린다.
        window.dispatchEvent(new CustomEvent('history:refresh'));
    };

    // 폴더가 없는 일반 대화는 이쪽이 연다. HISTORY(history.js)에서 눌렀을 때 쓴다.
    window.loadChatSession = loadChatSession;
