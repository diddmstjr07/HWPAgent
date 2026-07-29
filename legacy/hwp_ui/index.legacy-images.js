/* 레거시 문서(docContent) 안의 이미지 자리표시자를 채우던 로더. 2026-07-29 제거. */

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