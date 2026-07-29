/* 레거시 문서 생성 UI의 이벤트 바인딩(다운로드 모달·템플릿·캔버스·인라인 편집).
   2026-07-29 제거. 원래 위치: static/js/index.js (정리 중) 1244~1507행 */

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
