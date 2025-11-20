document.addEventListener('DOMContentLoaded', () => {
    // =================================================================
    // DOM 요소 및 전역 상태
    // =================================================================
    
    // 왼쪽 패널
    const userRequest = document.getElementById('userRequest');
    const generateBtn = document.getElementById('generateBtn');
    const templateUploadBtn = document.getElementById('templateUploadBtn');
    const templateFileInput = document.getElementById('templateFileInput');
    const templatePreview = document.getElementById('templatePreview');
    const templatePreviewText = document.getElementById('templatePreviewText');
    const templateName = document.getElementById('templateName');
    const templateRemoveBtn = document.getElementById('templateRemoveBtn');
    
    // AI 수정 섹션
    const refineControlSection = document.getElementById('refineControlSection');
    const modeSelector = refineControlSection.querySelector('.mode-selector');
    const unifiedInputSection = refineControlSection.querySelector('.unified-input-section');
    const unifiedRequest = document.getElementById('unifiedRequest');
    const backBtn = document.getElementById('backBtn');
    const applyBtn = document.getElementById('applyBtn');

    // 리로스쿨 섹션
    const riroLoginOpenBtn = document.getElementById('riroLoginOpenBtn');
    const riroUserActions = document.getElementById('riroUserActions');
    const riroScheduleBtn = document.getElementById('riroScheduleBtn');
    const riroLogoutBtn = document.getElementById('riroLogoutBtn');

    // 오른쪽 패널
    const docTitle = document.getElementById('docTitle');
    const saveBtn = document.getElementById('saveBtn');
    const styleBtn = document.getElementById('styleBtn');
    const formatSelect = document.getElementById('formatSelect');
    const progressBar = document.getElementById('progressBar');
    const placeholder = document.getElementById('placeholder');
    const documentPreview = document.getElementById('documentPreview');
    const previewTitle = document.getElementById('previewTitle');
    const previewContent = document.getElementById('previewContent');
    const editModeToggle = document.getElementById('editModeToggle');
    const toggleEditBtn = document.getElementById('toggleEditBtn');
    const charCount = document.getElementById('charCount');
    const wordCount = document.getElementById('wordCount');

    // 모달 및 토스트
    const toast = document.getElementById('toast');
    const styleModal = document.getElementById('styleModal');
    const riroLoginModal = document.getElementById('riroLoginModal');
    const riroScheduleModal = document.getElementById('riroScheduleModal');

    // 전역 상태 변수
    let state = {
        isGenerating: false,
        isRefining: false,
        isSaving: false,
        isTemplateUploading: false,
        isFontUploading: false,
        isEditMode: false,
        currentMode: null, // 'refine', 'format'
        currentDocumentContent: '',
        currentImagesNeeded: [],
        currentImageUrls: [],
        currentTemplate: { name: '', text: '', id: null },
        availableFonts: [],
        fontsLoaded: false,
        currentStyle: {
            font_id: '',
            font_size: 11,
            line_spacing: 1.5,
            paragraph_spacing: 8,
            treat_images_as_text: false,
        }
    };
    
    // =================================================================
    // 초기화
    // =================================================================
    
    function init() {
        initEventListeners();
        initBrandLogoReveal();
        updateStats();
        loadInitialData();
    }
    
    function loadInitialData() {
        fetchAvailableFonts(false); // 리로스쿨 관련 데이터 로드 로직 추가 가능
    }

    function initBrandLogoReveal() {
        const brandLogo = document.querySelector('.brand-mark');
        if (!brandLogo) return;
        
        const reveal = () => brandLogo.classList.add('is-visible');
        if (brandLogo.complete) {
            reveal();
        } else {
            brandLogo.addEventListener('load', reveal, { once: true });
        }
    }
    
    // =================================================================
    // 이벤트 리스너
    // =================================================================
    
    function initEventListeners() {
        // 왼쪽 패널
        generateBtn.addEventListener('click', generateContent);
        userRequest.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generateContent();
        });
        templateUploadBtn.addEventListener('click', () => templateFileInput.click());
        templateFileInput.addEventListener('change', (e) => uploadTemplateFile(e.target.files[0]));
        templateRemoveBtn.addEventListener('click', () => clearTemplateSelection(true));

        // AI 수정 섹션
        modeSelector.addEventListener('click', (e) => {
            const modeBtn = e.target.closest('.mode-btn');
            if (!modeBtn) return;
            const mode = modeBtn.dataset.mode;
            if (mode === 'direct') {
                toggleDirectEdit(true);
            } else {
                showUnifiedInput(mode);
            }
        });
        backBtn.addEventListener('click', backToModeSelector);
        applyBtn.addEventListener('click', applyCurrentMode);
        unifiedRequest.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) applyCurrentMode();
        });

        // 리로스쿨
        riroLoginOpenBtn.addEventListener('click', () => toggleModal(riroLoginModal, true));
        // riroLogoutBtn.addEventListener('click', handleRiroLogout);
        // riroScheduleBtn.addEventListener('click', () => toggleModal(riroScheduleModal, true));

        // 오른쪽 패널
        docTitle.addEventListener('input', () => {
            previewTitle.textContent = docTitle.value;
            saveBtn.disabled = !state.currentDocumentContent.trim();
        });
        saveBtn.addEventListener('click', saveDocument);
        styleBtn.addEventListener('click', () => toggleModal(styleModal, true));
        toggleEditBtn.addEventListener('click', () => toggleDirectEdit());
        
        previewContent.addEventListener('input', () => {
             if (state.isEditMode) {
                 syncContentFromPreview();
                 updateStats();
             }
        });

        // 모달 공통
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) toggleModal(modal, false);
            });
        });
        document.querySelectorAll('.modal-close, .modal-footer .btn-secondary').forEach(btn => {
            btn.addEventListener('click', () => toggleModal(btn.closest('.modal'), false));
        });
        
        // 서식 모달
        document.getElementById('styleModalApplyBtn').addEventListener('click', applyStyle);
        document.getElementById('fontUploadBtn').addEventListener('click', () => document.getElementById('fontFileInput').click());
        document.getElementById('fontFileInput').addEventListener('change', (e) => uploadFontFile(e.target.files[0]));

        // 리로스쿨 로그인 모달
        document.getElementById('riroLoginSubmitBtn').addEventListener('click', handleRiroLogin);
    }
    
    // =================================================================
    // UI 상태 관리
    // =================================================================
    
    function setButtonLoading(button, isLoading) {
        const spinner = button.querySelector('.spinner');
        const btnText = button.querySelector('.btn-text');
        button.disabled = isLoading;
        if (spinner) spinner.style.display = isLoading ? 'inline-block' : 'none';
        if (btnText) btnText.style.display = isLoading ? 'none' : 'inline-block';
    }

    function toggleProgressBar(show) {
        progressBar.style.display = show ? 'block' : 'none';
    }

    function updateStats() {
        const content = state.currentDocumentContent;
        const charLength = content.length;
        const wordLength = content.trim().split(/\s+/).filter(Boolean).length;
        charCount.textContent = `${charLength.toLocaleString()}자`;
        wordCount.textContent = `${wordLength.toLocaleString()}단어`;
    }
    
    function showToast(message, type = 'info') {
        toast.textContent = message;
        toast.className = `toast show ${type}`;
        setTimeout(() => toast.classList.remove('show'), 3000);
    }
    
    function toggleModal(modal, show) {
        if (!modal) return;
        if (show) {
            if (modal === styleModal && !state.fontsLoaded) {
                 fetchAvailableFonts(true);
            }
            modal.classList.add('show');
        } else {
            modal.classList.remove('show');
        }
    }
    
    // =================================================================
    // 핵심 기능: 생성, 수정, 저장
    // =================================================================

    async function generateContent() {
        const request = userRequest.value.trim();
        const template = state.currentTemplate.text.trim();
        const finalRequest = request || (template ? '제공된 문서 양식에 맞춰 전체 내용을 작성해 주세요.' : '');

        if (!finalRequest) {
            showToast('요청 내용 또는 문서 양식을 입력해주세요.', 'error');
            return;
        }
        
        state.isGenerating = true;
        setButtonLoading(generateBtn, true);
        toggleProgressBar(true);
        resetDocumentState();
        
        placeholder.style.display = 'none';
        documentPreview.style.display = 'block';

        try {
            const response = await fetch('/api/generate-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request: finalRequest, template }),
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '', fullContent = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n\n');
                buffer = lines.pop(); // Keep incomplete line

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const jsonStr = line.substring(6);
                    const data = JSON.parse(jsonStr);

                    if (data.error) throw new Error(data.error);

                    if (data.chunk) {
                        fullContent += data.chunk;
                        state.currentDocumentContent = fullContent;
                        updateHtmlPreview();
                        updateStats();
                    }
                    
                    if (data.done && data.result) {
                        state.currentDocumentContent = data.result.body || fullContent;
                        docTitle.value = data.result.title || '';
                        state.currentImagesNeeded = data.result.images_needed || [];
                        updateHtmlPreview();
                        updateStats();
                        fetchAndDisplayImages();
                    }
                }
            }
            showToast('문서 생성이 완료되었습니다.', 'success');
            document.getElementById('initialInputSection').style.display = 'none';
            refineControlSection.style.display = 'block';
            editModeToggle.style.display = 'block';
            saveBtn.disabled = false;

        } catch (error) {
            showToast(`생성 오류: ${error.message}`, 'error');
            resetToInitialState();
        } finally {
            state.isGenerating = false;
            setButtonLoading(generateBtn, false);
            toggleProgressBar(false);
        }
    }
    
    async function saveDocument() {
        const format = formatSelect.value;
        const title = docTitle.value.trim() || '문서';
        const content = state.currentDocumentContent;

        if (!content) {
            showToast('저장할 내용이 없습니다.', 'error');
            return;
        }

        state.isSaving = true;
        document.getElementById('saveBtnText').textContent = '저장중';
        toggleProgressBar(true);
        saveBtn.disabled = true;

        try {
            const response = await fetch('/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title,
                    content,
                    format,
                    style: state.currentStyle,
                    images_needed: state.currentImagesNeeded,
                    image_urls: state.currentImageUrls
                }),
            });

            const data = await response.json();
            if (!data.success) throw new Error(data.error);

            showToast(`${format.toUpperCase()} 파일 저장 완료!`, 'success');
            window.location.href = `/api/download/${encodeURIComponent(data.file_path.split('/').pop())}`;

        } catch (error) {
            showToast(`저장 실패: ${error.message}`, 'error');
        } finally {
            state.isSaving = false;
            document.getElementById('saveBtnText').textContent = '저장';
            toggleProgressBar(false);
            saveBtn.disabled = false;
        }
    }
    
    // =================================================================
    // UI 모드 전환
    // =================================================================
    
    function showUnifiedInput(mode) {
        state.currentMode = mode;
        const placeholders = {
            refine: "어떻게 수정할까요?\n\n예: 더 전문적으로 작성해줘",
            format: "서식을 어떻게 변경할까요?\n\n예: 첫 번째 문단 굵게 처리"
        };
        unifiedRequest.placeholder = placeholders[mode];
        modeSelector.style.display = 'none';
        unifiedInputSection.style.display = 'flex';
        unifiedRequest.value = '';
        unifiedRequest.focus();
    }

    function backToModeSelector() {
        unifiedInputSection.style.display = 'none';
        modeSelector.style.display = 'flex';
        state.currentMode = null;
    }

    function resetToInitialState() {
        resetDocumentState();
        document.getElementById('initialInputSection').style.display = 'block';
        refineControlSection.style.display = 'none';
        editModeToggle.style.display = 'none';
    }

    function resetDocumentState() {
        docTitle.value = '';
        state.currentDocumentContent = '';
        state.currentImagesNeeded = [];
        state.currentImageUrls = [];
        updateHtmlPreview();
        updateStats();
        placeholder.style.display = 'flex';
        documentPreview.style.display = 'none';
        saveBtn.disabled = true;
    }
    
    async function applyCurrentMode() {
        const request = unifiedRequest.value.trim();
        const content = state.currentDocumentContent;

        if (!request || !content) {
            showToast('요청 내용을 입력해주세요.', 'error');
            return;
        }

        setButtonLoading(applyBtn, true);
        toggleProgressBar(true);

        try {
            if(state.currentMode === 'refine') {
                const response = await fetch('/api/refine', {
                     method: 'POST',
                     headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify({ content, request }),
                });
                const data = await response.json();
                if (!data.success) throw new Error(data.error);
                state.currentDocumentContent = data.content;
                showToast('문서가 수정되었습니다.', 'success');

            } else { // format
                 const response = await fetch('/api/adjust-format', {
                     method: 'POST',
                     headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify({ content, request }),
                 });
                 const data = await response.json();
                 if (!data.success) throw new Error(data.error);
                 state.currentDocumentContent = data.content;
                 showToast('서식이 적용되었습니다.', 'success');
            }
            
            updateHtmlPreview();
            updateStats();
            backToModeSelector();

        } catch (error) {
            showToast(`오류: ${error.message}`, 'error');
        } finally {
            setButtonLoading(applyBtn, false);
            toggleProgressBar(false);
        }
    }

    // =================================================================
    // 직접 편집
    // =================================================================

    function toggleDirectEdit(forceEnable) {
        state.isEditMode = forceEnable !== undefined ? forceEnable : !state.isEditMode;
        
        if (state.isEditMode) {
            previewContent.contentEditable = 'true';
            toggleEditBtn.classList.add('active');
            toggleEditBtn.innerHTML = '<i class="bi bi-check-square"></i> 편집 완료';
            if (state.currentMode !== 'direct') modeSelector.style.display = 'none';
            previewContent.focus();
            showToast('직접 편집 모드 활성화', 'info');
        } else {
            previewContent.contentEditable = 'false';
            toggleEditBtn.classList.remove('active');
            toggleEditBtn.innerHTML = '<i class="bi bi-pencil-square"></i> 편집 모드';
            syncContentFromPreview();
            showToast('편집 내용이 동기화되었습니다.', 'success');
            if (state.currentMode !== 'direct') modeSelector.style.display = 'flex';
        }
        state.currentMode = state.isEditMode ? 'direct' : null;
    }
    
    function syncContentFromPreview() {
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = previewContent.innerHTML;
        
        tempDiv.querySelectorAll('.gen-image-placeholder, .gen-image-loaded').forEach(el => {
            const keyword = el.querySelector('.image-keyword, .image-caption')?.textContent || '이미지';
            el.replaceWith(`[gen_img]${keyword}[/gen_img]`);
        });

        let markdown = tempDiv.innerHTML
            .replace(/<p>/g, '').replace(/<\/p>/g, '\n\n')
            .replace(/<h1>/g, '# ').replace(/<\/h1>/g, '\n\n')
            .replace(/<h2>/g, '## ').replace(/<\/h2>/g, '\n\n')
            .replace(/<h3>/g, '### ').replace(/<\/h3>/g, '\n\n')
            .replace(/<strong>/g, '**').replace(/<\/strong>/g, '**')
            .replace(/<em>/g, '*').replace(/<\/em>/g, '*')
            .replace(/<br>/g, '\n');
            
        const cleanDiv = document.createElement('div');
        cleanDiv.innerHTML = markdown;
        state.currentDocumentContent = (cleanDiv.textContent || cleanDiv.innerText).trim();
    }
    
    // =================================================================
    // 미리보기 및 렌더링
    // =================================================================

    function updateHtmlPreview() {
        previewTitle.textContent = docTitle.value;
        const dirtyHtml = marked.parse(state.currentDocumentContent);
        previewContent.innerHTML = dirtyHtml.replace(/<img[^>]+>/g, '').replace(/<div class="gen-image-placeholder"><i class="bi bi-image"><\/i> <span class="image-keyword">(.*?)<\/span><\/div>/g, '<div class="gen-image-placeholder"><i class="bi bi-image"></i> <span class="image-keyword">$1</span></div>');
        documentPreview.scrollTop = documentPreview.scrollHeight;
    }
    
    async function fetchAndDisplayImages() {
        const placeholders = previewContent.querySelectorAll('.gen-image-placeholder');
        if (placeholders.length === 0) return;

        const imagePromises = Array.from(placeholders).map(async (p, i) => {
            const keyword = state.currentImagesNeeded[i];
            if (!keyword) return null;
            
            try {
                const response = await fetch('/api/search-images', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: keyword, count: 1 })
                });
                const data = await response.json();
                if (data.success && data.images.length > 0) {
                    return { placeholder: p, image: data.images[0], keyword };
                }
                return null;
            } catch {
                return null;
            }
        });

        const results = await Promise.all(imagePromises);
        state.currentImageUrls = [];
        results.forEach(result => {
            if (result) {
                const { placeholder, image, keyword } = result;
                state.currentImageUrls.push({ keyword, url: image.url });
                const imageElement = document.createElement('div');
                imageElement.className = 'gen-image-loaded';
                imageElement.innerHTML = `<img src="${image.url}" alt="${keyword}" loading="lazy"><div class="image-caption">${keyword}</div>`;
                placeholder.replaceWith(imageElement);
            }
        });
    }

    // =================================================================
    // 부가 기능: 템플릿, 폰트, 서식, 리로스쿨
    // =================================================================
    
    function clearTemplateSelection(showNotice) {
        state.currentTemplate = { name: '', text: '', id: null };
        templatePreview.style.display = 'none';
        templateFileInput.value = '';
        if (showNotice) showToast('양식이 제거되었습니다.', 'info');
    }
    
    async function uploadTemplateFile(file) {
        if (!file || state.isTemplateUploading) return;
        
        state.isTemplateUploading = true;
        setButtonLoading(templateUploadBtn, true);
        const formData = new FormData();
        formData.append('template', file);
        
        try {
            const response = await fetch('/api/template/upload', { method: 'POST', body: formData });
            const data = await response.json();
            if (!data.success) throw new Error(data.error);

            state.currentTemplate = { name: data.template_name, text: data.template_text, id: data.template_id };
            templateName.textContent = data.template_name;
            templatePreviewText.textContent = data.template_text.substring(0, 500) + (data.template_text.length > 500 ? '...' : '');
            templatePreview.style.display = 'block';
            showToast('양식이 적용되었습니다.', 'success');
            
        } catch (error) {
            showToast(`양식 업로드 실패: ${error.message}`, 'error');
            clearTemplateSelection(false);
        } finally {
            state.isTemplateUploading = false;
            setButtonLoading(templateUploadBtn, false);
        }
    }
    
    async function fetchAvailableFonts(preserveSelection) {
        try {
            const response = await fetch('/api/fonts');
            const data = await response.json();
            if (!data.success) throw new Error(data.error);
            state.availableFonts = data.fonts || [];
            state.fontsLoaded = true;
            populateFontSelects();
        } catch (error) {
            showToast(`폰트 목록 로드 실패: ${error.message}`, 'error');
        }
    }
    
    function populateFontSelects() {
        const fontSelect = document.getElementById('fontId');
        if (!fontSelect) return;
        fontSelect.innerHTML = '';
        state.availableFonts.forEach(font => {
            const option = document.createElement('option');
            option.value = font.id;
            option.textContent = font.display_name;
            fontSelect.appendChild(option);
        });
        fontSelect.value = state.currentStyle.font_id;
    }
    
    async function uploadFontFile(file) {
        if (!file || state.isFontUploading) return;
        state.isFontUploading = true;
        const statusEl = document.getElementById('fontFileStatus');
        statusEl.textContent = '업로드 중...';
        
        const formData = new FormData();
        formData.append('font', file);
        
        try {
            const response = await fetch('/api/font/upload', { method: 'POST', body: formData });
            const data = await response.json();
            if (!data.success) throw new Error(data.error);
            
            showToast('폰트가 업로드되었습니다.', 'success');
            statusEl.textContent = file.name;
            await fetchAvailableFonts(true);
            document.getElementById('fontId').value = data.font_id;

        } catch (error) {
            showToast(`폰트 업로드 실패: ${error.message}`, 'error');
            statusEl.textContent = '선택된 폰트 없음';
        } finally {
            state.isFontUploading = false;
            fontFileInput.value = '';
        }
    }

    function applyStyle() {
        const fontSelect = document.getElementById('fontId');
        const treatImagesAsText = document.getElementById('treatImagesAsText');
        
        state.currentStyle = {
            font_id: fontSelect.value,
            font_size: parseFloat(document.getElementById('fontSize').value),
            line_spacing: parseFloat(document.getElementById('lineSpacing').value),
            paragraph_spacing: parseFloat(document.getElementById('paragraphSpacing').value),
            treat_images_as_text: treatImagesAsText.checked
        };
        
        showToast('서식이 적용되었습니다.', 'success');
        toggleModal(styleModal, false);
        
        previewContent.style.fontSize = `${state.currentStyle.font_size}pt`;
        previewContent.style.lineHeight = state.currentStyle.line_spacing;
    }

    function handleRiroLogin() {
        showToast('리로스쿨 기능은 현재 개발 중입니다.', 'info');
    }
    
    marked.setOptions({
        breaks: true,
        gfm: true,
    });
    
    init();
});
