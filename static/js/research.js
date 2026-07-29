/**
 * 3년 연구 서사 — 한 장의 로드맵.
 *
 * 서버가 가진 6단계 파이프라인(onboarding → themes → select_theme → framework →
 * subjects → done)을 좌측 레일과 본문 타임라인 양쪽에 그대로 세운다. 데이터가 없어도
 * 1·2·3학년 축을 흐리게 미리 그려서, 빈 화면이 '아무것도 없음'이 아니라 '앞으로
 * 채워질 자리'로 읽히게 한다. 채워지면 같은 자리가 실제 내용으로 바뀐다.
 *
 * 대화 입구는 우하단 미니 채팅 하나뿐이다. 각 단계의 실행 버튼은 기존 AI 엔드포인트를
 * 그대로 호출한다.
 */
(() => {
    'use strict';

    const nav = document.getElementById('nav');
    const detail = document.getElementById('detail');
    const curtheme = document.getElementById('curtheme');
    const toastEl = document.getElementById('toast');

    const STATUS_LABEL = { draft: '초안', narrowing: '좁히는 중', fixed: '확정' };
    const APPROACH_LABEL = { linked: '교과 연계형', deepening: '교과 심화형' };

    // 서버 _STAGE_GUIDE와 같은 순서. sec는 레일을 눌렀을 때 스크롤할 본문 구간.
    const STAGES = [
        { key: 'onboarding',   name: '출발점 정리',   sec: 'sec-profile' },
        { key: 'themes',       name: '테마 후보',     sec: 'sec-theme' },
        { key: 'select_theme', name: '테마 고르기',   sec: 'sec-theme' },
        { key: 'framework',    name: '3년 계획',      sec: 'sec-track' },
        { key: 'subjects',     name: '과목별 세특',   sec: 'sec-track' },
        { key: 'experiments',  name: '실험 · 보고서', sec: 'sec-track' },
        { key: 'done',         name: '3년 완성',      sec: 'sec-track' },
    ];
    const RAIL_STATE_LABEL = { done: '완료', current: '지금 할 일', locked: '잠김' };

    let state = null;
    let guide = null;     // /api/research/next 응답
    let toastTimer = null;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    const toast = (message) => {
        toastEl.textContent = message;
        toastEl.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3200);
    };

    const api = async (url, options = {}) => {
        const res = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(body.error || '요청을 처리하지 못했습니다.');
        return body;
    };

    // ---------- 데이터 헬퍼 ----------

    const sortedPlans = () => (state.grade_plans || []).slice().sort((a, b) => a.grade - b.grade);
    const subjectsFor = (planId) => (state.subject_plans || []).filter((s) => s.grade_plan_id === planId);
    const selectedTheme = () => (state.themes || []).find((t) => t.is_selected) || null;
    const hasProfile = () => Boolean(state.profile && state.profile.problem_statement);

    const stageKey = () => (guide && guide.stage) || 'onboarding';
    const stageIndex = () => Math.max(0, STAGES.findIndex((s) => s.key === stageKey()));

    /** 지금 단계가 실제로 보여야 할 자리. 들어오자마자 여기로 데려간다. */
    const currentAnchorId = () => {
        // 설계를 마친 채팅이 /research#grade-2 처럼 학년을 지목해 보낼 수 있다.
        // 그때는 진행 단계보다 그 학년이 우선이다.
        const asked = (location.hash || '').replace('#', '');
        if (/^grade-[123]$/.test(asked) && document.getElementById(asked)) return asked;

        const stage = stageKey();
        if (stage === 'subjects') {
            const grade = guide && guide.grade;
            if (grade && document.getElementById(`grade-${grade}`)) return `grade-${grade}`;
        }
        return (STAGES.find((s) => s.key === stage) || STAGES[0]).sec;
    };

    // ---------- 조각 ----------

    const mark = (status, small) =>
        `<span class="mk${small ? ' sm' : ''}" data-status="${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`;

    const ghostLines = (count, widths = []) => Array.from({ length: count }, (_, i) =>
        `<div class="ghost-line" style="width:${widths[i] || (92 - i * 18)}%"></div>`).join('');

    const ghostBlock = (note, lines = 2) =>
        `<div class="ghost">${ghostLines(lines)}<div class="ghost-note">${note}</div></div>`;

    /** 이 자리는 채팅이 채운다는 안내. 이 페이지에는 생성 버튼을 두지 않는다. */
    const chatNote = (text) =>
        `<p class="chat-hint"><i class="bi bi-chat-dots" aria-hidden="true"></i>${text}</p>`;

    // 채팅은 후보를 번호로 고른다("2번으로 할래"). 그래서 번호가 화면에 보여야 한다.
    const themeCard = (theme, index) => `
        <article class="theme-card${theme.is_selected ? ' selected' : ''}">
            <div class="theme-top">
                <h3><span class="theme-no">${index + 1}</span>${esc(theme.title)}</h3>
                ${theme.is_selected ? '<span class="theme-flag">고른 테마</span>' : ''}
            </div>
            ${(theme.rationale || theme.expansion) ? `
                <div class="theme-grid">
                    ${theme.rationale ? `<p><span>왜 나에게 맞나</span>${esc(theme.rationale)}</p>` : ''}
                    ${theme.expansion ? `<p><span>3년간 확장</span>${esc(theme.expansion)}</p>` : ''}
                </div>` : ''}
        </article>`;

    /**
     * 실험 상태에 따라 카드 아래에 놓을 것.
     *  - 아직 안 함  → 실험 대화방을 열고 메인 채팅으로 보내는 버튼
     *  - 하는 중     → 이어서 하기(같은 대화방)
     *  - 끝남       → 만들어진 한글 보고서를 여는 버튼
     * 문서 아이콘은 학습을 끝낸 뒤에만 나타난다. 그 전에는 열 문서가 없다.
     *
     * 실험은 전용 페이지가 아니라 메인(/) 채팅방에서 진행한다. 이 버튼은
     * '실험' 폴더에 그 과목의 대화방을 만들고 거기로 데려가는 일만 한다.
     */
    const experimentAction = (plan) => {
        if (plan.experiment_status === 'done') {
            // 보고서는 내려받는 것보다 편집기에서 이어 손보는 쪽이 기본이다.
            // 다만 편집기는 HWP만 연다. HWP 조립이 실패해 DOCX로 저장된 보고서는
            // 편집기로 보내면 알 수 없는 오류만 나므로 내려받기로 준다.
            // 편집 가능 여부는 서버가 파일 내용을 보고 알려준다(report_editable).
            const editable = (plan.report_editable !== undefined
                              && plan.report_editable !== null)
                ? !!plan.report_editable
                : /\.hwp$/i.test(plan.report_file || '');
            if (plan.report_file && editable) {
                return `<a class="btn doc" href="/editor?file=${encodeURIComponent(plan.report_file)}">
                            <img src="/static/images/hwp-doc.svg" alt="" class="doc-ico"> 보고서 열기
                        </a>`;
            }
            if (plan.report_file) {
                return `<a class="btn doc" href="/api/download/${encodeURIComponent(plan.report_file)}">
                            <i class="bi bi-download"></i> 보고서 내려받기
                        </a>`;
            }
            return `<button class="btn" type="button" data-act="open-exp" data-id="${plan.id}">
                        <i class="bi bi-chat-square-text"></i> 대화 보기
                    </button>`;
        }
        const running = plan.experiment_status === 'running';
        return `<button class="btn" type="button" data-act="open-exp" data-id="${plan.id}">
                    <i class="bi bi-${running ? 'arrow-right-circle' : 'play-fill'}"></i>
                    ${running ? '실험 이어하기' : '실험 진행'}
                </button>`;
    };

    const subjectCard = (plan) => {
        const design = plan.activity_design || {};
        const code = (plan.standard_codes || [])[0];
        return `
            <article class="subject" data-subject-id="${plan.id}"
                     data-exp="${esc(plan.experiment_status || 'none')}">
                <div class="subject-top">
                    <span class="subject-name">${esc(plan.subject)}</span>
                    ${plan.approach ? `<span class="appr" data-kind="${esc(plan.approach)}">${esc(APPROACH_LABEL[plan.approach] || plan.approach)}</span>` : ''}
                </div>
                ${(plan.area_name || code) ? `<div class="area"><i class="bi bi-bookmark"></i> ${esc(plan.area_name || '')}${code ? ` · <code>${esc(code)}</code>` : ''}</div>` : ''}
                ${design.question ? `<div class="subject-q">${esc(design.question)}</div>` : ''}
                <div class="subject-foot">
                    ${mark(plan.status, true)}
                    ${experimentAction(plan)}
                </div>
            </article>`;
    };

    // ---------- 좌측 레일 ----------

    const renderRail = () => {
        const current = stageIndex();
        nav.innerHTML = STAGES.map((stage, index) => {
            const st = index < current ? 'done' : (index === current ? 'current' : 'locked');
            const glyph = st === 'done' ? '<i class="bi bi-check-lg"></i>' : String(index + 1);
            return `
                <button class="rail-step" type="button" data-state="${st}"
                        data-target="${stage.sec}" data-locked="${st === 'locked'}"
                        data-stage="${esc(stage.name)}"
                        ${st === 'current' ? 'aria-current="step"' : ''}>
                    <span class="rail-mark">${glyph}</span>
                    <span class="rail-text">
                        <span class="rail-name">${esc(stage.name)}</span>
                        <span class="rail-state">${RAIL_STATE_LABEL[st]}</span>
                    </span>
                </button>`;
        }).join('');

        // 테마를 고르기 전에는 보여줄 게 없으므로 숨긴다.
        const theme = selectedTheme();
        curtheme.innerHTML = theme
            ? `<div class="lbl">현재 테마</div><div class="val">${esc(theme.title)}</div>`
            : '';
        curtheme.style.display = theme ? '' : 'none';
    };

    // ---------- 본문 구간 ----------

    const profileSection = () => {
        const done = hasProfile();
        const profile = state.profile || {};
        const chips = (items) => (items || []).length
            ? items.map((v) => `<span class="chip">${esc(v)}</span>`).join('')
            : '<span class="chip empty">아직 없음</span>';

        const body = done ? `
            <div class="anchor">
                <div class="lbl">문제의식</div>
                <div class="name">${esc(profile.problem_statement)}</div>
            </div>
            <div class="section-label">관심 도메인</div><div class="chips">${chips(profile.interests)}</div>
            <div class="section-label">강점 교과</div><div class="chips">${chips(profile.strength_subjects)}</div>
            <div class="section-label">활동 이력</div><div class="chips">${chips(profile.activity_history)}</div>
            ${profile.aspired_track ? `<div class="section-label">지망 계열</div><div class="chips"><span class="chip">${esc(profile.aspired_track)}</span></div>` : ''}
            <p class="chat-hint"><i class="bi bi-arrow-repeat" aria-hidden="true"></i>고치고 싶으면 <a href="/welcome">다시 답하기</a>.</p>`
            : ghostBlock('네 가지 질문에 답하면 <b>문제의식·관심 도메인·강점 교과·활동 이력</b>이 여기에 채워집니다.', 3);

        return `
            <section class="sec" id="sec-profile">
                <div class="sec-head">
                    <h3>출발점</h3>
                    <span class="sec-state">${done ? '완료' : '아직 비어 있음'}</span>
                </div>
                ${body}
            </section>`;
    };

    const themeSection = () => {
        const themes = state.themes || [];
        const selected = selectedTheme();
        const framework = state.framework;

        let body;
        let stateLabel;
        if (!themes.length) {
            stateLabel = hasProfile() ? '만들 차례' : '출발점부터';
            body = `
                ${ghostBlock('3년을 관통할 테마 후보가 여기에 놓입니다. 각 후보마다 <b>왜 나에게 맞는지</b>와 <b>3년간 어떻게 확장되는지</b>가 함께 붙습니다.', 2)}
                ${chatNote(hasProfile()
                    ? '채팅에서 하고 싶은 탐구를 이야기하면 후보가 여기에 정리됩니다.'
                    : '먼저 출발점을 정리해야 후보를 만들 수 있어요.')}`;
        } else if (!selected) {
            stateLabel = '고를 차례';
            body = `
                <div class="themes">${themes.map(themeCard).join('')}</div>
                ${chatNote('채팅에 <b>“2번으로 할래”</b>처럼 번호로 말하면 그 테마로 정해집니다.')}`;
        } else {
            stateLabel = selected.status === 'fixed' ? '확정' : '고름';
            const others = themes.filter((t) => !t.is_selected);
            body = `
                <section class="thesis">
                    <div class="thesis-actions">
                        ${mark(selected.status)}
                        <button class="btn" type="button" data-act="toggle-status" data-entity="theme"
                                data-id="${selected.id}" data-status="${esc(selected.status)}">
                            ${selected.status === 'fixed' ? '확정 해제' : '이 테마로 확정'}
                        </button>
                    </div>
                    <h2>${esc(selected.title)}</h2>
                    ${framework && framework.core_question
                        ? `<div class="question"><b>핵심 질문</b> · ${esc(framework.core_question)}</div>` : ''}
                </section>
                ${others.length ? `
                    <div class="section-label">다른 후보</div>
                    <div class="themes">${others.map((theme) =>
                        themeCard(theme, themes.indexOf(theme))).join('')}</div>` : ''}`;
        }

        return `
            <section class="sec" id="sec-theme">
                <div class="sec-head">
                    <h3>3년 테마</h3>
                    <span class="sec-state">${stateLabel}</span>
                </div>
                ${body}
            </section>`;
    };

    /** 계획이 있으면 실제 내용, 없으면 같은 자리에 1·2·3학년 고스트를 세운다. */
    const trackSection = () => {
        const plans = sortedPlans();
        const hasPlans = plans.length > 0;

        const items = hasPlans
            ? plans.map((plan) => {
                const anchor = plan.anchor_project || {};
                const subs = subjectsFor(plan.id);
                const itemState = subs.length ? (plan.status === 'fixed' ? 'done' : 'active') : 'active';
                return `
                    <li class="track-item" data-state="${itemState}" id="grade-${plan.grade}">
                        <span class="track-node">${plan.grade}</span>
                        <div class="track-head">
                            <h4 class="track-title">${plan.grade}학년</h4>
                            ${mark(plan.status)}
                            <button class="btn" type="button" style="margin-left:auto"
                                    data-act="toggle-status" data-entity="grade-plan"
                                    data-id="${plan.id}" data-status="${esc(plan.status)}">
                                ${plan.status === 'fixed' ? '확정 해제' : `${plan.grade}학년 확정`}
                            </button>
                        </div>
                        <div class="track-body">
                            ${plan.goal ? `<p class="goal" style="margin-top:0">${esc(plan.goal)}</p>` : ''}
                            ${anchor.title ? `
                                <div class="anchor">
                                    <div class="lbl">앵커 프로젝트</div>
                                    <div class="name">${esc(anchor.title)}</div>
                                    ${anchor.description ? `<div class="desc">${esc(anchor.description)}</div>` : ''}
                                </div>` : ''}
                            ${subs.length ? `
                                <div class="section-label">과목별 세특 설계</div>
                                <div class="subjects">${subs.map(subjectCard).join('')}</div>`
                                : chatNote(`채팅에 <b>“${plan.grade}학년 세특 설계해줘”</b>라고 하면 이 자리에 채워집니다.`)}
                        </div>
                    </li>`;
            }).join('')
            : [1, 2, 3].map((grade) => `
                <li class="track-item" data-state="locked">
                    <span class="track-node">${grade}</span>
                    <div class="track-head"><h4 class="track-title">${grade}학년</h4></div>
                    <div class="track-body">
                        ${ghostBlock(grade === 1
                            ? '학년 목표와 <b>앵커 프로젝트</b>, 그 아래 과목별 세특이 이 자리에 놓입니다.'
                            : '테마를 고르면 3년이 학년별로 나뉘어 여기에 채워집니다.', 2)}
                    </div>
                </li>`).join('');

        const cta = !hasPlans && selectedTheme()
            ? chatNote('채팅에 <b>“3년 계획 짜줘”</b>라고 하면 학년별 목표와 앵커 프로젝트가 이 축에 채워집니다.')
            : '';

        // 보고서가 2개는 있어야 '이어짐'을 말할 수 있다. 그 전에는 버튼을 숨긴다.
        const doneReports = (state?.subject_plans || [])
            .filter((plan) => plan.experiment_status === 'done' && plan.report_file);
        const narrative = doneReports.length >= 2 ? `
            <div class="sec-head" style="margin-top:28px">
                <h3>서사 점검</h3>
                <button class="btn" type="button" data-act="narrative-check">
                    <i class="bi bi-link-45deg"></i> 보고서 ${doneReports.length}개가 이어지는지 보기
                </button>
            </div>
            <div id="narrativeOut"></div>` : '';

        return `
            <section class="sec" id="sec-track">
                <div class="sec-head">
                    <h3>3년 로드맵</h3>
                    <span class="sec-state">${hasPlans ? '진행 중' : '아직 비어 있음'}</span>
                </div>
                <ol class="track">${items}</ol>
                ${cta}
                ${narrative}
            </section>`;
    };

    // 들어오자마자 한 번만 현재 위치로 데려간다. 이후 다시 그릴 때는
    // 보고 있던 자리를 뺏지 않는다(확정 토글 등).
    let landed = false;

    const render = () => {
        renderRail();
        detail.innerHTML = `
            <div class="eyebrow">3년 연구 서사</div>
            <h2 class="view-title">테마 하나로 3년을 잇는다</h2>
            <p class="lead">출발점 → 테마 → 학년별 계획 → 과목 세특 순으로 쌓입니다.
                아래 축은 앞으로 채워질 자리를 미리 보여줍니다.</p>
            ${profileSection()}
            ${themeSection()}
            ${trackSection()}`;

        if (!landed) {
            landed = true;
            // 첫 진입은 애니메이션 없이 바로 그 자리에서 시작한다.
            document.getElementById(currentAnchorId())?.scrollIntoView({ block: 'start' });
        }
    };

    // ---------- 액션 ----------

    const withBusy = async (button, label, task) => {
        const original = button.innerHTML;
        button.disabled = true;
        button.innerHTML = `<i class="bi bi-arrow-repeat spin"></i> ${label}`;
        try {
            await task();
        } catch (error) {
            toast(error.message);
            button.disabled = false;
            button.innerHTML = original;
        }
    };

    const load = async () => {
        // 다음 단계 안내는 실패해도 화면은 그려야 한다.
        const [nextState, nextGuide] = await Promise.all([
            api('/api/research/state'),
            api('/api/research/next').catch(() => null),
        ]);
        state = nextState;
        guide = nextGuide;
        render();
    };

    const scrollToSection = (id) => {
        document.getElementById(id)?.scrollIntoView({
            behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
            block: 'start',
        });
    };

    // 레일 이동
    nav.addEventListener('click', (event) => {
        const button = event.target.closest('[data-target]');
        if (!button) return;
        if (button.dataset.locked === 'true') {
            const current = STAGES[stageIndex()];
            toast(`먼저 "${current.name}"부터 끝내야 열려요.`);
            return;
        }
        scrollToSection(button.dataset.target);
    });

    document.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-act]');
        if (!button) return;
        const act = button.dataset.act;

        if (act === 'open-exp') {
            // 방을 먼저 만들고(있으면 그대로) 메인 채팅의 그 방으로 들어간다.
            await withBusy(button, '여는 중', async () => {
                const opened = await api(`/api/research/experiment/${button.dataset.id}/open`,
                                         { method: 'POST' });
                location.href = opened.redirect || '/';
            });
            return;
        }

        if (act === 'narrative-check') {
            // 보고서 전부를 읽고 판단하는 일이라 오래 걸린다. 버튼에 상태를 남긴다.
            await withBusy(button, '보고서 읽는 중...', async () => {
                const result = await api('/api/research/narrative-check',
                                         { method: 'POST' });
                const out = document.getElementById('narrativeOut');
                if (!out) return;
                const icon = { strength: '🔗', gap: '✂️' };
                out.innerHTML = `
                    <div class="notice" style="margin-top:12px">
                        <b>${esc(result.summary)}</b>
                        <ul style="margin:10px 0 0; padding-left:18px">
                            ${(result.findings || []).map((f) => `
                                <li style="margin-top:6px">${icon[f.kind] || '·'}
                                    ${esc(f.message)}</li>`).join('')}
                        </ul>
                    </div>`;
            });
            return;
        }

        if (act === 'toggle-status') {
            const next = button.dataset.status === 'fixed' ? 'narrowing' : 'fixed';
            await withBusy(button, next === 'fixed' ? '확정 중' : '해제 중', async () => {
                await api(`/api/research/${button.dataset.entity}/${button.dataset.id}/status`, {
                    method: 'POST', body: JSON.stringify({ status: next }),
                });
                await load();
                toast(next === 'fixed' ? '확정했어요. 이후 제안은 이 내용을 기준으로 만들어집니다.' : '확정을 해제했어요.');
            });
            return;
        }

    });

    // 미니 채팅에서 계획이 바뀌면 로드맵을 다시 읽는다.
    window.researchReload = load;

    load().catch((error) => {
        nav.innerHTML = '';
        curtheme.innerHTML = '';
        detail.innerHTML = `<div class="notice"><b>불러오지 못했어요</b>${esc(error.message)}
            <br><button class="btn" type="button" onclick="location.reload()">다시 시도</button></div>`;
    });
})();
