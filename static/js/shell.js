/**
 * 앱 셸 — 화면 전체가 공유하는 것들만 남긴 파일.
 *
 * 테마 / 사이드바 / 알림(토스트) / 계정(로그인·프로필) / 리로스쿨 연동 / 과제 캘린더.
 *
 * 예전에는 이 파일이 문서 생성 UI까지 전부 들고 있었다(5600줄). 그 경로는
 * DOCX·HTML을 만들어 보여주던 것이라 진짜 HWP가 아니었고, 2026-07-29에 걷어냈다.
 * 걷어낸 코드는 legacy/hwp_ui/ 아래에 그대로 남겨 뒀다.
 *
 * 지금 대화는 guide.js(설계·실험)가, 사이드바 목록은 history.js가, 첫 화면은
 * home.js가 그린다. 이 파일은 그 셋이 올라앉을 껍데기만 맡는다.
 */
document.addEventListener('DOMContentLoaded', () => {
    const THEME_STORAGE_KEY = 'docAgentTheme';
    const THEME_COLORS = {
        light: '#F8FAFC',
        dark: '#0B0F17'
    };

    // DOM 요소 캐싱 (에러 방지를 위해 Optional Chaining 사용)
    const els = {
        // Views
        homeView: document.getElementById('homeView'),
        resultView: document.getElementById('resultView'),
        chatStream: document.getElementById('chatStream'),
        scrollContainer: document.getElementById('scrollContainer'),

        // Inputs & Buttons
        userRequest: document.getElementById('userRequest'),
        btnSend: document.getElementById('btnSend'),
        iconSend: document.getElementById('iconSend'),
        spinnerSend: document.getElementById('spinnerSend'),
        
        // Toggles & Sidebar
        sidebar: document.getElementById('sidebar'),
        sidebarOverlay: document.getElementById('sidebarOverlay'),
        btnMenu: document.getElementById('btnMenu'),
        btnDesktopSidebarToggle: document.getElementById('btnDesktopSidebarToggle'),
        
        // Modals
        modalAuth: document.getElementById('modalAuth'),
        modalLogin: document.getElementById('modalLogin'),
        modalProfile: document.getElementById('modalProfile'),
        profileModalBox: document.getElementById('profileModalBox'),
        modalCalendar: document.getElementById('modalCalendar'),
        btnOpenAuth: document.getElementById('btnOpenAuth'),
        btnAuthToggle: document.getElementById('btnAuthToggle'),
        closeProfile: document.getElementById('closeProfile'),
        profileAvatar: document.getElementById('profileAvatar'),
        profileName: document.getElementById('profileName'),
        profileEmail: document.getElementById('profileEmail'),
        profileProvider: document.getElementById('profileProvider'),
        profileLogin: document.getElementById('profileLogin'),
        profileLogout: document.getElementById('profileLogout'),
        
        // Riro Inputs
        riroSchool: document.getElementById('riroSchool'),
        riroId: document.getElementById('riroId'),
        riroPw: document.getElementById('riroPw'),
        btnLoginAction: document.getElementById('btnLoginAction'),
        riroSchoolLabel: document.getElementById('riroSchoolLabel'),
        riroStatus: document.getElementById('riroStatus'),
        riroFindId: document.getElementById('riroFindId'),
        riroFindPw: document.getElementById('riroFindPw'),
        riroTabStudent: document.getElementById('riroTabStudent'),
        riroTabParent: document.getElementById('riroTabParent'),
        riroAuthNotice: document.getElementById('riroAuthNotice'),
        riroTab1Img: document.getElementById('riroTab1Img'),
        riroTab2Img: document.getElementById('riroTab2Img'),
        riroNoneSignup: document.getElementById('riroNoneSignup'),

        // Auth Inputs
        authName: document.getElementById('authName'),
        authStudentNumber: document.getElementById('authStudentNumber'),
        authEmail: document.getElementById('authEmail'),
        authPassword: document.getElementById('authPassword'),
        btnAuthLogin: document.getElementById('btnAuthLogin'),
        btnAuthRegister: document.getElementById('btnAuthRegister'),
        btnAuthGoogle: document.getElementById('btnAuthGoogle'),
        authStatus: document.getElementById('authStatus'),
        userNameLabel: document.getElementById('userNameLabel'),
        userEmailLabel: document.getElementById('userEmailLabel'),
        userAvatar: document.getElementById('userAvatar'),
        userProfile: document.getElementById('userProfile'),
        
        // New Chat Button
        btnNewChat: document.getElementById('btnNewChat'),
        
        // Etc
        toast: document.getElementById('toast'),
    };

    // 상태 관리 (State)
    // 이 파일이 들고 있는 상태는 이것뿐이다. 문서 생성·템플릿·캔버스 상태는
    // 그 기능과 함께 사라졌다(legacy/hwp_ui/ 참고).
    const state = {
        isGenerating: false,
        riroEvents: [],
        riroLoggedIn: false,
        user: null,
        authChecked: false,
    };

    const theme = {
        meta: document.querySelector('meta[name="theme-color"]'),
        toggles: Array.from(document.querySelectorAll('[data-theme-toggle]')),
        icons: Array.from(document.querySelectorAll('[data-theme-icon]'))
    };

    const applyTheme = (themeName, { persist = true } = {}) => {
        const resolved = themeName === 'dark' ? 'dark' : 'light';
        document.body.dataset.theme = resolved;
        document.documentElement.style.colorScheme = resolved;
        if (theme.meta) theme.meta.setAttribute('content', THEME_COLORS[resolved]);
        theme.toggles.forEach((btn) => {
            btn.setAttribute('aria-pressed', resolved === 'dark' ? 'true' : 'false');
        });
        theme.icons.forEach((icon) => {
            icon.classList.toggle('bi-sun', resolved === 'dark');
            icon.classList.toggle('bi-moon-stars', resolved !== 'dark');
        });
        if (persist) localStorage.setItem(THEME_STORAGE_KEY, resolved);
    };

    const toggleTheme = () => {
        const current = document.body.dataset.theme === 'dark' ? 'dark' : 'light';
        applyTheme(current === 'dark' ? 'light' : 'dark');
    };

    const initTheme = () => {
        const stored = localStorage.getItem(THEME_STORAGE_KEY);
        const hasStored = stored === 'dark' || stored === 'light';
        if (hasStored) {
            applyTheme(stored, { persist: true });
            return;
        }
        applyTheme('light', { persist: false });
    };

    const getPremiumState = () => {
        const hostname = window.location.hostname.toLowerCase();
        const email = (state.user?.email || '').toLowerCase();
        const matchesDomain = hostname === 'okgwa.hs.jne.kr' || hostname.endsWith('.okgwa.hs.jne.kr');
        const matchesEmail = email.endsWith('@okgwa.hs.jne.kr');
        const tierValue = String(state.user?.tier || state.user?.plan || state.user?.subscription || '').toLowerCase();
        const hasPremiumFlag = state.user?.is_premium === true;
        const hasTier = ['premium', 'plus', 'pro'].includes(tierValue);
        const isPremium = hasPremiumFlag || hasTier || matchesDomain || matchesEmail;

        return { matchesDomain, matchesEmail, isPremium };
    };

    const applyAccountUIState = () => {
        const { matchesDomain, matchesEmail, isPremium } = getPremiumState();
        const shouldHideUpgrade = matchesDomain || matchesEmail;

        document.querySelectorAll('[data-upgrade-item]').forEach((item) => {
            item.classList.toggle('hidden', shouldHideUpgrade);
            item.setAttribute('aria-hidden', shouldHideUpgrade ? 'true' : 'false');
        });

        document.querySelectorAll('[data-premium-badge]').forEach((badge) => {
            badge.classList.toggle('hidden', !isPremium);
            badge.setAttribute('aria-hidden', isPremium ? 'false' : 'true');
        });
    };

    // ============================================================ 
    // 1. 핵심 로직: 화면 렌더링 (View)
    // ============================================================ 

    // 마크다운 변환기 (에러 방지 래퍼)
    const parseMarkdown = (text) => {
        if (!text) return '';
        try {
            // 1. 최신 marked.parse() 시도
            if (window.marked && typeof window.marked.parse === 'function') {
                const result = window.marked.parse(text);
                // 동기적으로 문자열이 반환된 경우만 사용
                if (typeof result === 'string') return result;
            }
            // 2. 구버전 marked() 함수 시도
            if (typeof window.marked === 'function') {
                return window.marked(text);
            }
        } catch (e) { 
            console.warn('Marked lib parsing error:', e); 
        }
        
        // Fallback: HTML 이스케이프 후 줄바꿈 처리
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\n/g, '<br>');
    };

    const safeJsonParse = (text) => {
        if (!text) return null;
        try {
            return JSON.parse(text);
        } catch {
            return null;
        }
    };

    const parseJsonResponse = async (response) => {
        const text = await response.text();
        const data = safeJsonParse(text);
        if (data) return data;
        if (!text) return { success: false, error: `HTTP ${response.status}` };
        return { success: false, error: text };
    };

    const postFormDataViaXHR = (url, formData) =>
        new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', url, true);
            xhr.responseType = 'text';
            xhr.onload = () => {
                const data = safeJsonParse(xhr.responseText || '');
                resolve({
                    ok: xhr.status >= 200 && xhr.status < 300,
                    status: xhr.status,
                    data: data || { success: false, error: xhr.responseText || `HTTP ${xhr.status}` }
                });
            };
            xhr.onerror = () => reject(new TypeError('Failed to fetch'));
            xhr.send(formData);
        });

    // Safari/모바일에서 fetch FormData 업로드가 실패하는 경우 XHR로 폴백
    const postFormData = async (url, formData) => {
        try {
            const response = await fetch(url, { method: 'POST', body: formData });
            const data = await parseJsonResponse(response);
            return { ok: response.ok, status: response.status, data };
        } catch (err) {
            const message = String(err && err.message ? err.message : '');
            if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {
                return await postFormDataViaXHR(url, formData);
            }
            throw err;
        }
    };


    // ============================================================
    // 3. 보조 기능 (이미지, UI 상태 등)
    // ============================================================

    const updateSendButtonState = (isLoading = state.isGenerating) => {
        if (!els.btnSend) return;
        const hasInput = !!(els.userRequest && els.userRequest.value.trim());
        const loading = !!isLoading;

        els.btnSend.classList.toggle('active', hasInput && !loading);
        els.btnSend.classList.toggle('loading', loading);
        els.btnSend.disabled = !hasInput && !loading;
        els.btnSend.setAttribute('aria-busy', loading ? 'true' : 'false');
        els.btnSend.setAttribute('aria-disabled', (!hasInput || loading) ? 'true' : 'false');

        if (els.iconSend) els.iconSend.classList.toggle('hidden', loading);
        if (els.spinnerSend) els.spinnerSend.classList.toggle('hidden', !loading);
    };

    const setLoadingState = (loading) => {
        updateSendButtonState(loading);
    };

    // 알림은 화면 상단 중앙 한 곳에서만 뜬다(.app-toast). 저장·복사·오류가 모두 같은 자리다.
    let toastTimer = null;
    const showToast = (msg, type='info') => {
        if (!els.toast) return;
        els.toast.textContent = msg;
        els.toast.className = `app-toast show${type && type !== 'info' ? ` ${type}` : ''}`;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { els.toast.classList.remove('show'); }, 3000);
    };

    // ============================================================
    // 인증 상태 관리
    // ============================================================

    const resolveProviderLabel = (user) => {
        if (!user || !user.id) return 'Guest';
        const id = String(user.id);
        if (id.startsWith('google_')) return 'Google 계정';
        if (id.startsWith('kakao_')) return 'Kakao 계정';
        if (id.startsWith('naver_')) return 'Naver 계정';
        if (id.startsWith('admin_')) return 'Admin 계정';
        if (id.startsWith('demo_')) return 'Demo 계정';
        if (id.startsWith('user_')) return 'Local 계정';
        return '계정';
    };

    const renderUserProfile = () => {
        const name = state.user?.name || 'Guest';
        const email = state.user?.email || '로그인 필요';
        const initial = (name || email || 'G').trim().charAt(0).toUpperCase() || 'G';
        const picture = state.user?.picture || '';
        const providerLabel = resolveProviderLabel(state.user);
        const { isPremium } = getPremiumState();

        if (els.userNameLabel) els.userNameLabel.textContent = name;
        if (els.userEmailLabel) els.userEmailLabel.textContent = email;
        if (els.userAvatar) {
            if (picture) {
                els.userAvatar.classList.add('has-photo');
                els.userAvatar.style.backgroundImage = `url("${picture}")`;
                els.userAvatar.textContent = '';
            } else {
                els.userAvatar.classList.remove('has-photo');
                els.userAvatar.style.backgroundImage = '';
                els.userAvatar.textContent = initial;
            }
        }
        if (els.profileName) els.profileName.textContent = name;
        if (els.profileEmail) els.profileEmail.textContent = email;
        if (els.profileProvider) {
            if (isPremium) {
                els.profileProvider.textContent = '프리미엄 계정';
                els.profileProvider.classList.add('profile-provider--premium');
            } else {
                els.profileProvider.textContent = providerLabel;
                els.profileProvider.classList.remove('profile-provider--premium');
            }
        }
        if (els.profileAvatar) {
            if (picture) {
                els.profileAvatar.classList.add('has-photo');
                els.profileAvatar.style.backgroundImage = `url("${picture}")`;
                els.profileAvatar.textContent = '';
            } else {
                els.profileAvatar.classList.remove('has-photo');
                els.profileAvatar.style.backgroundImage = '';
                els.profileAvatar.textContent = initial;
            }
        }
        if (els.profileLogin) {
            els.profileLogin.style.display = state.user ? 'none' : 'flex';
        }
        if (els.profileLogout) {
            els.profileLogout.style.display = state.user ? 'flex' : 'none';
        }
        if (els.btnAuthToggle) {
            els.btnAuthToggle.innerHTML = state.user
                ? '<i class="bi bi-box-arrow-right"></i>'
                : '<i class="bi bi-box-arrow-in-right"></i>';
            els.btnAuthToggle.title = state.user ? '로그아웃' : '로그인';
        }

        // Toggle Login Button visibility
        if (els.btnOpenAuth) {
            els.btnOpenAuth.style.display = state.user ? 'none' : 'flex';
        }

        applyAccountUIState();
    };

    const getSafeNextPath = () => {
        const next = window.location.pathname + window.location.search;
        if (!next.startsWith('/') || next.startsWith('//')) return '/';
        return next;
    };

    const withNextParam = (base) => {
        const next = getSafeNextPath();
        const joiner = base.includes('?') ? '&' : '?';
        return `${base}${joiner}next=${encodeURIComponent(next)}`;
    };

    const updateAuthLinks = () => {
        if (els.btnAuthGoogle) {
            els.btnAuthGoogle.href = withNextParam('/api/auth/social/google');
        }
    };

    const setAuthStatus = (msg, type='muted') => {
        if (!els.authStatus) return;
        // 카드가 흰 배경이라 밝은 계열 대신 /login과 같은 대비의 색을 쓴다
        const colors = {
            error: '#EF4444',
            success: '#10B981',
            muted: '#64748B'
        };
        els.authStatus.textContent = msg;
        els.authStatus.style.color = colors[type] || colors.muted;
    };

    const setAuthLoading = (loading) => {
        [els.btnAuthLogin, els.btnAuthRegister].forEach(btn => {
            if (!btn) return;
            if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent;
            btn.disabled = loading;
            btn.textContent = loading ? '처리 중...' : btn.dataset.originalText;
        });
    };

    const openAuthModal = () => {
        if (!els.modalAuth) return;
        els.modalAuth.style.display = 'flex';
        setTimeout(() => els.modalAuth.classList.add('show'), 10);
    };

    const closeAuthModal = () => {
        if (!els.modalAuth) return;
        els.modalAuth.classList.remove('show');
        setTimeout(() => els.modalAuth.style.display = 'none', 200);
    };

    const openProfileModal = () => {
        if (!els.modalProfile || !els.profileModalBox) return;
        renderUserProfile();
        els.modalProfile.style.display = 'flex';

        const anchor = els.userProfile;
        const modalBox = els.profileModalBox;
        const gap = 12;

        let top = (window.innerHeight - modalBox.offsetHeight) / 2;
        let left = (window.innerWidth - modalBox.offsetWidth) / 2;
        let origin = '50% 50%';

        if (anchor) {
            const rect = anchor.getBoundingClientRect();
            const modalRect = modalBox.getBoundingClientRect();
            left = rect.right - modalRect.width;
            top = rect.top - modalRect.height - gap;
            let placeBelow = false;
            if (top < 12) {
                top = rect.bottom + gap;
                placeBelow = true;
            }
            const maxLeft = window.innerWidth - modalRect.width - 12;
            const maxTop = window.innerHeight - modalRect.height - 12;
            left = Math.min(Math.max(left, 12), Math.max(12, maxLeft));
            top = Math.min(Math.max(top, 12), Math.max(12, maxTop));
            origin = placeBelow ? '50% 0%' : '50% 100%';
        }

        modalBox.style.left = `${left}px`;
        modalBox.style.top = `${top}px`;
        modalBox.style.transformOrigin = origin;

        setTimeout(() => els.modalProfile.classList.add('show'), 10);
    };

    const closeProfileModal = () => {
        if (!els.modalProfile) return;
        els.modalProfile.classList.remove('show');
        setTimeout(() => els.modalProfile.style.display = 'none', 200);
    };

    const fetchAuthMe = async () => {
        try {
            const res = await fetch('/api/auth/me');
            const data = await res.json();
            state.user = data && data.authenticated ? data.user : null;
        } catch (e) {
            console.warn('Auth check failed', e);
            state.user = null;
        } finally {
            state.authChecked = true;
            renderUserProfile();
            // 사이드바 대화 목록은 history.js가 그린다. 그쪽에 알리기만 한다.
            window.dispatchEvent(new CustomEvent('history:refresh'));
        }
    };

    const readAuthForm = () => ({
        name: els.authName?.value.trim() || '',
        student_number: els.authStudentNumber?.value.trim() || '',
        email: els.authEmail?.value.trim(),
        password: els.authPassword?.value || ''
    });

    const handleAuthLogin = async () => {
        const { email, password } = readAuthForm();
        if (!email || !password) {
            setAuthStatus('이메일과 비밀번호를 입력하세요.', 'error');
            return;
        }
        setAuthLoading(true);
        setAuthStatus('로그인 중...', 'muted');
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || '로그인 실패');
            state.user = data.user;
            renderUserProfile();
            setAuthStatus('로그인 완료!', 'success');
            showToast('로그인되었습니다.', 'success');
            closeAuthModal();
        } catch (e) {
            console.error(e);
            setAuthStatus(e.message, 'error');
            showToast(e.message, 'error');
        } finally {
            setAuthLoading(false);
        }
    };

    const handleAuthRegister = async () => {
        const { name, student_number, email, password } = readAuthForm();
        if (!name || !email || !password || !/^[1-3][1-9](?:0[1-9]|[1-9]\d)$/.test(student_number)) {
            setAuthStatus('이름, 학번 4자리, 이메일과 비밀번호를 입력하세요. 예: 2412', 'error');
            return;
        }
        setAuthLoading(true);
        setAuthStatus('계정을 생성하는 중...', 'muted');
        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, student_number, email, password })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || '회원가입 실패');
            state.user = data.user;
            renderUserProfile();
            setAuthStatus('가입이 완료되었습니다.', 'success');
            showToast('로그인되었습니다.', 'success');
            closeAuthModal();
        } catch (e) {
            console.error(e);
            setAuthStatus(e.message, 'error');
            showToast(e.message, 'error');
        } finally {
            setAuthLoading(false);
        }
    };

    const handleAuthLogout = async () => {
        try {
            await fetch('/api/auth/logout', { method: 'POST' });
        } catch (e) {
            console.warn('Logout failed', e);
        }
        state.user = null;
        clearRiroCache();
        renderUserProfile();
        showToast('로그아웃되었습니다.', 'success');
    };


    // ============================================================
    // 3.5. RiroSchool Logic
    // ============================================================

    const RIRO_EVENTS_STORAGE_KEY = 'riro_events';
    const RIRO_LOGIN_STORAGE_KEY = 'riro_logged_in';
    const RIRO_META_STORAGE_KEY = 'riro_events_meta';
    const getCurrentAcademicYear = () => {
        const now = new Date();
        return now.getMonth() >= 2 ? now.getFullYear() : now.getFullYear() - 1;
    };
    const clearRiroCache = () => {
        localStorage.removeItem(RIRO_EVENTS_STORAGE_KEY);
        localStorage.removeItem(RIRO_LOGIN_STORAGE_KEY);
        localStorage.removeItem(RIRO_META_STORAGE_KEY);
        state.riroEvents = [];
        state.riroLoggedIn = false;
    };

    const normalizeRiroEvents = (raw) => {
        if (!raw) return [];
        let events = [];
        if (Array.isArray(raw)) {
            events = raw;
        } else if (typeof raw === 'object') {
            Object.entries(raw).forEach(([date, value]) => {
                if (Array.isArray(value)) {
                    value.forEach(item => {
                        if (!item) return;
                        events.push({ ...(item || {}), date: item.date || date });
                    });
                } else if (value && typeof value === 'object') {
                    events.push({ ...value, date: value.date || date });
                }
            });
        }
        events = events.map(evt => ({
            ...evt,
            date: evt.date || evt.raw_date || '',
            type: evt.type || 'assignment'
        }));
        try {
            events.sort((a, b) => (a.date || '').localeCompare(b.date || ''));
        } catch (e) { /* ignore */ }
        return events;
    };

    const saveRiroEvents = (events, forceLoggedIn = false, metadata = null) => {
        state.riroEvents = events;
        state.riroLoggedIn = forceLoggedIn || events.length > 0 || state.riroLoggedIn;
        localStorage.setItem(RIRO_EVENTS_STORAGE_KEY, JSON.stringify(events));
        localStorage.setItem(RIRO_LOGIN_STORAGE_KEY, state.riroLoggedIn ? 'true' : 'false');
        if (metadata) {
            localStorage.setItem(RIRO_META_STORAGE_KEY, JSON.stringify(metadata));
        }
    };

    const loadRiroFromStorage = () => {
        try {
            const stored = localStorage.getItem(RIRO_EVENTS_STORAGE_KEY);
            const storedMeta = localStorage.getItem(RIRO_META_STORAGE_KEY);
            const metadata = storedMeta ? JSON.parse(storedMeta) : null;
            const isCurrentAcademicYear = metadata
                && Number(metadata.academic_year) === getCurrentAcademicYear();
            const isCurrentUser = metadata
                && metadata.user_id
                && state.user
                && metadata.user_id === state.user.id;

            if (!isCurrentAcademicYear || !isCurrentUser) {
                clearRiroCache();
                return;
            }

            const parsed = stored ? JSON.parse(stored) : [];
            const wasLogged = localStorage.getItem(RIRO_LOGIN_STORAGE_KEY) === 'true';
            saveRiroEvents(normalizeRiroEvents(parsed), wasLogged, metadata);
        } catch (e) {
            console.warn('Failed to load Riro events from storage', e);
            clearRiroCache();
        }
    };

    const buildRiroSummary = (events) => {
        if (!events || events.length === 0) return '리로스쿨 일정이 없습니다.';
        const lines = events.slice(0, 5).map(evt => {
            const guide = evt.guide ? ` — ${evt.guide.slice(0, 120)}${evt.guide.length > 120 ? '...' : ''}` : '';
            return `- ${evt.date || '날짜 미정'}: ${evt.title}${guide}`;
        });
        return [
            `✅ **리로스쿨 연동 완료!** 총 ${events.length}개의 수행평가/일정을 가져왔어요.`,
            ...lines,
            '',
            "이 정보를 참고해 일정 관리나 학습 계획을 물어보면 바로 답해줄게요."
        ].join('\n');
    };

    let calendarInstance = null;
    let calendarRenderToken = 0;

    const renderCalendar = () => {
        const calendarEl = document.getElementById('calendarView');
        if (!calendarEl || typeof FullCalendar === 'undefined') return;

        const countEl = document.getElementById('calendarEventCount');
        const renderToken = ++calendarRenderToken;

        if (calendarInstance) {
            calendarInstance.destroy();
            calendarInstance = null;
        }

        const cached = localStorage.getItem(RIRO_EVENTS_STORAGE_KEY);
        const fallback = cached ? normalizeRiroEvents(JSON.parse(cached)) : [];
        const events = (state.riroEvents && state.riroEvents.length > 0)
            ? state.riroEvents
            : fallback;

        if (!events.length) {
            if (countEl) countEl.textContent = '0개 일정';
            calendarEl.removeAttribute('aria-busy');
            calendarEl.innerHTML = `
                <div class="calendar-state calendar-empty" role="status">
                    <div class="calendar-state-content">
                        <span class="calendar-state-icon" aria-hidden="true"><i class="bi bi-calendar2"></i></span>
                        <h4>아직 등록된 일정이 없어요</h4>
                        <p>리로스쿨을 연동하면 수행평가와 학교 공지가 여기에 자동으로 정리됩니다.</p>
                        <button class="calendar-empty-action" id="calendarConnectRiro" type="button">
                            <i class="bi bi-arrow-repeat" aria-hidden="true"></i>리로스쿨 연동
                        </button>
                    </div>
                </div>`;
            document.getElementById('calendarConnectRiro')?.addEventListener('click', () => {
                if (els.modalCalendar) {
                    els.modalCalendar.classList.remove('show');
                    els.modalCalendar.style.display = 'none';
                }
                document.getElementById('btnOpenLogin')?.click();
            });
            return;
        }

        if (countEl) countEl.textContent = `${events.length}개 일정`;
        calendarEl.setAttribute('aria-busy', 'true');
        calendarEl.innerHTML = '<div class="calendar-skeleton" role="status" aria-label="캘린더를 불러오는 중"></div>';

        requestAnimationFrame(() => {
            if (renderToken !== calendarRenderToken) return;

            try {
                calendarEl.innerHTML = '';

                const fcEvents = events.map(evt => {
                    const eventType = evt.type === 'assignment'
                        ? 'assignment'
                        : evt.type === 'notice' ? 'notice' : 'default';

                    return {
                        title: evt.title,
                        start: evt.date,
                        allDay: true,
                        backgroundColor: 'transparent',
                        borderColor: 'transparent',
                        textColor: 'inherit',
                        classNames: [`calendar-event--${eventType}`],
                        extendedProps: {
                            original: evt,
                            categoryLabel: eventType === 'assignment' ? '수행평가' : eventType === 'notice' ? '학교 공지' : '일정'
                        }
                    };
                });

                calendarInstance = new FullCalendar.Calendar(calendarEl, {
                    initialView: 'dayGridMonth',
                    headerToolbar: {
                        left: 'title',
                        center: '',
                        right: 'prev,next today dayGridMonth,listMonth'
                    },
                    buttonText: {
                        today: '오늘',
                        month: '월',
                        list: '목록'
                    },
                    views: {
                        dayGridMonth: { dayMaxEvents: true },
                        listMonth: { noEventsContent: '이 달에는 등록된 일정이 없습니다.' }
                    },
                    events: fcEvents,
                    height: '100%',
                    fixedWeekCount: false,
                    dayCellContent: (info) => String(info.date.getDate()),
                    moreLinkContent: (info) => `+${info.num}`,
                    locale: 'ko',
                    eventDidMount: (info) => {
                        const props = info.event.extendedProps;
                        const label = `${props.categoryLabel}: ${info.event.title}`;
                        info.el.setAttribute('aria-label', label);
                        info.el.setAttribute('title', label);
                    }
                });
                calendarInstance.render();
            } catch (error) {
                console.error('Failed to render calendar', error);
                calendarEl.innerHTML = `
                    <div class="calendar-state calendar-error" role="alert">
                        <div class="calendar-state-content">
                            <span class="calendar-state-icon" aria-hidden="true"><i class="bi bi-exclamation-circle"></i></span>
                            <h4>캘린더를 표시하지 못했어요</h4>
                            <p>잠시 후 다시 시도해 주세요.</p>
                            <button class="calendar-empty-action" id="calendarRetry" type="button">다시 시도</button>
                        </div>
                    </div>`;
                document.getElementById('calendarRetry')?.addEventListener('click', renderCalendar);
            } finally {
                calendarEl.removeAttribute('aria-busy');
            }
        });
    };

    // 리로스쿨은 학교마다 하위 도메인이 다르다(okgwa.riroschool.kr).
    // 서버는 하위 도메인 조각만 받으므로 주소를 통째로 붙여넣어도 조각만 남긴다.
    const normalizeRiroSchool = (raw) => (raw || '')
        .trim()
        .toLowerCase()
        .replace(/^https?:\/\//, '')
        .replace(/\.riroschool\.kr.*$/, '')
        .replace(/\/.*$/, '')
        .replace(/[^a-z0-9-]/g, '');

    const setRiroStatus = (msg = '', type = 'error') => {
        if (!els.riroStatus) return;
        els.riroStatus.className = type === 'success' ? 'signin_error success' : 'signin_error';
        els.riroStatus.textContent = '';
        if (!msg) return;
        // 메시지에 서버 문구가 섞이므로 텍스트 노드로만 붙인다.
        const icon = document.createElement('i');
        icon.className = type === 'success' ? 'bi bi-check-circle-fill' : 'bi bi-exclamation-circle-fill';
        icon.setAttribute('aria-hidden', 'true');
        els.riroStatus.append(icon, msg);
    };

    // 인사말의 학교 이름은 학교 주소 입력에서 바로 나온다.
    // 원본은 학교별 도메인이라 학교명이 하드코딩돼 있지만 우리는 입력을 따라간다.
    const syncRiroSchool = () => {
        const slug = normalizeRiroSchool(els.riroSchool?.value);
        if (els.riroSchoolLabel) els.riroSchoolLabel.textContent = slug || '우리 학교';
        return slug;
    };

    // 서버는 앱 계정 세션이 없으면 리로 로그인을 401로 막는다.
    // 폼을 열 때 미리 알려주지 않으면 아이디·비번이 맞는데 안 된다고 느끼게 된다.
    const syncRiroAuthNotice = (force = false) => {
        const needsLogin = force || !state.user;
        els.riroAuthNotice?.classList.toggle('show', needsLogin);
        if (els.btnLoginAction) els.btnLoginAction.disabled = needsLogin;
        const link = document.getElementById('riroAuthNoticeLink');
        if (link) link.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        return needsLogin;
    };

    const openRiroModal = () => {
        if (!els.modalLogin) return;
        setRiroStatus('');
        syncRiroAuthNotice();
        els.modalLogin.style.display = 'flex';
        setTimeout(() => els.modalLogin.classList.add('show'), 10);
    };

    const handleRiroLogin = async () => {
        if (syncRiroAuthNotice()) {
            setRiroStatus('DOC Agent 계정으로 먼저 로그인하세요.');
            return;
        }

        const rawSchool = (els.riroSchool?.value || '').trim();
        const school = syncRiroSchool();
        const username = els.riroId?.value.trim();
        const password = els.riroPw?.value.trim();

        // 리로 로그인 폼처럼 어느 칸이 비었는지 짚어주고 그 칸으로 커서를 보낸다.
        if (!school) {
            // 학교 이름을 한글로 적으면 하위 도메인이 안 나온다. 그 경우를 따로 짚어준다.
            setRiroStatus(rawSchool
                ? '학교 이름 대신 리로스쿨 주소를 영문으로 입력하세요. 예: okgwa'
                : '학교 주소를 입력하세요. 예: okgwa');
            els.riroSchool?.focus();
            return;
        }
        if (!username) {
            setRiroStatus('아이디를 다시 확인하세요.');
            els.riroId?.focus();
            return;
        }
        if (!password) {
            setRiroStatus('비밀번호를 다시 확인하세요.');
            els.riroPw?.focus();
            return;
        }

        setRiroStatus('');
        const btn = els.btnLoginAction;
        const originalText = btn.textContent;
        btn.textContent = '로그인 중...';
        btn.disabled = true;

        try {
            const response = await fetch('/api/riroschool/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ school, username, password })
            });
            const data = await response.json();
            
            if (data.success) {
                const normalizedEvents = normalizeRiroEvents(data.events || data.events_by_date);
                saveRiroEvents(normalizedEvents, true, {
                    academic_year: Number(data.academic_year || data.year),
                    grade: Number(data.grade),
                    user_id: state.user?.id || null,
                    fetched_at: new Date().toISOString()
                });
                showToast('리로스쿨 연동 성공!', 'success');
                
                if (normalizedEvents.length) {
                    renderCalendar(); // 캘린더 갱신
                    
                    // 캘린더 모달 열기
                    if (els.modalCalendar) {
                        els.modalCalendar.style.display = 'flex';
                        setTimeout(() => {
                            els.modalCalendar.classList.add('show');
                            renderCalendar();
                        }, 10);
                    }
                } else {
                    showToast('연동은 됐지만 가져올 수행평가 일정이 없어요.', 'info');
                }

                // Close login modal
                if (els.modalLogin) {
                    setRiroStatus('');
                    if (els.riroPw) els.riroPw.value = '';
                    els.modalLogin.classList.remove('show');
                    setTimeout(() => els.modalLogin.style.display='none', 300);
                }
            } else {
                if (data.code === 'STUDENT_NUMBER_REQUIRED') {
                    window.location.href = data.setup_url || '/student-number/update';
                    return;
                }
                // 세션이 끊겨 401이면 리로 계정 문제가 아니므로 안내 배너를 띄운다.
                if (response.status === 401) {
                    state.user = null;
                    syncRiroAuthNotice(true);
                    renderUserProfile();
                }
                throw new Error(data.error || '로그인 실패');
            }
        } catch (e) {
            // 리로 로그인 폼처럼 실패하면 비밀번호만 비우고 아이디는 남겨둔다.
            setRiroStatus(e.message);
            if (els.riroPw) els.riroPw.value = '';
            els.riroPw?.focus();
        } finally {
            btn.textContent = originalText;
            btn.disabled = false;
        }
    };

    // ============================================================
    // 4. 이벤트 리스너 바인딩
    // ============================================================

    // 입력창 높이만 여기서 맞춘다. 보내는 일은 guide.js(설계·실험 대화)가 가져간다 —
    // 예전에는 이 파일이 문서 생성 요청을 직접 보냈지만 그 경로는 걷어냈다.
    if (els.userRequest) {
        els.userRequest.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            updateSendButtonState();
        });
    }
    updateSendButtonState();
    if (els.btnLoginAction) els.btnLoginAction.addEventListener('click', handleRiroLogin);

    // 리로 로그인 폼과 같은 입력 동작: 앞뒤 공백은 받지 않고, 엔터로 다음 칸까지 이어간다.
    [els.riroSchool, els.riroId, els.riroPw].forEach((input, idx, all) => {
        if (!input) return;
        input.addEventListener('input', () => {
            const trimmed = input.value.replace(/^\s+|\s+$/g, '');
            if (trimmed !== input.value) input.value = trimmed;
            setRiroStatus('');
            if (input === els.riroSchool) syncRiroSchool();
        });
        input.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            const next = all.slice(idx + 1).find(Boolean);
            if (next && !next.value) next.focus();
            else handleRiroLogin();
        });
    });
    // 학교 주소를 붙여넣은 뒤 칸을 벗어나면 하위 도메인 조각만 남긴다.
    if (els.riroSchool) {
        els.riroSchool.addEventListener('blur', () => {
            const slug = syncRiroSchool();
            if (slug) els.riroSchool.value = slug;
        });
    }
    // 아이디/비밀번호 찾기 — 원본과 같은 user.php?action=find_* 로 이동하되,
    // 학교별 도메인이 필요하므로 학교 주소가 없으면 그 칸으로 보낸다.
    [[els.riroFindId, 'find_id'], [els.riroFindPw, 'find_pw']].forEach(([btn, action]) => {
        btn?.addEventListener('click', () => {
            const slug = syncRiroSchool();
            if (!slug) {
                setRiroStatus('학교 주소를 먼저 입력하세요.');
                els.riroSchool?.focus();
                return;
            }
            window.open(`https://${slug}.riroschool.kr/user.php?action=${action}`, '_blank', 'noopener');
        });
    });

    // 학생·교사 / 학부모 탭 — 원본 User1()/User2()와 같은 전환.
    // (연동 크롤러는 학생 로그인 흐름만 타므로 학부모 탭은 원본과 같은 안내만 띄운다)
    const RIRO_CHECK_ON = '/static/images/riro/check_regular.svg';
    const RIRO_CHECK_OFF = '/static/images/riro/non_check_regular.svg';
    const setRiroUserType = (isParent) => {
        if (els.riroTab1Img) els.riroTab1Img.src = isParent ? RIRO_CHECK_OFF : RIRO_CHECK_ON;
        if (els.riroTab2Img) els.riroTab2Img.src = isParent ? RIRO_CHECK_ON : RIRO_CHECK_OFF;
        els.riroTabStudent?.classList.toggle('on', !isParent);
        els.riroTabParent?.classList.toggle('on', isParent);
        if (els.riroId) els.riroId.placeholder = isParent ? '통합 아이디(이메일)' : '학교 아이디 또는 통합 아이디(이메일)';
        els.riroNoneSignup?.classList.toggle('show', isParent);
    };
    els.riroTabStudent?.addEventListener('click', () => setRiroUserType(false));
    els.riroTabParent?.addEventListener('click', () => setRiroUserType(true));
    syncRiroSchool();
    if (els.btnAuthLogin) els.btnAuthLogin.addEventListener('click', handleAuthLogin);
    if (els.btnAuthRegister) els.btnAuthRegister.addEventListener('click', handleAuthRegister);
    if (els.btnOpenAuth) {
        els.btnOpenAuth.addEventListener('click', () => {
            window.location.href = withNextParam('/login');
        });
    }
    if (els.btnAuthToggle) {
        els.btnAuthToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            if (state.user) {
                handleAuthLogout();
            } else {
                window.location.href = withNextParam('/login');
            }
        });
    }
    if (els.userProfile) {
        els.userProfile.addEventListener('click', () => {
            openProfileModal();
        });
    }
    if (els.closeProfile) {
        els.closeProfile.addEventListener('click', closeProfileModal);
    }
    if (els.modalProfile) {
        els.modalProfile.addEventListener('click', (e) => {
            if (e.target === els.modalProfile) closeProfileModal();
        });
    }
    if (els.profileLogin) {
        els.profileLogin.addEventListener('click', () => {
            closeProfileModal();
            if (!state.user) {
                window.location.href = withNextParam('/login');
            }
        });
    }
    if (els.profileLogout) {
        els.profileLogout.addEventListener('click', async () => {
            await handleAuthLogout();
            closeProfileModal();
        });
    }
    const btnCloseAuth = document.getElementById('closeAuth');
    if (btnCloseAuth) btnCloseAuth.addEventListener('click', closeAuthModal);

    // 새 대화 — 지난 설계 대화는 HISTORY에 남고, 새 대화방에서 다시 시작한다.
    if (els.btnNewChat) {
        els.btnNewChat.addEventListener('click', async () => {
            try {
                if (window.ResearchChat) await window.ResearchChat.reset();
            } catch (_) { /* 실패해도 새로고침으로 새 화면은 열린다 */ }
            location.href = '/';
        });
    }

    // 사이드바
    const toggleSidebar = (open) => {
        if(open) {
            els.sidebar.classList.add('open');
            els.sidebarOverlay.classList.add('open');
        } else {
            els.sidebar.classList.remove('open');
            els.sidebarOverlay.classList.remove('open');
        }
    };
    els.btnMenu?.addEventListener('click', () => toggleSidebar(true));
    els.sidebarOverlay?.addEventListener('click', () => toggleSidebar(false));

    // Desktop Sidebar Toggle
    if (els.btnDesktopSidebarToggle) {
        els.btnDesktopSidebarToggle.addEventListener('click', () => {
            els.sidebar.classList.toggle('collapsed');
        });
    }

    if (theme.toggles.length) {
        theme.toggles.forEach((btn) => {
            btn.addEventListener('click', toggleTheme);
        });
    }

    // 모달 (로그인, 캘린더 등 껍데기 동작만 연결)
    const setupModal = (btnId, modalId, closeId) => {
        const btn = document.getElementById(btnId);
        const modal = document.getElementById(modalId);
        const close = document.getElementById(closeId);
        if(btn && modal) {
            btn.addEventListener('click', () => { modal.classList.add('show'); modal.style.display='flex'; });
        }
        if(close && modal) {
            close.addEventListener('click', () => { modal.classList.remove('show'); setTimeout(()=>modal.style.display='none', 300); });
        }
    };
    // 리로 모달은 열 때 앱 계정 상태를 먼저 확인해야 해서 전용 핸들러를 쓴다.
    document.getElementById('btnOpenLogin')?.addEventListener('click', openRiroModal);
    document.getElementById('closeLogin')?.addEventListener('click', () => {
        els.modalLogin?.classList.remove('show');
        setTimeout(() => { if (els.modalLogin) els.modalLogin.style.display = 'none'; }, 300);
    });
    
    // 캘린더 모달은 별도 처리 (렌더링 필요)
    const btnCalendar = document.getElementById('btnOpenCalendar');
    const modalCalendar = document.getElementById('modalCalendar');
    const closeCalendar = document.getElementById('closeCalendar');
    
    if (btnCalendar && modalCalendar) {
        btnCalendar.addEventListener('click', () => {
            modalCalendar.style.display = 'flex';
            setTimeout(() => {
                modalCalendar.classList.add('show');
                renderCalendar(); // 모달이 뜰 때 캘린더 다시 그리기 (사이즈 계산 위함)
            }, 10);
        });
    }
    if (closeCalendar && modalCalendar) {
        closeCalendar.addEventListener('click', () => {
            modalCalendar.classList.remove('show');
            setTimeout(() => modalCalendar.style.display = 'none', 300);
        });
    }

    // 초기 실행
    initTheme();
    applyAccountUIState();
    renderUserProfile();
    updateAuthLinks();
    fetchAuthMe().then(() => {
        loadRiroFromStorage();
        // 대화 목록·본문은 history.js와 guide.js가 그린다. 여기서는 건드리지 않는다.
        window.dispatchEvent(new CustomEvent('history:refresh'));
    });
});
