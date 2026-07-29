"""테스트용 시드 라우터.

연구 서사 파이프라인의 6단계(onboarding → themes → select_theme → framework →
subjects → done) 중 아무 지점으로나 즉시 건너뛰기 위한 개발용 API입니다.

## 왜 남지 않는가

시드 데이터는 실제 테이블에 들어가지만 사용자 id가 항상 ``test_`` 로 시작하고,
그 id를 잡고 있는 손잡이는 **브라우저 세션 쿠키 하나뿐**입니다. 캐시(쿠키)를 지우면
손잡이가 사라지고, 남은 행은 다음 호출 때 ``_purge_orphans()`` 가 지웁니다.

살아 있는 테스트 사용자 목록은 프로세스 메모리(``_ACTIVE``)에만 있으므로 서버를
재시작해도 같은 방식으로 전부 고아가 되어 정리됩니다. 즉 어느 쪽을 초기화하든
테스트 데이터는 실서비스 데이터를 건드리지 않고 사라집니다.

## 켜는 법

기본은 꺼져 있습니다. ``.env`` 에 ``DEV_TEST_ROUTES=1`` 을 넣어야 열립니다.
로컬 주소라는 이유만으로 열지 않는 것은, 리버스 프록시 뒤에서는 실제 사용자
요청도 127.0.0.1로 보이기 때문입니다.
"""
import logging
import os
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from database import db
from models import get_academic_year
from modules.research_store import ResearchStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/test', tags=['Test Fixtures'])
# 사람이 눌러서 쓰는 콘솔은 /test 로 연다(접두사 없이).
page_router = APIRouter(tags=['Test Fixtures'])
store = ResearchStore(db)

TEST_USER_PREFIX = 'test_'

# user_id로 사용자를 구분하는 모든 테이블. 고아 정리 대상이다.
USER_SCOPED_TABLES = (
    'student_profiles',
    'research_themes',
    'research_frameworks',
    'grade_plans',
    'subject_plans',
    'research_messages',
    'agent_runs',
    'chat_sessions',
    'document_history',
    'analytics_events',
    'student_number_reminders',
)

# 이 프로세스가 만들어 아직 살아 있다고 보는 테스트 사용자.
# 재시작하면 비므로 이전 실행이 남긴 데이터는 전부 고아가 된다.
_ACTIVE: set = set()

STAGES = ('onboarding', 'themes', 'select_theme', 'framework', 'subjects', 'done')


def _enabled() -> bool:
    return str(os.getenv('DEV_TEST_ROUTES', '')).strip().lower() in {'1', 'true', 'yes', 'on'}


def _error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({'error': message}, status_code=status_code)


def _guard() -> Optional[JSONResponse]:
    if not _enabled():
        return _error('테스트 라우터가 꺼져 있습니다. .env에 DEV_TEST_ROUTES=1을 넣고 서버를 다시 시작하세요.', 404)
    return None


# ---------- 정리 ----------

def _delete_users(user_ids: List[str]) -> int:
    """테스트 사용자와 그들이 만든 모든 행을 지운다."""
    if not user_ids:
        return 0
    marks = ','.join('?' for _ in user_ids)
    conn = db.get_connection()
    try:
        for table in USER_SCOPED_TABLES:
            try:
                conn.execute(f'DELETE FROM {table} WHERE user_id IN ({marks})', user_ids)
            except Exception:
                # 아직 만들어지지 않은 테이블은 건너뛴다.
                logger.debug('테이블 %s 정리를 건너뜀', table)
        conn.execute(f'DELETE FROM users WHERE id IN ({marks})', user_ids)
        conn.commit()
    finally:
        conn.close()
    for user_id in user_ids:
        _ACTIVE.discard(user_id)
    return len(user_ids)


def _all_test_user_ids() -> List[str]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            'SELECT id FROM users WHERE id LIKE ?', (f'{TEST_USER_PREFIX}%',)
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _purge_orphans() -> int:
    """세션이나 프로세스가 초기화되어 아무도 잡고 있지 않은 테스트 사용자를 지운다."""
    orphans = [uid for uid in _all_test_user_ids() if uid not in _ACTIVE]
    if orphans:
        logger.info('[TEST] 고아 테스트 사용자 %d명 정리', len(orphans))
    return _delete_users(orphans)


# ---------- 시드 ----------

def _create_test_user() -> str:
    """테스트 전용 사용자 행을 직접 만든다(prefix를 우리가 정해야 하므로 raw SQL)."""
    user_id = f'{TEST_USER_PREFIX}{secrets.token_hex(8)}'
    now = datetime.now().isoformat()
    academic_year = get_academic_year()
    conn = db.get_connection()
    try:
        conn.execute('''
            INSERT INTO users (
                id, email, name, picture, password_hash, admission_year,
                student_number, student_number_academic_year, student_number_updated_at,
                created_at, last_login
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, f'{user_id}@test.local', '테스트 학생', None, None,
            # 2학년으로 보이도록 입학연도를 맞춘다. 리로 연동 등 학년이 필요한 화면도 통과한다.
            academic_year - 1, '2412', academic_year, now, now, now,
        ))
        conn.commit()
    finally:
        conn.close()
    _ACTIVE.add(user_id)
    return user_id


# 도시 열섬 이야기 한 줄기. 온보딩 예시 문구와 이어지도록 맞췄다.
_PROFILE = {
    'interests': ['도시 열섬', '기후', '건축 환경'],
    'problem_statement': '왜 같은 도시인데 어떤 동네만 밤에도 안 식는지 알고 싶다',
    'aspired_track': '환경공학 · 건축',
    'strength_subjects': ['과학', '수학'],
    'activity_history': ['기상 동아리에서 １년간 기온 기록', '학교 주변 온도 지도 만들기'],
}

_THEMES = [
    {
        'title': '도시 표면이 밤 기온을 붙잡는 방식',
        'rationale': '기온 기록 경험이 있고, 관측을 설계로 이어갈 수 있다.',
        'expansion': '1학년 관측 → 2학년 변인 실험 → 3학년 완화 설계 제안',
    },
    {
        'title': '녹지 배치가 체감 온도를 바꾸는 임계점',
        'rationale': '건축·환경 지망과 직접 맞닿아 있다.',
        'expansion': '1학년 사례 조사 → 2학년 모델링 → 3학년 학교 부지 제안',
    },
    {
        'title': '학교 건물 재질과 여름철 실내 온도',
        'rationale': '학교라는 접근 가능한 현장을 3년간 반복 관측할 수 있다.',
        'expansion': '1학년 실측 → 2학년 재질 비교 → 3학년 개선안 검증',
    },
]

_FRAMEWORK = {
    'core_question': '도시의 어떤 물리적 조건이 야간 기온 하강을 막는가?',
    'sub_areas': ['표면 재질과 열용량', '녹지·수공간 배치', '건물 배치와 통풍'],
    'final_destination': '학교 주변 열섬 완화 설계안과 3년치 관측 데이터',
}

_GRADE_PLANS = [
    {
        'grade': 1,
        'goal': '학교 주변의 야간 기온 차이를 직접 측정해 문제가 실재함을 확인한다.',
        'anchor_project': {
            'title': '학교 반경 1km 야간 기온 지도',
            'description': '지점 8곳을 정해 여름 4주간 같은 시각에 기온을 기록하고 지도로 만든다.',
        },
    },
    {
        'grade': 2,
        'goal': '기온 차를 만드는 변인을 하나씩 분리해 실험으로 확인한다.',
        'anchor_project': {
            'title': '표면 재질별 야간 냉각 속도 비교',
            'description': '아스팔트·잔디·흙 시료의 냉각 곡선을 측정해 열용량 차이를 설명한다.',
        },
    },
    {
        'grade': 3,
        'goal': '측정과 실험을 근거로 완화 설계안을 만들고 검증한다.',
        'anchor_project': {
            'title': '학교 부지 열섬 완화 설계안',
            'description': '녹지 배치안을 만들고 간이 모델로 효과를 추정해 제안서로 정리한다.',
        },
    },
]

_SUBJECTS = [
    {
        'subject': '통합과학', 'approach': 'linked', 'area_name': '열과 에너지',
        'standard_codes': ['9과01-03'],
        'activity_design': {'question': '표면 재질에 따라 야간 냉각 속도가 어떻게 달라지는가?'},
    },
    {
        'subject': '수학', 'approach': 'deepening', 'area_name': '함수',
        'standard_codes': ['10수02-05'],
        'activity_design': {'question': '냉각 곡선을 어떤 함수로 근사해야 설명력이 높은가?'},
    },
]


def _seed(user_id: str, stage: str) -> None:
    """요청한 단계 직전까지 데이터를 채운다."""
    index = STAGES.index(stage)
    if index < 1:
        return  # onboarding: 아무것도 없는 상태가 정답

    profile = store.save_profile(user_id, **_PROFILE)
    if index < 2:
        return

    themes = store.replace_theme_candidates(
        user_id, [dict(t, profile_id=profile.id) for t in _THEMES])
    if index < 3:
        return  # select_theme: 후보만 있고 고르지 않은 상태

    selected = store.select_theme(user_id, themes[0].id)
    if index < 4:
        return  # framework: 테마는 골랐고 계획은 없는 상태

    framework = store.save_framework(user_id, theme_id=selected.id, **_FRAMEWORK)
    plans = [
        store.upsert_grade_plan(user_id, framework.id, plan['grade'],
                                goal=plan['goal'], anchor_project=plan['anchor_project'])
        for plan in _GRADE_PLANS
    ]
    if index < 5:
        return  # subjects: 학년 계획까지만

    for plan in plans:
        for subject in _SUBJECTS:
            store.upsert_subject_plan(user_id, plan.id, subject['subject'], **{
                k: v for k, v in subject.items() if k != 'subject'
            })


# ---------- 엔드포인트 ----------

@router.get('/status')
def test_status(request: Request):
    """지금 어떤 테스트 사용자로 보고 있는지."""
    blocked = _guard()
    if blocked:
        return blocked
    user_id = request.session.get('user_id')
    is_test = bool(user_id and user_id.startswith(TEST_USER_PREFIX))
    return {
        'enabled': True,
        'stages': list(STAGES),
        'user_id': user_id if is_test else None,
        'is_test_user': is_test,
        'active_in_process': len(_ACTIVE),
        'orphans': max(0, len(_all_test_user_ids()) - len(_ACTIVE)),
    }


@router.post('/seed')
async def test_seed(request: Request):
    """원하는 단계의 테스트 사용자를 만들고 그 계정으로 로그인한다.

    body: {"stage": "framework"}  — 생략하면 done
    """
    blocked = _guard()
    if blocked:
        return blocked

    try:
        payload = await request.json()
        payload = payload if isinstance(payload, dict) else {}
    except Exception:
        payload = {}

    stage = str(payload.get('stage') or 'done').strip()
    if stage not in STAGES:
        return _error(f"stage는 {', '.join(STAGES)} 중 하나여야 합니다.", 400)

    # 새 시드를 만들기 전에 손잡이 없는 이전 데이터를 먼저 걷어낸다.
    _purge_orphans()

    # 지금 테스트 사용자로 보고 있었다면 그것도 정리하고 새로 만든다.
    previous = request.session.get('user_id')
    if previous and previous.startswith(TEST_USER_PREFIX):
        _delete_users([previous])

    user_id = _create_test_user()
    try:
        _seed(user_id, stage)
    except Exception as exc:
        _delete_users([user_id])
        logger.exception('[TEST] 시드 실패')
        return _error(f'시드에 실패했습니다: {exc}', 500)

    request.session['user_id'] = user_id
    return {
        'success': True,
        'stage': stage,
        'user_id': user_id,
        'note': '브라우저 캐시(쿠키)를 지우거나 서버를 재시작하면 이 데이터는 다음 호출 때 정리됩니다.',
    }


@router.post('/reset')
def test_reset(request: Request):
    """지금 보고 있는 테스트 사용자를 지우고 로그아웃한다."""
    blocked = _guard()
    if blocked:
        return blocked
    user_id = request.session.get('user_id')
    removed = 0
    if user_id and user_id.startswith(TEST_USER_PREFIX):
        removed = _delete_users([user_id])
        request.session.pop('user_id', None)
    removed += _purge_orphans()
    return {'success': True, 'removed': removed}


@router.post('/purge')
def test_purge(request: Request):
    """실행 중인 것까지 포함해 모든 테스트 사용자를 지운다."""
    blocked = _guard()
    if blocked:
        return blocked
    user_id = request.session.get('user_id')
    removed = _delete_users(_all_test_user_ids())
    if user_id and user_id.startswith(TEST_USER_PREFIX):
        request.session.pop('user_id', None)
    return {'success': True, 'removed': removed}


# ---------- 콘솔 페이지 ----------

_STAGE_NOTE = {
    'onboarding': '아무 데이터도 없는 새 계정',
    'themes': '프로필만 있음 · 테마 만들 차례',
    'select_theme': '테마 후보 3개 · 아직 안 고름',
    'framework': '테마 고름 · 3년 계획 없음',
    'subjects': '1·2·3학년 계획까지 · 세특 없음',
    'done': '세특까지 전부 채워진 상태',
}

_CONSOLE_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>테스트 시드 콘솔</title>
<link rel="stylesheet" href="/static/css/score-dream.css">
<style>
  :root { --ink:#0F172A; --line:#E2E8F0; --muted:#64748B; }
  * { box-sizing:border-box; }
  body { margin:0; background:#F8FAFC; color:var(--ink);
         font-family:'S-Core Dream','Noto Sans KR',sans-serif; font-size:15px; line-height:1.6; }
  .wrap { max-width:640px; margin:0 auto; padding:48px 20px 80px; }
  h1 { font-size:1.4rem; margin:0 0 6px; }
  .sub { color:var(--muted); font-size:0.9rem; margin:0 0 8px; }
  .warn { display:inline-block; font-size:0.76rem; font-weight:700; color:#B45309;
          background:#FEF3C7; border-radius:6px; padding:3px 9px; margin-bottom:28px; }
  .grid { display:grid; gap:10px; }
  button { font-family:inherit; }
  .stage { display:flex; align-items:center; gap:14px; width:100%; text-align:left;
           padding:15px 17px; border:1px solid var(--line); border-radius:13px;
           background:#fff; cursor:pointer; color:inherit;
           transition:border-color .18s, box-shadow .18s; }
  .stage:hover { border-color:var(--ink); box-shadow:0 0 0 3px rgba(15,23,42,.12); }
  .stage:disabled { opacity:.5; cursor:wait; }
  .n { flex:0 0 auto; width:24px; height:24px; border-radius:50%; border:1.5px solid var(--ink);
       display:flex; align-items:center; justify-content:center; font-size:.72rem; font-weight:700; }
  .k { font-weight:700; }
  .d { font-size:.82rem; color:var(--muted); }
  .row { display:flex; gap:10px; margin-top:26px; flex-wrap:wrap; }
  .mini { padding:9px 15px; border-radius:10px; border:1px solid var(--line);
          background:#fff; cursor:pointer; font-size:.85rem; font-weight:600; color:inherit; }
  .mini:hover { border-color:var(--ink); box-shadow:0 0 0 3px rgba(15,23,42,.12); }
  .out { margin-top:22px; padding:14px 16px; border-radius:12px; background:#fff;
         border:1px solid var(--line); font-size:.85rem; white-space:pre-wrap;
         word-break:break-all; min-height:22px; color:var(--muted); }
  .out.err { border-color:#FCA5A5; color:#B91C1C; }
  a { color:var(--ink); }
</style></head><body><div class="wrap">
  <h1>테스트 시드 콘솔</h1>
  <p class="sub">단계를 누르면 그 지점까지 채워진 임시 계정으로 바로 로그인됩니다.</p>
  <span class="warn">개발 전용 · 캐시(쿠키)를 지우거나 서버를 재시작하면 정리됩니다</span>
  <div class="grid" id="grid">__STAGES__</div>
  <div class="row">
    <button class="mini" data-go="/research">/research 열기</button>
    <button class="mini" data-go="/">홈 열기</button>
    <button class="mini" data-post="/api/test/reset">지금 계정 정리</button>
    <button class="mini" data-post="/api/test/purge">전부 정리</button>
    <button class="mini" data-get="/api/test/status">상태 보기</button>
  </div>
  <div class="out" id="out">대기 중</div>
<script>
const out = document.getElementById('out');
const say = (text, isError) => { out.textContent = text; out.classList.toggle('err', !!isError); };
const call = async (url, method) => {
  say('요청 중...');
  try {
    const res = await fetch(url, { method, credentials: 'same-origin',
      headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
      body: undefined });
    const body = await res.json();
    say(JSON.stringify(body, null, 2), !res.ok);
    return res.ok;
  } catch (e) { say(e.message, true); return false; }
};
document.getElementById('grid').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-stage]'); if (!btn) return;
  btn.disabled = true;
  say('시드 중...');
  try {
    const res = await fetch('/api/test/seed', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage: btn.dataset.stage }) });
    const body = await res.json();
    say(JSON.stringify(body, null, 2), !res.ok);
    // 시드 후에는 채팅이 있는 메인으로 보낸다. 확인은 대부분 거기서 시작한다.
    if (res.ok) setTimeout(() => { location.href = '/'; }, 700);
  } catch (err) { say(err.message, true); }
  btn.disabled = false;
});
document.querySelector('.row').addEventListener('click', (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  if (btn.dataset.go) { location.href = btn.dataset.go; return; }
  if (btn.dataset.post) call(btn.dataset.post, 'POST');
  if (btn.dataset.get) call(btn.dataset.get, 'GET');
});
</script></div></body></html>"""


@page_router.get('/test', response_class=HTMLResponse)
def test_console(request: Request):
    """사람이 눌러서 쓰는 시드 콘솔."""
    if not _enabled():
        return HTMLResponse(
            '<p style="font-family:sans-serif;padding:40px">테스트 라우터가 꺼져 있습니다. '
            '<code>.env</code>에 <code>DEV_TEST_ROUTES=1</code>을 넣고 서버를 다시 시작하세요.</p>',
            status_code=404)

    buttons = ''.join(
        f'<button class="stage" type="button" data-stage="{stage}">'
        f'<span class="n">{index + 1}</span>'
        f'<span><span class="k">{stage}</span><br><span class="d">{_STAGE_NOTE[stage]}</span></span>'
        f'</button>'
        for index, stage in enumerate(STAGES)
    )
    return HTMLResponse(_CONSOLE_HTML.replace('__STAGES__', buttons))
