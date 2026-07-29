/**
 * 사이드바 HISTORY.
 *
 * 메인 채팅방 하나에서 설계 대화와 실험 대화가 모두 진행되기 때문에, 목록을 한 줄로
 * 늘어놓으면 무엇이 무엇인지 알 수 없다. 그래서 폴더로 나눈다.
 *   설계 — 메인에서 세특·3년 계획을 논의한 연구 서사 대화
 *   실험 — 과목 카드의 「실험 진행」에서 시작된 대화
 * 이름은 서버가 짓는다(설계는 대화 내용의 요약, 실험은 '과목명 - 키워드').
 *
 * 폴더가 없는 옛 대화도 빠뜨리지 않고 '기타'에 모아 둔다.
 */
(() => {
    'use strict';

    const list = document.getElementById('historyList');
    if (!list) return;

    const FOLDERS = [
        { key: '설계', icon: 'bi-diagram-3', empty: '아직 설계 대화가 없어요.' },
        { key: '실험', icon: 'bi-beaker', empty: '로드맵에서 「실험 진행」을 누르면 여기에 생겨요.' },
        { key: '기타', icon: 'bi-chat-left-text', empty: '' },
    ];

    // 접어 둔 폴더는 다음에 와도 접힌 채로 있어야 한다.
    const CLOSED_KEY = 'historyClosedFolders';
    const closed = new Set((() => {
        try { return JSON.parse(localStorage.getItem(CLOSED_KEY)) || []; } catch (_) { return []; }
    })());
    const rememberClosed = () =>
        localStorage.setItem(CLOSED_KEY, JSON.stringify([...closed]));

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    // 지금 열려 있는 대화. 주소가 지목했거나, 채팅 쪽이 알려 준다
    // (설계 방은 대화를 복원하는 시점에야 정해진다).
    let openChat = new URLSearchParams(location.search).get('chat');

    const groupOf = (session) =>
        FOLDERS.some((folder) => folder.key === session.folder) ? session.folder : '기타';

    const render = (sessions) => {
        list.innerHTML = FOLDERS.map((folder) => {
            const items = sessions.filter((session) => groupOf(session) === folder.key);
            // 폴더는 설계·실험 둘뿐이다. '기타'는 담긴 대화가 있을 때만 보여준다.
            if (folder.key === '기타' && !items.length) return '';
            const isOpen = !closed.has(folder.key);
            return `
                <button class="folder" type="button" data-folder="${esc(folder.key)}"
                        aria-expanded="${isOpen}" aria-controls="folder-${esc(folder.key)}">
                    <i class="bi ${folder.icon}"></i>
                    <span>${esc(folder.key)}</span>
                    <span class="count">${items.length}</span>
                    <i class="bi bi-chevron-down chev" aria-hidden="true"></i>
                </button>
                <div class="folder-body" id="folder-${esc(folder.key)}" ${isOpen ? '' : 'hidden'}>
                    ${items.length
                        ? items.map((session) => `
                            <a class="chat-row" href="/?chat=${encodeURIComponent(session.id)}"
                               ${session.id === openChat ? 'aria-current="true"' : ''}
                               title="${esc(session.title || '새로운 대화')}">
                                <span class="dot" aria-hidden="true"></span>
                                <span class="txt">${esc(session.title || '새로운 대화')}</span>
                            </a>`).join('')
                        : (folder.empty ? `<div class="folder-empty">${esc(folder.empty)}</div>` : '')}
                </div>`;
        }).join('');
    };

    const load = async () => {
        try {
            // 로그인 여부와 대화 목록을 함께 묻는다(직렬로 기다리면 열림이 그만큼 늦다).
            // 첫 로드는 <head> 프리페치(window.__boot)가 이미 보내 둔 요청을 그대로 받는다.
            // 대화 목록 API는 비로그인이어도 IP 기준의 빈 목록을 돌려주기 때문에,
            // 로그인 확인 없이 그리면 기록이 "사라진 것처럼" 보인다.
            // (주소가 바뀌면 — 127.0.0.1 ↔ 192.168.x — 쿠키가 따로라 로그인도 따로다.)
            const boot = window.__boot || {};
            const preSessions = boot.sessions;
            boot.sessions = null;   // 갱신(history:refresh) 때는 새로 받는다

            let authStatus;
            let data = null;
            if (preSessions) {
                const [auth, sess] = await Promise.all([boot.next, preSessions]);
                authStatus = auth ? auth.status : 0;
                data = sess && sess.ok ? sess.body : null;
            }
            if (data === null) {
                const [auth, res] = await Promise.all([
                    fetch('/api/research/next', { credentials: 'same-origin' }),
                    fetch('/api/chat/sessions', { credentials: 'same-origin' }),
                ]);
                authStatus = auth.status;
                data = res.ok ? await res.json() : null;
            }

            if (authStatus === 401) {
                // 비로그인이면 그냥 비워 둔다. 로그인 안내는 채팅 쪽이 이미 하고 있어서
                // 사이드바까지 나서면 같은 말이 두 군데서 반복된다.
                list.innerHTML = '';
                return;
            }
            if (data && data.success) render(data.sessions || []);
        } catch (_) { /* 사이드바 하나 때문에 화면을 막지는 않는다 */ }
    };

    list.addEventListener('click', (event) => {
        const folder = event.target.closest('.folder');
        if (!folder) return;
        const key = folder.dataset.folder;
        const body = document.getElementById(`folder-${key}`);
        const isOpen = folder.getAttribute('aria-expanded') === 'true';
        folder.setAttribute('aria-expanded', String(!isOpen));
        if (body) body.hidden = isOpen;
        if (isOpen) closed.add(key); else closed.delete(key);
        rememberClosed();
    });

    // 대화가 한 걸음 나가면 이름과 순서가 달라진다(설계 대화방 이름은 요약이라 계속 바뀐다).
    window.addEventListener('history:refresh', (event) => {
        const active = event.detail && event.detail.active;
        if (active) openChat = active;
        load();
    });
    load();
})();
