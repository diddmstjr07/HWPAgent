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
const pdfViewer = document.getElementById('pdfViewer');
const pdfPlaceholder = document.getElementById('pdfPlaceholder');
const pdfLoading = document.getElementById('pdfLoading');
const htmlPreviewContainer = document.getElementById('htmlPreviewContainer');
const previewTitle = document.getElementById('previewTitle');
const previewContent = document.getElementById('previewContent');

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

// 현재 PDF 파일명 저장
let currentPdfFile = null;

// 스트리밍 상태
let isStreaming = false;

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
    }
}

// 전역 변수: 이미지 키워드 및 URL 저장
let currentImagesNeeded = [];
let currentImageUrls = [];  // 검색된 이미지 URL 저장

// 서식 설정 전역 변수
let currentStyle = {
    font_name: '맑은 고딕',
    font_size: 11,
    title_size: 18,
    heading_size: 14,
    line_spacing: 1.5
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
    
    if (!request) {
        showToast('요청 내용을 입력해주세요', 'error');
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
            body: JSON.stringify({ request }),
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
userRequest.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        generateContent();
    }
});

refineRequest.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        refineContent();
    }
});

// 서식 설정
const styleBtn = document.getElementById('styleBtn');
const styleModal = document.getElementById('styleModal');

styleBtn.addEventListener('click', () => {
    styleModal.classList.add('show');
});

function closeStyleModal() {
    styleModal.classList.remove('show');
}

async function applyStyle() {
    currentStyle = {
        font_name: document.getElementById('fontName').value,
        font_size: parseInt(document.getElementById('fontSize').value),
        title_size: parseInt(document.getElementById('titleSize').value),
        heading_size: parseInt(document.getElementById('headingSize').value),
        line_spacing: parseFloat(document.getElementById('lineSpacing').value)
    };
    
    showToast('서식을 적용하고 PDF를 재생성합니다...', 'info');
    closeStyleModal();
    
    // PDF 재생성
    await generatePdfPreview();
}

// 모달 외부 클릭 시 닫기
styleModal.addEventListener('click', (e) => {
    if (e.target === styleModal) {
        closeStyleModal();
    }
});

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
        updated_at: timestamp
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
