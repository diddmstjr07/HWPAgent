// DOM 요소
const userRequest = document.getElementById('userRequest');
const generateBtn = document.getElementById('generateBtn');
const refineRequest = document.getElementById('refineRequest');
const refineBtn = document.getElementById('refineBtn');
const refineSection = document.querySelector('.refine-section');
const formatRequest = document.getElementById('formatRequest');
const formatAdjustBtn = document.getElementById('formatAdjustBtn');
const docTitle = document.getElementById('docTitle');
const contentEditor = document.getElementById('contentEditor');
const saveBtn = document.getElementById('saveBtn');
const formatSelect = document.getElementById('formatSelect');
const charCount = document.getElementById('charCount');
const wordCount = document.getElementById('wordCount');
const toast = document.getElementById('toast');
const pdfViewerContainer = document.getElementById('pdfViewerContainer');
const pdfViewer = document.getElementById('pdfViewer');
const pdfPlaceholder = document.getElementById('pdfPlaceholder');
const pdfLoading = document.getElementById('pdfLoading');
const htmlPreviewContainer = document.getElementById('htmlPreviewContainer');
const previewTitle = document.getElementById('previewTitle');
const previewContent = document.getElementById('previewContent');
const bodyFontSelect = document.getElementById('bodyFontSelect');
const headingFontSelect = document.getElementById('headingFontSelect');
const titleFontSelect = document.getElementById('titleFontSelect');
const heading1SizeInput = document.getElementById('heading1Size');
const heading2SizeInput = document.getElementById('heading2Size');
const heading3SizeInput = document.getElementById('heading3Size');
const titleSizeInput = document.getElementById('titleSize');
const fontSizeInput = document.getElementById('fontSize');
const lineSpacingSelect = document.getElementById('lineSpacing');
const fontUploadBtn = document.getElementById('fontUploadBtn');
const fontFileInput = document.getElementById('fontFileInput');
const fontRemoveBtn = document.getElementById('fontRemoveBtn');
const fontFileStatus = document.getElementById('fontFileStatus');
const templateUploadBtn = document.getElementById('templateUploadBtn');
const templateFileInput = document.getElementById('templateFileInput');
const templatePreview = document.getElementById('templatePreview');
const templatePreviewText = document.getElementById('templatePreviewText');
const templateName = document.getElementById('templateName');
const templateRemoveBtn = document.getElementById('templateRemoveBtn');
const riroLoginOpenBtn = document.getElementById('riroLoginOpenBtn');
const riroScheduleBtn = document.getElementById('riroScheduleBtn');
const riroLogoutBtn = document.getElementById('riroLogoutBtn');
const riroArchiveBtn = document.getElementById('riroArchiveBtn');
const brandTitle = document.querySelector('.brand-copy h1');
const riroLoginOverlay = document.getElementById('riroLoginOverlay');

const RIRO_GUIDE_ENDPOINT = '/api/riroschool/guide';

// 브랜드 로고 페이드-인
const initBrandLogoReveal = () => {
    const brandLogo = document.querySelector('.brand-mark');
    if (brandLogo) {
        const revealLogo = () => brandLogo.classList.add('is-visible');
        if (brandLogo.complete) {
            revealLogo();
        } else {
            brandLogo.addEventListener('load', revealLogo, { once: true });
        }
    }
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBrandLogoReveal);
} else {
    initBrandLogoReveal();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTemplateUploadControls);
} else {
    initTemplateUploadControls();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFontUploadControls);
} else {
    initFontUploadControls();
}

const initFontCatalog = () => fetchAvailableFonts(false);

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFontCatalog);
} else {
    initFontCatalog();
}

// 현재 PDF 파일명 저장
let currentPdfFile = null;

// 스트리밍 상태
let isStreaming = false;

// 리로스쿨 일정 데이터
let latestRiroEvents = {};
let isRiroLoggedIn = false;
let riroUserId = localStorage.getItem('riroUserId') || null;
const RiroDraftStorageKey = 'riro_doc_draft';
let riroCalendarState = (() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
})();

let currentTemplateText = '';
let currentTemplateName = '';
let currentTemplateId = null;
let isTemplateUploading = false;
let currentFontInfo = null;
let isFontUploading = false;
let availableFonts = [];
let fontsLoaded = false;

function resetDocumentState() {
    if (docTitle) docTitle.value = '';
    if (contentEditor) {
        contentEditor.value = '';
        updateStats();
    }
    if (previewTitle) previewTitle.textContent = '';
    if (previewContent) previewContent.innerHTML = '';
    if (htmlPreviewContainer) htmlPreviewContainer.style.display = 'none';
    if (pdfViewerContainer) {
        const imgContainer = document.getElementById('pdfImageContainer');
        if (imgContainer) imgContainer.remove();
    }
    if (pdfViewer) pdfViewer.style.display = 'none';
    if (pdfPlaceholder) pdfPlaceholder.style.display = 'flex';
    if (pdfLoading) pdfLoading.style.display = 'none';
    currentPdfFile = null;
}

function applyTemplateSelection(name, text, templateId = null) {
    currentTemplateText = text || '';
    currentTemplateName = name || '업로드된 양식';
    currentTemplateId = templateId;
    if (templatePreview) {
        templatePreview.style.display = text ? 'block' : 'none';
    }
    if (templateName) {
        templateName.textContent = currentTemplateName;
    }
    if (templatePreviewText) {
        const maxLength = 800;
        let previewText = text || '';
        if (previewText.length > maxLength) {
            previewText = previewText.slice(0, maxLength) + '\n...';
        }
        templatePreviewText.textContent = previewText;
    }
}

function clearTemplateSelection(showNotice = false) {
    currentTemplateText = '';
    currentTemplateName = '';
    currentTemplateId = null;
    if (templatePreview) {
        templatePreview.style.display = 'none';
    }
    if (templateFileInput) {
        templateFileInput.value = '';
    }
    if (showNotice) {
        showToast('양식이 제거되었습니다.', 'info');
    }
}

async function uploadTemplateFile(file) {
    if (!file) {
        return;
    }
    if (isTemplateUploading) {
        return;
    }
    isTemplateUploading = true;
    if (templateUploadBtn) {
        templateUploadBtn.disabled = true;
        templateUploadBtn.textContent = '업로드 중...';
    }
    const formData = new FormData();
    formData.append('template', file);
    try {
        const response = await fetch('/api/template/upload', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || '템플릿 업로드에 실패했습니다.');
        }
        applyTemplateSelection(data.template_name || file.name, data.template_text, data.template_id);
        showToast('양식이 적용되었습니다.', 'success');
    } catch (error) {
        console.error('[TEMPLATE] Upload failed:', error);
        showToast(error.message, 'error');
        clearTemplateSelection(false);
    } finally {
        isTemplateUploading = false;
        if (templateUploadBtn) {
            templateUploadBtn.disabled = false;
            templateUploadBtn.textContent = '양식 업로드하기';
        }
        if (templateFileInput) {
            templateFileInput.value = '';
        }
    }
}

function initTemplateUploadControls() {
    if (templateUploadBtn && templateFileInput) {
        templateUploadBtn.addEventListener('click', () => {
            templateFileInput.click();
        });
        templateFileInput.addEventListener('change', (event) => {
            const file = event.target.files && event.target.files[0];
            if (file) {
                uploadTemplateFile(file);
            }
        });
    }
    if (templateRemoveBtn) {
        templateRemoveBtn.addEventListener('click', () => {
            clearTemplateSelection(true);
        });
    }
}

function updateFontStatusLabel() {
    if (!fontFileStatus) return;
    if (isFontUploading) {
        fontFileStatus.textContent = '업로드 중...';
        return;
    }
    fontFileStatus.textContent = currentFontInfo ? `${currentFontInfo.font_name || '사용자 폰트'}` : '선택된 폰트 없음';
}

function clearFontSelection(showNotice = false) {
    currentFontInfo = null;
    if (fontFileInput) {
        fontFileInput.value = '';
    }
    updateFontStatusLabel();
    if (showNotice) {
        showToast('최근 업로드 기록을 지웠습니다.', 'info');
    }
}

function applyFontSelection(data) {
    currentFontInfo = data;
    updateFontStatusLabel();
    showToast('폰트가 업로드되었습니다. 목록에서 선택해 주세요.', 'success');
    fetchAvailableFonts();
}

async function uploadFontSelection(file) {
    if (!file || isFontUploading) return;
    isFontUploading = true;
    updateFontStatusLabel();
    const formData = new FormData();
    formData.append('font', file);
    try {
        const response = await fetch('/api/font/upload', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || '폰트 업로드에 실패했습니다.');
        }
        applyFontSelection({
            font_id: data.font_id,
            font_name: data.font_name,
            font_path: data.font_path
        });
    } catch (error) {
        console.error('[FONT] Upload failed:', error);
        showToast(error.message, 'error');
        clearFontSelection(false);
    } finally {
        isFontUploading = false;
        updateFontStatusLabel();
        if (fontFileInput) {
            fontFileInput.value = '';
        }
    }
}

function initFontUploadControls() {
    if (fontUploadBtn && fontFileInput) {
        fontUploadBtn.addEventListener('click', () => {
            fontFileInput.click();
        });
        fontFileInput.addEventListener('change', (event) => {
            const file = event.target.files && event.target.files[0];
            if (file) {
                uploadFontSelection(file);
            }
        });
    }
    if (fontRemoveBtn) {
        fontRemoveBtn.addEventListener('click', () => clearFontSelection(true));
    }
    updateFontStatusLabel();
}

function getCurrentFontSelections() {
    return {
        body: bodyFontSelect?.value || currentStyle.body_font_id || '',
        heading: headingFontSelect?.value || currentStyle.heading_font_id || '',
        title: titleFontSelect?.value || currentStyle.title_font_id || ''
    };
}

function setSelectValue(selectEl, value) {
    if (!selectEl || !selectEl.options.length) return;
    if (value && Array.from(selectEl.options).some(opt => opt.value === value)) {
        selectEl.value = value;
    } else {
        selectEl.selectedIndex = 0;
    }
}

function populateFontSelect(selectEl, selectedId) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    availableFonts.forEach((font) => {
        const option = document.createElement('option');
        option.value = font.id;
        option.textContent = font.display_name;
        selectEl.appendChild(option);
    });
    if (!availableFonts.length) {
        const fallback = document.createElement('option');
        fallback.value = 'system-default';
        fallback.textContent = '기본 폰트';
        selectEl.appendChild(fallback);
    }
    setSelectValue(selectEl, selectedId);
}

function populateFontSelects(selections = {}) {
    populateFontSelect(bodyFontSelect, selections.body || currentStyle.body_font_id);
    populateFontSelect(headingFontSelect, selections.heading || currentStyle.heading_font_id || selections.body);
    populateFontSelect(titleFontSelect, selections.title || currentStyle.title_font_id || selections.heading);
}

async function fetchAvailableFonts(preserveSelection = true) {
    const previous = preserveSelection ? getCurrentFontSelections() : {};
    try {
        const response = await fetch('/api/fonts');
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || '폰트 목록을 불러오지 못했습니다.');
        }
        availableFonts = data.fonts || [];
        fontsLoaded = true;
        populateFontSelects(previous);
    } catch (error) {
        console.error('[FONTS] Failed to load font catalog:', error);
        showToast(error.message || '폰트 목록 로드 실패', 'error');
    }
}

function findFontById(fontId) {
    if (!fontId) return null;
    return availableFonts.find(font => font.id === fontId) || null;
}

async function openStyleModal() {
    if (!fontsLoaded) {
        await fetchAvailableFonts(false);
    }
    populateStyleModalFields();
    styleModal.classList.add('show');
}

function populateStyleModalFields() {
    if (!styleModal) return;
    if (!fontsLoaded) {
        populateFontSelects();
    }
    setSelectValue(bodyFontSelect, currentStyle.body_font_id || bodyFontSelect?.value);
    setSelectValue(headingFontSelect, currentStyle.heading_font_id || headingFontSelect?.value || bodyFontSelect?.value);
    setSelectValue(titleFontSelect, currentStyle.title_font_id || titleFontSelect?.value || headingFontSelect?.value);
    if (titleSizeInput) {
        titleSizeInput.value = currentStyle.title_size || 24;
    }
    if (heading1SizeInput) {
        heading1SizeInput.value = currentStyle.heading_level1_size || 20;
    }
    if (heading2SizeInput) {
        heading2SizeInput.value = currentStyle.heading_level2_size || 18;
    }
    if (heading3SizeInput) {
        heading3SizeInput.value = currentStyle.heading_level3_size || 16;
    }
    if (fontSizeInput) {
        fontSizeInput.value = currentStyle.font_size || 13;
    }
    if (lineSpacingSelect) {
        lineSpacingSelect.value = currentStyle.line_spacing || '1.5';
    }
    updateFontStatusLabel();
}

function loadStoredRiroEvents() {
    try {
        const stored = localStorage.getItem('riroEvents');
        latestRiroEvents = stored ? JSON.parse(stored) : {};
    } catch {
        latestRiroEvents = {};
    }
    isRiroLoggedIn = localStorage.getItem('riroLoggedIn') === 'true';
    if (isRiroLoggedIn) {
        riroUserId = localStorage.getItem('riroUserId');
        if (!riroUserId) {
            isRiroLoggedIn = false;
            localStorage.removeItem('riroLoggedIn');
        }
    } else {
        riroUserId = null;
        localStorage.removeItem('riroUserId');
    }
    if (!isRiroLoggedIn) {
        purgeDocumentHistory();
    }
    updateRiroControls();
}

function clearStoredRiroEvents() {
    localStorage.removeItem('riroEvents');
    localStorage.removeItem('riroLoggedIn');
    localStorage.removeItem('riroUserId');
    latestRiroEvents = {};
    isRiroLoggedIn = false;
    riroUserId = null;
    updateRiroControls();
    const scheduleModal = document.getElementById('riroScheduleModal');
    const dayPopup = document.getElementById('riroDayPopup');
    if (scheduleModal) scheduleModal.classList.remove('show');
    if (dayPopup) dayPopup.style.display = 'none';
    resetRiroCalendarState();
}

function persistRiroEvents(events) {
    latestRiroEvents = events || {};
    localStorage.setItem('riroEvents', JSON.stringify(latestRiroEvents));
    localStorage.setItem('riroLoggedIn', 'true');
    isRiroLoggedIn = true;
    resetRiroCalendarState();
    updateRiroControls();
}

function updateRiroControls() {
    const showSchedule = isRiroLoggedIn;
    if (riroLoginOpenBtn) {
        riroLoginOpenBtn.style.display = showSchedule ? 'none' : 'inline-flex';
    }
    if (riroScheduleBtn) {
        riroScheduleBtn.style.display = showSchedule ? 'inline-flex' : 'none';
    }
    if (riroLogoutBtn) {
        riroLogoutBtn.style.display = showSchedule ? 'inline-flex' : 'none';
    }
    if (riroArchiveBtn) {
        riroArchiveBtn.style.display = showSchedule ? 'inline-flex' : 'none';
    }
}

function resetRiroCalendarState(baseDate = new Date()) {
    riroCalendarState = {
        year: baseDate.getFullYear(),
        month: baseDate.getMonth()
    };
}

function wipeAppCaches() {
    try {
        localStorage.clear();
    } catch (error) {
        console.warn('[CACHE] Failed to clear localStorage:', error);
    }
    try {
        sessionStorage.clear();
    } catch (error) {
        console.warn('[CACHE] Failed to clear sessionStorage:', error);
    }
}

function handleRiroLogoutNavigation() {
    clearStoredRiroEvents();
    resetDocumentState();
    purgeDocumentHistory();
    riroUserId = null;
    wipeAppCaches();
    fetch('/api/riroschool/logout', { method: 'POST' }).catch(() => {});
    showToast('리로스쿨에서 로그아웃되었습니다.', 'info');
    setTimeout(() => {
        window.location.href = '/';
    }, 300);
}

function setRiroLoginLoading(isLoading) {
    if (riroLoginOverlay) {
        riroLoginOverlay.style.display = isLoading ? 'flex' : 'none';
    }
    const submitBtn = document.getElementById('riroLoginSubmitBtn');
    if (submitBtn) {
        submitBtn.disabled = isLoading;
        submitBtn.textContent = isLoading ? '로그인 중...' : '로그인';
    }
    const modal = document.getElementById('riroLoginModal');
    if (modal) {
        modal.querySelectorAll('input, select, textarea, button').forEach((el) => {
            if (el.id === 'riroLoginSubmitBtn') return;
            if (isLoading) {
                el.setAttribute('data-disabled', 'true');
                el.disabled = true;
            } else if (el.getAttribute('data-disabled') === 'true') {
                el.disabled = false;
                el.removeAttribute('data-disabled');
            }
        });
    }
}

function closeRiroScheduleModal() {
    const scheduleModal = document.getElementById('riroScheduleModal');
    const dayPopup = document.getElementById('riroDayPopup');
    if (scheduleModal) {
        scheduleModal.classList.remove('show');
    }
    if (dayPopup) {
        dayPopup.style.display = 'none';
    }
}

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeRiroEventCollection(eventData) {
    if (!eventData) return [];
    if (Array.isArray(eventData)) {
        return eventData.filter(Boolean);
    }
    return [eventData];
}

function formatRiroDateLabel(dateStr) {
    const candidate = new Date(dateStr);
    if (Number.isNaN(candidate.getTime())) return dateStr;
    return `${candidate.getFullYear()}년 ${candidate.getMonth() + 1}월 ${candidate.getDate()}일`;
}

function buildDefaultGuideStructure(date) {
    const label = formatRiroDateLabel(date || new Date().toISOString().slice(0, 10));
    return `# ${label} 과제 기본 구조

## 1. 서론
- 주제 소개 및 작성 동기
- 관련 배경/문제의식 요약

## 2. 본론
- 핵심 내용 1 : 자료 조사, 실험, 분석 등
- 핵심 내용 2 : 결과 해석, 근거 제시

## 3. 결론
- 핵심 요약 및 느낀 점
- 향후 계획/제언

### 작성 체크리스트
- 분량: 최소 3페이지 (11pt 기준)
- 서체/크기: 제목 15pt, 본문 11pt
- 여백: 기본 용지 설정 유지
- 참고 자료 출처 명시`;
}

function injectGuideIntoRequest(guideText) {
    if (!userRequest) return;
    userRequest.value = guideText;
    userRequest.dispatchEvent(new Event('input', { bubbles: true }));
    userRequest.classList.remove('guide-pulse');
    // restart animation
    void userRequest.offsetWidth;
    userRequest.classList.add('guide-pulse');
    userRequest.addEventListener('animationend', () => {
        userRequest.classList.remove('guide-pulse');
    }, { once: true });
    userRequest.focus();
}

function setGuideButtonState(isLoading) {
    const popup = document.getElementById('riroDayPopup');
    const btn = popup?.querySelector('.btn-fetch-guide');
    if (btn) {
        btn.disabled = isLoading;
        btn.textContent = isLoading ? '가져오는 중...' : '가져오기';
    }
}

async function fetchRiroGuideFromServer(date, events) {
    try {
        const primaryEvent = events.find(evt => (evt?.url || evt?.link)) || events[0] || {};
        const eventUrl = primaryEvent?.url || primaryEvent?.link || '';
        const response = await fetch(RIRO_GUIDE_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                date,
                eventUrl,
                events: events.map(evt => ({
                    title: evt?.title || '',
                    description: evt?.description || evt?.desc || '',
                    url: evt?.url || evt?.link || '',
                    code: evt?.code || evt?.id || ''
                }))
            })
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        if (data?.success && data?.guide) {
            return data.guide;
        }
        return data?.guide || '';
    } catch (error) {
        console.error('[RIRO GUIDE] API 호출 실패:', error);
        return '';
    }
}

async function requestRiroGuide(date, events = []) {
    const normalizedEvents = Array.isArray(events) ? events : normalizeRiroEventCollection(events);
    if (!normalizedEvents.length) {
        showToast('가져올 일정이 없습니다.', 'warning');
        return;
    }
    const cachedGuideEvent = normalizedEvents.find(evt => evt?.guide);
    if (cachedGuideEvent && cachedGuideEvent.guide) {
        injectGuideIntoRequest(cachedGuideEvent.guide);
        closeRiroScheduleModal();
        showToast('과제 가이드라인을 입력창에 불러왔어요.', 'success');
        return;
    }
    setGuideButtonState(true);
    let guideText = '';
    try {
        guideText = await fetchRiroGuideFromServer(date, normalizedEvents);
    } catch (error) {
        console.error('[RIRO GUIDE] 처리 실패:', error);
    }
    if (guideText) {
        injectGuideIntoRequest(guideText);
        closeRiroScheduleModal();
        showToast('과제 가이드라인을 입력창에 불러왔어요.', 'success');
    } else {
        const defaultStructure = buildDefaultGuideStructure(date);
        injectGuideIntoRequest(defaultStructure);
        closeRiroScheduleModal();
        showToast('가이드 라인이 없습니다. 기본 구조를 입력창에 넣어드렸어요.', 'warning');
    }
    setGuideButtonState(false);
}

// 토스트 알림 함수
function showToast(message, type = 'info') {
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// 통계 업데이트
function updateStats() {
    const content = contentEditor.value;
    const chars = content.length;
    const words = content.trim() ? content.trim().split(/\s+/).length : 0;
    
    charCount.textContent = `${chars.toLocaleString()}자`;
    wordCount.textContent = `${words.toLocaleString()}단어`;
    
    // 저장 버튼 활성화
    saveBtn.disabled = !content.trim();
}

// PDF를 이미지로 로드
async function loadPdfAsImages(filename) {
    console.log('[PDF-IMG] Loading PDF as images:', filename);
    try {
        const response = await fetch(`/api/pdf-to-images/${encodeURIComponent(filename)}`);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('[PDF-IMG] Received', data.pages, 'pages');
        
        if (data.success && data.images) {
            // iframe 대신 이미지 컨테이너 생성
            const container = document.getElementById('pdfViewerContainer');
            
            // 기존 컨텐츠 제거
            pdfViewer.style.display = 'none';
            pdfPlaceholder.style.display = 'none';
            pdfLoading.style.display = 'none';
            
            // 이미지 컨테이너 생성 또는 업데이트
            let imageContainer = document.getElementById('pdfImageContainer');
            if (!imageContainer) {
                imageContainer = document.createElement('div');
                imageContainer.id = 'pdfImageContainer';
                imageContainer.className = 'pdf-image-container';
                container.appendChild(imageContainer);
            }
            
            // 이미지 표시
            imageContainer.innerHTML = data.images.map(page => `
                <div class="pdf-page">
                    <img src="${page.image}" alt="Page ${page.page}" />
                </div>
            `).join('');
            
            imageContainer.style.display = 'block';
            console.log('[PDF-IMG] Successfully displayed', data.images.length, 'pages');
            showToast(`✅ PDF 미리보기 준비 완료 (${data.pages}페이지)`, 'success');
        } else {
            console.error('[PDF-IMG] Load failed:', data.error);
            showToast(data.error || 'PDF 로드 실패', 'error');
            pdfPlaceholder.style.display = 'flex';
        }
    } catch (error) {
        console.error('[PDF-IMG] Error:', error);
        showToast('PDF 변환 오류: ' + error.message, 'error');
        pdfPlaceholder.style.display = 'flex';
    } finally {
        pdfLoading.style.display = 'none';
    }
}

// PDF 미리보기 생성
async function generatePdfPreview() {
    const title = docTitle.value.trim() || '문서';
    const content = contentEditor.value.trim();
    
    console.log('[PDF] Starting PDF generation');
    console.log('[PDF] Title:', title);
    console.log('[PDF] Content length:', content.length);
    console.log('[PDF] Images needed:', currentImagesNeeded);
    
    if (!content) {
        console.error('[PDF] No content to generate PDF');
        showToast('내용이 비어있습니다', 'error');
        return;
    }
    
    // 로딩 표시
    pdfLoading.style.display = 'flex';
    pdfPlaceholder.style.display = 'none';
    pdfViewer.style.display = 'none';
    
    // 기존 이미지 컨테이너 숨기기
    const existingImageContainer = document.getElementById('pdfImageContainer');
    if (existingImageContainer) {
        existingImageContainer.style.display = 'none';
    }
    
    try {
        console.log('[PDF] Sending request to /api/save');
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                title,
                content,
                format: 'pdf',
                style: currentStyle,
                images_needed: currentImagesNeeded,  // 이미지 키워드 전달
                image_urls: currentImageUrls  // 검색된 이미지 URL 전달
            }),
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('[PDF] Save response:', data);
        
        if (data.success) {
            const filename = data.file_path.split('/').pop();
            currentPdfFile = filename;
            console.log('[PDF] PDF file created:', filename);
            
            // PDF를 이미지로 변환하여 표시
            await loadPdfAsImages(filename);
        } else {
            console.error('[PDF] Save failed:', data.error);
            showToast(data.error || 'PDF 생성 실패', 'error');
            pdfLoading.style.display = 'none';
            pdfPlaceholder.style.display = 'flex';
        }
    } catch (error) {
        console.error('[PDF] Generation error:', error);
        showToast('PDF 생성 오류: ' + error.message, 'error');
        pdfLoading.style.display = 'none';
        pdfPlaceholder.style.display = 'flex';
    }
}

// HTML을 서식이 포함된 텍스트로 변환
function htmlToFormattedText(html) {
    const div = document.createElement('div');
    div.innerHTML = html;
    
    // HTML 태그를 마크다운 스타일로 변환
    div.querySelectorAll('h1').forEach(h => {
        h.outerHTML = `# ${h.textContent}\n\n`;
    });
    div.querySelectorAll('h2').forEach(h => {
        h.outerHTML = `## ${h.textContent}\n\n`;
    });
    div.querySelectorAll('h3').forEach(h => {
        h.outerHTML = `### ${h.textContent}\n\n`;
    });
    div.querySelectorAll('p').forEach(p => {
        p.outerHTML = `${p.innerHTML}\n\n`;
    });
    div.querySelectorAll('strong').forEach(s => {
        s.outerHTML = `**${s.textContent}**`;
    });
    div.querySelectorAll('em').forEach(e => {
        e.outerHTML = `*${e.textContent}*`;
    });
    
    return div.textContent;
}

// 텍스트를 HTML 서식으로 변환
function textToHtml(text) {
    let html = text;
    
    // [gen_img] 태그를 이미지 플레이스홀더로 변환
    html = html.replace(/\[gen_img\](.+?)\[\/gen_img\]/g, '<div class="gen-image-placeholder"><span class="image-icon">🖼️</span><span class="image-keyword">$1</span></div>');
    
    // 제목
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    
    // 굵게/기울임
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    
    // 단락
    html = html.split('\n\n').map(para => {
        if (para.trim() && !para.startsWith('<h')) {
            return `<p>${para}</p>`;
        }
        return para;
    }).join('\n');
    
    return html;
}

// 문자열 해시 함수
function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;  // Convert to 32bit integer
    }
    return hash;
}

// 이미지 URL 접근 가능성 테스트 (403 체크)
async function testImageUrl(url) {
    try {
        // HEAD 요청으로 빠르게 테스트
        const response = await fetch(url, { 
            method: 'HEAD',
            mode: 'no-cors',  // CORS 오류 방지
            cache: 'no-cache'
        });
        // no-cors 모드에서는 opaque response가 반환됨
        // 실제로는 img.onerror로 확인해야 함
        return true;  // 일단 허용
    } catch (e) {
        console.log(`[IMAGE TEST] Failed to test ${url.substring(0, 50)}:`, e.message);
        return true;  // 테스트 실패해도 일단 시도
    }
}

// 이미지 로드 가능성 테스트 (img 태그 사용)
function testImageLoad(url) {
    return new Promise((resolve) => {
        const img = new Image();
        const timeout = setTimeout(() => {
            resolve(false);  // 타임아웃
        }, 3000);  // 3초 대기
        
        img.onload = () => {
            clearTimeout(timeout);
            resolve(true);  // 성공
        };
        
        img.onerror = () => {
            clearTimeout(timeout);
            resolve(false);  // 실패 (403, 404 등)
        };
        
        img.src = url;
    });
}

// 이미지 검색 및 표시 - [gen_img] 플레이스홀더를 실제 이미지로 교체
async function fetchAndDisplayImages() {
    if (!currentImagesNeeded || currentImagesNeeded.length === 0) {
        return;
    }
    
    console.log('[IMAGES] Fetching images for:', currentImagesNeeded);
    
    try {
        // 모든 [gen_img] 플레이스홀더 찾기
        const placeholders = document.querySelectorAll('.gen-image-placeholder');
        
        if (placeholders.length === 0) {
            console.log('[IMAGES] No placeholders found');
            return;
        }
        
        console.log('[IMAGES] Found', placeholders.length, 'placeholders');
        
        // 각 키워드에 대해 이미지 검색 및 검증
        const imagePromises = currentImagesNeeded.map(async (keyword, index) => {
            try {
                console.log(`[IMAGES] Searching ${index + 1}/${currentImagesNeeded.length}: "${keyword}"`);
                const response = await fetch('/api/search-images', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: keyword, count: 3 })  // 3개 가져와서 테스트
                });
                const data = await response.json();
                
                if (!data.success || data.images.length === 0) {
                    return null;
                }
                
                // 각 이미지 URL을 테스트하여 접근 가능한 것 찾기
                console.log(`[IMAGES] Testing ${data.images.length} image URLs for: "${keyword}"`);
                for (const img of data.images) {
                    const isAccessible = await testImageLoad(img.url);
                    if (isAccessible) {
                        console.log(`[IMAGES] ✅ Accessible image found: ${img.url.substring(0, 60)}...`);
                        return { keyword, image: img, index };
                    } else {
                        console.log(`[IMAGES] ❌ Image not accessible (403/404): ${img.url.substring(0, 60)}...`);
                    }
                }
                
                // 모두 실패하면 fallback 사용
                console.log(`[IMAGES] All images failed, using fallback for: "${keyword}"`);
                const fallbackImg = {
                    url: `https://picsum.photos/seed/${Math.abs(hashCode(keyword))}/800/600`,
                    description: `${keyword} (fallback)`,
                    author: 'Lorem Picsum'
                };
                return { keyword, image: fallbackImg, index };
                
            } catch (e) {
                console.error('[IMAGES] Search failed for', keyword, e);
                return null;
            }
        });
        
        const results = await Promise.all(imagePromises);
        
        // 이미지 URL 저장 (다운로드 시 재사용)
        currentImageUrls = [];
        
        // 각 플레이스홀더를 실제 이미지로 교체
        results.forEach((result, index) => {
            if (result && result.image && placeholders[index]) {
                const img = result.image;
                
                // 이미지 URL 저장
                currentImageUrls.push({
                    keyword: result.keyword,
                    url: img.url,
                    description: img.description,
                    author: img.author
                });
                
                const imageElement = document.createElement('div');
                imageElement.className = 'gen-image-loaded';
                imageElement.innerHTML = `
                    <img src="${img.url}" alt="${img.description}" loading="lazy" />
                    <div class="image-caption">${result.keyword}</div>
                `;
                placeholders[index].replaceWith(imageElement);
                console.log(`[IMAGES] ✅ Replaced placeholder ${index + 1}:`);
                console.log(`  Keyword: "${result.keyword}"`);
                console.log(`  Image URL: ${img.url}`);
                console.log(`  Author: ${img.author}`);
            } else if (placeholders[index]) {
                console.log(`[IMAGES] ❌ No image found for placeholder ${index + 1}`);
                // 실패한 경우에도 null 추가 (인덱스 유지)
                currentImageUrls.push(null);
            }
        });
        
        const successCount = results.filter(r => r !== null).length;
        console.log(`[IMAGES] Total: ${successCount}/${currentImagesNeeded.length} images loaded`);
        
        if (successCount > 0) {
            showToast(`✅ 이미지 ${successCount}개 로드 완료`, 'success');
        }
        
    } catch (error) {
        console.error('[IMAGES] Error:', error);
        showToast('이미지 로드 오류', 'error');
    }
}

// HTML 미리보기 업데이트
function updateHtmlPreview() {
    const title = docTitle.value.trim();
    const content = contentEditor.value.trim();
    
    if (title) {
        previewTitle.textContent = title;
    }
    
    if (content) {
        previewContent.innerHTML = textToHtml(content);
        previewContent.scrollTop = previewContent.scrollHeight;
    }
    previewContent.scrollIntoView({ block: 'end', behavior: 'smooth' });
}

// 전역 변수: 이미지 키워드 및 URL 저장
let currentImagesNeeded = [];
let currentImageUrls = [];  // 검색된 이미지 URL 저장

// 서식 설정 전역 변수
let currentStyle = {
    font_name: '맑은 고딕',
    heading_font_name: '맑은 고딕',
    title_font_name: '맑은 고딕',
    font_size: 13,
    title_size: 24,
    heading_level1_size: 20,
    heading_level2_size: 18,
    heading_level3_size: 16,
    line_spacing: 1.5,
    font_file_path: '',
    heading_font_file_path: '',
    title_font_file_path: '',
    font_file_id: '',
    heading_font_file_id: '',
    title_font_file_id: '',
    font_file_name: '',
    heading_font_file_name: '',
    title_font_file_name: '',
    body_font_id: '',
    heading_font_id: '',
    title_font_id: ''
};

// 진행 바 표시/숨김
const progressBar = document.getElementById('progressBar');

function showProgressBar() {
    progressBar.style.display = 'block';
}

function hideProgressBar() {
    progressBar.style.display = 'none';
}

// AI 콘텐츠 생성 (스트리밍)
async function generateContent() {
    const request = userRequest.value.trim();
    const template = currentTemplateText ? currentTemplateText.trim() : '';
    const finalRequest = request || (template ? '제공된 문서 양식에 맞춰 전체 내용을 작성해 주세요.' : '');

    if (!finalRequest) {
        showToast('요청 내용 또는 문서 양식을 입력해주세요', 'error');
        return;
    }
    if (isTemplateUploading) {
        showToast('양식 업로드가 끝날 때까지 잠시 기다려주세요.', 'info');
        return;
    }
    
    // 진행 바 표시
    showProgressBar();
    
    // 로딩 상태
    const btnText = generateBtn.querySelector('.btn-text');
    const spinner = generateBtn.querySelector('.spinner');
    btnText.style.display = 'none';
    spinner.style.display = 'inline';
    generateBtn.disabled = true;
    
    // 에디터 초기화
    contentEditor.value = '';
    docTitle.value = '';
    
    // HTML 미리보기 표시, PDF 숨기기
    isStreaming = true;
    pdfViewerContainer.style.display = 'none';
    htmlPreviewContainer.style.display = 'block';
    previewTitle.textContent = '';
    previewContent.innerHTML = '';
    
    let streamCompleted = false;
    let finalBody = '';
    
    try {
        const response = await fetch('/api/generate-stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ request: finalRequest, template }),
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let chunkCount = 0;
        
        while (true) {
            const {done, value} = await reader.read();
            
            if (done) {
                console.log('[CLIENT] Stream reader done');
                break;
            }
            
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n\n');
            buffer = lines.pop(); // 마지막 불완전한 라인 보관
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const jsonStr = line.substring(6);
                    try {
                        const data = JSON.parse(jsonStr);
                        
                        if (data.error) {
                            showToast(data.error, 'error');
                            console.error('[CLIENT] Error from server:', data.error);
                            return;
                        }
                        
                        if (data.chunk) {
                            chunkCount++;
                            // 스트리밍 텍스트 추가
                            contentEditor.value += data.chunk;
                            updateStats();
                            
                            // HTML 미리보기 실시간 업데이트
                            updateHtmlPreview();
                        }
                        
                        if (data.done && data.result) {
                            console.log('[CLIENT] Received DONE signal');
                            console.log('[CLIENT] Total chunks received:', chunkCount);
                            console.log('[CLIENT] Result body length:', data.result.body ? data.result.body.length : 0);
                            console.log('[CLIENT] Current editor length:', contentEditor.value.length);
                            
                            // 중요: 서버에서 보낸 전체 body를 사용
                            if (data.result.body) {
                                finalBody = data.result.body;
                                contentEditor.value = finalBody;
                            } else {
                                finalBody = contentEditor.value;
                            }
                            
                            if (data.result.title) {
                                docTitle.value = data.result.title;
                            }
                            
                            // 이미지 키워드 저장
                            if (data.result.images_needed) {
                                currentImagesNeeded = data.result.images_needed;
                                console.log('[CLIENT] Images needed:', currentImagesNeeded);
                                
                                // 이미지 검색 및 표시
                                setTimeout(() => fetchAndDisplayImages(), 500);
                            }
                            
                            updateStats();
                            updateHtmlPreview();
                            
                            streamCompleted = true;
                            console.log('[CLIENT] Stream completed flag set to true');
                        }
                    } catch (e) {
                        console.error('[CLIENT] JSON parse error:', e, 'Line:', line);
                    }
                }
            }
        }
        
        // 버퍼에 남은 데이터 처리
        if (buffer.trim()) {
            console.log('[CLIENT] Processing remaining buffer:', buffer);
        }
        
    } catch (error) {
        showToast('서버 오류가 발생했습니다: ' + error.message, 'error');
        console.error('[CLIENT] Stream error:', error);
        return;
    } finally {
        btnText.style.display = 'inline';
        spinner.style.display = 'none';
        generateBtn.disabled = false;
        isStreaming = false;
        hideProgressBar();
    }
    
    // 스트리밍 완료 - HTML 프리뷰만 표시 (PDF는 저장 버튼 클릭 시 생성)
    if (streamCompleted && contentEditor.value.trim()) {
        console.log('[CLIENT] Document generation completed');
        showToast('✅ 문서 생성 완료! 저장 버튼으로 파일을 다운로드하세요.', 'success');
        
        // HTML 프리뷰 계속 표시 (PDF 자동 생성 제거)
        // htmlPreviewContainer는 이미 표시되어 있음
        
        // 모드 선택 UI 표시
        showModeSelector();
        
        // 히스토리에 자동 저장 (localStorage + 서버)
        const title = docTitle.value.trim() || '문서';
        saveToHistory(title, contentEditor.value);
    } else {
        console.error('[CLIENT] Stream did not complete properly. Completed:', streamCompleted, 'Has content:', !!contentEditor.value.trim());
        showToast('⚠️ 문서 생성이 완료되지 않았습니다.', 'error');
    }
}

// 문서 수정
async function refineContent() {
    const request = refineRequest.value.trim();
    const content = contentEditor.value.trim();
    
    if (!request || !content) {
        showToast('수정 요청과 내용을 확인해주세요', 'error');
        return;
    }
    
    refineBtn.disabled = true;
    refineBtn.textContent = '⏳ 수정 중...';
    
    try {
        const response = await fetch('/api/refine', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                content,
                request,
            }),
        });
        
        const data = await response.json();
        
        if (data.success) {
            contentEditor.value = data.content;
            updateStats();
            refineRequest.value = '';
            showToast('✅ 문서가 수정되었습니다!', 'success');
            
            // PDF 재생성
            await generatePdfPreview();
        } else {
            showToast(data.error || '수정 실패', 'error');
        }
    } catch (error) {
        showToast('서버 오류가 발생했습니다', 'error');
        console.error(error);
    } finally {
        refineBtn.disabled = false;
        refineBtn.textContent = '🔄 수정 요청';
    }
}

// HTML 프리뷰를 PDF로 저장하는 함수
async function convertHtmlToPdf() {
    const title = docTitle.value.trim() || '문서';
    const content = contentEditor.value.trim();
    
    if (!content) {
        showToast('저장할 내용이 없습니다', 'error');
        return;
    }
    
    console.log('[PDF SAVE] Starting PDF conversion');
    console.log('[PDF SAVE] Title:', title);
    console.log('[PDF SAVE] Content length:', content.length);
    console.log('[PDF SAVE] Images:', currentImageUrls);
    
    showProgressBar();
    saveBtn.disabled = true;
    saveBtn.textContent = '💾 저장 중...';
    
    try {
        // HTML 프리뷰를 그대로 PDF로 변환
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                title,
                content,
                format: 'pdf',
                style: currentStyle,
                images_needed: currentImagesNeeded,
                image_urls: currentImageUrls
            }),
        });
        
        console.log('[PDF SAVE] Response status:', response.status);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('[PDF SAVE] Response data:', data);
        
        if (data.success) {
            const filename = data.file_path.split('/').pop();
            const imagesCount = data.images_count || 0;
            const imageMsg = imagesCount > 0 ? ` (이미지 ${imagesCount}개 포함)` : '';
            
            console.log('[PDF SAVE] PDF filename:', filename);
            console.log('[PDF SAVE] Starting download...');
            
            showToast(`✅ PDF 파일이 생성되었습니다!${imageMsg}`, 'success');
            
            // 즉시 다운로드
            const downloadUrl = `/api/download/${encodeURIComponent(filename)}`;
            console.log('[PDF SAVE] Download URL:', downloadUrl);
            
            setTimeout(() => {
                window.location.href = downloadUrl;
            }, 500);
        } else {
            console.error('[PDF SAVE] Failed:', data.error);
            showToast(data.error || 'PDF 생성 실패', 'error');
        }
    } catch (error) {
        console.error('[PDF SAVE] Error:', error);
        showToast('서버 오류가 발생했습니다: ' + error.message, 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '저장';
        hideProgressBar();
    }
}

// 문서 저장
async function saveDocument() {
    const format = formatSelect.value;
    
    // PDF 형식이면 HTML 프리뷰를 그대로 PDF로 변환
    if (format === 'pdf') {
        await convertHtmlToPdf();
        return;
    }
    
    // 다른 형식 (HWP, DOCX, MD)
    const title = docTitle.value.trim() || '문서';
    const content = contentEditor.value.trim();
    
    if (!content) {
        showToast('저장할 내용이 없습니다', 'error');
        return;
    }
    
    showProgressBar();
    saveBtn.disabled = true;
    saveBtn.textContent = '💾 저장 중...';
    
    try {
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                title,
                content,
                format,
                style: currentStyle,
                images_needed: currentImagesNeeded,
                image_urls: currentImageUrls
            }),
        });
        
        const data = await response.json();
        
        if (data.success) {
            const filename = data.file_path.split('/').pop();
            const imagesCount = data.images_count || 0;
            const imageMsg = imagesCount > 0 ? ` (이미지 ${imagesCount}개 포함)` : '';
            
            showToast(`✅ ${format.toUpperCase()} 파일로 저장되었습니다!${imageMsg}`, 'success');
            
            // 다운로드
            setTimeout(() => {
                window.location.href = `/api/download/${encodeURIComponent(filename)}`;
            }, 500);
        } else {
            showToast(data.error || '저장 실패', 'error');
        }
    } catch (error) {
        showToast('서버 오류가 발생했습니다', 'error');
        console.error(error);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '저장';
        hideProgressBar();
    }
}

// 서식 조정
async function adjustFormat() {
    const request = formatRequest.value.trim();
    const content = contentEditor.value.trim();
    
    if (!request || !content) {
        showToast('서식 조정 요청과 내용을 확인해주세요', 'error');
        return;
    }
    
    formatAdjustBtn.disabled = true;
    formatAdjustBtn.textContent = '⏳ 서식 적용 중...';
    
    console.log('[FORMAT] Adjusting format:', request);
    
    try {
        const response = await fetch('/api/adjust-format', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                content,
                request,
            }),
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('[FORMAT] Response:', data);
        
        if (data.success) {
            contentEditor.value = data.content;
            updateStats();
            updateHtmlPreview();
            formatRequest.value = '';
            showToast('✅ 서식이 적용되었습니다!', 'success');
            
            // PDF 재생성
            showToast('PDF를 재생성하는 중...', 'info');
            await new Promise(resolve => setTimeout(resolve, 1000));
            await generatePdfPreview();
        } else {
            showToast(data.error || '서식 적용 실패', 'error');
        }
    } catch (error) {
        showToast('서버 오류가 발생했습니다: ' + error.message, 'error');
        console.error('[FORMAT ERROR]', error);
    } finally {
        formatAdjustBtn.disabled = false;
        formatAdjustBtn.textContent = '✨ 서식 적용';
    }
}

// ============================================
// UI 모드 전환 로직
// ============================================

const initialInputSection = document.getElementById('initialInputSection');
const modeSelector = document.getElementById('modeSelector');
const unifiedInputSection = document.getElementById('unifiedInputSection');
const directEditBtn = document.getElementById('directEditBtn');
const modifyBtn = document.getElementById('modifyBtn');
const formatBtn = document.getElementById('formatBtn');
const backBtn = document.getElementById('backBtn');
const applyBtn = document.getElementById('applyBtn');
const unifiedRequest = document.getElementById('unifiedRequest');
const editModeToggle = document.getElementById('editModeToggle');
const toggleEditBtn = document.getElementById('toggleEditBtn');

let currentMode = null;  // 'modify', 'format', 'direct'
let isEditMode = false;  // 직접 편집 모드 여부

const placeholders = {
    modify: "어떻게 수정할까요?\n\n예시:\n더 전문적으로 작성해줘\n3개 문단으로 요약해줘\n초등학생도 이해할 수 있게 쉽게 써줘",
    format: "서식을 어떻게 변경할까요?\n\n예시:\n첫 번째 문단 볼드처리\n기후변화 단어 모두 기울임\n제목을 대제목으로 변경"
};

// 문서 생성 완료 후 모드 선택 표시
function showModeSelector() {
    initialInputSection.style.display = 'none';
    modeSelector.style.display = 'flex';
    unifiedInputSection.style.display = 'none';
    editModeToggle.style.display = 'block';  // 편집 모드 버튼 표시
}

// 모드 선택 후 입력 섹션 표시
function showUnifiedInput(mode) {
    currentMode = mode;
    
    if (mode === 'direct') {
        // 직접 편집 모드 활성화
        enableDirectEdit();
        return;
    }
    
    modeSelector.style.display = 'none';
    unifiedInputSection.style.display = 'flex';
    unifiedRequest.placeholder = placeholders[mode];
    unifiedRequest.value = '';
    unifiedRequest.focus();
}

// 모드 선택 화면으로 돌아가기
function backToModeSelector() {
    unifiedInputSection.style.display = 'none';
    modeSelector.style.display = 'flex';
    currentMode = null;
}

// 수정/서식 적용 실행
async function applyCurrentMode() {
    const request = unifiedRequest.value.trim();
    const content = contentEditor.value.trim();
    
    if (!request || !content) {
        showToast('요청 내용을 입력해주세요', 'error');
        return;
    }
    
    const btnText = applyBtn.querySelector('.btn-text');
    const spinner = applyBtn.querySelector('.spinner');
    btnText.style.display = 'none';
    spinner.style.display = 'inline';
    applyBtn.disabled = true;
    
    try {
        if (currentMode === 'modify') {
            // 문서 수정 (스트리밍)
            await refineContentWithAnimation(content, request);
            unifiedRequest.value = '';
            backToModeSelector();
        } else if (currentMode === 'format') {
            // 서식 조정
            const response = await fetch('/api/adjust-format', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content, request }),
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            if (data.success) {
                contentEditor.value = data.content;
                updateStats();
                updateHtmlPreview();
                unifiedRequest.value = '';
                showToast('✅ 서식이 적용되었습니다!', 'success');
                backToModeSelector();
            } else {
                showToast(data.error || '서식 적용 실패', 'error');
            }
        }
    } catch (error) {
        showToast('서버 오류가 발생했습니다: ' + error.message, 'error');
        console.error(error);
    } finally {
        btnText.style.display = 'inline';
        spinner.style.display = 'none';
        applyBtn.disabled = false;
    }
}

// ============================================
// AI 수정 스트리밍 및 애니메이션
// ============================================

async function refineContentWithAnimation(originalContent, request) {
    console.log('[REFINE STREAM] Starting...');
    
    // 1. 기존 콘텐츠에 삭제 애니메이션 적용
    previewContent.classList.add('content-updating');
    
    // 짧은 딥레이 후 기존 콘텐츠 삭제 애니메이션
    await new Promise(resolve => setTimeout(resolve, 300));
    
    // 기존 콘텐츠를 서서히 페이드 아웃
    previewContent.style.transition = 'opacity 0.5s ease-out';
    previewContent.style.opacity = '0.3';
    
    await new Promise(resolve => setTimeout(resolve, 500));
    
    // 2. 스트리밍으로 새 콘텐츠 받기
    try {
        const response = await fetch('/api/refine-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: originalContent, request }),
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let newContent = '';
        
        // 커서 추가
        previewContent.innerHTML = '<span class="typing-cursor"></span>';
        previewContent.style.opacity = '1';
        
        while (true) {
            const {done, value} = await reader.read();
            
            if (done) {
                console.log('[REFINE STREAM] Done');
                break;
            }
            
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\n\n');
            buffer = lines.pop();
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const jsonStr = line.substring(6);
                    try {
                        const data = JSON.parse(jsonStr);
                        
                        if (data.error) {
                            showToast(data.error, 'error');
                            console.error('[REFINE STREAM] Error:', data.error);
                            return;
                        }
                        
                        if (data.chunk) {
                            newContent += data.chunk;
                            
                            // HTML로 변환하여 표시
                            const htmlContent = textToHtml(newContent);
                            previewContent.innerHTML = htmlContent + '<span class="typing-cursor"></span>';
                            
                            // 스크롤 하단으로
                            previewContent.scrollTop = previewContent.scrollHeight;
                            previewContent.scrollIntoView({ block: 'end', behavior: 'smooth' });
                        }
                        
                        if (data.done) {
                            console.log('[REFINE STREAM] Complete');
                            // 커서 제거
                            previewContent.innerHTML = textToHtml(newContent);
                            
                            // contentEditor에 동기화
                            contentEditor.value = newContent;
                            updateStats();
                            
                            showToast('✅ 문서가 수정되었습니다!', 'success');
                        }
                    } catch (e) {
                        console.error('[REFINE STREAM] JSON parse error:', e, 'Line:', line);
                    }
                }
            }
        }
        
    } catch (error) {
        console.error('[REFINE STREAM] Error:', error);
        showToast('수정 중 오류가 발생했습니다: ' + error.message, 'error');
        
        // 원래 콘텐츠 복원
        updateHtmlPreview();
    } finally {
        previewContent.classList.remove('content-updating');
        previewContent.style.transition = '';
        previewContent.style.opacity = '1';
    }
}

// ============================================
// 직접 편집 모드
// ============================================

function enableDirectEdit() {
    isEditMode = true;
    previewContent.contentEditable = 'true';
    toggleEditBtn.classList.add('active');
    toggleEditBtn.innerHTML = '<i class="bi bi-check-square"></i> 편집 완료';
    modeSelector.style.display = 'none';
    previewContent.focus();
    showToast('직접 편집 모드가 활성화되었습니다', 'info');
}

function disableDirectEdit() {
    isEditMode = false;
    previewContent.contentEditable = 'false';
    toggleEditBtn.classList.remove('active');
    toggleEditBtn.innerHTML = '<i class="bi bi-pencil-square"></i> 편집 모드';
    
    // 편집된 내용을 contentEditor에 동기화
    syncContentFromPreview();
    
    showToast('편집 내용이 저장되었습니다', 'success');
    modeSelector.style.display = 'flex';
}

function syncContentFromPreview() {
    // HTML 프리뷰에서 텍스트 추출
    const htmlContent = previewContent.innerHTML;
    
    // HTML을 마크다운 스타일로 변환
    let markdown = htmlContent;
    
    // 제목 변환
    markdown = markdown.replace(/<h1>(.*?)<\/h1>/g, '# $1\n\n');
    markdown = markdown.replace(/<h2>(.*?)<\/h2>/g, '## $1\n\n');
    markdown = markdown.replace(/<h3>(.*?)<\/h3>/g, '### $1\n\n');
    
    // 굵게/기울임
    markdown = markdown.replace(/<strong>(.*?)<\/strong>/g, '**$1**');
    markdown = markdown.replace(/<em>(.*?)<\/em>/g, '*$1*');
    
    // 단락
    markdown = markdown.replace(/<p>(.*?)<\/p>/g, '$1\n\n');
    
    // 이미지 플레이스홀더
    markdown = markdown.replace(/<div class="gen-image-placeholder">.*?<span class="image-keyword">(.*?)<\/span><\/div>/g, '[gen_img]$1[/gen_img]\n\n');
    markdown = markdown.replace(/<div class="gen-image-loaded">.*?<div class="image-caption">(.*?)<\/div><\/div>/g, '[gen_img]$1[/gen_img]\n\n');
    
    // HTML 태그 제거
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = markdown;
    markdown = tempDiv.textContent || tempDiv.innerText || '';
    
    contentEditor.value = markdown.trim();
    updateStats();
}

toggleEditBtn.addEventListener('click', () => {
    if (isEditMode) {
        disableDirectEdit();
    } else {
        enableDirectEdit();
    }
});

// 이벤트 리스너: 모드 선택
directEditBtn.addEventListener('click', () => showUnifiedInput('direct'));
modifyBtn.addEventListener('click', () => showUnifiedInput('modify'));
formatBtn.addEventListener('click', () => showUnifiedInput('format'));
backBtn.addEventListener('click', backToModeSelector);
applyBtn.addEventListener('click', applyCurrentMode);

// Enter 키로 적용
unifiedRequest.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        applyCurrentMode();
    }
});

// 이벤트 리스너
generateBtn.addEventListener('click', generateContent);
saveBtn.addEventListener('click', saveDocument);
contentEditor.addEventListener('input', updateStats);

// Enter 키로 생성/수정
if (userRequest) {
    userRequest.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            generateContent();
        }
    });
}

if (refineRequest) {
    refineRequest.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            refineContent();
        }
    });
}

// 서식 설정
const styleBtn = document.getElementById('styleBtn');
const styleModal = document.getElementById('styleModal');

if (styleBtn) {
    styleBtn.addEventListener('click', openStyleModal);
}

function closeStyleModal() {
    styleModal.classList.remove('show');
}

async function applyStyle() {
    if (isFontUploading) {
        showToast('폰트 업로드가 끝날 때까지 잠시만 기다려주세요.', 'info');
        return;
    }

    const bodyFont = findFontById(bodyFontSelect?.value) || availableFonts[0] || {
        id: 'system-default',
        docx_name: '맑은 고딕',
        display_name: '맑은 고딕 (OS 기본)',
        font_path: ''
    };
    const headingFont = findFontById(headingFontSelect?.value) || bodyFont;
    const titleFont = findFontById(titleFontSelect?.value) || headingFont;

    const titleSize = parseFloat(titleSizeInput?.value) || 24;
    const heading1 = parseFloat(heading1SizeInput?.value) || 20;
    const heading2 = parseFloat(heading2SizeInput?.value) || 18;
    const heading3 = parseFloat(heading3SizeInput?.value) || 16;
    const bodySize = parseFloat(fontSizeInput?.value) || 13;
    const spacing = parseFloat(lineSpacingSelect?.value) || 1.5;

    const normalizedHeading3 = Math.max(bodySize + 0.5, heading3);
    const normalizedHeading2 = Math.max(normalizedHeading3 + 0.5, heading2);
    const normalizedHeading1 = Math.max(normalizedHeading2 + 0.5, heading1);
    const normalizedTitle = Math.max(normalizedHeading1 + 1, titleSize);

    currentStyle = {
        font_name: bodyFont.docx_name || bodyFont.display_name || '맑은 고딕',
        heading_font_name: headingFont.docx_name || headingFont.display_name || bodyFont.docx_name,
        title_font_name: titleFont.docx_name || titleFont.display_name || headingFont.docx_name,
        font_size: bodySize,
        title_size: normalizedTitle,
        heading_level1_size: normalizedHeading1,
        heading_level2_size: normalizedHeading2,
        heading_level3_size: normalizedHeading3,
        line_spacing: spacing,
        font_file_path: bodyFont.font_path || '',
        heading_font_file_path: headingFont.font_path || '',
        title_font_file_path: titleFont.font_path || '',
        font_file_id: bodyFont.id || '',
        heading_font_file_id: headingFont.id || '',
        title_font_file_id: titleFont.id || '',
        font_file_name: bodyFont.display_name || bodyFont.docx_name || '',
        heading_font_file_name: headingFont.display_name || headingFont.docx_name || '',
        title_font_file_name: titleFont.display_name || titleFont.docx_name || '',
        body_font_id: bodyFont.id || '',
        heading_font_id: headingFont.id || '',
        title_font_id: titleFont.id || ''
    };
    
    showToast('서식을 적용하고 PDF를 재생성합니다...', 'info');
    closeStyleModal();
    
    // PDF 재생성
    await generatePdfPreview();
}

// 모달 외부 클릭 시 닫기 (서식)
if (styleModal) {
    styleModal.addEventListener('click', (e) => {
        if (e.target === styleModal) {
            closeStyleModal();
        }
    });
}

// 리로스쿨 로그인 모달 동작
function initRiroLoginModal() {
    const riroLoginModal = document.getElementById('riroLoginModal');
    const riroLoginCloseBtn = document.getElementById('riroLoginCloseBtn');
    const riroLoginCancelBtn = document.getElementById('riroLoginCancelBtn');
    const riroLoginSubmitBtn = document.getElementById('riroLoginSubmitBtn');

    console.log('[RIRO LOGIN] Initializing modal...');
    console.log('[RIRO LOGIN] Open button:', riroLoginOpenBtn);
    console.log('[RIRO LOGIN] Modal:', riroLoginModal);

    const openRiroLogin = () => {
        console.log('[RIRO LOGIN] Opening modal...');
        if (riroLoginModal) {
            riroLoginModal.classList.add('show');
            console.log('[RIRO LOGIN] Modal classes:', riroLoginModal.className);
        }
    };
    
    const closeRiroLogin = () => {
        console.log('[RIRO LOGIN] Closing modal...');
        if (riroLoginModal) {
            riroLoginModal.classList.remove('show');
            setRiroLoginLoading(false);
        }
    };

    if (riroLoginOpenBtn) {
        riroLoginOpenBtn.addEventListener('click', (e) => {
            console.log('[RIRO LOGIN] Button clicked!');
            e.preventDefault();
            openRiroLogin();
        });
        console.log('[RIRO LOGIN] Event listener attached to open button');
    } else {
        console.error('[RIRO LOGIN] Open button not found!');
    }

    if (riroLoginCloseBtn) {
        riroLoginCloseBtn.addEventListener('click', closeRiroLogin);
    }
    
    if (riroLoginCancelBtn) {
        riroLoginCancelBtn.addEventListener('click', closeRiroLogin);
    }
    
    if (riroLoginModal) {
        riroLoginModal.addEventListener('click', (e) => {
            if (e.target === riroLoginModal) closeRiroLogin();
        });
    }
    
    if (riroLoginSubmitBtn) {
        riroLoginSubmitBtn.addEventListener('click', async () => {
            const school = document.getElementById('riroSchool').value.trim();
            const username = document.getElementById('riroId').value.trim();
            const password = document.getElementById('riroPw').value.trim();
            
            if (!school || !username || !password) {
                showToast('모든 필드를 입력해주세요.', 'error');
                return;
            }
            
            console.log('[RIRO LOGIN] School:', school);
            console.log('[RIRO LOGIN] Username:', username);
            
            setRiroLoginLoading(true);
            try {
                // API 호출
                const response = await fetch('/api/riroschool/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        school: school,
                        username: username,
                        password: password,
                        grade: '1',
                        year: '2025'
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    console.log('[RIRO LOGIN] Success!', data);
                    riroUserId = data.riro_id || username;
                    if (riroUserId) {
                        localStorage.setItem('riroUserId', riroUserId);
                    }
                    persistRiroEvents(data.events || {});
                    closeRiroLogin();
                    showToast(`${school} 계정과 연동되었습니다.`, 'success');
                } else {
                    console.error('[RIRO LOGIN] Failed:', data.error);
                    showToast(`❌ ${data.error}`, 'error');
                }
            } catch (error) {
                console.error('[RIRO LOGIN] Error:', error);
                showToast('네트워크 오류가 발생했습니다.', 'error');
            } finally {
                setRiroLoginLoading(false);
            }
        });
    }
}

function initRiroScheduleModal() {
    const scheduleModal = document.getElementById('riroScheduleModal');
    const closeBtn = document.getElementById('riroScheduleCloseBtn');
    const dismissBtn = document.getElementById('riroScheduleDismissBtn');
    const dayPopup = document.getElementById('riroDayPopup');
    if (!riroScheduleBtn || !scheduleModal) return;
    
    const openModal = () => {
        if (!isRiroLoggedIn) {
            showToast('리로스쿨 로그인 후 이용해주세요.', 'info');
            return;
        }
        renderRiroSchedule();
        scheduleModal.classList.add('show');
    };
    
    const closeModal = () => {
        scheduleModal.classList.remove('show');
        if (dayPopup) dayPopup.style.display = 'none';
    };
    
    riroScheduleBtn.addEventListener('click', openModal);
    closeBtn?.addEventListener('click', closeModal);
    dismissBtn?.addEventListener('click', closeModal);
    scheduleModal.addEventListener('click', (e) => {
        if (e.target === scheduleModal) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && scheduleModal.classList.contains('show')) {
            closeModal();
        }
    });
}

function renderRiroSchedule(events = latestRiroEvents || {}) {
    const calendarEl = document.getElementById('riroCalendarContainer');
    const dayPopup = document.getElementById('riroDayPopup');
    if (!calendarEl) return;
    
    const eventDates = Object.keys(events || {});
    const map = eventDates.reduce((acc, date) => {
        acc[date] = events[date];
        return acc;
    }, {});
    
    const state = riroCalendarState || {};
    const today = new Date();
    const year = Number.isFinite(state.year) ? state.year : today.getFullYear();
    const month = Number.isFinite(state.month) ? state.month : today.getMonth();
    const first = new Date(year, month, 1);
    const start = first.getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const weekdays = ['일', '월', '화', '수', '목', '금', '토'];
    
    let calendarHtml = `
        <div class="riro-calendar-header">
            <button class="calendar-nav" data-offset="-1" aria-label="이전 달 보기">&lsaquo;</button>
            <span>${year}년 ${month + 1}월</span>
            <button class="calendar-nav" data-offset="1" aria-label="다음 달 보기">&rsaquo;</button>
        </div>
    `;
    calendarHtml += '<div class="riro-calendar-grid">';
    weekdays.forEach(day => {
        calendarHtml += `<div class="weekday">${day}</div>`;
    });
    
    for (let i = 0; i < start; i += 1) {
        calendarHtml += '<div class="riro-calendar-day empty"></div>';
    }
    
    for (let day = 1; day <= daysInMonth; day += 1) {
        const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const hasEvent = Boolean(map[dateStr]);
        calendarHtml += `<div class="riro-calendar-day${hasEvent ? ' has-event' : ''}"${hasEvent ? ` data-date="${dateStr}"` : ''}>
            <span class="day-number">${day}</span>
        </div>`;
    }
    
    calendarHtml += '</div>';
    calendarEl.innerHTML = calendarHtml;
    if (dayPopup) {
        dayPopup.style.display = 'none';
        dayPopup.innerHTML = '';
    }
    
    calendarEl.querySelectorAll('.calendar-nav').forEach((btn) => {
        btn.addEventListener('click', () => {
            const offset = Number(btn.dataset.offset);
            shiftRiroCalendar(offset, events);
        });
    });
    
    calendarEl.querySelectorAll('.riro-calendar-day.has-event').forEach(cell => {
        cell.addEventListener('click', () => {
            const date = cell.dataset.date;
            if (date) showDayPopup(date, events[date]);
        });
    });
}

function shiftRiroCalendar(offset = 0, events = latestRiroEvents || {}) {
    if (!Number.isFinite(offset)) return;
    const base = new Date(
        riroCalendarState.year,
        riroCalendarState.month + offset,
        1
    );
    riroCalendarState = {
        year: base.getFullYear(),
        month: base.getMonth()
    };
    renderRiroSchedule(events);
}

function showDayPopup(date, eventData) {
    const popup = document.getElementById('riroDayPopup');
    if (!popup) return;
    const formatted = formatRiroDateLabel(date);
    const events = normalizeRiroEventCollection(eventData);
    const hasEvents = events.length > 0;
    const bodyContent = hasEvents
        ? events.map(evt => {
            const safeTitle = escapeHtml(evt?.title || '등록된 일정');
            const safeDesc = escapeHtml(evt?.description || evt?.desc || '');
            const safeUrl = escapeHtml(evt?.url || evt?.link || '');
            return `
                <div class="popup-event${safeUrl ? ' has-link' : ''}">
                    <div class="event-title">${safeTitle}</div>
                    ${safeDesc ? `<div class="event-desc">${safeDesc}</div>` : ''}
                    ${safeUrl ? `<a href="${safeUrl}" target="_blank" rel="noopener">상세보기</a>` : ''}
                </div>
            `;
        }).join('')
        : '<div class="popup-empty">등록된 일정이 없습니다.</div>';
    const actionSection = hasEvents ? `
        <div class="popup-actions">
            <button class="btn-fetch-guide" type="button" data-date="${date}" title="과제 가이드라인을 왼쪽 입력창으로 가져오기">
                가져오기
            </button>
        </div>
    ` : '';
    
    popup.innerHTML = `
        <div class="popup-header">
            <span>${formatted}</span>
            <button class="popup-close" type="button">&times;</button>
        </div>
        <div class="popup-body">
            ${bodyContent}
        </div>
        ${actionSection}
    `;
    popup.style.display = 'block';
    const closeBtn = popup.querySelector('.popup-close');
    closeBtn?.addEventListener('click', () => {
        popup.style.display = 'none';
    });
    const fetchBtn = popup.querySelector('.btn-fetch-guide');
    if (fetchBtn) {
        fetchBtn.addEventListener('click', () => requestRiroGuide(date, events));
    }
}

async function saveRiroDocumentSnapshot(title, content) {
    if (!riroUserId) return;
    try {
        const response = await fetch('/api/riroschool/documents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title,
                content,
                image_urls: (currentImageUrls || []).filter((url) => !!url)
            })
        });
        if (response.status === 401) {
            riroUserId = null;
            localStorage.removeItem('riroUserId');
            localStorage.removeItem('riroLoggedIn');
            isRiroLoggedIn = false;
            updateRiroControls();
            return;
        }
        const data = await response.json();
        if (!data.success) {
            console.error('[RIRO DOCS] Save failed:', data.error);
        }
    } catch (error) {
        console.error('[RIRO DOCS] Save failed:', error);
    }
}

function applyRiroDocument(doc) {
    if (!doc) return;
    docTitle.value = doc.title || '문서';
    contentEditor.value = doc.content || '';
    currentImageUrls = Array.isArray(doc.image_urls) ? doc.image_urls.slice() : [];
    updateStats();
    if (htmlPreviewContainer) {
        htmlPreviewContainer.style.display = 'block';
    }
    if (pdfViewerContainer) {
        pdfViewerContainer.style.display = 'none';
    }
    updateHtmlPreview();
    showModeSelector();
    showToast('저장된 문서를 불러왔습니다.', 'success');
}

function consumeDeferredRiroDocument() {
    try {
        const stored = localStorage.getItem(RiroDraftStorageKey);
        if (!stored) return;
        localStorage.removeItem(RiroDraftStorageKey);
        const doc = JSON.parse(stored);
        applyRiroDocument(doc);
    } catch (error) {
        console.warn('[RIRO DOCS] Failed to consume deferred draft:', error);
    }
}

if (riroArchiveBtn) {
    riroArchiveBtn.addEventListener('click', () => {
        if (!isRiroLoggedIn) {
            showToast('리로스쿨 로그인 후 이용해주세요.', 'info');
            return;
        }
        window.location.href = '/riroschool/docs';
    });
}

function initRiroFeatures() {
    loadStoredRiroEvents();
    initRiroLoginModal();
    initRiroScheduleModal();
    if (brandTitle) {
        brandTitle.addEventListener('click', () => {
            clearStoredRiroEvents();
            showToast('리로스쿨 정보가 초기화되었습니다.', 'info');
        });
    }
    if (riroLogoutBtn) {
        riroLogoutBtn.addEventListener('click', handleRiroLogoutNavigation);
    }
    consumeDeferredRiroDocument();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initRiroFeatures);
} else {
    initRiroFeatures();
}

// 초기 통계 표시
updateStats();

// ============================================
// 페이지 로드 시 마지막 문서 복원
// ============================================

function restoreLastDocument() {
    try {
        const documents = getDocumentsFromStorage();
        
        if (documents && documents.length > 0) {
            // 가장 최근 문서 가져오기
            const lastDoc = documents[0];
            
            console.log('[RESTORE] Restoring last document:', lastDoc.title);
            
            // 제목과 내용 복원
            docTitle.value = lastDoc.title;
            contentEditor.value = lastDoc.content;

            if (lastDoc.template_text) {
                applyTemplateSelection(lastDoc.template_name || '저장된 양식', lastDoc.template_text);
            } else {
                clearTemplateSelection(false);
            }
            
            // 통계 업데이트
            updateStats();
            
            // HTML 미리보기 표시
            htmlPreviewContainer.style.display = 'block';
            pdfViewerContainer.style.display = 'none';
            updateHtmlPreview();
            
            // 이미지 추출 및 표시
            const imageMatches = lastDoc.content.match(/\[gen_img\](.+?)\[\/gen_img\]/g);
            if (imageMatches) {
                currentImagesNeeded = imageMatches.map(match => 
                    match.replace(/\[gen_img\]|\[\/gen_img\]/g, '')
                );
                console.log('[RESTORE] Images needed:', currentImagesNeeded);
                setTimeout(() => fetchAndDisplayImages(), 500);
            }
            
            // 모드 선택 UI 표시
            showModeSelector();
            
            showToast('📄 마지막 문서를 복원했습니다', 'info');
        }
    } catch (error) {
        console.error('[RESTORE] Failed to restore document:', error);
    }
}

// 페이지 로드 후 마지막 문서 복원
window.addEventListener('DOMContentLoaded', () => {
    restoreLastDocument();
});

// ============================================
// localStorage 기반 문서 히스토리 관리
// ============================================

const STORAGE_KEY = 'hwp_agent_documents';
const MAX_DOCUMENTS = 50;  // 최대 저장 문서 수

function purgeDocumentHistory() {
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
        console.warn('[DOC STORAGE] Failed to purge history:', error);
    }
}

// localStorage에서 문서 목록 불러오기
function getDocumentsFromStorage() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        return stored ? JSON.parse(stored) : [];
    } catch (error) {
        console.error('[STORAGE] Failed to load documents:', error);
        return [];
    }
}

// localStorage에 문서 목록 저장
function saveDocumentsToStorage(documents) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(documents));
        return true;
    } catch (error) {
        console.error('[STORAGE] Failed to save documents:', error);
        return false;
    }
}

// 문서 생성 완료 시 자동 저장 (localStorage + 서버)
async function saveToHistory(title, content) {
    const timestamp = new Date().toISOString();
    
    // 1. localStorage에 저장
    const documents = getDocumentsFromStorage();
    const newDoc = {
        id: Date.now(),
        title: title || '문서',
        content: content,
        created_at: timestamp,
        updated_at: timestamp,
        template_text: currentTemplateText || '',
        template_name: currentTemplateName || ''
    };
    
    documents.unshift(newDoc);  // 맨 앞에 추가
    
    // 최대 개수 초과 시 오래된 것 삭제
    if (documents.length > MAX_DOCUMENTS) {
        documents.length = MAX_DOCUMENTS;
    }
    
    if (saveDocumentsToStorage(documents)) {
        console.log('[HISTORY] Saved to localStorage:', newDoc.id);
        showToast('💾 문서가 저장되었습니다', 'success');
    }
    
    // 2. 서버에도 저장 (백업 목적)
    try {
        const response = await fetch('/api/documents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title || '문서', content })
        });
        
        const data = await response.json();
        
        if (data.success) {
            console.log('[HISTORY] Backed up to server:', data.document);
        }
    } catch (error) {
        console.error('[HISTORY] Server backup failed:', error);
        // localStorage에는 저장되었으므로 오류 무시
    }

    if (riroUserId) {
        await saveRiroDocumentSnapshot(title || '문서', content);
    }
}

// localStorage에서 문서 불러오기
function loadDocumentFromStorage(docId) {
    const documents = getDocumentsFromStorage();
    return documents.find(doc => doc.id === docId);
}

// localStorage에서 문서 삭제
function deleteDocumentFromStorage(docId) {
    const documents = getDocumentsFromStorage();
    const filtered = documents.filter(doc => doc.id !== docId);
    return saveDocumentsToStorage(filtered);
}
