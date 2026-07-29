/**
 * 첫 화면 — 인사말이 아니라 '지금 할 일'.
 *
 * 예전 첫 화면은 "How can I help you?"와 빈 입력창뿐이었다. 이 앱이 무엇을 하는
 * 곳인지 알 수 없고, 학생은 백지 앞에 선다. 그런데 서버는 다음에 할 일을 이미
 * 정확히 알고 있다(/api/research/next의 stage·message·choices). 그것을 그대로
 * 첫 화면에 세운다.
 *
 * 여기서 새로 부르는 API는 없다. <head> 프리페치(window.__boot)가 이미 받아 둔
 * 것을 쓰고, 버튼은 guide.js의 대화 경로를 그대로 탄다 — 화면만 앞당긴 것이지
 * 규약이 새로 생기지는 않는다.
 */
(() => {
    'use strict';

    const home = document.getElementById('homeView');
    const card = document.getElementById('homeCard');
    if (!home || !card) return;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    // /research의 레일과 같은 순서. 진행률을 같은 기준으로 보여준다.
    const STAGES = [
        { key: 'onboarding', name: '출발점' },
        { key: 'themes', name: '테마 만들기' },
        { key: 'select_theme', name: '테마 고르기' },
        { key: 'framework', name: '3년 계획' },
        { key: 'subjects', name: '과목 세특' },
        { key: 'experiments', name: '실험·보고서' },
        { key: 'done', name: '완성' },
    ];

    const stepsHtml = (stage) => {
        const at = STAGES.findIndex((item) => item.key === stage);
        return `
            <div class="home-steps" role="img"
                 aria-label="${at >= 0 ? `${STAGES.length}단계 중 ${at + 1}단계` : '진행 전'}">
                ${STAGES.map((item, index) => {
                    const state = index < at ? 'done' : (index === at ? 'now' : '');
                    return `<span class="home-step ${state}"><i></i>${esc(item.name)}</span>`;
                }).join('')}
            </div>`;
    };

    /** 화면을 그린다. body는 카드 안쪽 HTML, 버튼은 [{label, onClick}]. */
    const paint = (body, buttons = []) => {
        card.innerHTML = body;
        if (!buttons.length) return;
        const row = document.createElement('div');
        row.className = 'home-actions';
        buttons.forEach((item, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = index === 0 ? 'home-btn primary' : 'home-btn';
            button.textContent = item.label;
            button.addEventListener('click', item.onClick);
            row.appendChild(button);
        });
        card.appendChild(row);
    };

    const goto = (href) => () => { location.href = href; };

    /**
     * 대화를 이 자리에서 시작한다. guide.js가 화면을 채우면 홈은 비켜난다.
     * 버튼은 말하기의 지름길일 뿐이라, 직접 타이핑한 것과 같은 길을 탄다.
     */
    const say = (text) => () => {
        const input = document.getElementById('userRequest');
        const send = document.getElementById('btnSend');
        if (!input || !send) return;
        input.value = text;
        send.click();
    };

    const render = (next, status) => {
        if (status === 401) {
            paint(`
                <div class="home-mark" aria-hidden="true">✳</div>
                <div class="home-eyebrow">3년 연구 서사</div>
                <h1 class="home-title">생기부를 하나의 이야기로</h1>
                <p class="home-lead">테마 하나로 3년을 잇고, 과목마다 직접 탐구해서
                    그 기록을 한글 보고서로 남겨요.</p>`,
                [{ label: '로그인하고 시작하기', onClick: goto('/login') }]);
            return;
        }
        if (!next) { home.hidden = true; return; }

        // 이 단계가 AI를 쓰는데 연결이 안 돼 있으면 그것부터 알려준다.
        const needsAi = next.needs_ai && !next.ai_connected;
        const title = next.title || '지금 할 일';
        const lead = needsAi
            ? `${next.message || ''}\n\n그러려면 ChatGPT 계정을 연결해야 해. 네 계정의 사용량으로 동작해.`
            : (next.message || '');

        const body = `
            <div class="home-mark" aria-hidden="true">✳</div>
            <div class="home-eyebrow">3년 연구 서사</div>
            <h1 class="home-title">${esc(title)}</h1>
            <p class="home-lead">${esc(lead).replace(/\n/g, '<br>')}</p>
            ${stepsHtml(next.stage)}`;

        if (!next.ai_configured && next.needs_ai) {
            paint(body, [{ label: '로드맵 보기', onClick: goto('/research') }]);
            return;
        }

        // 서버가 알려준 다음 행동을 그대로 첫 버튼으로 세운다.
        const first = ((next.choices || {}).options || [])[0];
        const buttons = [];
        if (needsAi) {
            buttons.push({ label: 'ChatGPT 연결하기', onClick: say('ChatGPT 연결할래') });
        } else if (next.href) {
            buttons.push({ label: next.label || '이어서 하기', onClick: goto(next.href) });
        } else if (first) {
            buttons.push({ label: next.label || first.label, onClick: say(first.send) });
        }
        if (next.stage !== 'onboarding') {
            buttons.push({ label: '3년 로드맵', onClick: goto('/research') });
        }
        paint(body, buttons);
    };

    /**
     * 입력창 위 작은 칩과 메뉴 점.
     * 대화로 들어가면 첫 화면은 사라지지만 "지금 몇 단계인지"는 계속 보여야 한다.
     */
    const markShell = (next) => {
        const chip = document.getElementById('stageChip');
        if (chip && next && next.stage && next.stage !== 'done') {
            const at = STAGES.findIndex((item) => item.key === next.stage);
            const name = at >= 0 ? STAGES[at].name : '';
            if (name) {
                chip.textContent = `${at + 1}/${STAGES.length} ${name}`;
                chip.hidden = false;
            }
        }
        // 지금 할 일이 남아 있으면 메뉴 버튼에 점을 켠다.
        const dot = document.getElementById('menuDot');
        if (dot && next && next.stage && next.stage !== 'done') dot.hidden = false;
    };

    (async () => {
        try {
            const boot = window.__boot || {};
            // 프리페치를 소비하지 않는다 — guide.js도 같은 값을 기다리고 있다.
            const pre = boot.next ? await boot.next : null;
            const body = pre ? pre.body : null;
            const status = pre ? pre.status : null;
            if (pre) { render(body, status); markShell(body); return; }
            const res = await fetch('/api/research/next', { credentials: 'same-origin' });
            const data = res.ok ? await res.json() : null;
            render(data, res.status);
            markShell(data);
        } catch (_) {
            // 첫 화면 하나 때문에 앱을 막지는 않는다. 조용히 비운다.
            home.hidden = true;
        }
    })();
})();
