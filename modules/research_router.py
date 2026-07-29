"""연구 서사(Research Narrative) API.

app.py를 더 키우지 않도록 v2_hwp_proxy.py와 같은 APIRouter 패턴으로 분리합니다.
"""
import asyncio
import logging
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database import db
from models import RESEARCH_STATUSES, STATUS_FIXED, STATUS_NARROWING, SUBJECT_APPROACHES
from modules import (codex_auth, codex_generator, codex_runner, hwp_inspect,
                     hwp_report, ppt_report,
                     report_figures, research_pipeline)
from modules.docx_handler import DOCXHandler
from modules.research_pipeline import PipelineError
from modules.research_store import ResearchStateError, ResearchStore

logger = logging.getLogger(__name__)

# 보고서 파일은 앱의 다른 문서와 같은 곳(output/)에 쓴다. /api/download 가 여기서 내려준다.
_docx_handler = DOCXHandler(output_dir='output')

router = APIRouter(prefix='/api/research', tags=['Research Narrative'])
store = ResearchStore(db)

# 진행 중인 대화 턴. 학생이 새로고침해도 서버는 계속 만들고 있어야 하고,
# 돌아왔을 때 "만드는 중"인지 "다 됐는지"를 알려줄 수 있어야 한다.
# 프로세스 메모리에만 두므로 서버가 재시작되면 그 작업과 함께 사라진다.
_CHAT_JOBS: Dict[str, Dict[str, Any]] = {}

# 이 시간 안에 끝나면 폴링을 시키지 않고 그 자리에서 결과를 돌려준다.
_CHAT_INLINE_WAIT_SECONDS = 2.0

# 결과를 받아 가지 않은 기록을 치우는 기준(탭을 닫아 버린 경우).
_CHAT_JOB_TTL_SECONDS = 30 * 60

# 대화방 이름. 연구 서사 대화와 과목별 실험 대화는 서로 독립적으로 진행된다.
_ROOM_RESEARCH = 'research'

# 사이드바 HISTORY의 폴더. 대화는 이 둘 중 하나에 들어간다.
FOLDER_DESIGN = '설계'
FOLDER_EXPERIMENT = '실험'

# 설계 대화방을 막 만들었을 때의 이름. 내용이 쌓이면 요약으로 바뀐다.
_DESIGN_DEFAULT_TITLE = '새 연구 설계'


def _room_experiment(plan_id: int) -> str:
    return f'experiment:{plan_id}'


def _grade_anchor(grade: Optional[int]) -> str:
    """로드맵에서 그 학년이 보이는 자리. 최상단이 아니라 방금 만든 학년으로 데려간다."""
    return f'/research#grade-{grade}' if grade else '/research'

# 상태 전이 API가 다룰 수 있는 테이블. 임의 테이블명이 들어오지 않도록 화이트리스트로 제한한다.
STATUS_TABLES = {
    'profile': 'student_profiles',
    'theme': 'research_themes',
    'framework': 'research_frameworks',
    'grade-plan': 'grade_plans',
    'subject-plan': 'subject_plans',
}


def _error(message: str, status_code: int = 400, kind: Optional[str] = None) -> JSONResponse:
    payload: Dict[str, Any] = {'error': message}
    # 화면이 다르게 보여줘야 하는 실패는 종류를 함께 알린다(예: usage_limit).
    if kind:
        payload['error_kind'] = kind
    return JSONResponse(payload, status_code=status_code)


def _current_user_id(request: Request) -> Optional[str]:
    return request.session.get('user_id') if hasattr(request, 'session') else None


async def _json(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _normalize_code(code: Any) -> str:
    """성취기준 코드 표기를 통일합니다.

    DB는 '[10통과1-01-01]' 처럼 대괄호를 포함해 저장하지만, 모델은 대괄호를 떼거나
    공백을 넣어 돌려주는 경우가 있어 비교 전에 정규화합니다.
    """
    return re.sub(r'[\[\]\s]', '', str(code or ''))


def _codex_instance(request: Request) -> Optional[str]:
    """AI 생성에 쓸 Codex 세션. ChatGPT가 연결돼 있어야 한다."""
    session = codex_auth.auth_session_from_request(request)
    if not session:
        return None
    instance_id = session['instance_id']
    return instance_id if codex_generator.is_available(instance_id) else None


async def _offload(func, *args, **kwargs):
    """Codex를 부르는 동기 함수를 별도 스레드에서 돌립니다.

    codex_runner는 requests로 러너를 호출하고, 한 턴이 수십 초 걸립니다.
    async 라우트 안에서 그대로 부르면 그동안 이벤트 루프가 멈춰
    서버 전체가 응답하지 않습니다(다른 페이지로 이동조차 안 됩니다).
    예외는 그대로 다시 던져지므로 호출부의 try/except는 그대로 둡니다.
    """
    return await asyncio.to_thread(func, *args, **kwargs)


@router.get('/state')
def research_state(request: Request):
    """로드맵 대시보드가 한 번에 그릴 수 있도록 전체 상태를 반환합니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    profile = store.get_profile(user_id)
    framework = store.get_framework(user_id)
    grade_plans = store.list_grade_plans(user_id)
    subject_plans = store.list_subject_plans(user_id)

    return {
        'profile': profile.to_dict() if profile else None,
        'themes': [theme.to_dict() for theme in store.list_themes(user_id)],
        'framework': framework.to_dict() if framework else None,
        'grade_plans': [plan.to_dict() for plan in grade_plans],
        'subject_plans': [_plan_view(plan) for plan in subject_plans],
        'fixed': store.fixed_context(user_id),
    }


@router.post('/profile')
async def save_profile(request: Request):
    """Phase 1 프로파일 저장."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    payload = await _json(request)
    try:
        profile = store.save_profile(
            user_id,
            interests=payload.get('interests'),
            problem_statement=payload.get('problem_statement'),
            aspired_track=payload.get('aspired_track'),
            strength_subjects=payload.get('strength_subjects'),
            activity_history=payload.get('activity_history'),
            interview_state=payload.get('interview_state'),
            extra=payload.get('extra'),
        )
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'profile': profile.to_dict()}


@router.post('/themes')
async def save_theme_candidates(request: Request):
    """Phase 2 테마 후보를 저장합니다(2~3개)."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    payload = await _json(request)
    candidates = payload.get('candidates')
    if not isinstance(candidates, list) or not candidates:
        return _error('테마 후보를 1개 이상 보내주세요.', 422)
    try:
        themes = store.replace_theme_candidates(user_id, candidates)
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'themes': [theme.to_dict() for theme in themes]}


@router.post('/themes/{theme_id}/select')
def select_theme(theme_id: int, request: Request):
    """후보 중 하나를 고릅니다. 선택은 확정이 아니며 상태는 narrowing이 됩니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    try:
        theme = store.select_theme(user_id, theme_id)
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'theme': theme.to_dict()}


@router.post('/framework')
async def save_framework(request: Request):
    """Phase 3 연구 프레임 저장."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    payload = await _json(request)
    try:
        framework = store.save_framework(
            user_id,
            theme_id=payload.get('theme_id'),
            core_question=payload.get('core_question'),
            sub_areas=payload.get('sub_areas'),
            final_destination=payload.get('final_destination'),
        )
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'framework': framework.to_dict()}


@router.post('/grade-plans/{grade}')
async def save_grade_plan(grade: int, request: Request):
    """학년별 계획 저장. 학년은 1~3만 허용합니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    if grade not in (1, 2, 3):
        return _error('학년은 1, 2, 3 중 하나여야 합니다.', 422)

    payload = await _json(request)
    framework = store.get_framework(user_id)
    try:
        plan = store.upsert_grade_plan(
            user_id,
            framework.id if framework else None,
            grade,
            goal=payload.get('goal'),
            anchor_project=payload.get('anchor_project'),
            curriculum_alignment=payload.get('curriculum_alignment'),
        )
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'grade_plan': plan.to_dict()}


@router.post('/subject-plans')
async def save_subject_plan(request: Request):
    """Phase 5 과목별 세특 플랜 저장."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    payload = await _json(request)
    grade_plan_id = payload.get('grade_plan_id')
    subject = (payload.get('subject') or '').strip()
    if not grade_plan_id or not subject:
        return _error('grade_plan_id와 subject는 필수입니다.', 422)

    approach = payload.get('approach')
    if approach and approach not in SUBJECT_APPROACHES:
        return _error(f'approach는 {" 또는 ".join(SUBJECT_APPROACHES)} 여야 합니다.', 422)

    try:
        plan = store.upsert_subject_plan(
            user_id, int(grade_plan_id), subject,
            subject_uid=payload.get('subject_uid'),
            approach=approach,
            approach_rationale=payload.get('approach_rationale'),
            area_name=payload.get('area_name'),
            standard_codes=payload.get('standard_codes'),
            motivation=payload.get('motivation'),
            activity_design=payload.get('activity_design'),
        )
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'subject_plan': plan.to_dict()}


@router.post('/{entity}/{row_id}/status')
async def change_status(entity: str, row_id: int, request: Request):
    """Draft / Narrowing / Fixed 전이. fixed 해제는 narrowing으로만 가능합니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    table = STATUS_TABLES.get(entity)
    if not table:
        return _error('알 수 없는 항목 종류입니다.', 404)

    payload = await _json(request)
    target = payload.get('status')
    if target not in RESEARCH_STATUSES:
        return _error(f'status는 {", ".join(RESEARCH_STATUSES)} 중 하나여야 합니다.', 422)

    try:
        applied = store.set_status(table, row_id, user_id, target)
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'status': applied}


# ============ AI 파이프라인 (Phase 1~5) ============

def _require_ai(request: Request):
    """(user_id, codex_instance_id) 또는 에러 응답을 돌려줍니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return None, None, _error('로그인이 필요합니다.', 401)
    instance_id = _codex_instance(request)
    if not instance_id:
        return None, None, _error('ChatGPT 계정을 먼저 연결해 주세요.', 409)
    return user_id, instance_id, None


@router.post('/ai/interview')
async def ai_interview(request: Request):
    """Phase 1: 다층 인터뷰 다음 질문을 받습니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error
    payload = await _json(request)
    profile = store.get_profile(user_id)
    try:
        result = await _offload(
            research_pipeline.interview,
            instance_id,
            payload.get('history') or [],
            profile.to_dict() if profile else None,
        )
    except PipelineError as exc:
        return _error(exc.message, exc.status_code)

    # 인터뷰가 끝났다고 판단되면 프로파일 초안을 저장해 둔다.
    if result.get('is_complete') and isinstance(result.get('profile'), dict):
        draft = result['profile']
        try:
            store.save_profile(
                user_id,
                interests=draft.get('interests'),
                problem_statement=draft.get('problem_statement'),
                aspired_track=draft.get('aspired_track'),
                strength_subjects=draft.get('strength_subjects'),
                activity_history=draft.get('activity_history'),
                interview_state={'completed': True},
            )
        except ResearchStateError as exc:
            return _error(exc.message, exc.status_code)
    return result


# 온보딩 자유 답변을 규칙 기반으로 나눈다. AI 연결이 없어도 프로파일이 완성되어야 한다.
_SPLIT_RE = re.compile(r'[,\n·/]|그리고|하고')

# 학생이 문장으로 답해도 과목과 계열을 갈라내기 위한 사전.
# 문장을 통째로 두면 '지망 계열'과 '강점 교과'가 같은 값이 되어버린다.
_SUBJECT_WORDS = (
    '통합과학', '통합사회', '한국사', '생명과학', '지구과학', '제2외국어',
    '국어', '수학', '영어', '과학', '사회', '물리', '화학', '정보',
    '역사', '지리', '윤리', '경제', '음악', '미술', '체육', '한문',
)
_TRACK_WORDS = (
    '건축', '환경공학', '환경', '컴퓨터', '전자', '기계', '화공', '신소재',
    '생명공학', '간호', '약학', '의학', '수의학', '법학', '경영', '경제',
    '교육', '심리', '디자인', '공학', '자연과학', '인문', '사회과학', '예체능',
)


def _split_items(text: str, limit: int = 5) -> List[str]:
    parts = [part.strip(' .') for part in _SPLIT_RE.split(text or '')]
    return [part for part in parts if part][:limit]


def _match_words(text: str, words: tuple, limit: int) -> List[str]:
    """사전에 있는 표현만 뽑아낸다. 긴 표현부터 검사해 '환경공학'이 '환경'에 먹히지 않게 한다."""
    found: List[str] = []
    haystack = text or ''
    for word in words:
        if word in haystack and not any(word in picked for picked in found):
            found.append(word)
        if len(found) >= limit:
            break
    return found


# 메인 채팅이 학생을 다음 단계로 이끌 때 쓰는 안내문.
# message는 '무엇을 할지'를 설명하고, ask는 '지금 뭐라고 답하면 되는지'를 예시로 준다.
# ask 없이 설명만 주면 "어떻게 할까?" 같은 막연한 질문이 되어 학생이 답을 못 한다.
_STAGE_GUIDE = {
    'onboarding': {
        'title': '먼저 너를 알려줘',
        'message': '3년 계획을 세우려면 어떤 것에 끌리는지부터 알아야 해요. 네 가지만 물어볼게요.',
        'ask': '요즘 관심 가는 걸 한 줄로 말해줄래? 예: "도시가 왜 밤에도 안 식는지 궁금해"',
        'label': '시작하기',
        'href': '/welcome',
        'needs_ai': False,
    },
    'themes': {
        'title': '3년 테마를 만들 차례',
        # 처음 온 학생은 '테마'가 뭔지 모른다. 무엇이 몇 개 나오는지, 마음에 안 들면
        # 어떻게 되는지까지 말해 줘야 버튼을 누를 수 있다. 관심사는 next_step이
        # 프로파일에서 채워 넣는다({interests}) — 방금 적은 내용이 되비쳐야
        # 자기 얘기라는 감각이 생긴다.
        'message': '네가 적어 준 관심사({interests})로 3년 동안 이어갈 탐구 테마 후보를 '
                   '2~3개 만들어 볼게. 테마는 앞으로 모든 학년·과목 설계의 기준이 되는데, '
                   '마음에 드는 게 없으면 바꿔 달라고 하면 돼.',
        'ask': '준비되면 아래 버튼을 누르거나 "테마 만들어줘"라고 말해줘.',
        'label': '테마 후보 만들기',
        'endpoint': '/api/research/ai/themes',
        'needs_ai': True,
    },
    'select_theme': {
        'title': '테마를 하나 고르자',
        'message': '후보를 만들어 뒀어요. 고른 테마가 이후 모든 학년·과목 설계의 기준이 됩니다.',
        'ask': '마음에 드는 번호를 말해줘. 예: "2번으로 할래"',
        'label': '후보 보러 가기',
        'href': '/research',
        'needs_ai': False,
    },
    'framework': {
        'title': '3년을 학년별로 나누자',
        'message': '고른 테마로 핵심 질문을 세우고 1·2·3학년 계획과 앵커 프로젝트를 만들 거예요.',
        'ask': '"3년 계획 짜줘"라고 말해줘. 학년별로 하고 싶은 게 있으면 같이 알려줘.',
        'label': '3년 계획 만들기',
        'endpoint': '/api/research/ai/framework',
        'needs_ai': True,
    },
    'subjects': {
        'title': '과목별 세특을 설계하자',
        'message': '학년 앵커 프로젝트를 과목별 탐구 질문과 성취기준으로 풀어낼게요.',
        'ask': '"{grade}학년 세특 설계해줘"라고 말해줘. 특정 과목만 원하면 과목 이름도 같이 말해도 돼.',
        'label': '과목별 세특 설계',
        'endpoint': '/api/research/ai/subject-plans',
        'needs_ai': True,
    },
    'experiments': {
        'title': '설계한 세특을 실제로 해보자',
        'message': '설계만으로는 세특이 되지 않아요. 과목마다 실험을 직접 진행하면서 배우고, '
                   '그 과정을 그대로 보고서로 남깁니다.',
        'ask': '/research 에서 과목 카드의 「실험 진행」을 눌러 줘. '
               '{grade}학년 과목을 모두 끝내야 다음 학년 설계가 열려.',
        'label': '실험하러 가기',
        'href': '/research',
        'needs_ai': False,
    },
    'done': {
        'title': '3년 설계와 실험이 모두 끝났어요',
        'message': '학년마다 세특을 설계하고 실험까지 마쳤어요. 보고서는 과목 카드에서 열 수 있어요.',
        'ask': '고치고 싶은 게 있으면 말해줘. 예: "2학년을 더 실험 위주로 바꿔줘"',
        'label': '로드맵 보기',
        'href': '/research',
        'needs_ai': False,
    },
}


def _stage_choices(user_id: str, stage: str, extra: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """지금 단계에서 학생이 고를 수 있는 것들.

    프런트는 이걸 버튼으로 그리고, 누르면 `send`에 담긴 문장을 그대로 보낸다.
    즉 버튼은 말하기의 지름길일 뿐이라 서버에 새 명령 규약이 생기지 않는다.
    직접 타이핑해도 똑같이 동작한다.
    """
    if stage == 'select_theme':
        themes = store.list_themes(user_id)
        if not themes:
            return None
        return {
            'prompt': '어떤 테마로 3년을 끌고 갈까?',
            'options': [
                {'label': f'{index}. {theme.title}', 'send': f'{index}번으로 할래'}
                for index, theme in enumerate(themes, start=1)
            ] + [
                # 방향 조정은 후보를 본 지금이 적기다. 만들기 전에 물으면
                # 판단할 근거가 없다. 문구에는 목적어(테마)를 넣는다.
                {'label': '테마를 실험 위주로 다시 만들어줘',
                 'send': '실험 많이 하는 쪽으로 테마 다시 만들어줘'},
                {'label': '테마를 자료 조사 위주로 다시 만들어줘',
                 'send': '자료 조사 위주로 테마 다시 만들어줘'},
            ],
        }

    if stage == 'themes':
        # 실행 버튼 하나만 둔다. 전에는 '그냥 만들어줘/실험 위주/자료 조사 위주'를
        # 나란히 놨는데, 실행과 조건이 섞여 있어 처음 온 학생이 조건을 골라야만
        # 하는 줄 알았다. 방향 조정은 후보를 본 다음(select_theme)에 묻는다 —
        # 구체물을 본 뒤의 방향 선택은 쉽고, 보기 전의 방향 선택은 어렵다.
        return {
            'options': [
                {'label': '테마 후보 보기', 'send': '테마 만들어줘',
                 'aliases': ['테마 후보 보기', '테마 후보 만들어줘']},
            ],
        }

    if stage == 'framework':
        # 실행 버튼 하나만. '기본/실험 위주' 두 개를 나란히 놓으면 무슨 차이인지
        # 계획을 보기 전에는 알 수 없다(테마 단계에서 겪은 것과 같은 문제).
        # 방향 조정은 계획이 나온 다음(subjects 단계 선택지)에 붙인다.
        return {
            'options': [
                {'label': '3년 계획 짜줘', 'send': '3년 계획 짜줘'},
            ],
        }

    if stage == 'subjects':
        grade = extra.get('grade') or 1
        options = [
            {'label': f'{grade}학년 세특 설계해줘',
             'send': f'{grade}학년 세특 설계해줘',
             # 예전 문구와 자연스럽게 나오는 표현도 같은 행동으로 받는다.
             'aliases': [f'{grade}학년 세특 짜줘', f'{grade}학년 세특 만들어줘']},
        ]
        # 3년 계획을 막 본 시점(1학년 설계 전)에만 계획 조정 버튼을 붙인다.
        # 계획을 봤으니 이제 '실험 위주'가 무슨 뜻인지 판단할 근거가 있다.
        # 2·3학년쯤에는 이미 설계가 얹혀 있어 계획을 갈아엎는 버튼이 위험하다.
        if grade == 1:
            options.append({'label': '3년 계획을 실험 위주로 다시 짜줘',
                            'send': '실험 위주로 3년 계획 다시 짜줘'})
        return {
            'prompt': f'{grade}학년 세특을 설계할까?',
            'options': options,
        }

    return None


# 곧바로 실행했을 때 돌려줄 말. 모델을 거치지 않으므로 여기서 직접 쓴다.
_DIRECT_REPLY = {
    'create_themes': '테마 후보를 만들었어. 마음에 드는 번호를 골라줘.',
    'select_theme': '그 테마로 정할게. 이제 3년 계획을 세울 수 있어.',
    'create_framework': '3년 계획을 만들었어. 학년별 목표와 앵커 프로젝트를 로드맵에 넣어 뒀어.',
    'create_subjects': '과목별 세특을 설계했어. 로드맵으로 옮겨 줄 테니 직접 보고 이상한 데가 없는지 봐줘.',
}


def _clip_line(text: Any, limit: int = 140) -> str:
    text = str(text or '').strip().replace('\n', ' ')
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _outcome_summary(action: str, outcome: Dict[str, Any]) -> str:
    """방금 만든 것을 채팅에 보여줄 요약. "만들었어"라고만 하고 안 보여주면
    학생은 판단할 근거 없이 번호를 골라야 한다(실제로 그런 화면이 나왔다).
    """
    if action == 'create_themes':
        themes = outcome.get('themes') or []
        return '\n\n'.join(
            f"**{index}. {theme.get('title')}**\n{_clip_line(theme.get('rationale'))}"
            for index, theme in enumerate(themes, start=1))

    if action == 'select_theme':
        theme = outcome.get('theme') or {}
        return f"**{theme.get('title')}**" if theme.get('title') else ''

    if action == 'create_framework':
        framework = outcome.get('framework') or {}
        lines = []
        if framework.get('core_question'):
            lines.append(f"핵심 질문 — **{_clip_line(framework['core_question'])}**")
        for plan in sorted(outcome.get('grade_plans') or [],
                           key=lambda item: item.get('grade') or 0):
            anchor = plan.get('anchor_project') or {}
            anchor_title = anchor.get('title') if isinstance(anchor, dict) else anchor
            lines.append(f"**{plan.get('grade')}학년** · {_clip_line(plan.get('goal'), 90)}"
                         + (f"\n   앵커: {_clip_line(anchor_title, 90)}" if anchor_title else ''))
        return '\n'.join(lines)

    if action == 'create_subjects':
        subjects = [item.get('subject') for item in outcome.get('subject_plans') or []
                    if item.get('subject')]
        return f"설계한 과목: {', '.join(subjects)}" if subjects else ''

    return ''


def _action_reply(action: str, outcome: Dict[str, Any]) -> str:
    """직접 실행한 행동의 응답. 만든 내용을 본문에 함께 싣는다."""
    base = _DIRECT_REPLY.get(action, '처리했어.')
    summary = _outcome_summary(action, outcome)
    if not summary:
        return base
    if action == 'create_themes':
        return ('테마 후보를 만들었어. 왜 너에게 맞는지도 같이 봐줘.\n\n'
                f'{summary}\n\n마음에 드는 번호를 골라줘. '
                '다 별로면 방향을 바꿔서 다시 만들어 달라고 해도 돼.')
    if action == 'select_theme':
        return f'{summary} 테마로 정할게. 이제 3년 계획을 세울 수 있어.'
    if action == 'create_framework':
        return (f'3년 계획을 만들었어.\n\n{summary}\n\n'
                '자세한 건 /research 로드맵에서 볼 수 있어.')
    if action == 'create_subjects':
        return (f'과목별 세특을 설계했어. {summary}\n\n'
                '로드맵으로 옮겨 줄 테니 직접 보고 이상한 데가 없는지 봐줘.')
    return f'{base}\n\n{summary}'

# AI 없이도 되는 행동. 테마 고르기는 저장된 후보 중 하나를 지정하는 일이라 생성이 필요 없다.
_ACTIONS_WITHOUT_AI = {'select_theme'}


def _direct_action(user_id: str, stage: str, extra: Dict[str, Any],
                   message: str) -> Optional[tuple]:
    """버튼이 보낸 문장이면 모델 판단을 건너뛰고 바로 실행한다.

    모델에게 맡기면 "3년 계획을 만들게"라고 답만 하고 실제로는 아무것도
    만들지 않는 일이 생긴다. 화면이 '이렇게 말하라'고 알려준 문장만큼은
    말한 대로 실행되어야 한다. 자유롭게 쓴 문장은 그대로 모델이 판단한다.
    """
    choices = _stage_choices(user_id, stage, extra)
    if not choices:
        return None

    squashed = re.sub(r'\s+', '', message)

    def _says(item: Dict[str, Any]) -> bool:
        """버튼 문장이거나, 같은 뜻으로 등록해 둔 다른 표현이면 같은 것으로 본다."""
        wordings = [item['send'], *(item.get('aliases') or [])]
        return any(re.sub(r'\s+', '', text) == squashed for text in wordings)

    option = next((item for item in choices['options'] if _says(item)), None)
    if not option:
        return None

    # 조건이 붙은 선택지는 그 조건을 note로 넘겨 생성에 반영한다.
    note = option['label'] if option['send'] != option['label'] else ''

    if stage == 'select_theme':
        return ('select_theme', re.sub(r'[^0-9]', '', option['send']), '')
    if stage == 'themes':
        return ('create_themes', '', note)
    if stage == 'framework':
        return ('create_framework', '', note)
    if stage == 'subjects':
        return ('create_subjects', str(extra.get('grade') or ''), '')
    return None


def _resolve_stage(user_id: str) -> tuple:
    """지금 학생이 서 있는 지점과 그때 필요한 값을 돌려줍니다."""
    if not store.get_profile(user_id):
        return 'onboarding', {}

    themes = store.list_themes(user_id)
    if not themes:
        return 'themes', {}

    selected = store.selected_theme(user_id)
    if not selected:
        return 'select_theme', {}

    plans = store.list_grade_plans(user_id)
    if not plans:
        return 'framework', {}

    # 학년은 순서대로 하나씩 끝낸다.
    # 한 학년은 '세특 설계 → 과목별 실험 완료'까지 가야 끝난 것으로 보고,
    # 그래야 다음 학년 설계가 열린다. 설계만 해두고 다음 학년으로 넘어가면
    # 실험이 밀려 3년치 설계만 남기 때문이다.
    for plan in sorted(plans, key=lambda item: item.grade):
        subjects = store.list_subject_plans(user_id, plan.id)
        if not subjects:
            return 'subjects', {'grade': plan.grade}
        remaining = [item for item in subjects if item.experiment_status != 'done']
        if remaining:
            return 'experiments', {
                'grade': plan.grade,
                'remaining': [item.subject for item in remaining],
                'total': len(subjects),
            }
    return 'done', {}


@router.get('/next')
def next_step(request: Request):
    """메인 채팅이 다음 단계를 안내하기 위해 조회합니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    stage, extra = _resolve_stage(user_id)
    guide = dict(_STAGE_GUIDE[stage])
    guide.update(extra)
    guide['stage'] = stage
    # 예시 문장에 학년이 들어가는 단계가 있다. 아직 모르면 자리표시를 지운다.
    if '{grade}' in (guide.get('ask') or ''):
        guide['ask'] = guide['ask'].replace('{grade}', str(extra.get('grade') or '1'))
    # 테마 안내에는 방금 온보딩에서 적은 관심사를 되비춘다. 자기가 쓴 말이
    # 그대로 돌아와야 "내 얘기로 만드는 중"이라는 감각이 생긴다.
    if '{interests}' in (guide.get('message') or ''):
        profile = store.get_profile(user_id)
        interests = ', '.join((profile.interests if profile else None) or [])
        guide['message'] = guide['message'].replace(
            '{interests}', interests or '네 프로필')
    # 로드맵으로 보낼 때는 최상단이 아니라 지금 다루는 학년 자리로 데려간다.
    if guide.get('href') == '/research' and extra.get('grade'):
        guide['href'] = _grade_anchor(extra['grade'])
    guide['choices'] = _stage_choices(user_id, stage, extra)
    # 이 단계가 AI를 쓰는데 ChatGPT가 연결돼 있지 않으면 프런트가 연결을 먼저 요청한다.
    guide['ai_connected'] = bool(_codex_instance(request))
    guide['ai_configured'] = codex_runner.is_configured()
    return guide


@router.post('/onboarding')
async def onboarding(request: Request):
    """가입 직후 온보딩 답변으로 프로파일을 만듭니다.

    ChatGPT가 연결돼 있으면 답변을 다듬어 저장하고, 없으면 규칙 기반으로 나눕니다.
    AI가 없어도 온보딩이 끝까지 진행되어야 하므로 여기서는 AI를 요구하지 않습니다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    payload = await _json(request)
    answers = {key: (payload.get(key) or '').strip()
               for key in ('interests', 'problem', 'track', 'activity')}
    if not answers['interests'] and not answers['problem']:
        return _error('관심 있는 것이나 풀고 싶은 문제 중 하나는 알려주세요.', 422)

    fields = None
    instance_id = _codex_instance(request)
    if instance_id:
        try:
            fields = await _offload(
                research_pipeline.refine_onboarding, instance_id, answers)
        except PipelineError as exc:
            # AI 정제가 실패해도 온보딩을 막지 않는다.
            logger.info('[ONBOARDING] AI 정제 실패, 규칙 기반으로 진행: %s', exc.message)

    if not fields:
        subjects = _match_words(answers['track'], _SUBJECT_WORDS, 4)
        tracks = _match_words(answers['track'], _TRACK_WORDS, 2)
        fields = {
            'interests': _split_items(answers['interests'], 3),
            'problem_statement': answers['problem'] or answers['interests'],
            # 사전에 걸리는 표현이 없으면 학생이 쓴 문장을 그대로 남긴다.
            'aspired_track': ' · '.join(tracks) or answers['track'],
            'strength_subjects': subjects,
            'activity_history': _split_items(answers['activity'], 5),
        }

    try:
        profile = store.save_profile(
            user_id,
            interests=fields.get('interests'),
            problem_statement=fields.get('problem_statement'),
            aspired_track=fields.get('aspired_track'),
            strength_subjects=fields.get('strength_subjects'),
            activity_history=fields.get('activity_history'),
            interview_state={'source': 'onboarding', 'refined_by_ai': bool(instance_id)},
        )
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'profile': profile.to_dict(), 'refined_by_ai': bool(instance_id)}


@router.post('/ai/themes')
async def ai_themes(request: Request):
    """Phase 2: 테마 후보를 생성하고 저장합니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    profile = store.get_profile(user_id)
    if not profile:
        return _error('먼저 학생 프로파일을 만들어 주세요.', 409)

    try:
        result = await _offload(
            research_pipeline.propose_themes,
            instance_id, profile.to_dict(), store.fixed_context(user_id))
        candidates = result.get('candidates') or []
        if not candidates:
            return _error('테마 후보를 만들지 못했습니다. 다시 시도해 주세요.', 502)
        themes = store.replace_theme_candidates(user_id, candidates)
    except PipelineError as exc:
        return _error(exc.message, exc.status_code)
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)
    return {'themes': [theme.to_dict() for theme in themes]}


@router.post('/ai/framework')
async def ai_framework(request: Request):
    """Phase 3: 연구 프레임과 1·2·3학년 계획을 생성하고 저장합니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    theme = store.selected_theme(user_id)
    if not theme:
        return _error('먼저 테마를 선택해 주세요.', 409)
    profile = store.get_profile(user_id)

    try:
        result = await _offload(
            research_pipeline.design_framework,
            instance_id, theme.to_dict(),
            profile.to_dict() if profile else {},
            store.fixed_context(user_id),
        )
        framework = store.save_framework(
            user_id,
            theme_id=theme.id,
            core_question=result.get('core_question'),
            sub_areas=result.get('sub_areas'),
            final_destination=result.get('final_destination'),
        )
        for plan in result.get('grade_plans') or []:
            grade = plan.get('grade')
            if grade not in (1, 2, 3):
                continue
            store.upsert_grade_plan(
                user_id, framework.id, grade,
                goal=plan.get('goal'),
                anchor_project=plan.get('anchor_project'),
                curriculum_alignment=[plan.get('curriculum_rationale')],
            )
    except PipelineError as exc:
        return _error(exc.message, exc.status_code)
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)

    return {
        'framework': framework.to_dict(),
        'grade_plans': [plan.to_dict() for plan in store.list_grade_plans(user_id)],
    }


@router.post('/ai/narrow')
async def ai_narrow(request: Request):
    """Phase 4: 대화형 구체화. AI가 비현실적 계획에 대안을 제시합니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error
    payload = await _json(request)
    message = (payload.get('message') or '').strip()
    if not message:
        return _error('요청 내용을 입력해 주세요.', 422)
    try:
        result = await _offload(
            research_pipeline.narrow,
            instance_id,
            payload.get('target') or '현재 계획',
            payload.get('current') or '(내용 없음)',
            message,
            store.fixed_context(user_id),
        )
    except PipelineError as exc:
        return _error(exc.message, exc.status_code)
    return result


@router.post('/ai/subject-plans')
async def ai_subject_plans(request: Request):
    """Phase 5: 앵커 프로젝트 확정 + 과목별 세특 플랜 생성."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    payload = await _json(request)
    grade = int(payload.get('grade') or 1)
    if grade not in (1, 2, 3):
        return _error('학년은 1, 2, 3 중 하나여야 합니다.', 422)

    grade_plan = next((plan for plan in store.list_grade_plans(user_id)
                       if plan.grade == grade), None)
    if not grade_plan:
        return _error(f'{grade}학년 계획을 먼저 만들어 주세요.', 409)

    # 성취기준은 DB에서 뽑아 프롬프트에 넣는다. 목록 밖 코드는 쓰지 못하게 한다.
    subject_uids = payload.get('subject_uids') or []
    standards: List[Dict[str, Any]] = []
    if subject_uids:
        for uid in subject_uids[:12]:
            standards.extend(db.get_curriculum_standards(subject_uid=uid))
    else:
        grade_band = '1' if grade == 1 else '2-3'
        for subject in db.get_curriculum_subjects(grade_band=grade_band)[:8]:
            standards.extend(db.get_curriculum_standards(
                subject_uid=subject['subject_uid']))

    # 표기 차이로 정상 코드가 버려지지 않도록 정규화한 키로 대조한다.
    allowed_codes = {_normalize_code(row['code']): row for row in standards}
    dropped: List[str] = []
    try:
        result = await _offload(
            research_pipeline.design_subject_plans,
            instance_id, grade, grade_plan.to_dict(), standards,
            store.fixed_context(user_id), subjects=payload.get('subjects'),
        )
        saved = []
        for plan in result.get('subject_plans') or []:
            subject = (plan.get('subject') or '').strip()
            if not subject:
                continue
            # 지어낸 성취기준 코드는 버리고, 살아남은 코드는 DB 표기로 되돌린다.
            codes = []
            for raw_code in plan.get('standard_codes') or []:
                row = allowed_codes.get(_normalize_code(raw_code))
                if row:
                    codes.append(row['code'])
                else:
                    dropped.append(str(raw_code))
            match = next((allowed_codes[_normalize_code(code)] for code in codes), None)
            saved.append(store.upsert_subject_plan(
                user_id, grade_plan.id, subject,
                subject_uid=match['subject_uid'] if match else None,
                approach=plan.get('approach'),
                approach_rationale=plan.get('approach_rationale'),
                area_name=plan.get('area_name'),
                standard_codes=codes,
                motivation=plan.get('motivation'),
                activity_design=plan.get('activity_design'),
            ))
    except PipelineError as exc:
        return _error(exc.message, exc.status_code)
    except ResearchStateError as exc:
        return _error(exc.message, exc.status_code)

    if dropped:
        # 목록에 없는 코드를 모델이 만들어냈다는 뜻이라 조용히 넘기지 않는다.
        logger.warning('[RESEARCH] 목록 밖 성취기준 코드 %s건 무시: %s', len(dropped), dropped[:5])

    return {
        'anchor_project': result.get('anchor_project'),
        'subject_plans': [plan.to_dict() for plan in saved],
        'dropped_codes': dropped,
    }


def _execute_run(user_id: str, instance_id: str, run_id: int,
                 plan: Dict[str, Any], standards: List[Dict[str, Any]],
                 fixed: Dict[str, Any]) -> None:
    """백그라운드에서 Codex 실행을 끝내고 결과를 기록합니다."""
    try:
        result = research_pipeline.run_experiment(instance_id, plan, standards, fixed)
    except PipelineError as exc:
        store.complete_agent_run(user_id, run_id, error=exc.message)
        return
    except Exception as exc:  # noqa: BLE001 - 백그라운드에서 조용히 죽지 않게 한다.
        logger.warning('[RESEARCH] 실행 실패: %s', type(exc).__name__)
        store.complete_agent_run(user_id, run_id, error='실행 중 오류가 발생했습니다.')
        return

    for step in result.get('steps') or []:
        store.append_agent_step(user_id, run_id, {
            'label': step.get('label'), 'detail': step.get('detail'), 'state': 'done',
        })
    store.complete_agent_run(user_id, run_id, report_markdown=result.get('report_markdown'))


@router.post('/ai/run/{subject_plan_id}')
async def ai_run_experiment(subject_plan_id: int, request: Request):
    """Agentic 실행을 시작합니다.

    Codex 한 턴이 40초를 넘기고 중간 이벤트도 오지 않으므로, 응답을 붙잡지 않고
    바로 run을 돌려줍니다. 진행 상황은 GET /runs/{run_id} 로 폴링합니다.
    """
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    plan = next((item for item in store.list_subject_plans(user_id)
                 if item.id == subject_plan_id), None)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)

    standards = (db.get_curriculum_standards(codes=plan.standard_codes)
                 if plan.standard_codes else [])
    run = store.create_agent_run(user_id, subject_plan_id=plan.id, run_type='experiment')

    asyncio.create_task(asyncio.to_thread(
        _execute_run, user_id, instance_id, run.id,
        plan.to_dict(), standards, store.fixed_context(user_id),
    ))
    return {'run': run.to_dict()}


@router.get('/runs/{run_id}')
def get_run(run_id: int, request: Request):
    """실행 진행 상황 폴링."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    run = store.get_agent_run(user_id, run_id)
    if not run:
        return _error('실행 기록을 찾을 수 없습니다.', 404)
    return {'run': run.to_dict()}


@router.get('/runs')
def list_runs(request: Request, subject_plan_id: Optional[int] = None):
    """Agentic 실행 기록 목록."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    return {'runs': [run.to_dict() for run in store.list_agent_runs(user_id, subject_plan_id)]}


# ---------- 설계 대화방 ----------
#
# 설계 대화(세특·3년 계획 논의)도 사이드바 HISTORY의 한 칸이다.
# 말 자체는 research_messages에 남고, 대화방(제목·순서)은 chat_sessions가 들고 있다.

def _design_rooms(user_id: str) -> List[Any]:
    """이 학생의 설계 대화방을 만든 순서대로."""
    rooms = db.get_chat_sessions(user_id, limit=100, folder=FOLDER_DESIGN)
    return sorted(rooms, key=lambda room: room.created_at or '')


def _design_session(user_id: str, session_id: Optional[str] = None) -> tuple:
    """설계 대화방을 정합니다. 없으면 이 시점에 만듭니다.

    (session_id, include_orphans)를 돌려줍니다. include_orphans는 대화방이 생기기
    전에 쌓인 기록을 함께 보여줄지로, 첫 대화방에서만 참입니다.
    """
    rooms = _design_rooms(user_id)
    if session_id:
        found = next((room for room in rooms if room.id == session_id), None)
        if found:
            return found.id, rooms[0].id == found.id
    if rooms:
        # 마지막으로 쓴 방을 이어서 쓴다.
        latest = max(rooms, key=lambda room: room.updated_at or '')
        return latest.id, rooms[0].id == latest.id
    # 방이 하나도 없다면 폴더가 생기기 전부터 해오던 대화가 여기로 들어온다.
    # 그 대화는 이미 어딘가까지 가 있으므로, 처음부터 지금까지의 요약을 이름으로 단다.
    created = db.create_chat_session(user_id, _design_title(user_id), [], folder=FOLDER_DESIGN)
    return created.id, True


def _design_title(user_id: str) -> str:
    """설계 대화방 이름 = 그 대화가 어디까지 갔는지의 요약.

    모델을 한 번 더 부르지 않는다. 이 대화에서 정해진 것(테마 → 3년 계획 → N학년 세특)이
    곧 대화 내용이므로, 지금 상태에서 그대로 뽑아 쓴다.
    """
    theme = store.selected_theme(user_id)
    head = theme.title if theme else ('테마 고르기' if store.list_themes(user_id) else None)

    tail = None
    graded = [plan for plan in store.list_grade_plans(user_id)
              if store.list_subject_plans(user_id, plan.id)]
    if graded:
        tail = f'{max(plan.grade for plan in graded)}학년 세특'
    elif store.list_grade_plans(user_id):
        tail = '3년 계획'
    elif store.get_profile(user_id) and not head:
        tail = '출발점 정리'

    name = ' · '.join([part for part in (head, tail) if part])
    return name[:60] or _DESIGN_DEFAULT_TITLE


def _touch_design_room(user_id: str, session_id: str) -> None:
    """대화 한 턴이 끝날 때마다 이름과 순서를 지금 상태에 맞춘다."""
    try:
        db.update_chat_session(session_id, user_id, title=_design_title(user_id))
    except Exception as exc:  # noqa: BLE001 - 이름을 못 고쳐도 대화는 계속돼야 한다.
        logger.info('[RESEARCH] 설계 대화방 갱신 실패: %s', type(exc).__name__)


def _state_summary(user_id: str) -> str:
    """AI가 지금 상황을 알 수 있도록 현재 데이터를 짧게 요약합니다."""
    lines = []
    profile = store.get_profile(user_id)
    if profile:
        lines.append(f"프로파일: {profile.problem_statement or '-'} "
                     f"(관심 {', '.join(profile.interests or []) or '-'})")
    themes = store.list_themes(user_id)
    if themes:
        lines.append('테마 후보:')
        for number, theme in enumerate(themes, start=1):
            mark = ' <- 선택됨' if theme.is_selected else ''
            lines.append(f'  {number}) {theme.title}{mark}')
    for plan in store.list_grade_plans(user_id):
        subjects = store.list_subject_plans(user_id, plan.id)
        anchor_project = (plan.anchor_project or {}).get('title') or '-'
        lines.append(f"{plan.grade}학년: {plan.goal or '-'} / 앵커 {anchor_project} / "
                     f"세특 {len(subjects)}개")
    return '\n'.join(lines) or '아직 아무것도 없다.'


def _run_action(user_id: str, instance_id: str,
                action: str, target: str, note: str) -> Dict[str, Any]:
    """AI가 고른 행동을 실제로 수행합니다. 학생이 말한 조건(note)을 그대로 넘깁니다."""
    if action == 'create_themes':
        profile = store.get_profile(user_id)
        if not profile:
            return {'error': '먼저 프로파일을 만들어야 해요.'}
        result = research_pipeline.propose_themes(
            instance_id, profile.to_dict(), store.fixed_context(user_id), note=note)
        themes = store.replace_theme_candidates(user_id, result.get('candidates') or [])
        return {'done': 'create_themes', 'themes': [t.to_dict() for t in themes]}

    if action == 'select_theme':
        themes = store.list_themes(user_id)
        chosen = None
        digits = re.sub(r'[^0-9]', '', target or '')
        if digits and 1 <= int(digits) <= len(themes):
            chosen = themes[int(digits) - 1]
        else:
            chosen = next((t for t in themes if target and target in t.title), None)
        if not chosen:
            return {'error': '어떤 후보인지 알 수 없었어요. 번호로 알려주세요.'}
        theme = store.select_theme(user_id, chosen.id)
        return {'done': 'select_theme', 'theme': theme.to_dict()}

    if action == 'create_framework':
        theme = store.selected_theme(user_id)
        if not theme:
            return {'error': '먼저 테마를 골라야 해요.'}
        profile = store.get_profile(user_id)
        result = research_pipeline.design_framework(
            instance_id, theme.to_dict(), profile.to_dict() if profile else {},
            store.fixed_context(user_id), note=note)
        framework = store.save_framework(
            user_id, theme_id=theme.id,
            core_question=result.get('core_question'),
            sub_areas=result.get('sub_areas'),
            final_destination=result.get('final_destination'))
        for plan in result.get('grade_plans') or []:
            if plan.get('grade') in (1, 2, 3):
                store.upsert_grade_plan(
                    user_id, framework.id, plan['grade'],
                    goal=plan.get('goal'), anchor_project=plan.get('anchor_project'),
                    curriculum_alignment=[plan.get('curriculum_rationale')])
        # 만든 것을 채팅이 보여줄 수 있게 내용까지 돌려준다. "만들었어"라는 말만
        # 돌아오면 학생은 로드맵으로 건너가야만 무엇이 생겼는지 안다.
        return {'done': 'create_framework',
                'framework': framework.to_dict(),
                'grade_plans': [p.to_dict() for p in store.list_grade_plans(user_id)]}

    if action == 'create_subjects':
        digits = re.sub(r'[^0-9]', '', target or '')
        grade = int(digits) if digits in ('1', '2', '3') else None
        plans = store.list_grade_plans(user_id)
        plan = (next((p for p in plans if p.grade == grade), None) if grade
                else next((p for p in plans if not store.list_subject_plans(user_id, p.id)), None))
        if not plan:
            return {'error': '어느 학년인지 알 수 없었어요.'}
        return _build_subject_plans(user_id, instance_id, plan, note)

    return {}


def _build_subject_plans(user_id: str, instance_id: str, plan, note: str) -> Dict[str, Any]:
    grade_band = '1' if plan.grade == 1 else '2-3'
    standards: List[Dict[str, Any]] = []
    for subject in db.get_curriculum_subjects(grade_band=grade_band)[:8]:
        standards.extend(db.get_curriculum_standards(subject_uid=subject['subject_uid']))

    allowed = {_normalize_code(row['code']): row for row in standards}
    result = research_pipeline.design_subject_plans(
        instance_id, plan.grade, plan.to_dict(), standards,
        store.fixed_context(user_id), note=note)

    saved = []
    for item in result.get('subject_plans') or []:
        subject = (item.get('subject') or '').strip()
        if not subject:
            continue
        codes = [allowed[_normalize_code(c)]['code'] for c in (item.get('standard_codes') or [])
                 if _normalize_code(c) in allowed]
        match = next((allowed[_normalize_code(c)] for c in codes), None)
        saved.append(store.upsert_subject_plan(
            user_id, plan.id, subject,
            subject_uid=match['subject_uid'] if match else None,
            approach=item.get('approach'),
            approach_rationale=item.get('approach_rationale'),
            area_name=item.get('area_name'),
            standard_codes=codes,
            motivation=item.get('motivation'),
            activity_design=item.get('activity_design')))
    # 세특은 만들고 끝이 아니라 학생이 직접 봐야 한다.
    # 채팅에 목록을 늘어놓는 대신 로드맵으로 보내 눈으로 확인하고 진단하게 한다.
    # 최상단이 아니라 방금 설계한 학년 자리로 데려간다.
    return {'done': 'create_subjects', 'grade': plan.grade,
            'redirect': _grade_anchor(plan.grade),
            'subject_plans': [p.to_dict() for p in saved]}


def _chat_turn(user_id: str, instance_id: Optional[str], stage: str,
               extra: Dict[str, Any], message: str,
               history: List[Dict[str, Any]],
               session_id: Optional[str] = None) -> Dict[str, Any]:
    """대화 한 턴을 끝까지 처리하고 답변까지 저장합니다.

    전부 동기 코드라 스레드에서 돌립니다. 답변을 DB에 남기는 일까지 이 안에서
    끝나므로, 학생이 도중에 새로고침해 요청이 끊겨도 결과가 사라지지 않습니다.

    성공하면 {'ok': True, 'payload': ...}, 실패하면 {'ok': False, ...}를 돌려줍니다.
    HTTP 응답으로 바꾸는 일은 호출부(_chat_response)가 맡습니다.
    """
    def _reply(reply: str, action: str, outcome: Dict[str, Any]) -> Dict[str, Any]:
        """행동을 끝낸 뒤의 응답. 단계와 선택지는 항상 결과 기준으로 다시 계산한다."""
        after_stage, after_extra = _resolve_stage(user_id)
        db.add_research_message(user_id, 'assistant', reply, action, session_id=session_id)
        if session_id:
            _touch_design_room(user_id, session_id)
        return {'ok': True, 'payload': {
            'reply': reply,
            'action': action,
            'note': '',
            'session_id': session_id,
            'stage': after_stage,
            'stage_changed': after_stage != stage,
            'outcome': outcome,
            'choices': _stage_choices(user_id, after_stage, after_extra),
        }}

    # 화면이 알려준 문장은 말한 대로 실행한다(모델 판단을 기다리지 않는다).
    direct = _direct_action(user_id, stage, extra, message)
    if direct and (direct[0] in _ACTIONS_WITHOUT_AI or instance_id):
        action, target, note = direct
        try:
            outcome = _run_action(user_id, instance_id, action, target, note)
        except (PipelineError, ResearchStateError) as exc:
            outcome = {'error': exc.message, 'error_kind': getattr(exc, 'kind', None)}
        return _reply(outcome.get('error') or _action_reply(action, outcome),
                      action, outcome)

    if not instance_id:
        reply = ('지금은 AI 기능을 쓸 수 없어요. 관리자에게 문의해 주세요.'
                 if not codex_runner.is_configured()
                 else 'ChatGPT 계정을 연결하면 이어서 도와줄게요. 네 계정의 사용량으로 동작해요. 연결할까요?')
        action = 'none' if not codex_runner.is_configured() else 'connect_chatgpt'
        db.add_research_message(user_id, 'assistant', reply, action, session_id=session_id)
        return {'ok': True, 'payload': {'reply': reply, 'action': action, 'stage': stage,
                                        'session_id': session_id}}

    try:
        turn = research_pipeline.converse(
            instance_id, message, history,
            stage, _state_summary(user_id), store.fixed_context(user_id))
    except PipelineError as exc:
        return {'ok': False, 'error': exc.message, 'status': exc.status_code,
                'error_kind': getattr(exc, 'kind', None)}

    action = turn.get('action') or 'none'
    outcome: Dict[str, Any] = {}
    if action not in ('none', 'open_research', 'connect_chatgpt'):
        try:
            outcome = _run_action(user_id, instance_id, action,
                                  turn.get('target') or '', turn.get('note') or '')
        except (PipelineError, ResearchStateError) as exc:
            outcome = {'error': exc.message, 'error_kind': getattr(exc, 'kind', None)}

    next_stage, next_extra = _resolve_stage(user_id)
    # 모델이 자유 문장으로 답해도, 방금 만든 내용은 채팅에 함께 보여야 한다.
    reply = turn.get('reply') or ''
    summary = _outcome_summary(action, outcome) if not outcome.get('error') else ''
    if summary and summary not in reply:
        reply = f'{reply}\n\n{summary}'.strip()
    db.add_research_message(user_id, 'assistant', reply, action,
                            session_id=session_id)
    if session_id:
        _touch_design_room(user_id, session_id)
    return {'ok': True, 'payload': {
        'reply': reply,
        'action': action,
        'note': turn.get('note') or '',
        'session_id': session_id,
        'stage': next_stage,
        'stage_changed': next_stage != stage,
        'outcome': outcome,
        # 행동이 끝난 뒤 상태 기준으로 만든다. 방금 테마를 만들었으면 곧바로 고를 수 있다.
        'choices': _stage_choices(user_id, next_stage, next_extra),
    }}


def _job_result(task: 'asyncio.Task') -> Dict[str, Any]:
    """끝난 작업의 결과. 예상 못 한 예외도 화면에 보일 말로 바꿔 돌려준다."""
    try:
        return task.result()
    except Exception as exc:  # noqa: BLE001 - 백그라운드에서 조용히 죽지 않게 한다.
        logger.warning('[RESEARCH] 대화 처리 실패: %s', type(exc).__name__)
        return {'ok': False, 'error': '처리 중 오류가 발생했습니다.', 'status': 500}


def _chat_response(result: Dict[str, Any], **extra: Any):
    """_chat_turn의 결과를 HTTP 응답으로 바꿉니다."""
    if not result.get('ok'):
        return _error(result.get('error') or '처리 중 오류가 발생했습니다.',
                      result.get('status') or 500, result.get('error_kind'))
    return {**result['payload'], **extra}


def _drop_stale_jobs() -> None:
    """폴링하러 돌아오지 않은 작업 기록을 치웁니다(탭을 닫아 버린 경우)."""
    limit = time.time() - _CHAT_JOB_TTL_SECONDS
    for key in [k for k, job in _CHAT_JOBS.items()
                if job['at'] < limit and job['task'].done()]:
        _CHAT_JOBS.pop(key, None)


def _job_key(user_id: str, room: str) -> str:
    """대화방마다 따로 센다. 연구 서사 대화와 실험 대화가 서로를 막으면 안 된다."""
    return f'{room}::{user_id}'


def _user_busy(user_id: str) -> bool:
    """이 학생의 턴이 어느 방에서든 돌고 있는가.

    러너는 로그인 하나당 한 번에 한 턴만 돌린다. 방을 나눠 두었어도 설계 대화와
    실험 대화가 동시에 나가면 러너가 뒤엣것을 거절한다. 그 거절을 받고 나서
    알려주는 것보다, 여기서 미리 막고 기다리라고 말하는 편이 낫다.
    """
    suffix = f'::{user_id}'
    return any(not job['task'].done()
               for key, job in _CHAT_JOBS.items() if key.endswith(suffix))


async def _start_chat_job(user_id: str, room: str, func, *args, **info):
    """긴 대화 턴을 백그라운드로 돌리고, 잠깐 기다려 본 결과를 돌려줍니다.

    그 안에 끝나면 그 자리에서 결과를, 아니면 pending을 돌려줍니다.
    새로고침으로 화면이 날아가도 작업은 계속되고, 나중에 _poll_chat_job으로 받아 갑니다.
    """
    key = _job_key(user_id, room)
    task = asyncio.create_task(asyncio.to_thread(func, *args))
    _CHAT_JOBS[key] = {'task': task, 'at': time.time(), **info}

    await asyncio.wait({task}, timeout=_CHAT_INLINE_WAIT_SECONDS)
    if not task.done():
        return {'pending': True, **info}

    _CHAT_JOBS.pop(key, None)
    return _chat_response(_job_result(task))


def _poll_chat_job(user_id: str, room: str):
    """진행 중인 턴이 있는지 확인하고, 끝나 있으면 결과를 넘겨줍니다(한 번만)."""
    key = _job_key(user_id, room)
    job = _CHAT_JOBS.get(key)
    if not job:
        return {'pending': False, 'idle': True}
    if not job['task'].done():
        info = {k: v for k, v in job.items() if k not in ('task', 'at')}
        return {'pending': True, **info}

    _CHAT_JOBS.pop(key, None)
    return _chat_response(_job_result(job['task']), pending=False)


@router.post('/chat')
async def research_chat(request: Request):
    """대화로 연구 서사를 진행합니다. AI가 묻고, 학생의 말에 따라 행동합니다.

    한 턴을 백그라운드 작업으로 돌립니다. 세특 설계처럼 오래 걸리는 일은
    학생이 새로고침해도 서버에서 계속 진행되고, 돌아오면 GET /chat/pending으로
    "아직 만드는 중"인지 "다 됐는지"를 이어서 확인할 수 있습니다.
    금방 끝나는 일(테마 고르기 등)까지 폴링을 기다리게 하지는 않으려고,
    잠깐만 기다려 보고 그 안에 끝나면 그 자리에서 결과를 돌려줍니다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    payload = await _json(request)
    message = (payload.get('message') or '').strip()
    if not message:
        return _error('메시지를 입력해 주세요.', 422)

    _drop_stale_jobs()
    if _user_busy(user_id):
        return _error('앞의 요청을 아직 처리하고 있어요. 끝나면 이어서 답할게요.', 409)

    stage, extra = _resolve_stage(user_id)
    instance_id = _codex_instance(request)
    # 이 말이 어느 설계 대화방의 것인지 정한다(없으면 여기서 방이 하나 생긴다).
    session_id, _ = _design_session(user_id, payload.get('session_id'))
    db.add_research_message(user_id, 'user', message, session_id=session_id)

    return await _start_chat_job(
        user_id, _ROOM_RESEARCH,
        _chat_turn, user_id, instance_id, stage, extra, message,
        payload.get('history') or [], session_id,
        stage=stage, session_id=session_id)


@router.post('/chat/regenerate')
async def research_chat_regenerate(request: Request):
    """마지막 답변을 걷어내고 직전 발화로 다시 만듭니다.

    학생이 같은 말을 또 타이핑할 이유가 없다 — 서버가 직전 발화를 그대로 쓴다.
    실험 대화의 /regenerate와 같은 규약이다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    payload = await _json(request)
    _drop_stale_jobs()
    if _user_busy(user_id):
        return _error('앞의 요청을 아직 처리하고 있어요. 잠시만요.', 409)

    session_id = payload.get('session_id') or None
    message = db.pop_last_research_reply(user_id, session_id)
    if not message:
        return _error('다시 만들 답변이 없어요.', 409)

    stage, extra = _resolve_stage(user_id)
    instance_id = _codex_instance(request)
    return await _start_chat_job(
        user_id, _ROOM_RESEARCH,
        _chat_turn, user_id, instance_id, stage, extra, message,
        payload.get('history') or [], session_id,
        stage=stage, session_id=session_id)


@router.get('/chat/pending')
def chat_pending(request: Request):
    """진행 중인 대화 턴이 있는지 확인합니다.

    새로고침으로 화면이 날아가도 이 값으로 "생성 중" 표시를 되살리고,
    끝나 있으면 그 결과를 그대로 받아 갑니다. 한 번 받아 가면 기록은 지웁니다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    return _poll_chat_job(user_id, _ROOM_RESEARCH)


# ---------- 실험 동반 학습 ----------

def _plan_standards(plan) -> List[Dict[str, Any]]:
    return db.get_curriculum_standards(codes=plan.standard_codes) if plan.standard_codes else []


def _experiment_keyword(plan) -> str:
    """대화방 이름에 쓸 키워드. 탐구 질문에서 앞부분만 짧게 가져온다."""
    design = plan.activity_design or {}
    source = str(design.get('question') or plan.area_name or plan.subject or '').strip()
    source = re.sub(r'[?!.]+$', '', source)

    keyword = ''
    for word in source.split():
        if keyword and len(keyword) + len(word) + 1 > 16:
            break
        keyword = f'{keyword} {word}'.strip()
    return keyword or '탐구'


def _experiment_title(plan) -> str:
    """실험 대화방 이름은 '과목명 - 키워드'. 예) 공통국어 - 사용성 실험 전달"""
    return f'{plan.subject} - {_experiment_keyword(plan)}'


def _experiment_room(user_id: str, plan) -> tuple:
    """실험 대화방을 가져오거나 없으면 만듭니다. (session_id, messages)"""
    if plan.experiment_chat_id:
        session = db.get_chat_session(plan.experiment_chat_id, user_id)
        if session:
            # 폴더나 이름 규칙이 생기기 전에 만들어진 방이면 지금 맞춰 준다.
            # 그러지 않으면 HISTORY에서 '실험'으로 묶이지 않고, 열어도 실험이 시작되지 않는다.
            title = _experiment_title(plan)
            if not session.folder or session.title != title:
                db.update_chat_session(session.id, user_id, title=title,
                                       folder=FOLDER_EXPERIMENT, plan_id=plan.id)
            return session.id, list(session.messages or [])

    # 대화방은 일반 채팅 세션과 같은 것이다. 사이드바 HISTORY의 '실험' 폴더에 놓인다.
    session = db.create_chat_session(user_id, _experiment_title(plan), [],
                                     folder=FOLDER_EXPERIMENT, plan_id=plan.id)
    store.set_experiment(user_id, plan.id,
                         experiment_chat_id=session.id,
                         experiment_status=plan.experiment_status or 'running')
    return session.id, []


def _plan_grade(user_id: str, plan) -> Optional[int]:
    return next((item.grade for item in store.list_grade_plans(user_id)
                 if item.id == plan.grade_plan_id), None)


def _report_filename(plan, title: str) -> str:
    """output/ 아래에 쓸 파일 이름. 파일명에 쓸 수 없는 글자를 걷어낸다."""
    base = re.sub(r'[^\w가-힣 ._-]', '', (title or plan.subject or '탐구 보고서')).strip()
    base = re.sub(r'\s+', ' ', base)[:60] or '탐구 보고서'
    return f'{base}_{plan.grade_plan_id}-{plan.id}.hwp'


def _write_report_hwp(plan, title: str, body: str, figures=None) -> str:
    """보고서 본문을 저장하고 파일 이름을 돌려줍니다.

    hwp-node로 진짜 HWP를 만듭니다. 그래야 학생이 HWP 편집기에서 이어 손볼 수 있습니다.

    사이드카가 죽어 있으면 DOCX로 물러섭니다. 다만 이름도 .docx로 둔다 —
    예전에는 DOCX를 만들고 확장자만 .hwp로 바꿨는데, 그 파일을 편집기에서 열면
    "HWPX 오류: 필수 파일 누락: Contents/content.hpf"가 떴다. rhwp가 zip(=DOCX)을
    보고 HWPX로 읽으려다 실패한 것이다. 학생에게는 원인을 알 수 없는 고장으로만 보인다.
    확장자가 내용과 맞으면 편집기 링크를 걸지 않고 내려받기만 주면 된다.

    /api/download/{파일명} 이 output/ 에서 그대로 내려줍니다.
    """
    output_dir = Path('output')
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = _report_filename(plan, title)

    if hwp_report.build_hwp(title, body, output_dir / filename, figures=figures):
        return filename

    logger.warning('[EXPERIMENT] HWP 조립 실패 — DOCX로 저장합니다(plan=%s)', plan.id)
    filename = f'{Path(filename).stem}.docx'
    temp_docx = _docx_handler.create_document(
        title=title, content=body, filename=f'.experiment_{plan.id}_temp.docx')
    shutil.copy2(temp_docx, output_dir / filename)
    Path(temp_docx).unlink(missing_ok=True)
    return filename


# ---------- 생성 중 사용자 확인 ----------
#
# 문서 생성 도중 학생에게 물어야 할 것이 있다(예: 어떤 그림을 넣을지).
# 작업 스레드는 여기서 답을 기다리고, 폴링이 질문을 화면에 실어 나른다.
# 답이 오면 이벤트로 깨우고, 오래 없으면 계획대로 진행한다.
_PLAN_QUESTIONS: Dict[str, Dict[str, Any]] = {}
_FIGURE_CONFIRM_TIMEOUT_SECONDS = float(os.getenv('FIGURE_CONFIRM_TIMEOUT_MS', '300000')) / 1000


def _ask_figures(progress: Optional[Dict[str, Any]], plan_id: int,
                 figures: List[Dict[str, Any]],
                 timeout: Optional[float] = None) -> Optional[str]:
    """그림 계획을 학생에게 보여주고 답을 기다립니다.

    돌려주는 값: 학생이 적은 요청(빈 문자열 = 이대로 진행, None = 시간 초과).
    화면이 없는 호출(progress 없음)에서는 묻지 않고 그대로 진행합니다.
    """
    if progress is None or not figures:
        return ''

    question_id = uuid.uuid4().hex
    entry: Dict[str, Any] = {'event': threading.Event(), 'answer': None}
    _PLAN_QUESTIONS[question_id] = entry
    progress['question'] = {
        'id': question_id,
        'kind': 'figures',
        'plan_id': plan_id,
        'title': '보고서에 넣을 그림 계획이야. 이대로 갈까?',
        'figures': [{'no': figure.get('no'), 'kind': figure.get('kind'),
                     'caption': figure.get('caption')} for figure in figures],
    }
    try:
        answered = entry['event'].wait(timeout or _FIGURE_CONFIRM_TIMEOUT_SECONDS)
        return entry['answer'] if answered else None
    finally:
        progress.pop('question', None)
        _PLAN_QUESTIONS.pop(question_id, None)


class _Steps:
    """문서 생성 같은 큰 작업의 단계 진행판.

    같은 dict를 폴링 잡 기록이 들고 있어, 여기서 바꾸면 다음 폴링이
    그대로 읽어 간다. 화면은 이 목록을 점검표로 그린다.
    """

    def __init__(self, progress: Optional[Dict[str, Any]]):
        self.rows: List[Dict[str, str]] = []
        if progress is not None:
            progress['steps'] = self.rows

    def add(self, label: str) -> int:
        self.rows.append({'label': label, 'status': 'pending', 'note': ''})
        return len(self.rows) - 1

    def start(self, index: int) -> None:
        self.rows[index]['status'] = 'running'

    def done(self, index: int, note: str = '') -> None:
        self.rows[index].update(status='done', note=note)

    def fail(self, index: int, note: str = '') -> None:
        self.rows[index].update(status='failed', note=note)


def _compose_report(user_id: str, instance_id: str, plan,
                    standards: List[Dict[str, Any]],
                    messages: List[Dict[str, Any]],
                    progress: Optional[Dict[str, Any]]) -> tuple:
    """보고서를 단계별로 만듭니다. (title, markdown, figures)를 돌려줍니다.

    계획을 먼저 세우고(장 구성·그림 계획), 장마다 별도의 턴으로 집필합니다.
    한 번에 다 시키면 어느 부분이 왜 빠졌는지 알 수 없고,
    화면도 몇 분짜리 침묵이 됩니다. 계획 단계가 실패하면 예전처럼
    한 번의 호출로 만드는 방식으로 물러섭니다.
    """
    steps = _Steps(progress)
    planning = steps.add('문서 계획 세우기')
    steps.start(planning)

    fixed = store.fixed_context(user_id)
    try:
        outline = research_pipeline.report_plan(
            instance_id, plan.to_dict(), standards, fixed, messages)
        sections = [item for item in (outline.get('sections') or [])
                    if (item.get('heading') or '').strip()]
        if not sections:
            raise PipelineError('빈 계획')
    except PipelineError as exc:
        # 설계도가 없으면 단계를 나눌 수 없다. 이전 방식(한 번에)으로 만든다.
        logger.info('[REPORT] 계획 실패, 단일 호출로 물러섭니다: %s', exc.message)
        steps.fail(planning, '이전 방식으로 진행')
        single = steps.add('보고서 한 번에 작성')
        steps.start(single)
        report = research_pipeline.experiment_report(
            instance_id, plan.to_dict(), standards, fixed, messages)
        steps.done(single)
        return (report.get('title') or '', report.get('report_markdown') or '',
                report_figures.prepare(report.get('figures') or []))

    planned_figures = outline.get('figures') or []
    steps.done(planning, f'{len(sections)}개 장 · 그림 {len(planned_figures)}개')

    # 그림 계획을 학생에게 먼저 보여준다. 어떤 자료가 문서에 실릴지는
    # 학생이 정할 문제다 — 다 만들어 놓고 통째로 다시 만들게 하지 않는다.
    if planned_figures:
        confirming = steps.add('그림 계획 확인')
        steps.start(confirming)
        steps.rows[confirming]['note'] = '답변 기다리는 중'
        feedback = _ask_figures(progress, plan.id, planned_figures)
        if feedback:
            try:
                revised = research_pipeline.revise_figures(
                    instance_id, plan.subject,
                    (plan.activity_design or {}).get('question') or '',
                    planned_figures, feedback)
                planned_figures = revised.get('figures') or planned_figures
                outline['figures'] = planned_figures
                steps.done(confirming, (revised.get('note') or '요청 반영')[:40])
            except PipelineError as exc:
                logger.warning('[REPORT] 그림 계획 수정 실패: %s', exc.message)
                steps.fail(confirming, '수정 못 함 · 원래 계획으로')
        elif feedback == '':
            steps.done(confirming, '이대로 진행')
        else:
            steps.done(confirming, '응답 없어 계획대로 진행')

    # 이미지 그림은 검색 전담 턴이 실제 주소를 찾아온다.
    # 계획 턴에 검색까지 시키면 자주 건너뛰지만, 이 턴의 일은 검색뿐이라 빠질 수 없다.
    image_figures = [figure for figure in planned_figures if figure.get('kind') == 'image']
    searching = steps.add(f'이미지 검색 — {len(image_figures)}건') if image_figures else None

    writing = [steps.add(f"본문 쓰기 — {item['heading']}") for item in sections]
    figuring = steps.add('그림 준비')

    if searching is not None:
        steps.start(searching)
        try:
            found = research_pipeline.find_report_images(
                instance_id, plan.subject,
                (plan.activity_design or {}).get('question') or '',
                image_figures)
            for figure in image_figures:
                hit = found.get(figure.get('no'))
                if hit:
                    figure['image_url'] = hit['image_url']
            steps.done(searching, f'{len(found)}/{len(image_figures)}건 찾음')
        except PipelineError as exc:
            # 검색 턴이 죽어도 계획에 적힌 주소와 폴백 검색이 남아 있다.
            logger.warning('[REPORT] 이미지 검색 턴 실패: %s', exc.message)
            steps.fail(searching, '계획된 주소로 진행')

    parts: List[str] = []
    for index, section in enumerate(sections):
        steps.start(writing[index])
        try:
            written = research_pipeline.report_section(
                instance_id, plan.to_dict(), fixed, messages,
                outline, section, written_tail=(parts[-1][-500:] if parts else ''),
                standards=standards)
            parts.append((written.get('markdown') or '').strip())
            steps.done(writing[index])
        except PipelineError as exc:
            # 한 장이 실패해도 나머지는 낸다. 무엇이 빠졌는지는 단계판에 남는다.
            logger.warning('[REPORT] 장 집필 실패(%s): %s', section['heading'], exc.message)
            parts.append(f"# {section['heading']}\n\n(이 장은 만들지 못했습니다.)")
            steps.fail(writing[index], exc.message[:60])

    steps.start(figuring)
    figures = report_figures.prepare(planned_figures)
    if planned_figures:
        steps.done(figuring, f'{len(figures)}/{len(planned_figures)}개 준비')
    else:
        steps.done(figuring, '넣을 그림 없음')

    title = (outline.get('title') or '').strip()
    return title, '\n\n'.join(part for part in parts if part), figures


def _finish_experiment(user_id: str, instance_id: str, plan,
                       standards: List[Dict[str, Any]],
                       messages: List[Dict[str, Any]],
                       progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """실험이 끝났다. 대화 전체를 보고서로 만들고 세특에 붙인다."""
    title, body, figures = _compose_report(
        user_id, instance_id, plan, standards, messages, progress)
    title = (title or f'{plan.subject} 탐구 보고서').strip()

    steps = (progress or {}).get('steps')
    assembling = None
    if isinstance(steps, list):
        steps.append({'label': 'HWP 문서 조립', 'status': 'running', 'note': ''})
        assembling = len(steps) - 1
    try:
        filename = _write_report_hwp(plan, title, body, figures)
    except Exception as exc:  # noqa: BLE001 - 문서 생성이 실패해도 학습은 끝난 것이다.
        logger.warning('[EXPERIMENT] 보고서 파일 생성 실패: %s', type(exc).__name__)
        if assembling is not None:
            steps[assembling].update(status='failed', note='파일 생성 실패')
        store.set_experiment(user_id, plan.id, experiment_status='done')
        return {'report_error': '보고서 파일을 만들지 못했어요. 대화 내용은 남아 있어요.'}
    if assembling is not None:
        steps[assembling].update(status='done', note='')

    # 검수 — 데이터는 있는데 아무것도 안 보이는 문서가 실제로 나온 적이 있다.
    # 첫 페이지를 그려서 사람 눈에 보이는지 확인하고, 결과를 단계판에 남긴다.
    # DOCX로 물러선 경우는 검수 대상이 아니다. HWP가 아닌 파일을 열어보려 하면
    # 무조건 실패로 남아 '문서가 비어 보인다'는 엉뚱한 이유가 붙는다.
    if isinstance(steps, list):
        if not filename.lower().endswith('.hwp'):
            steps.append({'label': '문서 검수', 'status': 'failed',
                          'note': 'HWP 변환기가 멈춰서 DOCX로 저장했어요'})
        else:
            steps.append({'label': '문서 검수', 'status': 'running', 'note': ''})
            checked = hwp_report.verify(Path('output') / filename)
            steps[-1].update(
                status='done' if checked.get('ok') else 'failed',
                note=(f"{checked.get('text_paragraphs', 0)}개 문단 확인"
                      if checked.get('ok') else '문서가 비어 보일 수 있어요'))

    # 성취기준 대조 — 설계 때 고른 기준에 보고서가 실제로 닿았는지.
    # 생기부에 적힌 뒤에는 늦다. 실패해도 보고서는 이미 완성이므로 조용히 넘어간다.
    standards_check = None
    if standards and body:
        checking = None
        if isinstance(steps, list):
            steps.append({'label': '성취기준 확인', 'status': 'running', 'note': ''})
            checking = len(steps) - 1
        try:
            checked = research_pipeline.check_standards(
                instance_id, plan.subject, standards, body)
            verdicts = checked.get('verdicts') or []
            if verdicts:
                standards_check = verdicts
                reached = sum(1 for item in verdicts if item.get('reached') == 'yes')
                if checking is not None:
                    steps[checking].update(
                        status='done', note=f'{reached}/{len(verdicts)}개 도달')
        except PipelineError as exc:
            logger.warning('[EXPERIMENT] 성취기준 확인 실패: %s', exc.message)
            if checking is not None:
                steps[checking].update(status='failed', note='확인 못 함')

    store.set_experiment(user_id, plan.id, experiment_status='done', report_file=filename)
    # 실험이 끝나면 그 과목이 있는 학년 자리로 돌려보낸다(카드에 문서 아이콘이 붙어 있다).
    return {'report_file': filename, 'report_title': title,
            'report_editable': _report_editable(filename),
            'standards_check': standards_check,
            'redirect': _grade_anchor(_plan_grade(user_id, plan))}


def _experiment_turn(user_id: str, instance_id: str, plan_id: int,
                     message: str, progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """실험 대화 한 턴. 전부 동기 코드라 스레드에서 돌린다.

    학생의 말과 답변을 그때그때 대화방에 저장하므로, 도중에 새로고침해도
    진행한 만큼은 남습니다.
    """
    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return {'ok': False, 'error': '과목 플랜을 찾을 수 없습니다.', 'status': 404}

    session_id, messages = _experiment_room(user_id, plan)
    messages.append({'role': 'user', 'text': message})
    db.update_chat_session(session_id, user_id, messages=messages)
    return _experiment_answer(user_id, instance_id, plan, session_id, messages, message, progress)


def _experiment_regenerate(user_id: str, instance_id: str, plan_id: int,
                           progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """마지막 답변을 걷어내고 같은 질문으로 다시 만듭니다.

    답이 마음에 들지 않을 때 학생이 같은 말을 또 타이핑하게 하지 않으려는 것이라,
    새 질문을 받지 않고 직전 학생의 말을 그대로 다시 씁니다.
    """
    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return {'ok': False, 'error': '과목 플랜을 찾을 수 없습니다.', 'status': 404}

    session_id, messages = _experiment_room(user_id, plan)
    # 끝에 붙은 답변을 걷어내면 그 앞이 다시 만들 질문이다.
    while messages and messages[-1].get('role') != 'user':
        messages.pop()
    message = (messages[-1].get('text') if messages else '') or ''
    if not message:
        return {'ok': False, 'error': '다시 만들 답변이 없어요.', 'status': 409}

    db.update_chat_session(session_id, user_id, messages=messages)
    return _experiment_answer(user_id, instance_id, plan, session_id, messages, message, progress)


def _rebuild_report(user_id: str, instance_id: str, plan_id: int,
                    progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """대화는 그대로 두고 보고서 문서만 다시 만듭니다.

    실험을 다시 하라고 할 수는 없다. 문서가 마음에 들지 않거나 형식이 바뀌었을 때
    (예: 진짜 HWP로 다시 뽑아야 할 때) 쓰는 길이다.
    """
    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return {'ok': False, 'error': '과목 플랜을 찾을 수 없습니다.', 'status': 404}

    _, messages = _experiment_room(user_id, plan)
    if not messages:
        return {'ok': False, 'error': '아직 대화가 없어요.', 'status': 409}

    if progress is not None:
        progress['stage'] = 'thinking'
        progress['label'] = '보고서'

    try:
        made = _finish_experiment(user_id, instance_id, plan, _plan_standards(plan),
                                  messages, progress=progress)
    except PipelineError as exc:
        return {'ok': False, 'error': exc.message, 'status': exc.status_code,
                'error_kind': getattr(exc, 'kind', None)}

    # 화면이 대화를 늘리지 않고 보고서 칸만 갈아 끼우도록 종류를 밝힌다.
    return {'ok': True, 'payload': {'kind': 'report', **made}}


def _make_ppt(user_id: str, instance_id: str, plan_id: int,
              progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """보고서로 발표 슬라이드를 만듭니다. 학생이 원할 때만 눌러서 만드는 길이다.

    Codex가 장별 요점과 발표 메모를 추리고, 실패하면 장 제목만으로 뼈대를 준다.
    재료는 완성된 보고서에서만 가져온다 — 보고서에 없는 말이 발표에 나오면
    학생이 발표장에서 설명하지 못한다.
    """
    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return {'ok': False, 'error': '과목 플랜을 찾을 수 없습니다.', 'status': 404}
    if not plan.report_file:
        return {'ok': False, 'error': '아직 보고서가 없어요. 보고서부터 만들어 주세요.',
                'status': 409}

    if progress is not None:
        progress['stage'] = 'thinking'
        progress['label'] = '발표 자료'

    report_path = Path('output') / plan.report_file
    text = ppt_report.extract_report_text(report_path) if hwp_report.is_hwp(report_path) else ''
    title = Path(plan.report_file).stem.rsplit('_', 1)[0]
    topic = (plan.activity_design or {}).get('question') or ''

    slides = None
    if text:
        try:
            outline = research_pipeline.ppt_outline(instance_id, plan.subject, topic, text)
            slides = outline.get('slides') or None
            title = (outline.get('title') or title).strip() or title
        except PipelineError as exc:
            logger.warning('[PPT] 개요 턴 실패, 뼈대로 물러섭니다: %s', exc.message)
    if not slides:
        slides = ppt_report.fallback_slides(title, text)

    filename = f'{Path(plan.report_file).stem}.pptx'
    made = ppt_report.build_pptx(title, plan.subject, slides, Path('output') / filename)
    if not made:
        return {'ok': True, 'payload': {'kind': 'ppt',
                                        'ppt_error': '발표 자료를 만들지 못했어요.'}}
    return {'ok': True, 'payload': {'kind': 'ppt', 'ppt_file': filename,
                                    'ppt_title': title, 'slide_count': len(slides)}}


def _experiment_answer(user_id: str, instance_id: str, plan, session_id: str,
                       messages: List[Dict[str, Any]], message: str,
                       progress: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """마지막 학생의 말에 대한 답을 만들어 대화방에 붙입니다."""
    plan_id = plan.id

    def on_stage(name: str, label: str = '') -> None:
        """지금 무엇을 하고 있는지 폴링 쪽에 알린다(생각 중 / 찾는 중).

        같은 dict를 잡 기록이 들고 있어, 다음 폴링이 이 값을 그대로 읽어 간다.
        """
        if progress is not None:
            progress['stage'] = name
            progress['label'] = label

    standards = _plan_standards(plan)
    try:
        turn = research_pipeline.experiment_turn(
            instance_id, plan.to_dict(), standards,
            store.fixed_context(user_id), messages[:-1], message, on_stage=on_stage)
    except PipelineError as exc:
        return {'ok': False, 'error': exc.message, 'status': exc.status_code,
                'error_kind': getattr(exc, 'kind', None)}

    reply = turn.get('reply') or ''
    phase = turn.get('phase')
    # 찾아온 것도 함께 남긴다. 새로고침해도 이미지와 출처가 그대로 보여야 한다.
    messages.append({'role': 'assistant', 'text': reply, 'phase': phase,
                     'sources': turn.get('sources') or [],
                     'images': turn.get('images') or [],
                     'demo': turn.get('demo') or {},
                     'measure_table': turn.get('measure_table') or {}})
    db.update_chat_session(session_id, user_id, messages=messages)

    payload: Dict[str, Any] = {
        'reply': reply,
        'phase': phase,
        'phase_label': turn.get('phase_label') or '',
        'is_complete': bool(turn.get('is_complete')),
        # 웹에서 실제로 찾아왔는지. 화면이 "지어낸 말"과 구분해 보여준다.
        'sources': turn.get('sources') or [],
        'images': turn.get('images') or [],
        # 학생이 직접 눌러볼 화면. 대화 안에서 그대로 돌아간다.
        'demo': turn.get('demo') or {},
        # 측정값을 적을 표. 폰으로 실험하는 학생이 문장 대신 값만 넣게 한다.
        'measure_table': turn.get('measure_table') or {},
    }
    if payload['is_complete']:
        # 학습이 끝났으면 그 대화를 그대로 보고서로 옮긴다.
        plan = store.get_subject_plan(user_id, plan_id)
        try:
            payload.update(_finish_experiment(user_id, instance_id, plan, standards,
                                             messages, progress=progress))
        except PipelineError as exc:
            # 보고서를 못 만들었다고 학습까지 되돌리지는 않는다. 다시 시도할 수 있게 둔다.
            payload['is_complete'] = False
            payload['report_error'] = exc.message
    return {'ok': True, 'payload': payload}


def _report_editable(report_file: Optional[str]) -> bool:
    """보고서를 편집기로 보내도 되는지. 이름이 아니라 파일 내용을 보고 답한다.

    HWP 조립이 실패해 DOCX로 저장된 보고서를 편집기에 넘기면 학생은
    "필수 파일 누락: Contents/content.hpf"만 보게 된다. 그런 파일은
    내려받기로만 준다. 확장자를 .hwp로 잘못 붙여 둔 옛 파일까지 걸러야 하므로
    이름 대신 내용을 본다.
    """
    if not report_file:
        return False
    return hwp_report.is_hwp(Path('output') / report_file)


def _plan_view(plan) -> Dict[str, Any]:
    """플랜을 화면에 내보낼 형태로. 보고서를 편집기로 열 수 있는지 함께 알려준다."""
    data = plan.to_dict()
    data['report_editable'] = _report_editable(data.get('report_file'))
    return data


def _experiment_view(user_id: str, plan) -> Dict[str, Any]:
    session_id, messages = _experiment_room(user_id, plan)
    plan = store.get_subject_plan(user_id, plan.id)
    return {
        'plan': _plan_view(plan),
        'grade': _plan_grade(user_id, plan),
        'standards': _plan_standards(plan),
        'session_id': session_id,
        'messages': messages,
        'phases': [{'key': key, 'label': label}
                   for key, label in research_pipeline.EXPERIMENT_PHASES],
        'ai_connected': None,   # 라우트에서 채운다
    }


@router.post('/experiment/{plan_id}/open')
def open_experiment(plan_id: int, request: Request):
    """실험 대화방을 열고, 메인 채팅에서 그 방으로 들어갈 주소를 돌려줍니다.

    실험은 전용 페이지가 아니라 메인(/) 채팅방에서 진행한다.
    로드맵의 「실험 진행」은 방을 만들고 학생을 메인으로 보내기만 한다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)

    session_id, _ = _experiment_room(user_id, plan)
    return {'session_id': session_id, 'plan_id': plan.id,
            'redirect': f'/?chat={session_id}'}


@router.get('/experiment/{plan_id}')
def experiment_state(plan_id: int, request: Request):
    """실험 대화방을 엽니다. 없으면 이 시점에 만듭니다."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)

    view = _experiment_view(user_id, plan)
    view['ai_connected'] = bool(_codex_instance(request))
    view['ai_configured'] = codex_runner.is_configured()
    return view


@router.post('/experiment/{plan_id}/chat')
async def experiment_chat(plan_id: int, request: Request):
    """실험을 한 걸음 진행합니다. 오래 걸리면 백그라운드로 넘기고 pending을 돌려줍니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    payload = await _json(request)
    message = (payload.get('message') or '').strip()
    if not message:
        return _error('메시지를 입력해 주세요.', 422)

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)
    if plan.experiment_status == 'done':
        return _error('이미 끝난 실험이에요. 보고서를 확인해 주세요.', 409)

    room = _room_experiment(plan_id)
    _drop_stale_jobs()
    if _user_busy(user_id):
        return _error('앞의 말을 아직 생각하고 있어요. 잠시만요.', 409)

    # 잡 기록과 작업 스레드가 같은 dict를 본다. 작업이 이 값을 바꾸면
    # 다음 폴링이 곧바로 '찾는 중'을 알아챈다.
    progress: Dict[str, Any] = {'stage': 'thinking', 'label': ''}
    return await _start_chat_job(
        user_id, room, _experiment_turn, user_id, instance_id, plan_id, message, progress,
        progress=progress)


@router.post('/experiment/{plan_id}/regenerate')
async def experiment_regenerate(plan_id: int, request: Request):
    """마지막 답변이 마음에 들지 않을 때 같은 질문으로 다시 만듭니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)
    if plan.experiment_status == 'done':
        return _error('이미 끝난 실험이에요. 보고서를 확인해 주세요.', 409)

    room = _room_experiment(plan_id)
    _drop_stale_jobs()
    if _user_busy(user_id):
        return _error('앞의 말을 아직 생각하고 있어요. 잠시만요.', 409)

    progress: Dict[str, Any] = {'stage': 'thinking', 'label': ''}
    return await _start_chat_job(
        user_id, room, _experiment_regenerate, user_id, instance_id, plan_id, progress,
        progress=progress)


@router.post('/experiment/{plan_id}/report')
async def experiment_rebuild_report(plan_id: int, request: Request):
    """보고서 문서만 다시 만듭니다. 실험 대화는 건드리지 않습니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)

    room = _room_experiment(plan_id)
    _drop_stale_jobs()
    if _user_busy(user_id):
        return _error('앞의 요청을 아직 처리하고 있어요. 잠시만요.', 409)

    progress: Dict[str, Any] = {'stage': 'thinking', 'label': '보고서'}
    return await _start_chat_job(
        user_id, room, _rebuild_report, user_id, instance_id, plan_id, progress,
        progress=progress)


@router.post('/narrative-check')
def narrative_check(request: Request):
    """완성된 보고서들을 가로로 놓고 3년 서사가 이어지는지 봅니다.

    보고서가 2개는 있어야 '이어짐'을 말할 수 있다. 동기 호출이다 —
    로드맵 화면에서 가끔 한 번 누르는 버튼이라 백그라운드로 돌릴 이유가 없다.
    """
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    entries = []
    for plan in store.list_subject_plans(user_id):
        if plan.experiment_status != 'done' or not plan.report_file:
            continue
        path = Path('output') / plan.report_file
        if not hwp_report.is_hwp(path):
            continue
        text = ppt_report.extract_report_text(path)
        if not text.strip():
            continue
        entries.append({'grade': _plan_grade(user_id, plan),
                        'subject': plan.subject,
                        'title': Path(plan.report_file).stem.rsplit('_', 1)[0],
                        'text': text})
    if len(entries) < 2:
        return _error('보고서가 2개는 있어야 서사를 볼 수 있어요. 지금은 '
                      f'{len(entries)}개예요.', 409)

    try:
        result = research_pipeline.narrative_check(
            instance_id, store.fixed_context(user_id), entries)
    except PipelineError as exc:
        return _error(exc.message, exc.status_code)
    return {'summary': result.get('summary') or '',
            'findings': result.get('findings') or [],
            'report_count': len(entries)}


@router.post('/experiment/{plan_id}/ppt')
async def experiment_make_ppt(plan_id: int, request: Request):
    """보고서로 발표 슬라이드를 만듭니다. 학생이 원할 때만 누르는 길입니다."""
    user_id, instance_id, error = _require_ai(request)
    if error:
        return error

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)

    room = _room_experiment(plan_id)
    _drop_stale_jobs()
    if _user_busy(user_id):
        return _error('앞의 요청을 아직 처리하고 있어요. 잠시만요.', 409)

    progress: Dict[str, Any] = {'stage': 'thinking', 'label': '발표 자료'}
    return await _start_chat_job(
        user_id, room, _make_ppt, user_id, instance_id, plan_id, progress,
        progress=progress)


@router.post('/experiment/{plan_id}/inspect')
def experiment_inspect_report(plan_id: int, request: Request):
    """만들어진 보고서를 점검합니다. 문서는 고치지 않고 고칠 곳만 알려줍니다.

    본문을 고쳐 쓰는 건 학생 몫이다(원칙). 점검자는 그림 인용·장 번호·정렬처럼
    서식과 구조의 어긋남만 찾아 주고, 학생이 편집기에서 고친다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    plan = store.get_subject_plan(user_id, plan_id)
    if not plan:
        return _error('과목 플랜을 찾을 수 없습니다.', 404)
    if not plan.report_file:
        return _error('아직 만들어진 보고서가 없어요.', 404)

    result = hwp_inspect.inspect(Path('output') / plan.report_file)
    if not result.get('ok'):
        return _error(result.get('error') or '점검에 실패했어요.', 502)
    return result


@router.post('/experiment/{plan_id}/plan-answer')
async def experiment_plan_answer(plan_id: int, request: Request):
    """문서 생성 도중 띄운 질문(그림 계획 등)에 대한 학생의 답을 받습니다.

    빈 answer는 "이대로 진행"이라는 뜻입니다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)

    payload = await _json(request)
    entry = _PLAN_QUESTIONS.get(str(payload.get('question_id') or ''))
    if not entry:
        return _error('이미 진행됐어요. 다음 생성부터 반영할게요.', 409)
    entry['answer'] = str(payload.get('answer') or '').strip()
    entry['event'].set()
    return {'ok': True}


@router.get('/experiment/{plan_id}/pending')
def experiment_pending(plan_id: int, request: Request):
    """실험 대화가 아직 진행 중인지 확인합니다(새로고침 복구용)."""
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    return _poll_chat_job(user_id, _room_experiment(plan_id))


@router.get('/messages')
def list_messages(request: Request, session_id: Optional[str] = None):
    """지금까지의 대화를 돌려줍니다. 새로고침해도 이어서 보이게 한다.

    session_id를 주면 그 설계 대화방의 말만 돌려줍니다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    room_id, include_orphans = _design_session(user_id, session_id)
    return {
        'session_id': room_id,
        'messages': db.get_research_messages(
            user_id, session_id=room_id, include_orphans=include_orphans),
    }


@router.delete('/messages')
def clear_messages(request: Request):
    """대화를 처음부터 다시 시작합니다.

    지금 방을 비우는 게 아니라 새 설계 대화방을 엽니다. 지난 대화는 HISTORY에 남습니다.
    """
    user_id = _current_user_id(request)
    if not user_id:
        return _error('로그인이 필요합니다.', 401)
    room = db.create_chat_session(user_id, _DESIGN_DEFAULT_TITLE, [], folder=FOLDER_DESIGN)
    return {'success': True, 'session_id': room.id}


@router.get('/curriculum/subjects')
def curriculum_subjects(request: Request, grade_band: Optional[str] = None,
                        subject_type: Optional[str] = None,
                        curriculum_area: Optional[str] = None):
    """2022 개정 교육과정 과목 조회. 1학년 공통과목은 grade_band=1."""
    return {'subjects': db.get_curriculum_subjects(
        grade_band=grade_band, subject_type=subject_type, curriculum_area=curriculum_area)}


@router.get('/curriculum/standards')
def curriculum_standards(request: Request, subject_uid: Optional[str] = None,
                         area_no: Optional[str] = None, q: Optional[str] = None,
                         grade_band: Optional[str] = None, limit: int = 30):
    """성취기준 조회. subject_uid로 과목별 조회하거나 q로 검색합니다."""
    if q:
        return {'standards': db.search_curriculum_standards(
            q, grade_band=grade_band, limit=min(int(limit), 100))}
    if not subject_uid:
        return _error('subject_uid 또는 q 중 하나는 필요합니다.', 422)
    return {'standards': db.get_curriculum_standards(
        subject_uid=subject_uid, area_no=area_no)}
