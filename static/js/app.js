document.addEventListener('DOMContentLoaded', () => {
    // =================================================================
    // DOM Elements and Global State
    // =================================================================
    
    // Main containers
    const headerActions = document.getElementById('headerActions');
    const resultsContainer = document.querySelector('.results-container');
    const placeholder = document.getElementById('placeholder');
    const documentPreview = document.getElementById('documentPreview');
    
    // Input area
    const userRequest = document.getElementById('userRequest');
    const generateBtn = document.getElementById('generateBtn');
    const templateUploadBtn = document.getElementById('templateUploadBtn');
    const templateFileInput = document.getElementById('templateFileInput');

    // Preview area
    const previewTitle = document.getElementById('previewTitle');
    const previewContent = document.getElementById('previewContent');

    // Header actions
    const saveBtn = document.getElementById('saveBtn');
    const styleBtn = document.getElementById('styleBtn');
    const formatSelect = document.getElementById('formatSelect');

    // Modals & Toast
    const toast = document.getElementById('toast');
    const styleModal = document.getElementById('styleModal');

    // Global State
    let state = {
        isGenerating: false,
        isSaving: false,
        currentDocumentContent: '',
        currentImagesNeeded: [],
        currentImageUrls: [],
        currentTemplate: { name: '', text: '', id: null },
        availableFonts: [],
        fontsLoaded: false,
        currentStyle: {
            font_id: '',
            font_size: 11,
            line_spacing: 1.7,
            paragraph_spacing: 8,
            treat_images_as_text: false,
        }
    };

    // =================================================================
    // Initialization
    // =================================================================
    
    function init() {
        initEventListeners();
        loadInitialData();
        updateUI(); // Set initial UI state
    }
    
    function loadInitialData() {
        fetchAvailableFonts();
    }

    // =================================================================
    // Event Listeners
    // =================================================================
    
    function initEventListeners() {
        generateBtn.addEventListener('click', generateContent);
        userRequest.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                generateContent();
            }
        });
        
        templateUploadBtn.addEventListener('click', () => templateFileInput.click());
        templateFileInput.addEventListener('change', (e) => uploadTemplateFile(e.target.files[0]));
        
        saveBtn.addEventListener('click', saveDocument);
        styleBtn.addEventListener('click', () => toggleModal(styleModal, true));

        // Modal event listeners
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) toggleModal(modal, false);
            });
        });
        document.querySelectorAll('.modal-close, .modal-footer .btn-secondary').forEach(btn => {
            btn.addEventListener('click', () => toggleModal(btn.closest('.modal'), false));
        });
        
        document.getElementById('styleModalApplyBtn').addEventListener('click', applyStyle);
        document.getElementById('fontUploadBtn').addEventListener('click', () => document.getElementById('fontFileInput').click());
        document.getElementById('fontFileInput').addEventListener('change', (e) => uploadFontFile(e.target.files[0]));
    }
    
    // =================================================================
    // UI State Management
    // =================================================================

    function updateUI() {
        const hasContent = state.currentDocumentContent.trim().length > 0;
        
        if (hasContent) {
            placeholder.style.display = 'none';
            documentPreview.style.display = 'block';
            headerActions.style.display = 'flex';
        } else {
            placeholder.style.display = 'block';
            documentPreview.style.display = 'none';
            headerActions.style.display = 'none';
        }
    }

    function setButtonLoading(button, isLoading) {
        const spinner = button.querySelector('.spinner');
        const btnText = button.querySelector('.btn-text');
        button.disabled = isLoading;
        if (spinner) spinner.style.display = isLoading ? 'inline-block' : 'none';
        if (btnText) btnText.style.display = isLoading ? 'none' : 'inline-block';
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
                 fetchAvailableFonts();
            }
            modal.classList.add('show');
        } else {
            modal.classList.remove('show');
        }
    }
    
    // =================================================================
    // Core Features: Generate, Save, etc.
    // =================================================================

    async function generateContent() {
        const request = userRequest.value.trim();
        if (!request) {
            showToast('요청 내용을 입력해주세요.', 'error');
            return;
        }
        
        state.isGenerating = true;
        setButtonLoading(generateBtn, true);
        
        // Reset view
        state.currentDocumentContent = '';
        state.currentImagesNeeded = [];
        state.currentImageUrls = [];
        updateUI();

        try {
            const response = await fetch('/api/generate-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request, template: state.currentTemplate.text }),
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
                buffer = lines.pop(); 

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const data = JSON.parse(line.substring(6));

                    if (data.error) throw new Error(data.error);

                    if (data.chunk) {
                        fullContent += data.chunk;
                        state.currentDocumentContent = fullContent;
                        updateHtmlPreview();
                    }
                    
                    if (data.done && data.result) {
                        state.currentDocumentContent = data.result.body || fullContent;
                        previewTitle.textContent = data.result.title || '제목 없음';
                        state.currentImagesNeeded = data.result.images_needed || [];
                        updateHtmlPreview();
                        fetchAndDisplayImages();
                    }
                }
            }
            showToast('문서 생성이 완료되었습니다.', 'success');
        } catch (error) {
            showToast(`생성 오류: ${error.message}`, 'error');
        } finally {
            state.isGenerating = false;
            setButtonLoading(generateBtn, false);
            updateUI();
        }
    }
    
    async function saveDocument() {
        const format = formatSelect.value;
        const title = previewTitle.textContent.trim() || '문서';
        const content = state.currentDocumentContent;

        if (!content) {
            showToast('저장할 내용이 없습니다.', 'error');
            return;
        }

        state.isSaving = true;
        setButtonLoading(saveBtn, true);

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
            setButtonLoading(saveBtn, false);
        }
    }

    // =================================================================
    // Preview & Rendering
    // =================================================================

    function updateHtmlPreview() {
        const dirtyHtml = marked.parse(state.currentDocumentContent);
        previewContent.innerHTML = dirtyHtml.replace(/<img[^>]+>/g, '').replace(/<div class="gen-image-placeholder"><i class="bi bi-image"><\/i> <span class="image-keyword">(.*?)<\/span><\/div>/g, '<div class="gen-image-placeholder"><i class="bi bi-image"></i> <span class="image-keyword">$1</span></div>');
        resultsContainer.scrollTop = resultsContainer.scrollHeight;
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
            } catch { return null; }
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
    // Helper Functions: Templates, Fonts, Styles
    // =================================================================
    
    async function uploadTemplateFile(file) {
        if (!file) return;
        const formData = new FormData();
        formData.append('template', file);
        try {
            const response = await fetch('/api/template/upload', { method: 'POST', body: formData });
            const data = await response.json();
            if (!data.success) throw new Error(data.error);
            state.currentTemplate = { name: data.template_name, text: data.template_text, id: data.template_id };
            showToast(`양식 '${data.template_name}'이 적용되었습니다.`, 'success');
        } catch (error) {
            showToast(`양식 업로드 실패: ${error.message}`, 'error');
        }
    }
    
    async function fetchAvailableFonts() {
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
        if (!file) return;
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
            await fetchAvailableFonts();
            document.getElementById('fontId').value = data.font_id;
        } catch (error) {
            showToast(`폰트 업로드 실패: ${error.message}`, 'error');
            statusEl.textContent = '선택된 폰트 없음';
        }
    }

    function applyStyle() {
        state.currentStyle = {
            font_id: document.getElementById('fontId').value,
            font_size: parseFloat(document.getElementById('fontSize').value),
            line_spacing: parseFloat(document.getElementById('lineSpacing').value),
            paragraph_spacing: parseFloat(document.getElementById('paragraphSpacing').value),
            treat_images_as_text: document.getElementById('treatImagesAsText').checked
        };
        showToast('서식이 적용되었습니다.', 'success');
        toggleModal(styleModal, false);
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