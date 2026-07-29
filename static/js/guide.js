/**
 * 연구 서사 대화 진행자.
 *
 * 버튼으로 시키지 않는다. AI가 채팅으로 묻고, 학생이 말로 답하면 그 의도대로 실행한다.
 * 학생이 덧붙인 조건("좀 더 실험 위주로")은 서버가 생성 단계에 그대로 넘긴다.
 *
 * 메인 채팅(#chatStream)과 /research의 미니 채팅(#miniChat) 양쪽에서 같은 로직을 쓴다.
 * index.js(223KB)는 건드리지 않는다.
 */
(() => {
    'use strict';

    const api = async (url, options = {}) => {
        const res = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
            const error = new Error(body.error || '요청을 처리하지 못했습니다.');
            error.kind = body.error_kind || null;   // 예: usage_limit
            throw error;
        }
        return body;
    };

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    // 대화 이력은 화면을 벗어나면 사라진다. 진행 상태는 서버가 들고 있다.
    const history = [];
    let busy = false;
    let connectPoll = null;
    let turnPoll = null;   // 서버가 아직 만들고 있는 턴을 지켜보는 타이머
    let sessionId = null;  // 지금 열려 있는 '설계' 대화방. 서버가 정해 준 값을 그대로 쓴다.
    let lastReply = null;  // 마지막 답변 말풍선. '다시 생성'이 걷어낼 대상이다.

    /**
     * 서버가 알려준 곳으로 옮긴다.
     * 주소에 #grade-2 처럼 자리가 붙어 오면, 이미 그 페이지에 있을 때는
     * 새로 불러오지 않고 그 자리로 스크롤만 한다.
     */
    const goTo = (target) => {
        const url = new URL(target, location.origin);
        if (url.pathname !== location.pathname) { location.href = url.href; return; }
        if (!url.hash) return;
        const spot = document.getElementById(url.hash.slice(1));
        if (spot) spot.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else location.hash = url.hash;
    };

    /**
     * HISTORY 목록(제목·순서)이 달라졌을 수 있다고 알린다.
     * 지금 열려 있는 방을 함께 알려 사이드바가 그 줄을 짚어 준다.
     */
    const historyChanged = () => window.dispatchEvent(
        new CustomEvent('history:refresh', { detail: { active: sessionId } }));

    /** 한 턴의 결과를 화면에 반영한다. 바로 받은 응답과 기다렸다 받은 응답이 같은 길을 탄다. */
    const applyTurn = (turn, io) => {
        if (turn.session_id) sessionId = turn.session_id;
        let reply = turn.reply || '';
        const outcome = turn.outcome || {};
        // 서버가 실패 문구를 그대로 reply로 준 경우가 있어 같은 말이 두 번 나오지 않게 한다.
        if (outcome.error && !reply.includes(outcome.error)) reply += `\n\n(${outcome.error})`;

        history.push({ role: 'assistant', text: reply });
        // 마지막 답변에는 '다시 생성'을 붙인다. 답이 마음에 안 들면 같은 말을
        // 또 타이핑하는 대신 그 자리에서 다시 만들 수 있어야 한다.
        const bubble = io.showAI(reply, { ...turn, onRegenerate: () => regenerate(io) });
        lastReply = bubble;
        // 사용량 초과는 잠깐의 오류가 아니라 기다려야 하는 상태라 눈에 띄게 알린다.
        if (outcome.error_kind === 'usage_limit') {
            bubble?.classList.add('msg-error');
            window.dispatchEvent(new CustomEvent('research:usage-limit'));
        }
        offerChoices(turn.choices, io);

        if (turn.action === 'connect_chatgpt') startConnect(io);
        if (turn.action === 'open_research' && !location.pathname.startsWith('/research')) {
            setTimeout(() => { location.href = '/research'; }, 1200);
        }
        // 데이터가 바뀌었으면 화면을 새로 그린다(로드맵 등).
        if (outcome.done && io.onChanged) io.onChanged(outcome);
        // 대화가 한 걸음 나가면 이 방의 이름도 달라진다(요약으로 짓기 때문에).
        historyChanged();
        // 만들어 놓고 끝내면 안 되는 결과는 서버가 갈 곳을 알려준다(세특 설계 등).
        // N학년 세특을 마쳤으면 로드맵의 그 학년 자리까지 지목해서 온다.
        if (outcome.redirect) setTimeout(() => goTo(outcome.redirect), 1200);
        // 한 턴을 쓰면 사용량도 달라진다. 게이지를 지금 값으로 맞춘다.
        window.dispatchEvent(new CustomEvent('research:usage-refresh'));
    };

    const showFailure = (error, io) => {
        const failed = io.showAI(error.message, { action: 'none' });
        if (error.kind === 'usage_limit') {
            failed?.classList.add('msg-error');
            window.dispatchEvent(new CustomEvent('research:usage-limit'));
        }
    };

    const stopWatching = (io) => {
        if (turnPoll) { clearTimeout(turnPoll); turnPoll = null; }
        io.hideThinking();
        busy = false;
    };

    /**
     * 서버가 아직 만들고 있는 턴을 지켜본다.
     *
     * 세특 설계처럼 오래 걸리는 일은 새로고침해도 서버에서 계속 진행된다.
     * 화면은 생성 표시만 되살려 두고 끝날 때까지 기다리면 된다.
     * 호출 전에 생성 표시(showThinking)가 이미 떠 있어야 한다 — 여기서 또 띄우면
     * 점 세 개짜리 줄이 하나 더 생기고 지워지지 않는다.
     */
    const watchTurn = (io) => {
        if (turnPoll) return;
        busy = true;
        const tick = async () => {
            let body;
            try {
                body = await api('/api/research/chat/pending');
            } catch (error) {
                stopWatching(io);
                showFailure(error, io);
                return;
            }
            if (body.pending) { turnPoll = setTimeout(tick, 2000); return; }
            stopWatching(io);
            // idle이면 받아 갈 결과가 없다(다른 탭이 이미 가져갔거나 기록이 지워진 경우).
            if (!body.idle) applyTurn(body, io);
        };
        turnPoll = setTimeout(tick, 1500);
    };

    /**
     * 마지막 답변을 걷어내고 직전 발화로 다시 만든다.
     * 서버가 직전 발화를 그대로 쓰므로 학생이 같은 말을 또 타이핑할 일이 없다.
     */
    const regenerate = async (io) => {
        if (busy) return;
        busy = true;
        if (lastReply) { lastReply.remove(); lastReply = null; }
        while (history.length && history[history.length - 1].role === 'assistant') {
            history.pop();
        }
        io.showThinking();
        try {
            const turn = await api('/api/research/chat/regenerate', {
                method: 'POST',
                body: JSON.stringify({
                    session_id: sessionId,
                    history: history.slice(0, -1),
                }),
            });
            if (turn.pending) { watchTurn(io); return; }
            io.hideThinking();
            applyTurn(turn, io);
        } catch (error) {
            io.hideThinking();
            showFailure(error, io);
        } finally {
            if (!turnPoll) busy = false;
        }
    };

    /**
     * 한 턴을 보낸다. 화면에 그리는 방법은 호출자가 넘긴다.
     * @param {object} io  { showUser, showAI, showThinking, hideThinking, onChanged }
     */
    const send = async (text, io) => {
        if (busy || !text.trim()) return;
        busy = true;
        history.push({ role: 'user', text });
        io.showUser(text);
        io.showThinking();

        try {
            const turn = await api('/api/research/chat', {
                method: 'POST',
                body: JSON.stringify({
                    message: text,
                    history: history.slice(0, -1),
                    session_id: sessionId,
                }),
            });
            // 오래 걸리는 일은 서버가 백그라운드로 돌린다.
            // 생성 표시를 그대로 둔 채 끝날 때까지 지켜본다.
            if (turn.pending) { watchTurn(io); return; }
            io.hideThinking();
            applyTurn(turn, io);
        } catch (error) {
            io.hideThinking();
            showFailure(error, io);
        } finally {
            if (!turnPoll) busy = false;
        }
    };

    /**
     * 서버가 내려준 선택지를 화면에 띄운다.
     * 버튼은 말하기의 지름길일 뿐이다 — 누르면 `send` 문장을 그대로 보내므로
     * 직접 타이핑한 것과 완전히 같은 경로를 탄다.
     */
    const offerChoices = (choices, io) => {
        if (!choices || !(choices.options || []).length || !io.showChoices) return;
        io.showChoices(choices, (option) => {
            // 연결 버튼만 예외다. 보낼 말이 아니라 그 자리에서 인증을 시작한다.
            if (option.act === 'connect') { startConnect(io); return; }
            send(option.send, io);
        });
    };

    /** 이 단계를 진행하려면 ChatGPT 연결이 먼저 필요한가. */
    const needsConnect = (next) => Boolean(next && next.needs_ai && !next.ai_connected);

    /**
     * AI가 필요한 단계인데 연결이 안 돼 있으면 대화 안에서 연결을 요청한다.
     * 학생이 무언가 보내 보고 나서야 알게 되면 늦다.
     */
    const askToConnect = async (io, next) => {
        if (!next.ai_configured) {
            const line = '지금은 AI 기능을 쓸 수 없어요. 관리자에게 문의해 주세요.';
            history.push({ role: 'assistant', text: line });
            io.showAI(line, { action: 'none' });
            return;
        }
        const line = `${next.message || ''}\n\n그러려면 먼저 ChatGPT 계정을 연결해야 해. 네 계정의 사용량으로 동작해.`.trim();
        history.push({ role: 'assistant', text: line });
        io.showAI(line, { action: 'none' });
        offerChoices({ options: [{ label: 'ChatGPT 연결하기', act: 'connect' }] }, io);
    };

    /**
     * 연결이 끝났다. 인증 절차가 대화 중간에 끼어들었으므로, 하던 이야기의
     * 맥락(지금 단계 안내)을 다시 말해 준 뒤 선택지를 깐다. "무엇부터 할까요?"만
     * 던지면 학생은 인증 전에 무슨 얘기였는지 이미 잊었다.
     */
    const afterConnected = async (io) => {
        // 사이드바 USAGE는 페이지 로드 때 한 번만 그려진다.
        // 여기서 알려주지 않으면 새로고침해야만 연결이 반영된다.
        window.dispatchEvent(new CustomEvent('research:usage-refresh'));
        // 로그인이 이제 막 생긴 것일 수 있다. HISTORY도 이 계정의 목록으로 다시 그린다.
        historyChanged();
        try {
            const next = await api('/api/research/next');
            const line = ['연결됐어!', next.message, next.ask]
                .filter(Boolean).join('\n\n');
            history.push({ role: 'assistant', text: line });
            io.showAI(line, { action: 'none' });
            offerChoices(next.choices, io);
        } catch (_) { /* 조용히 넘어간다 */ }
    };

    /** ChatGPT 연결도 대화 안에서 처리한다. 코드가 나오면 승인될 때까지 지켜본다. */
    const startConnect = async (io) => {
        try {
            const result = await api('/api/auth/codex/connect', { method: 'POST' });
            if (result.connected) {
                // 인사는 afterConnected가 단계 안내와 함께 한다. 여기서 또 하면 두 번 인사한다.
                afterConnected(io);
                return;
            }
            const login = result.login;
            const code = login.user_code;

            // 코드를 먼저 클립보드에 넣어 둔다. 인증 창에서 손으로 옮겨 적을 일이 없게 한다.
            let copied = false;
            try {
                await navigator.clipboard.writeText(code);
                copied = true;
            } catch (_) {
                // 권한이 없거나 보안 컨텍스트가 아니면 화면의 코드를 직접 복사하게 둔다.
            }

            // 확인을 누른 뒤에 창을 연다. 코드가 복사된 걸 모르고 창부터 마주치지 않도록.
            window.alert(copied
                ? `인증 코드 ${code} 를 복사했습니다.\n확인을 누르면 인증 창이 열립니다. 거기에 붙여넣어 주세요.`
                : `인증 코드: ${code}\n확인을 누르면 인증 창이 열립니다. 이 코드를 직접 붙여넣어 주세요.`);

            window.open(login.verification_url, '_blank', 'noopener,noreferrer');
            io.showAI(
                (copied
                    ? `코드를 복사해 뒀어요. 인증 창에 붙여넣고 승인해 주세요.`
                    : `아래 코드를 인증 창에 붙여넣고 승인해 주세요.`) +
                `\n\n**${code}**\n\n창이 안 열렸다면 ${login.verification_url} 로 들어가면 됩니다.`,
                { action: 'none' });

            if (connectPoll) clearInterval(connectPoll);
            connectPoll = setInterval(async () => {
                try {
                    const status = await api('/api/auth/codex/status');
                    if (status.connection && status.connection.status === 'connected') {
                        clearInterval(connectPoll); connectPoll = null;
                        afterConnected(io);
                    }
                } catch (_) { /* 다음 주기에 재시도 */ }
            }, 3000);
        } catch (error) {
            io.showAI(error.message, { action: 'none' });
        }
    };

    /**
     * 페이지에 들어왔을 때 지난 대화를 복원한다.
     * 기록이 없을 때만 AI가 먼저 말을 건다.
     */
    const opener = async (io, wantedSession, prefetchedNext) => {
        try {
            // 새로고침 전에 시작한 턴이 아직 돌고 있을 수 있다. 대화를 복원하기 전에 확인한다.
            // 이미 끝나 있으면 이 호출이 그 결과를 받아 가 버리는데, 그래도 된다 —
            // 그 답변은 아래 대화 기록에 이미 들어 있어서 다시 그리면 같은 말이 두 번 나온다.
            // 두 요청은 서로를 기다릴 이유가 없다. 함께 보낸다(채팅이 그만큼 빨리 열린다).
            // 특정 방을 지목하지 않았으면 <head> 프리페치가 이미 받아 둔 것을 그대로 쓴다.
            const boot = (!wantedSession && window.__boot) || {};
            const preJob = boot.chatPending;
            const preSaved = boot.messages;
            boot.chatPending = null;   // 프리페치는 한 번만 쓴다(다음 열기는 새로 받는다)
            boot.messages = null;
            const unwrap = async (pre) => {
                const got = pre ? await pre : null;
                return got && got.ok ? got.body : null;
            };
            let [job, saved] = await Promise.all([
                preJob ? unwrap(preJob)
                       : api('/api/research/chat/pending').catch(() => null),
                unwrap(preSaved),
            ]);
            if (!saved) {
                saved = await api('/api/research/messages'
                    + (wantedSession ? `?session_id=${encodeURIComponent(wantedSession)}` : ''));
            }
            const working = Boolean(job && job.pending);
            sessionId = saved.session_id || wantedSession || null;
            // 설계 방은 이 호출로 처음 만들어지기도 한다. 사이드바가 뒤늦게라도 알아야 한다.
            historyChanged();
            const past = saved.messages || [];
            past.forEach((turn, index) => {
                history.push({ role: turn.role, text: turn.text });
                if (turn.role === 'user') { io.showUser(turn.text); return; }
                // 복원한 대화에서도 마지막 답변에는 '다시 생성'이 붙어야 한다.
                const isLast = index === past.length - 1;
                const bubble = io.showAI(turn.text, {
                    action: turn.action || 'none',
                    onRegenerate: isLast ? () => regenerate(io) : null,
                });
                if (isLast) lastReply = bubble;
            });

            // 아직 만드는 중이면 생성 표시를 되살리고 결과를 기다린다.
            // 선택지는 지금 깔지 않는다 — 턴이 끝나면 그 결과에 담겨 온다.
            if (working) { io.showThinking(); watchTurn(io); return; }

            if (past.length) {
                // 대화 밖에서 진도가 나갈 수 있다(/welcome에서 온보딩을 끝내는 경우).
                // 마지막 말이 이미 지난 단계를 가리킬 수 있으므로 지금 할 수 있는 선택지를
                // 다시 깔아 준다. 이건 저장하지 않아 대화 기록이 불어나지 않는다.
                // 부팅이 이미 받아 둔 값이 있으면 또 부르지 않는다.
                const current = prefetchedNext
                    || await api('/api/research/next').catch(() => null);
                if (!current) return;
                if (needsConnect(current)) await askToConnect(io, current);
                else offerChoices(current.choices, io);
                return;
            }

            const next = prefetchedNext || await api('/api/research/next');
            if (next.stage === 'done') return;
            // 아직 대화가 없으면 첫 화면(home.js)이 같은 안내를 이미 하고 있다.
            // 여기서 또 말하면 홈 카드가 뜨자마자 채팅으로 덮여 두 번 읽게 된다.
            // 학생이 버튼을 누르거나 입력하면 그때부터 이 대화가 시작된다.
            const homeCard = document.getElementById('homeView');
            if (homeCard && !homeCard.hidden
                    && getComputedStyle(homeCard).display !== 'none') return;
            // 이 단계가 AI를 쓰는데 연결이 안 돼 있으면 그것부터 해결한다.
            if (needsConnect(next)) { await askToConnect(io, next); return; }
            // 설명(message) 뒤에는 반드시 구체적인 질문(ask)이 온다.
            // 예전처럼 "어떻게 할까?"만 붙이면 무슨 말을 해야 할지 알 수 없다.
            const line = next.stage === 'onboarding'
                ? `${next.ask} 아니면 /welcome 에서 네 가지만 답해도 돼.`
                : [next.message, next.ask].filter(Boolean).join('\n\n');
            history.push({ role: 'assistant', text: line });
            io.showAI(line, { action: 'none' });
            offerChoices(next.choices, io);
        } catch (_) { /* 비로그인 등은 조용히 넘어간다 */ }
    };

    /** 지난 대화는 HISTORY에 두고, 새 설계 대화방에서 다시 시작한다. */
    const reset = async () => {
        const body = await api('/api/research/messages', { method: 'DELETE' });
        sessionId = body.session_id || null;
        history.length = 0;
        historyChanged();
    };

    /**
     * AI가 말로만 알려주던 페이지 경로를 진짜 링크로 바꾼다.
     * 이미 escape된 문자열에만 적용한다(md 안에서만 호출).
     */
    const LINKABLE_PATHS = /(^|[\s([{"'])\/(welcome|research)\b/g;
    const linkify = (escaped) => escaped.replace(
        LINKABLE_PATHS, '$1<a class="chat-link" href="/$2">/$2</a>');

    window.ResearchChat = {
        send, opener, reset, history, linkify, goTo,
        connect: startConnect,
        session: () => sessionId,
    };
})();


/**
 * 실험 동반 학습.
 *
 * 전제는 그대로다 — 실험은 AI가 대신 해주지 않는다. Agent는 다섯 국면
 * (배경 조사 → 탐구 설계 → 실행 → 결과 정리 → 결론)을 따라가며 묻기만 하고,
 * 학생이 직접 해온 것을 근거로 다음 국면으로 넘어간다. 다 끝나면 이 대화 전체가
 * 그대로 탐구 보고서(.hwp)가 된다.
 *
 * 달라진 것은 무대뿐이다. 전용 페이지 대신 메인(/) 채팅방에서 진행한다.
 */
(() => {
    'use strict';

    const api = async (url, options = {}) => {
        const res = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
            const error = new Error(body.error || '요청을 처리하지 못했습니다.');
            error.kind = body.error_kind || null;
            throw error;
        }
        return body;
    };

    let planId = null;
    let phases = [];
    let phase = null;
    let busy = false;
    let poll = null;
    let finished = false;

    const stopWatching = (io) => {
        if (poll) { clearTimeout(poll); poll = null; }
        io.hideThinking();
        busy = false;
    };

    /**
     * 지금 몇 번째 국면인지. 대화 옆에 한 줄로만 알려준다.
     * 웹에서 실제로 찾아온 답이면 그것도 함께 밝힌다 — 지어낸 말과 구분되어야 한다.
     */
    const phaseLine = (turn) => {
        const searched = (turn.sources || []).length ? '웹 검색' : '';
        if (!turn.phase) return searched;
        const at = phases.findIndex((item) => item.key === turn.phase);
        const label = turn.phase_label || (phases[at] || {}).label || '';
        const where = at >= 0 ? `${at + 1}/${phases.length} ${label}` : label;
        return [where, searched].filter(Boolean).join(' · ');
    };

    // 다시 만들 수 있는 답변은 맨 마지막 것 하나뿐이다. 그 자리를 들고 있는다.
    let lastAnswer = null;
    // 보고서 칸. 다시 만들면 이 자리를 갈아 끼운다.
    let reportCard = null;

    /** 보고서 칸을 그린다(있으면 갈아 끼운다). */
    const putReport = (io, file, title, editable) => {
        const next = io.showReport(file, title, {
            onRebuild: () => rebuildReport(io),
            onInspect: () => inspectReport(io),
            onPpt: () => makePpt(io),
            editable });
        reportCard?.remove();
        reportCard = next;
        return next;
    };

    /**
     * 대화는 그대로 두고 보고서 문서만 다시 만든다.
     * 실험을 처음부터 다시 하라고 할 수는 없으니, 문서만 새로 뽑는 길을 따로 둔다.
     */
    const rebuildReport = async (io) => {
        if (busy || !planId) return;
        busy = true;
        io.showThinking();
        try {
            const turn = await api(`/api/research/experiment/${planId}/report`,
                                   { method: 'POST' });
            if (turn.pending) { watchTurn(io); return; }
            applyTurn(turn, io);
        } catch (error) {
            io.hideThinking();
            io.showAI(error.message, { error: true });
        } finally {
            if (!poll) busy = false;
        }
    };

    /**
     * 보고서 점검. 문서를 고치지 않고 고칠 곳만 짚어 준다 — 고치는 건 학생이
     * 편집기에서 한다(AI가 대신 해주지 않는다는 원칙은 서식에도 적용된다).
     */
    const inspectReport = async (io) => {
        if (busy || !planId) return;
        busy = true;
        io.showThinking();
        try {
            const result = await api(`/api/research/experiment/${planId}/inspect`,
                                     { method: 'POST' });
            io.hideThinking();
            const findings = result.findings || [];
            if (!findings.length) {
                io.showAI('문서를 점검해 봤는데 고칠 곳을 못 찾았어. 그림 인용, 장 번호, '
                          + '정렬 다 맞아. 이대로 내도 되겠는데?', { action: 'none' });
                return;
            }
            const lines = findings.map((item) =>
                `${item.level === 'warn' ? '⚠️' : '·'} ${item.message}`);
            io.showAI(`문서를 점검해 봤어. 이런 게 보여:\n\n${lines.join('\n')}\n\n`
                      + '고칠지는 네가 정해 — 편집기에서 열어서 바꾸면 돼.',
                      { action: 'none' });
        } catch (error) {
            io.hideThinking();
            io.showAI(error.message, { error: true });
        } finally {
            busy = false;
        }
    };

    /** 발표 PPT. 보고서가 이미 있으니 문서만 뽑는다. 필요할 때만 학생이 누른다. */
    const makePpt = async (io) => {
        if (busy || !planId) return;
        busy = true;
        io.showThinking();
        try {
            const result = await api(`/api/research/experiment/${planId}/ppt`,
                                     { method: 'POST' });
            if (result.pending) { watchTurn(io); return; }
            applyTurn(result, io);
        } catch (error) {
            io.hideThinking();
            io.showAI(error.message, { error: true });
        } finally {
            if (!poll) busy = false;
        }
    };

    const applyTurn = (turn, io) => {
        io.hideThinking();
        // 발표 자료가 나오면 내려받기 카드로 보여준다. 대화는 늘리지 않는다.
        if (turn.kind === 'ppt') {
            if (turn.ppt_file) {
                io.showAI(`발표 자료를 만들었어. [${turn.ppt_title || '발표 슬라이드'}]`
                          + `(/api/download/${encodeURIComponent(turn.ppt_file)}) 여기서 내려받아. `
                          + '슬라이드마다 발표 메모도 넣어 뒀어.', { action: 'none' });
                io.toast('발표 PPT를 만들었어요.', 'success');
            } else {
                io.showAI(turn.ppt_error || '발표 자료를 만들지 못했어요.', { error: true });
            }
            return;
        }
        // 보고서만 다시 만든 결과는 대화를 늘리지 않는다. 그 칸만 갈아 끼운다.
        if (turn.kind === 'report') {
            putReport(io, turn.report_file, turn.report_title, turn.report_editable);
            showStandardsCheck(turn.standards_check, io);
            io.toast(turn.report_file ? '보고서를 다시 만들었어요.'
                                      : '보고서 파일을 만들지 못했어요.',
                     turn.report_file ? 'success' : 'error');
            return;
        }
        if (turn.phase) phase = turn.phase;
        if (io.showPhaseBar) io.showPhaseBar(phases, phase);
        lastAnswer = io.showAI(turn.reply || '', {
            badge: phaseLine(turn),
            images: turn.images || [],
            demo: turn.demo || null,
            measureTable: turn.measure_table || null,
            onMeasure: (text) => send(text, io),
            onRegenerate: () => regenerate(io),
        });
        if (turn.report_error) io.showAI(turn.report_error, { error: true });
        if (turn.is_complete) {
            finished = true;
            putReport(io, turn.report_file, turn.report_title, turn.report_editable);
            showStandardsCheck(turn.standards_check, io);
            // 로드맵으로 돌아가면 이 과목 카드에 문서 아이콘이 붙어 있다.
            // 성취기준 결과를 읽을 시간을 준다.
            if (turn.redirect) {
                setTimeout(() => { location.href = turn.redirect; },
                           turn.standards_check ? 12000 : 4000);
            }
        }
        window.dispatchEvent(new CustomEvent('research:usage-refresh'));
    };

    /**
     * 성취기준 대조 결과. 세특은 성취기준 도달의 기록이라, 보고서가 기준에
     * 닿았는지는 생기부에 적히기 전에 학생이 알아야 한다.
     */
    const showStandardsCheck = (verdicts, io) => {
        if (!verdicts || !verdicts.length) return;
        const icon = { yes: '✅', partial: '🔶', no: '❌' };
        const lines = verdicts.map((v) => {
            let line = `${icon[v.reached] || '·'} **${v.code}** — ${v.evidence || ''}`;
            if (v.gap) line += `\n   ↳ ${v.gap}`;
            return line;
        });
        const reached = verdicts.filter((v) => v.reached === 'yes').length;
        io.showAI(`설계 때 고른 성취기준에 보고서가 닿았는지 확인해 봤어 `
                  + `(${reached}/${verdicts.length}개 도달):\n\n${lines.join('\n')}`,
                  { action: 'none' });
    };

    /** 서버가 아직 생각 중인 턴을 지켜본다(새로고침해도 서버에서는 계속 진행된다). */
    const watchTurn = (io) => {
        if (poll) return;
        busy = true;
        const tick = async () => {
            let body;
            try {
                body = await api(`/api/research/experiment/${planId}/pending`);
            } catch (error) {
                stopWatching(io);
                io.showAI(error.message, { error: true });
                return;
            }
            if (body.pending) {
                // '생각 중'과 '찾는 중'은 다른 일이다. 화면도 그렇게 보여야 한다.
                const at = body.progress || {};
                if (io.showStage) io.showStage(at.stage || 'thinking', at.label || '', at.steps);
                // 생성 도중 서버가 물어볼 것이 있으면(그림 계획 등) 질문 카드를 띄운다.
                if (io.showPlanQuestion) {
                    io.showPlanQuestion(at.question || null, (questionId, answer) =>
                        api(`/api/research/experiment/${planId}/plan-answer`, {
                            method: 'POST',
                            body: JSON.stringify({ question_id: questionId, answer }),
                        }).catch(() => {}));
                }
                poll = setTimeout(tick, 1200);
                return;
            }
            stopWatching(io);
            if (!body.idle) applyTurn(body, io);
        };
        poll = setTimeout(tick, 1200);
    };

    /**
     * 마지막 답변을 지우고 같은 질문으로 다시 만든다.
     * 학생이 같은 말을 또 타이핑할 이유가 없다 — 서버가 직전 질문을 그대로 쓴다.
     */
    const regenerate = async (io) => {
        if (busy || finished || !planId) return;
        busy = true;
        if (lastAnswer) { lastAnswer.remove(); lastAnswer = null; }
        io.showThinking();
        try {
            const turn = await api(`/api/research/experiment/${planId}/regenerate`,
                                   { method: 'POST' });
            if (turn.pending) { watchTurn(io); return; }
            applyTurn(turn, io);
        } catch (error) {
            io.hideThinking();
            io.showAI(error.message, { error: true });
        } finally {
            if (!poll) busy = false;
        }
    };

    const send = async (text, io) => {
        if (busy || finished || !text.trim() || !planId) return;
        busy = true;
        io.showUser(text);
        io.showThinking();
        try {
            const turn = await api(`/api/research/experiment/${planId}/chat`, {
                method: 'POST',
                body: JSON.stringify({ message: text }),
            });
            if (turn.pending) { watchTurn(io); return; }
            applyTurn(turn, io);
        } catch (error) {
            io.hideThinking();
            io.showAI(error.message, { error: true });
        } finally {
            if (!poll) busy = false;
        }
    };

    /** 실험 대화방을 연다. 지난 대화를 되살리고, 처음이면 Agent가 먼저 말을 건다. */
    const open = async (id, io) => {
        planId = id;
        finished = false;
        let view = null;
        let job = null;
        try {
            // <head> 프리페치가 이미 받아 뒀으면 그대로 쓴다(가장 흔한 경로).
            const boot = window.__boot || {};
            if (boot.expView) {
                const [preView, prePending] = await Promise.all([
                    boot.expView, boot.expPending || Promise.resolve(null)]);
                boot.expView = null;
                boot.expPending = null;
                if (preView && preView.ok) view = preView.body;
                if (prePending && prePending.ok) job = prePending.body;
            }
            if (!view) {
                // 대화 내용과 "아직 만드는 중인지"는 서로를 기다릴 이유가 없다. 함께 묻는다.
                [view, job] = await Promise.all([
                    api(`/api/research/experiment/${planId}`),
                    api(`/api/research/experiment/${planId}/pending`).catch(() => null),
                ]);
            }
        } catch (error) {
            io.showAI(error.message, { error: true });
            return false;
        }

        const plan = view.plan || {};
        const design = plan.activity_design || {};
        phases = view.phases || [];

        io.showHeader({
            subject: plan.subject || '실험',
            meta: [view.grade ? `${view.grade}학년` : '', plan.area_name || ''].filter(Boolean).join(' · '),
            question: design.question || '',
            phases,
        });

        const past = view.messages || [];
        // 다시 만들 수 있는 건 마지막 답변뿐이다. 그 앞의 것들은 이미 대화의 일부다.
        const done = plan.experiment_status === 'done';
        const lastIndex = past.map((turn) => turn.role).lastIndexOf('assistant');

        // 마지막 국면은 대화 전체를 훑어야 안다(진행 바와 복귀 카드가 함께 쓴다).
        past.forEach((turn) => { if (turn.phase) phase = turn.phase; });

        const drawTurn = (turn, index) => {
            if (turn.role === 'user') { io.showUser(turn.text || ''); return; }
            const bubble = io.showAI(turn.text || '', {
                badge: phaseLine(turn),
                images: turn.images || [],
                demo: turn.demo || null,
                // 표는 아직 기록하지 않은 마지막 답변에만 되살린다.
                // 이미 지나간 턴의 입력기를 다시 띄우면 같은 값을 두 번 보내게 된다.
                measureTable: (index === lastIndex && !done) ? (turn.measure_table || null) : null,
                onMeasure: (text) => send(text, io),
                onRegenerate: (index === lastIndex && !done) ? () => regenerate(io) : null,
            });
            if (index === lastIndex) lastAnswer = bubble;
        };

        // 대화가 길게 쌓인 방은 통째로 펼치지 않는다. 어디까지 왔는지 한 줄로
        // 알려주고, 마지막 주고받은 것만 보여준다. 나머지는 눌러야 펼쳐진다.
        const RESUME_MIN = 6;   // 이보다 짧으면 접어 봐야 얻는 게 없다
        const RESUME_TAIL = 2;  // 바로 이어서 답할 수 있게 마지막 한 쌍은 남긴다
        if (!done && past.length >= RESUME_MIN && io.showResume) {
            const head = past.slice(0, past.length - RESUME_TAIL);
            const label = (phases.find((item) => item.key === phase) || {}).label || '시작';
            const lastUser = [...head].reverse().find((turn) => turn.role === 'user');
            io.showResume({
                phaseLabel: label,
                count: head.length,
                lastLine: (lastUser && lastUser.text || '').slice(0, 60),
            }, () => {
                // 접어 뒀던 것을 제자리(복귀 카드 다음, 최근 대화 앞)에 펼친다.
                const anchor = stream.querySelector('.resume-row');
                const held = document.createDocumentFragment();
                const moved = [];
                head.forEach((turn, index) => {
                    const before = stream.childElementCount;
                    drawTurn(turn, index);
                    for (let at = before; at < stream.childElementCount; at += 1) {
                        moved.push(stream.children[at]);
                    }
                });
                moved.forEach((element) => held.appendChild(element));
                anchor.after(held);
            });
            past.slice(past.length - RESUME_TAIL).forEach((turn, offset) =>
                drawTurn(turn, past.length - RESUME_TAIL + offset));
        } else {
            past.forEach(drawTurn);
        }

        if (io.showPhaseBar) io.showPhaseBar(phases, phase);

        if (plan.experiment_status === 'done') {
            finished = true;
            putReport(io, plan.report_file, '보고서 열기', plan.report_editable);
            return true;
        }

        // 나가 있는 동안 서버가 답을 만들고 있었을 수 있다(위에서 함께 받아 뒀다).
        if (job && job.pending) { io.showThinking(); watchTurn(io); return true; }

        if (!past.length) {
            if (!view.ai_connected) {
                io.showAI('실험을 함께 하려면 ChatGPT 연결이 필요해요. 먼저 연결해 줄래?');
                return false;
            }
            io.showAI(
                `이제 **${plan.subject || '이 과목'}** 실험을 같이 해보자.\n\n` +
                '내가 대신 해주지는 않아. 대신 뭘 찾아보고 뭘 해봐야 하는지 하나씩 알려줄게.\n\n' +
                '먼저 이 탐구 질문에 대해 네가 지금 알고 있는 것, 혹은 짐작하는 것을 말해줄래?');
        }
        return true;
    };

    window.ExperimentChat = { open, send, isFinished: () => finished };
})();

/**
 * 메인 채팅(/)을 연구 서사·실험 대화에 연결한다.
 *
 * 이 화면 하나가 두 가지 대화의 무대다.
 *  - 설계: 연구 서사가 끝나지 않았으면 입력을 가로채 /api/research/chat 으로 보낸다.
 *  - 실험: 주소에 ?chat=<대화방>이 붙어 오면 그 과목의 실험 대화를 연다.
 * index.js의 전송 핸들러보다 먼저 잡기 위해 capture 단계에서 처리한다.
 */
(() => {
    'use strict';

    const input = document.getElementById('userRequest');
    const sendBtn = document.getElementById('btnSend');
    const stream = document.getElementById('chatStream');
    const resultView = document.getElementById('resultView');
    const homeView = document.getElementById('homeView');
    if (!input || !sendBtn || !stream || !window.ResearchChat) return;

    let active = false;      // 이 화면의 입력을 우리가 가져가는가
    let mode = 'design';     // 'design'(연구 서사) | 'experiment'(과목 실험)
    let thinkingRow = null;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    // 실험에서 찾아온 출처는 링크로 남는다. 눌러서 열 수 있어야 확인하러 갈 수 있다.
    // esc를 거친 뒤이므로 여기서 만나는 &amp; 는 원래 & 였다.
    const LINK_RE = /https?:\/\/[^\s<]+[^\s<.,)\]]/g;
    const MD_LINK_RE = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;

    /** 주소에서 사람이 알아보는 부분만. www는 군더더기라 뗀다. */
    const hostOf = (url) => {
        try { return new URL(url).hostname.replace(/^www\./, ''); } catch (_) { return ''; }
    };
    const isPdf = (url) => /\.pdf($|[?#])/i.test(url);

    /**
     * 출처 칩. 주소를 통째로 늘어놓으면 문장이 읽히지 않으므로,
     * 제목과 도메인만 작게 보여주고 원문은 눌러서 연다.
     */
    const sourceChip = (label, url) => `
        <a class="src-chip" href="${url}" target="_blank" rel="noopener noreferrer"
           title="${label ? `${label} — ` : ''}${url}">
            <i class="bi bi-${isPdf(url) ? 'filetype-pdf' : 'link-45deg'}" aria-hidden="true"></i>
            <span class="t">${label || hostOf(url) || url}</span>
            ${label && hostOf(url) ? `<span class="d">${hostOf(url)}</span>` : ''}
        </a>`;

    /**
     * 아주 가벼운 마크다운(굵게, 줄바꿈, 링크)만 처리한다.
     * 링크를 먼저 자리표시자로 빼둔다 — 그러지 않으면 그냥 놓인 주소를 링크로
     * 바꾸는 단계가 방금 만든 <a href="…"> 안쪽까지 건드려 태그가 깨진다.
     */
    const md = (text) => {
        const chips = [];
        const keep = (html) => `@@C${chips.push(html) - 1}@@`;

        let out = esc(text)
            .replace(MD_LINK_RE, (_, label, url) => keep(sourceChip(label, url)))
            .replace(LINK_RE, (url) => keep(sourceChip('', url)));
        out = window.ResearchChat.linkify(out)
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
        return out.replace(/@@C(\d+)@@/g, (_, index) => chips[Number(index)]);
    };

    /** index.js가 그리는 것과 같은 모양의 메시지 행을 만든다. */
    const row = (role, html, badge = '') => {
        const div = document.createElement('div');
        div.className = 'message-row research-msg';
        const isUser = role === 'user';
        const name = isUser ? 'You' : (mode === 'experiment' ? '함께하는 Agent' : 'AI Agent');
        div.innerHTML = `
            <div class="role-avatar ${isUser ? 'user' : 'ai'}">
                <i class="bi bi-${isUser ? 'person' : 'stars'}"></i>
            </div>
            <div class="message-content">
                <div class="message-name">${name}${badge
                    ? `<span class="phase-badge">${esc(badge)}</span>` : ''}</div>
                <div class="markdown-body">${html}</div>
            </div>`;
        // 대화가 비어 있으면 결과 뷰가 숨겨져 있다. 메시지를 넣을 때 펼친다.
        // 대화가 시작되면 첫 화면 인사말은 자리를 비켜준다.
        if (homeView) homeView.style.display = 'none';
        if (resultView) resultView.style.display = 'flex';
        stream.style.display = 'flex';
        stream.appendChild(div);
        const scroller = document.getElementById('scrollContainer');
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
        return div;
    };

    /** 클릭으로 답할 수 있는 선택지. 고르면 그 자리에서 사라진다. */
    const choiceRow = (choices, onPick) => {
        const div = document.createElement('div');
        div.className = 'message-row choice-row';
        div.innerHTML = `
            <div class="role-avatar ghost" aria-hidden="true"></div>
            <div class="message-content">
                ${choices.prompt ? `<div class="choice-prompt">${esc(choices.prompt)}</div>` : ''}
                <div class="choice-list" role="group"${choices.prompt ? ` aria-label="${esc(choices.prompt)}"` : ''}></div>
            </div>`;
        const list = div.querySelector('.choice-list');
        choices.options.forEach((option) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'choice-btn';
            button.textContent = option.label;
            button.addEventListener('click', () => {
                div.remove();          // 고른 뒤에는 남겨두지 않는다
                onPick(option);
            });
            list.appendChild(button);
        });
        stream.appendChild(div);
        const scroller = document.getElementById('scrollContainer');
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
        return div;
    };

    /**
     * 실험 국면 진행 바. 폰에서는 머리말이 위로 스크롤돼 사라지므로,
     * 지금 몇 번째 국면인지가 화면에서 없어진다. 얇은 바를 위에 붙여 둔다.
     * 데스크톱에서는 머리말이 그 역할을 하므로 CSS로 숨긴다.
     */
    /**
     * 며칠 만에 돌아온 학생을 맞이하는 자리.
     *
     * 지난 대화 전체를 스크롤로 던지면 "어디까지 했더라"부터 다시 읽어야 하고,
     * 그 앞에서 그만둔다. 어디까지 왔는지 한 줄로 알려주고, 지난 대화는 접어 둔다.
     */
    const resumeCard = (info, onExpand) => {
        const card = document.createElement('div');
        card.className = 'message-row resume-row';
        card.innerHTML = `
            <div class="role-avatar ghost" aria-hidden="true"></div>
            <div class="message-content">
                <div class="resume-box">
                    <div class="resume-where">
                        <i class="bi bi-bookmark-check" aria-hidden="true"></i>
                        지난번에 <b>${esc(info.phaseLabel)}</b>까지 했어
                    </div>
                    ${info.lastLine ? `<div class="resume-last">"${esc(info.lastLine)}"</div>` : ''}
                    <button class="resume-open" type="button">
                        지난 대화 ${info.count}개 보기
                    </button>
                </div>
            </div>`;
        card.querySelector('.resume-open').addEventListener('click', () => {
            card.querySelector('.resume-open').remove();
            onExpand();
        });
        stream.appendChild(card);
        if (homeView) homeView.style.display = 'none';
        if (resultView) resultView.style.display = 'flex';
        stream.style.display = 'flex';
        return card;
    };

    let phaseBar = null;
    const setPhaseBar = (phases, current) => {
        if (!(phases || []).length) return;
        if (!phaseBar) {
            phaseBar = document.createElement('div');
            phaseBar.className = 'phase-bar';
            stream.parentElement.insertBefore(phaseBar, stream);
        }
        const at = phases.findIndex((item) => item.key === current);
        phaseBar.innerHTML = phases.map((item, index) => {
            const state = at < 0 ? '' : (index < at ? 'done' : (index === at ? 'now' : ''));
            return `<span class="phase-dot ${state}">
                ${index < at ? '<i class="bi bi-check-lg" aria-hidden="true"></i>' : ''}
                ${esc(item.label)}
            </span>`;
        }).join('');
        phaseBar.setAttribute('aria-label',
            at >= 0 ? `실험 진행: ${phases.length}단계 중 ${at + 1}단계` : '실험 진행');
    };

    /** 실험 대화방 머리말. 무슨 과목의 어떤 질문을 다루는 자리인지 위에 고정해 둔다. */
    const headerCard = (info) => {
        const div = document.createElement('div');
        div.className = 'message-row exp-head';
        div.innerHTML = `
            <div class="role-avatar ghost" aria-hidden="true"></div>
            <div class="message-content">
                <div class="exp-head-top">
                    <span class="exp-subject">${esc(info.subject)}</span>
                    ${info.meta ? `<span class="exp-meta">${esc(info.meta)}</span>` : ''}
                </div>
                ${info.question ? `<div class="exp-question">${esc(info.question)}</div>` : ''}
                ${(info.phases || []).length ? `<ol class="exp-phases">${info.phases
                    .map((item) => `<li>${esc(item.label)}</li>`).join('')}</ol>` : ''}
            </div>`;
        if (homeView) homeView.style.display = 'none';
        if (resultView) resultView.style.display = 'flex';
        stream.style.display = 'flex';
        stream.appendChild(div);
        return div;
    };

    /** 실험이 끝났다. 입력을 닫고 만들어진 문서를 열 수 있게 한다. */
    const reportCard = (file, title, opts = {}) => {
        // 편집기로 열 수 있는지는 서버가 파일 내용을 보고 알려준다(report_editable).
        // 알려주지 않은 옛 응답에서는 이름으로 짐작한다.
        const editable = !file ? false
            : (opts.editable !== undefined && opts.editable !== null)
                ? !!opts.editable
                : /\.hwp$/i.test(file);

        input.disabled = true;
        sendBtn.disabled = true;
        input.placeholder = '실험이 끝났어요.';

        const div = document.createElement('div');
        div.className = 'message-row exp-done';
        div.innerHTML = `
            <div class="role-avatar ghost" aria-hidden="true"></div>
            <div class="message-content">
                <div class="exp-done-title">실험이 끝났어요</div>
                <div class="exp-done-sub">${!file
                    ? '보고서 파일은 만들지 못했지만 대화 기록은 남아 있어요.'
                    : editable
                        ? '이 대화를 그대로 탐구 보고서로 옮겼어요. 편집기에서 이어 손봐도 돼.'
                        : 'HWP 변환기가 멈춰서 워드 파일로 저장했어요. 편집기에서는 못 열리니까 '
                          + '내려받아 쓰거나, 아래에서 문서를 다시 만들어 봐.'}</div>
                ${editable ? `
                    <a class="exp-doc" href="/editor?file=${encodeURIComponent(file)}">
                        <img src="/static/images/hwp-doc.svg" alt="">
                        ${esc(title || '보고서')}
                    </a>` : ''}
                ${file ? `
                    <a class="exp-dl" href="/api/download/${encodeURIComponent(file)}">
                        <i class="bi bi-download" aria-hidden="true"></i> 내려받기
                    </a>` : ''}
                <div class="msg-actions">
                    ${opts.onRebuild ? `
                        <button class="act-btn" type="button" data-act="rebuild">
                            <i class="bi bi-arrow-repeat" aria-hidden="true"></i> 문서 다시 만들기
                        </button>` : ''}
                    ${(editable && opts.onInspect) ? `
                        <button class="act-btn" type="button" data-act="inspect">
                            <i class="bi bi-search" aria-hidden="true"></i> 문서 점검
                        </button>` : ''}
                    ${(file && opts.onPpt) ? `
                        <button class="act-btn" type="button" data-act="ppt">
                            <i class="bi bi-easel" aria-hidden="true"></i> 발표 PPT 만들기
                        </button>` : ''}
                </div>
            </div>`;
        div.querySelector('[data-act="rebuild"]')
            ?.addEventListener('click', () => opts.onRebuild());
        div.querySelector('[data-act="inspect"]')
            ?.addEventListener('click', () => opts.onInspect());
        div.querySelector('[data-act="ppt"]')
            ?.addEventListener('click', () => opts.onPpt());
        stream.appendChild(div);
        const scroller = document.getElementById('scrollContainer');
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
        return div;
    };

    /**
     * 찾아온 이미지. 글로만 설명해서는 안 되는 것을 대화 안에서 바로 보여준다.
     * 누르면 크게 펼쳐 본다 — 대화를 떠나지 않고 그 자리에서 확인할 수 있어야 한다.
     * 화면 캡처는 작게 보면 글자가 안 보여서, 옮겨 가기 전에 크게 볼 수 있어야 쓸모가 있다.
     */
    const imageStrip = (images) => `
        <div class="img-strip">${images.map((item) => `
            <button class="img-card" type="button"
                    data-src="${esc(item.image_url)}"
                    data-page="${esc(item.page_url || '')}"
                    data-title="${esc(item.title || '')}"
                    title="${esc(item.title || '')}">
                <img src="${esc(item.image_url)}" alt="${esc(item.title || '')}" loading="lazy">
            </button>`).join('')}</div>`;

    /**
     * 크게 보기. 한 번에 하나만 뜨고, X·바깥 클릭·ESC로 닫는다.
     * 닫으면 눌렀던 자리로 초점을 돌려준다.
     */
    let lightbox = null;
    let lightboxOpener = null;

    const closeLightbox = () => {
        if (!lightbox) return;
        lightbox.remove();
        lightbox = null;
        document.removeEventListener('keydown', onLightboxKey);
        lightboxOpener?.focus();
        lightboxOpener = null;
    };

    function onLightboxKey(event) {
        if (event.key === 'Escape') closeLightbox();
    }

    const openLightbox = (card) => {
        closeLightbox();
        lightboxOpener = card;

        const title = card.dataset.title || '';
        const page = card.dataset.page || '';
        lightbox = document.createElement('div');
        lightbox.className = 'lightbox';
        lightbox.setAttribute('role', 'dialog');
        lightbox.setAttribute('aria-modal', 'true');
        lightbox.setAttribute('aria-label', title || '이미지 크게 보기');
        lightbox.innerHTML = `
            <div class="lightbox-body">
                <button class="lightbox-close" type="button" aria-label="닫기">
                    <i class="bi bi-x-lg" aria-hidden="true"></i>
                </button>
                <img src="${esc(card.dataset.src)}" alt="${esc(title)}">
                ${(title || page) ? `
                    <div class="lightbox-cap">
                        <span>${esc(title)}</span>
                        ${page ? `<a href="${esc(page)}" target="_blank" rel="noopener noreferrer">
                            출처 열기 <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>
                        </a>` : ''}
                    </div>` : ''}
            </div>`;

        // 바깥(어두운 곳)을 누르면 닫는다. 사진이나 설명을 누른 건 닫지 않는다.
        lightbox.addEventListener('click', (event) => {
            if (event.target === lightbox) closeLightbox();
        });
        lightbox.querySelector('.lightbox-close').addEventListener('click', closeLightbox);
        document.addEventListener('keydown', onLightboxKey);
        document.body.appendChild(lightbox);
        lightbox.querySelector('.lightbox-close').focus();
    };

    const DOTS = '<span class="research-dots"><i></i><i></i><i></i></span>';

    /**
     * 학생이 직접 눌러볼 화면.
     *
     * 만들어진 HTML은 우리가 쓴 코드가 아니므로 이 페이지에 그대로 붙이지 않는다.
     * sandbox iframe 안에서만 돌린다 — allow-same-origin을 주지 않으므로 이 화면의
     * DOM·쿠키·로그인 세션에 손댈 수 없다. 안에서 눌러보는 것만 된다.
     */
    const demoDocument = (html) => `<!doctype html><meta charset="utf-8">
        <style>
            body { margin:0; padding:16px; background:#fff; color:#0F172A;
                   font-family: 'Pretendard', system-ui, -apple-system, 'Noto Sans KR', sans-serif; }
            * { box-sizing: border-box; }
        </style>
        <script>
            // 클립보드는 이 안에서 쓸 수 없다. same-origin을 주지 않은 프레임이라
            // 브라우저가 막는다. 그래서 복사 요청만 바깥으로 넘기고 실제 복사는 바깥이 한다.
            // 화면을 만드는 쪽은 평소처럼 clipboard.writeText를 부르면 된다.
            (function () {
                var send = function (text) {
                    parent.postMessage({ demoCopy: String(text == null ? '' : text) }, '*');
                };
                try {
                    if (!navigator.clipboard) navigator.clipboard = {};
                    navigator.clipboard.writeText = function (text) {
                        send(text); return Promise.resolve();
                    };
                } catch (e) { /* 못 바꿔도 아래 execCommand 경로가 남는다 */ }

                var exec = document.execCommand && document.execCommand.bind(document);
                document.execCommand = function (command) {
                    if (String(command).toLowerCase() !== 'copy') {
                        return exec ? exec.apply(document, arguments) : false;
                    }
                    var picked = (window.getSelection && window.getSelection().toString()) || '';
                    var node = document.activeElement;
                    if (!picked && node && typeof node.value === 'string') {
                        picked = node.value.slice(node.selectionStart || 0,
                                                  node.selectionEnd || node.value.length)
                                 || node.value;
                    }
                    send(picked);
                    return true;
                };
            })();

            // 내용 높이를 바깥에 알려 준다. 스크롤바 두 개가 생기지 않게 하려는 것뿐이다.
            var tell = function () {
                parent.postMessage({ demoHeight: document.documentElement.scrollHeight }, '*');
            };
            new ResizeObserver(tell).observe(document.documentElement);
            addEventListener('load', tell); tell();
        </script>
        ${html}`;

    const demoCard = (demo) => {
        const card = document.createElement('div');
        card.className = 'demo-card';
        card.innerHTML = `
            <div class="demo-head">
                <i class="bi bi-window-stack" aria-hidden="true"></i>
                <span class="demo-title">${esc(demo.title || '직접 눌러보기')}</span>
                <button class="demo-reset" type="button">처음으로</button>
            </div>`;

        const frame = document.createElement('iframe');
        frame.className = 'demo-frame';
        frame.setAttribute('sandbox', 'allow-scripts');   // same-origin은 주지 않는다
        frame.setAttribute('title', demo.title || '실험 화면');
        // srcdoc은 속성 문자열로 만들지 않고 값으로 넣는다(따옴표 이스케이프 사고를 없앤다).
        frame.srcdoc = demoDocument(demo.html);
        card.appendChild(frame);

        // 여러 번 시도하는 실험이라 처음 상태로 되돌릴 수단이 있어야 한다.
        card.querySelector('.demo-reset').addEventListener('click', () => {
            frame.srcdoc = demoDocument(demo.html);
        });
        return card;
    };

    /**
     * 측정값 표 입력기.
     *
     * 실험은 책상이 아니라 주방·운동장에서, 폰으로 진행된다. 잰 값을 문장으로
     * 받아 적게 하면 그 자리에서 기록이 끊긴다. 열은 Agent가 탐구 설계에서
     * 정해 주고(measure_table), 값은 학생만 채운다 — 앱의 원칙 그대로다.
     *
     * 기록하면 마크다운 표 문장으로 대화에 보내진다. 보고서 조립이 그 표기를
     * 이미 진짜 HWP 표로 바꾸므로, 여기서 따로 형식을 만들지 않는다.
     */
    const measureCard = (table, onSubmit) => {
        const columns = table.columns || [];
        const card = document.createElement('div');
        card.className = 'measure-card';

        const cell = (rowIndex, colIndex) => `
            <td><input class="measure-input" type="text" inputmode="decimal"
                       aria-label="${esc(columns[colIndex])} ${rowIndex + 1}행"
                       data-row="${rowIndex}" data-col="${colIndex}"></td>`;

        const rowHtml = (rowIndex) => `
            <tr>${columns.map((_, colIndex) => cell(rowIndex, colIndex)).join('')}
                <td class="measure-del">
                    <button type="button" class="measure-drop" aria-label="${rowIndex + 1}행 지우기">
                        <i class="bi bi-x" aria-hidden="true"></i>
                    </button>
                </td>
            </tr>`;

        card.innerHTML = `
            <div class="measure-head">
                <i class="bi bi-table" aria-hidden="true"></i>
                <span class="measure-title">${esc(table.title || '측정값 기록')}</span>
            </div>
            <div class="measure-scroll">
                <table class="measure-table">
                    <thead><tr>${columns.map((name) =>
                        `<th>${esc(name)}</th>`).join('')}<th></th></tr></thead>
                    <tbody>${Array.from({ length: table.rows || 3 },
                        (_, index) => rowHtml(index)).join('')}</tbody>
                </table>
            </div>
            <div class="measure-actions">
                <button type="button" class="measure-add">
                    <i class="bi bi-plus-lg" aria-hidden="true"></i> 행 추가
                </button>
                <button type="button" class="measure-send">기록하기</button>
            </div>`;

        const body = card.querySelector('tbody');
        const addRow = () => {
            const temp = document.createElement('tbody');
            temp.innerHTML = rowHtml(body.children.length);
            body.appendChild(temp.firstElementChild);
        };
        card.querySelector('.measure-add').addEventListener('click', addRow);

        // 행 지우기. 마지막 한 줄은 남긴다 — 표가 통째로 사라지면 다시 만들 길이 없다.
        body.addEventListener('click', (event) => {
            const drop = event.target.closest('.measure-drop');
            if (!drop || body.children.length <= 1) return;
            drop.closest('tr').remove();
        });

        // 폰에서 다음 칸으로 넘어갈 때 키보드를 닫았다 여는 일이 없게 한다.
        body.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' || event.isComposing) return;
            event.preventDefault();
            const inputs = [...body.querySelectorAll('.measure-input')];
            const next = inputs[inputs.indexOf(event.target) + 1];
            if (next) next.focus(); else addRow();
        });

        card.querySelector('.measure-send').addEventListener('click', () => {
            const rows = [...body.querySelectorAll('tr')]
                .map((tr) => [...tr.querySelectorAll('.measure-input')]
                    .map((input) => input.value.trim()))
                .filter((values) => values.some((value) => value));
            if (!rows.length) { toast('값을 하나라도 넣어 줘.', 'error'); return; }

            // 마크다운 표로 보낸다. 보고서 조립이 이 표기를 그대로 HWP 표로 바꾼다.
            const line = (values) => `| ${values.join(' | ')} |`;
            const text = [
                table.title ? `${table.title} 측정값이야.` : '측정값이야.',
                '',
                line(columns),
                line(columns.map(() => '---')),
                ...rows.map((values) =>
                    line(columns.map((_, index) => values[index] || ''))),
            ].join('\n');

            card.remove();
            onSubmit(text);
        });
        return card;
    };

    /**
     * 잠깐 떴다 사라지는 알림. 화면 상단 중앙 한 곳에서만 뜬다.
     * 페이지에 이미 있는 알림 자리(#toast)를 그대로 쓴다 — 알림이 두 종류가 되면
     * 학생은 어디를 봐야 할지 알 수 없다.
     */
    let toastTimer = null;
    const toast = (text, type) => {
        let box = document.getElementById('toast');
        if (!box) {
            box = document.createElement('div');
            box.id = 'toast';
            box.setAttribute('role', 'status');
            box.setAttribute('aria-live', 'polite');
            document.body.appendChild(box);
        }
        box.textContent = text;
        box.className = `app-toast show${type ? ` ${type}` : ''}`;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => box.classList.remove('show'), 2600);
    };

    /**
     * 브라우저가 자동 복사를 막는 경우(사용자 조작이 프레임 안에서 일어났으므로
     * 바깥에는 그 권한이 없을 수 있다) 직접 고를 수 있게 펼쳐 준다.
     */
    const showCopyBox = (text) => {
        const wrap = document.createElement('div');
        wrap.className = 'lightbox';
        wrap.innerHTML = `
            <div class="lightbox-body copy-box">
                <button class="lightbox-close" type="button" aria-label="닫기">
                    <i class="bi bi-x-lg" aria-hidden="true"></i>
                </button>
                <div class="copy-head">복사가 자동으로 되지 않았어요. 아래 내용을 직접 복사해 줘.</div>
                <textarea readonly></textarea>
            </div>`;
        const area = wrap.querySelector('textarea');
        area.value = text;
        const close = () => wrap.remove();
        wrap.addEventListener('click', (event) => { if (event.target === wrap) close(); });
        wrap.querySelector('.lightbox-close').addEventListener('click', close);
        document.body.appendChild(wrap);
        area.focus();
        area.select();
    };

    /** 프레임 안에서 넘어온 복사 요청을 여기서 실제로 처리한다. */
    const copyFromDemo = async (text) => {
        if (!text) { toast('복사할 내용이 없어요.', 'error'); return; }
        try {
            await navigator.clipboard.writeText(text);
            toast('결과를 복사했어요. 채팅에 붙여넣어 알려줘.', 'success');
        } catch (_) {
            showCopyBox(text);
        }
    };

    // 안쪽 프레임이 보내오는 것들. 보낸 주인이 맞는지 창으로 확인한다.
    window.addEventListener('message', (event) => {
        const data = event.data;
        if (!data || typeof data !== 'object') return;
        const frames = [...document.querySelectorAll('.demo-frame')];
        const from = frames.find((frame) => frame.contentWindow === event.source);
        if (!from) return;   // 우리가 띄운 화면이 아니면 듣지 않는다

        const height = Number(data.demoHeight);
        if (height && Number.isFinite(height)) {
            from.style.height = `${Math.min(Math.max(height, 80), 620)}px`;
        }
        if (typeof data.demoCopy === 'string') copyFromDemo(data.demoCopy);
    });

    /**
     * 생성 도중 서버가 던진 질문(그림 계획 확인). 폴링이 1.2초마다 오지만
     * 카드는 질문 id가 바뀔 때만 새로 그린다 — 입력 중인 글이 지워지면 안 된다.
     */
    let planQuestionCard = null;
    let planQuestionId = null;

    const KIND_LABEL = { chart: '그래프', image: '사진' };

    const showPlanQuestion = (question, onAnswer) => {
        // 질문이 걷혔으면(답했거나 시간 초과) 카드도 걷는다.
        if (!question) {
            if (planQuestionCard) { planQuestionCard.remove(); planQuestionCard = null; }
            planQuestionId = null;
            return;
        }
        if (question.id === planQuestionId) return;   // 이미 떠 있다
        planQuestionId = question.id;
        planQuestionCard?.remove();

        const div = document.createElement('div');
        div.className = 'message-row plan-q';
        div.innerHTML = `
            <div class="role-avatar ai"><i class="bi bi-images"></i></div>
            <div class="message-content">
                <div class="message-name">그림 계획 확인</div>
                <div class="plan-q-card">
                    <div class="plan-q-title">${esc(question.title || '이 그림들로 갈까?')}</div>
                    <ul class="plan-q-list">${(question.figures || []).map((figure) => `
                        <li><span class="k" data-kind="${esc(figure.kind || '')}">${
                            esc(KIND_LABEL[figure.kind] || figure.kind || '')}</span>
                            <span class="c">Figure ${esc(String(figure.no ?? ''))}. ${
                            esc(figure.caption || '')}</span></li>`).join('')}</ul>
                    <div class="plan-q-actions">
                        <button class="plan-q-ok" type="button">이대로 진행</button>
                        <input class="plan-q-input" type="text"
                               placeholder="바꾸고 싶은 점을 적어줘 (예: 2번은 실제 앱 화면으로)">
                        <button class="plan-q-send" type="button">요청 반영</button>
                    </div>
                </div>
            </div>`;

        const finish = (label) => {
            div.querySelector('.plan-q-actions').outerHTML =
                `<div class="plan-q-done"><i class="bi bi-check-lg"></i> ${esc(label)}</div>`;
        };
        div.querySelector('.plan-q-ok').addEventListener('click', () => {
            finish('이대로 진행할게');
            onAnswer(question.id, '');
        });
        const send = () => {
            const text = div.querySelector('.plan-q-input').value.trim();
            finish(text ? `요청 보냈어: ${text}` : '이대로 진행할게');
            onAnswer(question.id, text);
        };
        div.querySelector('.plan-q-send').addEventListener('click', send);
        div.querySelector('.plan-q-input').addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); send(); }
        });

        stream.appendChild(div);
        planQuestionCard = div;
        const scroller = document.getElementById('scrollContainer');
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
    };

    const io = {
        showUser: (text) => row('user', md(text)),
        showPlanQuestion,
        showAI: (text, opts = {}) => {
            const images = opts.images || [];
            const bubble = row('ai', md(text) + (images.length ? imageStrip(images) : ''),
                               opts.badge || '');
            if (opts.error) bubble.classList.add('msg-error');
            // 직접 눌러볼 화면이 있으면 글 바로 아래에 띄운다(동작 버튼보다 위).
            if (opts.demo && opts.demo.html) {
                bubble.querySelector('.message-content').appendChild(demoCard(opts.demo));
            }
            // 측정값을 적을 표. 잰 값을 문장으로 받아 적게 하지 않는다.
            if (opts.measureTable && (opts.measureTable.columns || []).length
                    && opts.onMeasure) {
                bubble.querySelector('.message-content').appendChild(
                    measureCard(opts.measureTable, opts.onMeasure));
            }
            // 답이 마음에 들지 않으면 같은 질문으로 다시 만들 수 있다.
            // 버튼은 마지막 답변에만 있어야 하므로, 새 답이 오면 이전 버튼부터 걷어낸다.
            // (data-regen만 지운다 — 보고서 카드의 버튼들까지 지우면 안 된다.)
            if (opts.onRegenerate) {
                stream.querySelectorAll('.msg-actions[data-regen]')
                    .forEach((element) => element.remove());
                const actions = document.createElement('div');
                actions.className = 'msg-actions';
                actions.dataset.regen = '1';
                actions.innerHTML = `
                    <button class="act-btn" type="button">
                        <i class="bi bi-arrow-repeat" aria-hidden="true"></i> 다시 생성
                    </button>`;
                actions.querySelector('.act-btn').addEventListener('click', () => {
                    actions.remove();
                    opts.onRegenerate();
                });
                bubble.querySelector('.message-content').appendChild(actions);
            }
            // 서버가 확인했더라도 브라우저에서 막히는 이미지가 있다(핫링크 차단 등).
            // 깨진 칸을 남기느니 그 자리를 지운다.
            bubble.querySelectorAll('.img-card img').forEach((image) => {
                image.addEventListener('error', () => {
                    const card = image.closest('.img-card');
                    const strip = card && card.parentElement;
                    card?.remove();
                    if (strip && !strip.children.length) strip.remove();
                }, { once: true });
            });
            bubble.querySelectorAll('.img-card').forEach((card) => {
                card.addEventListener('click', () => openLightbox(card));
            });
            return bubble;
        },
        showChoices: (choices, onPick) => choiceRow(choices, onPick),
        showThinking: () => { thinkingRow = row('ai', DOTS); },
        /**
         * 지금 무엇을 하는 중인지. 생각하는 것과 찾는 것은 다른 일이라 다르게 보인다.
         * 문서 생성처럼 단계가 있는 작업은 점검표로 그려, 하나씩 끝나는 게 보이게 한다.
         */
        showStage: (stage, label, steps) => {
            if (!thinkingRow) return;
            const body = thinkingRow.querySelector('.markdown-body');
            const name = thinkingRow.querySelector('.message-name');

            if (Array.isArray(steps) && steps.length) {
                const ICON = {
                    pending: '<span class="st-pin"></span>',
                    running: '<i class="bi bi-arrow-repeat st-spin"></i>',
                    done: '<i class="bi bi-check-lg"></i>',
                    failed: '<i class="bi bi-x-lg"></i>',
                };
                body.innerHTML = `
                    <div class="steps-card">${steps.map((step) => `
                        <div class="step" data-state="${esc(step.status || 'pending')}">
                            <span class="st-ico">${ICON[step.status] || ICON.pending}</span>
                            <span class="st-label">${esc(step.label || '')}</span>
                            ${step.note ? `<span class="st-note">${esc(step.note)}</span>` : ''}
                        </div>`).join('')}</div>`;
                if (name) name.textContent = '문서 만드는 중';
                return;
            }

            const searching = stage === 'searching' || stage === 'searching_images';
            thinkingRow.classList.toggle('is-searching', searching);
            if (!searching) {
                body.innerHTML = DOTS;
                if (name) name.textContent = '함께하는 Agent';
                return;
            }
            const images = stage === 'searching_images';
            body.innerHTML = `
                <span class="searching">
                    <i class="bi bi-${images ? 'images' : 'search'}" aria-hidden="true"></i>
                    <span class="q">${esc(label || (images ? '이미지' : '자료'))}</span>
                </span>`;
            if (name) name.textContent = images ? '이미지 찾는 중' : '웹에서 찾는 중';
        },
        hideThinking: () => { if (thinkingRow) { thinkingRow.remove(); thinkingRow = null; } },
        onChanged: () => { /* 메인 채팅에는 다시 그릴 화면이 없다 */ },
        showHeader: (info) => headerCard(info),
        showPhaseBar: (phases, current) => setPhaseBar(phases, current),
        showResume: (info, onExpand) => resumeCard(info, onExpand),
        showReport: (file, title, opts) => reportCard(file, title, opts),
        toast: (text, type) => toast(text, type),
    };

    const submit = () => {
        const text = (input.value || '').trim();
        if (!text) return;
        input.value = '';
        input.style.height = 'auto';
        if (mode === 'experiment') window.ExperimentChat.send(text, io);
        else window.ResearchChat.send(text, io);
    };

    // capture 단계에서 먼저 잡아 index.js로 넘어가지 않게 한다.
    sendBtn.addEventListener('click', (event) => {
        if (!active) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        submit();
    }, true);

    input.addEventListener('keydown', (event) => {
        if (!active || event.key !== 'Enter' || event.shiftKey) return;
        // 연구 서사가 진행 중이면 Enter는 전부 이쪽이 가져간다.
        // 조합 중 Enter를 그냥 흘려보내면 index.js 핸들러가 대신 반응해
        // 빈 응답 자리(로딩 스켈레톤)가 하나 더 생긴다.
        event.stopImmediatePropagation();
        if (event.isComposing) return;  // 글자 확정만 하고 끝낸다
        event.preventDefault();
        submit();
    }, true);

    /**
     * 채팅 옆의 작은 로드맵. 6단계 중 어디까지 왔는지만 보여주고,
     * 누르면 /research로 넘어간다. 글은 최소로 두고 점과 선으로만 읽히게 한다.
     */
    const STAGE_ORDER = ['onboarding', 'themes', 'select_theme', 'framework',
                         'subjects', 'experiments', 'done'];
    const renderRoadmapPeek = (next) => {
        const peek = document.getElementById('roadmapPeek');
        const track = document.getElementById('roadmapPeekTrack');
        const count = document.getElementById('roadmapPeekCount');
        if (!peek || !track) return;

        const current = Math.max(0, STAGE_ORDER.indexOf(next.stage));
        const finished = next.stage === 'done' ? STAGE_ORDER.length : current;

        track.innerHTML = STAGE_ORDER.map((stage, index) => {
            const state = index < current ? 'done' : (index === current ? 'current' : 'locked');
            return `<span class="peek-node" data-state="${next.stage === 'done' ? 'done' : state}"></span>`;
        }).join('');
        if (count) count.textContent = `${finished} / ${STAGE_ORDER.length}`;
        peek.hidden = false;

        // 아래 화살표를 누르면 이 카드가 무엇인지 알려준다.
        const help = document.getElementById('roadmapPeekHelp');
        const hint = document.getElementById('roadmapPeekHint');
        if (help && hint && !help.dataset.bound) {
            help.dataset.bound = '1';
            help.addEventListener('click', () => {
                const open = help.getAttribute('aria-expanded') === 'true';
                help.setAttribute('aria-expanded', String(!open));
                hint.hidden = open;
            });
        }
    };

    /**
     * 사이드바 사용량 게이지.
     * Runner가 주는 rateLimit의 필드 이름을 확정할 수 없어, 흔한 표기를 모두 훑고
     * 퍼센트를 못 구하면 막대를 채우지 않는다(틀린 수치를 보이느니 비워 둔다).
     */
    const readUsagePercent = (limit) => {
        if (!limit || typeof limit !== 'object') return null;
        const source = limit.primary && typeof limit.primary === 'object' ? limit.primary : limit;
        const num = (...keys) => {
            for (const key of keys) {
                const value = source[key];
                if (typeof value === 'number' && Number.isFinite(value)) return value;
            }
            return null;
        };
        const direct = num('used_percent', 'usedPercent', 'percent_used', 'percentUsed', 'percent');
        if (direct !== null) return Math.max(0, Math.min(100, direct));
        const used = num('used', 'used_tokens', 'usedTokens', 'consumed');
        const total = num('limit', 'total', 'max', 'quota', 'allowed');
        if (used !== null && total) return Math.max(0, Math.min(100, (used / total) * 100));
        const left = num('remaining', 'remaining_tokens', 'remainingTokens');
        if (left !== null && total) return Math.max(0, Math.min(100, ((total - left) / total) * 100));
        return null;
    };

    const renderUsage = async () => {
        const box = document.getElementById('usageBox');
        if (!box) return;
        const pctEl = document.getElementById('usagePct');
        const fillEl = document.getElementById('usageFill');
        const noteEl = document.getElementById('usageNote');

        const paint = (level, pctText, width, note) => {
            box.dataset.level = level;
            if (pctEl) pctEl.textContent = pctText;
            if (fillEl) fillEl.style.width = `${width}%`;
            if (noteEl) noteEl.textContent = note;
        };

        try {
            // 첫 호출은 <head> 프리페치가 이미 받아 둔 것을 쓴다. 이후 갱신은 새로 받는다.
            let data = null;
            const boot = window.__boot || {};
            if (boot.codex) {
                const pre = await boot.codex;
                boot.codex = null;
                if (pre && pre.ok) data = pre.body;
            }
            if (!data) {
                const res = await fetch('/api/auth/codex/status', { credentials: 'same-origin' });
                if (!res.ok) { paint('idle', '–', 0, '로그인하면 표시돼요'); return; }
                data = await res.json();
            }
            if (!data.configured) { paint('idle', '–', 0, 'AI 기능이 꺼져 있어요'); return; }
            const connection = data.connection || {};
            if (connection.status !== 'connected') {
                paint('idle', '–', 0, 'ChatGPT를 연결하면 표시돼요');
                return;
            }
            const percent = readUsagePercent(connection.rate_limit);
            if (percent === null) {
                paint('idle', '–', 0, connection.plan_type ? `${connection.plan_type} 플랜` : '사용량 정보 없음');
                return;
            }
            const level = percent >= 100 ? 'over' : (percent >= 80 ? 'warn' : 'ok');
            const note = level === 'over'
                ? '한도를 다 썼어요. 초기화 후 다시 시도하세요'
                : (connection.plan_type ? `${connection.plan_type} 플랜` : '이번 주기 사용량');
            paint(level, `${Math.round(percent)}%`, percent, note);
        } catch (_) {
            paint('idle', '–', 0, '사용량을 불러오지 못했어요');
        }
    };

    /**
     * 게이지를 다시 그려야 하는 순간들.
     *  - ChatGPT 연결이 끝난 직후 (전에는 새로고침해야만 반영됐다)
     *  - 인증을 다른 창에서 마치고 이 탭으로 돌아왔을 때
     *  - 대화 한 턴이 끝나 사용량이 움직였을 때
     * 탭 전환이 잦아도 서버를 두드리지 않도록 3초 안의 중복은 묶는다.
     */
    let usageAt = 0;
    const refreshUsage = (immediate) => {
        const now = Date.now();
        if (!immediate && now - usageAt < 3000) return;
        usageAt = now;
        renderUsage();
        // 연결 직후에는 러너가 아직 사용량을 모른다. 잠시 뒤 한 번 더 확인한다.
        if (immediate) setTimeout(renderUsage, 5000);
    };
    window.addEventListener('research:usage-refresh', () => refreshUsage(true));
    window.addEventListener('focus', () => refreshUsage(false));
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') refreshUsage(false);
    });

    // 사용량 초과를 만나면 게이지도 곧바로 그 사실을 반영해야 한다.
    window.addEventListener('research:usage-limit', () => {
        const box = document.getElementById('usageBox');
        if (!box) return;
        box.dataset.level = 'over';
        const pctEl = document.getElementById('usagePct');
        const fillEl = document.getElementById('usageFill');
        const noteEl = document.getElementById('usageNote');
        if (pctEl) pctEl.textContent = '100%';
        if (fillEl) fillEl.style.width = '100%';
        if (noteEl) noteEl.textContent = '한도를 다 썼어요. 초기화 후 다시 시도하세요';
    });

    /** 주소가 지목한 대화방. 없으면 지금 이어서 할 설계 대화를 연다. */
    const askedChat = new URLSearchParams(location.search).get('chat');

    const openAskedChat = async (session) => {
        if (!session) return false;

        if (session.folder === '실험' && session.plan_id) {
            mode = 'experiment';
            active = true;
            const ready = await window.ExperimentChat.open(session.plan_id, io);
            if (!ready) { input.disabled = true; sendBtn.disabled = true; }
            return true;
        }
        if (session.folder === '설계') {
            mode = 'design';
            active = true;
            await window.ResearchChat.opener(io, session.id);
            return true;
        }
        // 폴더가 없는 옛 대화(레거시 문서 생성)는 더 이상 열 수 없다.
        return false;
    };

    /**
     * 로그인이 안 된 상태. 조용히 빈 화면을 두지 않는다 — 주소가 바뀌어
     * (127.0.0.1 ↔ 192.168.x) 쿠키가 새로 시작된 경우, 학생 눈에는 기록이
     * "사라진 것"으로 보이기 때문이다. 연결하면 같은 ChatGPT 계정으로
     * 같은 사용자가 되므로 대화·실험·로드맵이 그대로 돌아온다.
     */
    /**
     * 로그인이 없을 때. 로그인 화면으로 보낸다.
     *
     * 전에는 여기서 'ChatGPT 연결하기'를 내밀었다. 연결이 곧 로그인이었기 때문인데,
     * 그래서 같은 ChatGPT 계정을 연결한 사람이 남의 기록을 그대로 열어볼 수 있었다.
     * ChatGPT는 사용 한도를 빌려오는 것일 뿐이고, 신원은 앱 로그인이 정한다.
     */
    const offerLogin = () => {
        active = true;
        io.showAI('아직 로그인이 안 되어 있어. 로그인하면 하던 대화와 실험 기록이 그대로 돌아와.\n\n'
                  + 'ChatGPT 연결은 로그인한 다음에 해. 그건 네 계정의 사용량을 쓰기 위한 것이고, '
                  + '로그인 수단은 아니야.');
        io.showChoices({ options: [{ label: '로그인하러 가기' }] },
                       () => { location.href = '/login'; });
        // 다른 탭에서 로그인을 마치고 돌아왔을 수 있다. 살아나면 처음부터 다시 그린다.
        // (HISTORY·로드맵·설계 대화가 전부 로그인 이후 상태로 바뀌어야 한다.)
        const wait = setInterval(async () => {
            try {
                const res = await fetch('/api/research/next', { credentials: 'same-origin' });
                if (res.ok) { clearInterval(wait); location.reload(); }
            } catch (_) { /* 다음 주기에 재시도 */ }
        }, 3000);
    };

    // 페이지가 뜨는 즉시 시작한다. 첫 화면에 필요한 요청은 <head>의 프리페치가
    // 스크립트 파싱과 동시에 이미 보내 뒀다(window.__boot). 여기서는 받기만 한다.
    (async () => {
        renderUsage();
        try {
            const boot = window.__boot || {};
            const [pre, askedSession] = await Promise.all([
                boot.next || Promise.resolve(null),
                boot.session || Promise.resolve(null),
            ]);
            let status = pre && pre.status;
            let next = pre && pre.body;
            if (!pre) {   // 프리페치가 없는 페이지(/research 등)에서는 직접 부른다.
                const res = await fetch('/api/research/next', { credentials: 'same-origin' });
                status = res.status;
                next = res.ok ? await res.json() : null;
            }
            if (status === 401) { offerLogin(); return; }
            if (!next) return;
            renderRoadmapPeek(next);

            // 로드맵에서 「실험 진행」을 누르면 여기로 온다. 그 방을 그대로 연다.
            if (askedChat && await openAskedChat(askedSession)) return;

            // 입력은 항상 이쪽이 가져간다. 예전에는 index.js가 문서 생성 요청을
            // 받았지만 그 경로가 사라져서, 여기서 안 받으면 전송이 먹통이 된다.
            active = true;
            if (next.stage === 'done') return;
            window.ResearchChat.opener(io, null, next);
        } catch (_) { /* 조용히 넘어간다 */ }
    })();
})();

/**
 * /research의 미니 채팅.
 *
 * 로드맵을 보면서 "2학년은 더 실험 위주로" 같은 요구를 말하면 AI가 되묻고 반영한다.
 * 데이터가 바뀌면 로드맵을 다시 그린다.
 */
(() => {
    'use strict';

    const panel = document.getElementById('miniChat');
    const head = document.getElementById('miniHead');
    const body = document.getElementById('miniBody');
    const form = document.getElementById('miniForm');
    const input = document.getElementById('miniInput');
    if (!panel || !body || !form || !window.ResearchChat) return;

    let thinking = null;
    let opened = false;

    const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));

    const md = (text) => window.ResearchChat.linkify(esc(text))
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');

    const bubble = (role, html) => {
        const div = document.createElement('div');
        div.className = `mini-msg ${role === 'user' ? 'me' : 'ai'}`;
        div.innerHTML = html;
        body.appendChild(div);
        body.scrollTop = body.scrollHeight;
        return div;
    };

    const io = {
        showUser: (text) => bubble('user', md(text)),
        showAI: (text) => bubble('ai', md(text)),
        showChoices: (choices, onPick) => {
            const wrap = document.createElement('div');
            wrap.className = 'mini-choices';
            choices.options.forEach((option) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'mini-choice';
                button.textContent = option.label;
                button.addEventListener('click', () => { wrap.remove(); onPick(option); });
                wrap.appendChild(button);
            });
            body.appendChild(wrap);
            body.scrollTop = body.scrollHeight;
            return wrap;
        },
        showThinking: () => { thinking = bubble('ai', '<span class="mini-dots"><i></i><i></i><i></i></span>'); },
        hideThinking: () => { if (thinking) { thinking.remove(); thinking = null; } },
        // 계획이 바뀌었으면 로드맵을 새로 읽는다.
        onChanged: () => { if (window.researchReload) window.researchReload(); },
    };

    const expand = () => {
        if (!panel.classList.contains('collapsed')) return;
        panel.classList.remove('collapsed');
        if (!opened) {
            opened = true;
            // 메인 채팅에서 이어온 대화가 있으면 그대로, 없으면 서버 기록을 불러온다.
            const past = window.ResearchChat.history;
            if (past.length) {
                past.forEach((turn) => bubble(turn.role === 'user' ? 'user' : 'ai', md(turn.text)));
            } else {
                window.ResearchChat.opener(io);
            }
        }
        input.focus();
    };

    head.addEventListener('click', () => {
        if (panel.classList.contains('collapsed')) expand();
        else panel.classList.add('collapsed');
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const text = (input.value || '').trim();
        if (!text) return;
        input.value = '';
        input.style.height = 'auto';
        window.ResearchChat.send(text, io);
    });

    input.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        form.requestSubmit();
    });

    // 입력 높이를 내용에 맞춘다.
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 90)}px`;
    });
})();
