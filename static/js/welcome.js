/**
 * 가입 직후 온보딩.
 *
 * 네 개의 질문으로 탐구의 출발점을 만든다. 질문은 한 번에 하나씩만 보이고,
 * 답하면 위로 밀려 정리되며, 마지막에 네 답이 하나의 프로파일 카드로 조립된다.
 *
 * ChatGPT 연결이 없어도 끝까지 진행된다(서버가 규칙 기반으로 저장).
 */
(() => {
    'use strict';

    const rail = document.getElementById('rail');
    const root = document.getElementById('root');

    // 순서가 곧 깊이다. 끌림 → 문제 → 진로 → 근거.
    const STEPS = [
        {
            key: 'interests',
            kicker: '4개 중 첫 번째',
            ask: '요즘 어떤 것에 마음이 가나요?',
            hint: '과목 이름이 아니어도 괜찮아요. 뉴스에서 본 것, 계속 생각나는 장면도 좋습니다.',
            placeholder: '예: 여름에 밤인데도 안 식는 동네가 이상했어요',
        },
        {
            key: 'problem',
            kicker: '두 번째',
            ask: '그중에서 바꾸고 싶은 게 있나요?',
            hint: '아직 답을 몰라도 됩니다. 무엇이 문제로 보이는지만 적어주세요.',
            placeholder: '예: 왜 어떤 곳은 더 덥고 어떤 곳은 안 그런지 알고 싶어요',
        },
        {
            key: 'track',
            kicker: '세 번째',
            ask: '어느 쪽으로 가고 싶고, 어떤 과목이 잘 맞나요?',
            hint: '아직 확실하지 않으면 지금 끌리는 쪽으로 적어도 됩니다.',
            placeholder: '예: 건축이나 환경공학 쪽이요. 과학이랑 수학이 그나마 편해요',
        },
        {
            key: 'activity',
            kicker: '마지막',
            ask: '지금까지 해본 것 중 이어질 만한 게 있나요?',
            hint: '동아리, 수행평가, 혼자 찾아본 것 무엇이든 좋습니다. 없으면 "없어요"도 괜찮아요.',
            placeholder: '예: 동아리에서 날씨 기록했어요',
        },
    ];

    const answers = {};
    let index = 0;
    let busy = false;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    /** 오류는 좁은 화면에서도 보여야 하므로 error 클래스를 함께 붙인다. */
    const showError = (message) => {
        const meta = document.querySelector('.meta');
        if (!meta) return;
        meta.textContent = message;
        meta.classList.add('error');
    };

    const renderRail = (filled) => {
        rail.innerHTML = STEPS
            .map((_, i) => `<span class="${i < filled ? 'on' : ''}"></span>`).join('');
    };

    /** 질문을 한 글자씩 흘려보낸다. 끝나면 입력창에 포커스를 준다. */
    const typeAsk = (element, text, onDone) => {
        if (reduceMotion) {
            element.textContent = text;
            onDone();
            return;
        }
        element.classList.add('caret');
        let i = 0;
        const tick = () => {
            i += 1;
            element.textContent = text.slice(0, i);
            if (i < text.length) {
                setTimeout(tick, 26);
            } else {
                element.classList.remove('caret');
                onDone();
            }
        };
        tick();
    };

    const pastMarkup = () => STEPS.slice(0, index).map((step, i) => `
        <div class="past-item" style="animation-delay:${i * 40}ms">
            <div class="past-q">${esc(step.ask)}</div>
            <div class="past-a">${esc(answers[step.key] || '')}</div>
        </div>`).join('');

    const renderStep = () => {
        const step = STEPS[index];
        renderRail(index);

        root.innerHTML = `
            <div class="past">${pastMarkup()}</div>
            <div class="now">
                <div class="kicker">${esc(step.kicker)}</div>
                <h1 class="ask" id="ask"></h1>
                <p class="hint" id="hint" hidden>${esc(step.hint)}</p>
            </div>
            <form class="reply" id="reply" hidden>
                <textarea id="answer" rows="3" placeholder="${esc(step.placeholder)}"></textarea>
                <div class="row">
                    <span class="meta">Enter로 다음, Shift+Enter로 줄바꿈</span>
                    <div>
                        ${index > 0 ? '<button class="btn ghost" type="button" data-act="back">이전</button>' : ''}
                        <button class="btn" type="submit" id="next">
                            ${index === STEPS.length - 1 ? '정리하기' : '다음'}
                        </button>
                    </div>
                </div>
            </form>`;

        typeAsk(document.getElementById('ask'), step.ask, () => {
            const hint = document.getElementById('hint');
            const form = document.getElementById('reply');
            hint.hidden = false;
            form.hidden = false;
            const field = document.getElementById('answer');
            field.value = answers[step.key] || '';
            field.focus();
        });
    };

    const renderSaving = () => {
        renderRail(STEPS.length);
        root.innerHTML = `
            <div class="past">${pastMarkup()}</div>
            <div class="now">
                <div class="kicker">정리 중</div>
                <h1 class="ask">답을 모으고 있어요</h1>
                <p class="hint"><span class="thinking"><i></i><i></i><i></i></span></p>
            </div>`;
    };

    const chips = (items) => {
        const list = (items || []).filter(Boolean);
        return list.length
            ? list.map((v) => `<span class="chip">${esc(v)}</span>`).join('')
            : '<span class="chip empty">아직 없음</span>';
    };

    const renderDone = (profile) => {
        renderRail(STEPS.length);
        const fields = [
            { lbl: '문제의식', html: `<div class="val">${esc(profile.problem_statement || '')}</div>` },
            { lbl: '관심 도메인', html: `<div class="chips">${chips(profile.interests)}</div>` },
            { lbl: '지망 계열', html: profile.aspired_track
                ? `<div class="val">${esc(profile.aspired_track)}</div>`
                : '<div class="chips"><span class="chip empty">아직 없음</span></div>' },
            { lbl: '강점 교과', html: `<div class="chips">${chips(profile.strength_subjects)}</div>` },
            { lbl: '활동 이력', html: `<div class="chips">${chips(profile.activity_history)}</div>` },
        ];

        root.innerHTML = `
            <div class="done" style="margin-top:36px">
                <h1>여기서 시작합니다</h1>
                <p class="lead">이 내용이 3년 테마와 학년별 계획, 과목 세특 설계의 근거가 됩니다.
                    언제든 다시 고칠 수 있어요.</p>
                <div class="card">
                    ${fields.map((f, i) => `
                        <div class="field" style="animation-delay:${120 + i * 90}ms">
                            <div class="lbl">${esc(f.lbl)}</div>
                            ${f.html}
                        </div>`).join('')}
                </div>
                <div class="row">
                    <span class="meta"></span>
                    <div>
                        <button class="btn ghost" type="button" data-act="redo">다시 답하기</button>
                        <a class="btn" href="/">테마 만들러 가기</a>
                    </div>
                </div>
            </div>`;
    };

    const submitAll = async () => {
        busy = true;
        renderSaving();
        try {
            const res = await fetch('/api/research/onboarding', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(answers),
            });
            const body = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(body.error || '저장하지 못했습니다.');
            busy = false;
            renderDone(body.profile);
        } catch (error) {
            busy = false;
            // 답변은 그대로 두고 마지막 질문으로 돌려보낸다.
            index = STEPS.length - 1;
            renderStep();
            showError(error.message);
        }
    };

    const advance = () => {
        const field = document.getElementById('answer');
        const text = (field.value || '').trim();
        const step = STEPS[index];

        // 첫 두 질문 중 하나는 있어야 프로파일이 성립한다.
        if (!text && (step.key === 'interests' || step.key === 'problem')) {
            field.focus();
            showError('한 줄이라도 적어주세요.');
            return;
        }
        answers[step.key] = text;

        if (index === STEPS.length - 1) {
            submitAll();
            return;
        }
        index += 1;
        renderStep();
    };

    root.addEventListener('submit', (event) => {
        if (event.target.id !== 'reply') return;
        event.preventDefault();
        if (!busy) advance();
    });

    root.addEventListener('keydown', (event) => {
        if (event.target.id !== 'answer' || event.key !== 'Enter' || event.shiftKey) return;
        event.preventDefault();
        if (!busy) advance();
    });

    root.addEventListener('click', (event) => {
        const button = event.target.closest('[data-act]');
        if (!button) return;
        if (button.dataset.act === 'back' && index > 0) {
            const field = document.getElementById('answer');
            if (field) answers[STEPS[index].key] = (field.value || '').trim();
            index -= 1;
            renderStep();
        }
        if (button.dataset.act === 'redo') {
            index = 0;
            renderStep();
        }
    });

    renderStep();
})();
