"""연구 서사 Phase 1~5의 AI 파이프라인.

각 Phase는 Codex의 outputSchema로 출력 구조를 강제합니다. 자유 서술을 파싱하지 않으므로
필드 누락이나 형식 붕괴가 생기지 않습니다.

원칙:
- 확정(fixed)된 항목은 이후 모든 생성의 컨텍스트로 자동 주입되어 서사가 흔들리지 않는다.
- 모든 제안은 '왜 이 제안인지'를 함께 낸다(성취기준 코드, 교육과정 위계 등).
- Narrowing에서 AI는 무조건 수용하지 않고, 비현실적 계획에는 근거를 들어 대안을 낸다.
- 교사가 쓸 생기부 문장을 대신 써주지 않는다. 학생이 실제로 수행할 활동을 설계한다.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from modules import codex_runner, web_search

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = """너는 고등학생의 3년 생기부를 '연구 서사(Research Narrative)'로 설계하는 컨설턴트다.

지켜야 할 원칙:
- 생기부는 단발성 활동의 나열이 아니라 하나의 테마 아래 3년간 심화되는 서사여야 한다.
- 너는 교사가 쓸 생기부 문장을 대신 써주는 도구가 아니다. 학생이 실제로 수행할
  탐구·실험·보고서를 설계하고 기록하도록 돕는다.
- 모든 제안에는 근거를 함께 낸다. 교육과정 성취기준을 인용할 때는 반드시 주어진
  목록에 있는 코드만 쓴다. 목록에 없는 코드를 지어내지 않는다.
- 확정(FIXED)으로 표시된 내용은 바꿀 수 없는 기준값이다. 그것과 어긋나는 제안을 하지 않는다.
  단, [FIXED] 같은 표시 자체를 네가 만드는 문장에 옮겨 적지는 않는다.
- 학교 여건상 불가능한 계획(고가 장비, 과도한 기간, 통제 불가능한 변인)은 그대로 수용하지 말고
  근거를 들어 실현 가능한 대안을 제시한다.
- 한국어로 답한다."""

# 2022 개정 교육과정의 학년별 과목 위계. Phase 3 분해의 기준이다.
GRADE_STRUCTURE = """학년별 교육과정 구조(2022 개정):
- 1학년: 공통과목(공통국어1·2, 공통수학1·2, 공통영어1·2, 통합사회1·2, 통합과학1·2,
  과학탐구실험1·2, 한국사1·2). 기초 개념 습득과 문제 발견의 시기.
- 2학년: 일반선택 중심. 방법론 습득과 본격 탐구의 시기.
- 3학년: 진로선택·융합선택 중심. 종합·확장과 독자적 결과물의 시기."""


class PipelineError(Exception):
    def __init__(self, message: str, status_code: int = 502, kind: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        # 화면이 다르게 보여줘야 하는 실패의 종류(예: usage_limit)
        self.kind = kind


# ---------- 출력 스키마 ----------

PROFILE_INTERVIEW_SCHEMA = {
    'type': 'object',
    'properties': {
        'question': {'type': 'string', 'description': '다음에 물어볼 질문 하나'},
        'intent': {'type': 'string', 'description': '이 질문으로 알아내려는 것'},
        'layer': {
            'type': 'string',
            'enum': ['attraction', 'problem', 'method', 'evidence'],
            'description': '왜 끌리는가 / 어떤 문제를 풀고 싶은가 / 어떤 방법론에 흥미가 있는가 / 근거가 될 활동',
        },
        'is_complete': {'type': 'boolean', 'description': '프로파일을 만들 만큼 모였는지'},
        'profile': {
            'type': 'object',
            'properties': {
                'interests': {'type': 'array', 'items': {'type': 'string'}},
                'problem_statement': {'type': 'string'},
                'aspired_track': {'type': 'string'},
                'strength_subjects': {'type': 'array', 'items': {'type': 'string'}},
                'activity_history': {'type': 'array', 'items': {'type': 'string'}},
            },
            'required': ['interests', 'problem_statement', 'aspired_track',
                         'strength_subjects', 'activity_history'],
            'additionalProperties': False,
        },
    },
    'required': ['question', 'intent', 'layer', 'is_complete', 'profile'],
    'additionalProperties': False,
}

THEME_SCHEMA = {
    'type': 'object',
    'properties': {
        'candidates': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'description': '테마 한 줄 정의'},
                    'rationale': {'type': 'string', 'description': '왜 이 학생에게 맞는지'},
                    'expansion': {'type': 'string', 'description': '3년간 어떻게 확장되는지'},
                    'differentiation': {'type': 'string', 'description': '입시 관점에서의 차별성'},
                },
                'required': ['title', 'rationale', 'expansion', 'differentiation'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['candidates'],
    'additionalProperties': False,
}

FRAMEWORK_SCHEMA = {
    'type': 'object',
    'properties': {
        'core_question': {'type': 'string', 'description': '3년을 관통하는 핵심 질문'},
        'sub_areas': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'description': {'type': 'string'},
                },
                'required': ['name', 'description'],
                'additionalProperties': False,
            },
        },
        'final_destination': {'type': 'string', 'description': '3학년 말 최종 도달 지점'},
        'grade_plans': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'grade': {'type': 'integer'},
                    'goal': {'type': 'string'},
                    'anchor_project': {
                        'type': 'object',
                        'properties': {
                            'title': {'type': 'string'},
                            'description': {'type': 'string'},
                        },
                        'required': ['title', 'description'],
                        'additionalProperties': False,
                    },
                    'curriculum_rationale': {
                        'type': 'string',
                        'description': '그 학년에 실제로 배우는 과목·단원과 어떻게 맞물리는지',
                    },
                },
                'required': ['grade', 'goal', 'anchor_project', 'curriculum_rationale'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['core_question', 'sub_areas', 'final_destination', 'grade_plans'],
    'additionalProperties': False,
}

NARROWING_SCHEMA = {
    'type': 'object',
    'properties': {
        'assessment': {'type': 'string', 'description': '현재 안에 대한 평가'},
        'concerns': {
            'type': 'array',
            'description': '학교 여건·시간·장비 관점에서 비현실적인 부분',
            'items': {
                'type': 'object',
                'properties': {
                    'issue': {'type': 'string'},
                    'why': {'type': 'string'},
                    'alternative': {'type': 'string'},
                },
                'required': ['issue', 'why', 'alternative'],
                'additionalProperties': False,
            },
        },
        'question': {'type': 'string', 'description': '학생에게 되물을 질문 하나'},
        'revised': {'type': 'string', 'description': '조정된 안(변경할 것이 없으면 빈 문자열)'},
    },
    'required': ['assessment', 'concerns', 'question', 'revised'],
    'additionalProperties': False,
}

SUBJECT_PLAN_SCHEMA = {
    'type': 'object',
    'properties': {
        'anchor_project': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'description': {'type': 'string'},
                'why': {'type': 'string', 'description': '이 프로젝트를 앵커로 고른 근거'},
            },
            'required': ['title', 'description', 'why'],
            'additionalProperties': False,
        },
        'subject_plans': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'subject': {'type': 'string'},
                    'approach': {
                        'type': 'string',
                        'enum': ['linked', 'deepening'],
                        'description': 'linked=교과 연계형(앵커 요소를 과목과 연결), deepening=교과 심화형(과목 자체를 깊게)',
                    },
                    'approach_rationale': {'type': 'string', 'description': '왜 이 전략인지'},
                    'area_name': {'type': 'string', 'description': '연결되는 단원(영역)명'},
                    'standard_codes': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': '주어진 목록에 있는 성취기준 코드만 사용',
                    },
                    'motivation': {
                        'type': 'string',
                        'description': '수업 중 어떤 지점에서 호기심이 출발했는지의 서사',
                    },
                    'activity_design': {
                        'type': 'object',
                        'properties': {
                            'question': {'type': 'string', 'description': '탐구 질문'},
                            'method': {'type': 'string', 'description': '방법'},
                            'output': {'type': 'string', 'description': '예상 산출물'},
                        },
                        'required': ['question', 'method', 'output'],
                        'additionalProperties': False,
                    },
                },
                'required': ['subject', 'approach', 'approach_rationale', 'area_name',
                             'standard_codes', 'motivation', 'activity_design'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['anchor_project', 'subject_plans'],
    'additionalProperties': False,
}

AGENT_RUN_SCHEMA = {
    'type': 'object',
    'properties': {
        'steps': {
            'type': 'array',
            'description': '수행한 단계별 기록',
            'items': {
                'type': 'object',
                'properties': {
                    'label': {'type': 'string'},
                    'detail': {'type': 'string'},
                },
                'required': ['label', 'detail'],
                'additionalProperties': False,
            },
        },
        'report_markdown': {
            'type': 'string',
            'description': '탐구 보고서 초안(마크다운). 배경-질문-설계-방법-예상결과-한계 순서',
        },
    },
    'required': ['steps', 'report_markdown'],
    'additionalProperties': False,
}


# ---------- 실행 ----------

# 프롬프트에서 확정 항목을 표시하려고 쓰는 마커. 모델이 결과 문장에 그대로 베껴 넣는
# 경우가 있어 저장 전에 걷어낸다.
_MARKER_RE = re.compile(r'\[\s*FIXED\s*\]\s*')


def _strip_markers(value: Any) -> Any:
    if isinstance(value, str):
        return _MARKER_RE.sub('', value).strip()
    if isinstance(value, list):
        return [_strip_markers(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_markers(item) for key, item in value.items()}
    return value


def _parse(raw: str) -> Dict[str, Any]:
    text = (raw or '').strip()
    fenced = re.match(r'^```(?:json)?\s*(.+?)\s*```$', text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except ValueError:
        raise PipelineError('AI 응답을 해석하지 못했습니다. 다시 시도해 주세요.')
    if not isinstance(payload, dict):
        raise PipelineError('AI 응답 형식이 올바르지 않습니다.')
    return _strip_markers(payload)


def _run(instance_id: str, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = codex_runner.run(instance_id, prompt=prompt, output_schema=schema)
    except codex_runner.CodexRunnerError as exc:
        raise PipelineError(exc.message, exc.status_code, getattr(exc, 'kind', None))
    return _parse(result['text'])


def _fixed_block(fixed: Dict[str, Any]) -> str:
    """확정된 항목을 바꿀 수 없는 기준값으로 프롬프트에 주입합니다."""
    parts: List[str] = []
    theme = fixed.get('theme')
    if theme:
        parts.append(f"[FIXED] 3년 테마: {theme['title']}\n  근거: {theme.get('rationale') or '-'}")
    framework = fixed.get('framework')
    if framework:
        areas = ', '.join(
            area.get('name', '') if isinstance(area, dict) else str(area)
            for area in (framework.get('sub_areas') or [])
        )
        parts.append(
            f"[FIXED] 핵심 질문: {framework.get('core_question')}\n"
            f"  하위 영역: {areas}\n  최종 도달: {framework.get('final_destination') or '-'}"
        )
    for plan in fixed.get('grade_plans') or []:
        anchor = plan.get('anchor_project') or {}
        parts.append(
            f"[FIXED] {plan['grade']}학년 목표: {plan.get('goal')}\n"
            f"  앵커 프로젝트: {anchor.get('title') or '-'}"
        )
    for plan in fixed.get('subject_plans') or []:
        parts.append(
            f"[FIXED] {plan['subject']} 세특: {plan.get('approach')} / "
            f"{plan.get('area_name')} / {', '.join(plan.get('standard_codes') or [])}"
        )
    profile = fixed.get('profile')
    if profile:
        parts.append(
            f"[FIXED] 학생 프로파일: 관심 {', '.join(profile.get('interests') or [])} / "
            f"문제의식 {profile.get('problem_statement') or '-'} / "
            f"지망 {profile.get('aspired_track') or '-'}"
        )
    if not parts:
        return '아직 확정된 항목이 없다.'
    return '아래는 이미 확정되어 바꿀 수 없는 기준값이다.\n' + '\n'.join(parts)


def _profile_block(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return '학생 프로파일이 아직 없다.'
    return (
        f"관심 도메인: {', '.join(profile.get('interests') or []) or '-'}\n"
        f"문제의식: {profile.get('problem_statement') or '-'}\n"
        f"지망 계열: {profile.get('aspired_track') or '-'}\n"
        f"강점 교과: {', '.join(profile.get('strength_subjects') or []) or '-'}\n"
        f"활동 이력: {', '.join(profile.get('activity_history') or []) or '-'}"
    )


def _standards_block(standards: List[Dict[str, Any]]) -> str:
    """성취기준 목록을 프롬프트에 넣습니다. 여기 없는 코드는 쓰지 못하게 합니다."""
    if not standards:
        return '(제공된 성취기준 없음)'
    lines = []
    for row in standards:
        lines.append(f"{row['code']} [{row['subject']} / {row.get('area_name') or '-'}] "
                     f"{row['statement']}")
    return '\n'.join(lines)


def interview(instance_id: str, history: List[Dict[str, str]],
              profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Phase 1: 다층 인터뷰. 한 번에 질문 하나씩 파고든다."""
    transcript = '\n'.join(
        f"{'학생' if turn.get('role') == 'user' else '컨설턴트'}: {turn.get('text', '')}"
        for turn in (history or []) if turn.get('text')
    ) or '(아직 대화 없음)'

    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 Phase 1(심층 프로파일링)이다. 키워드만 수집하지 말고 다층으로 파고든다:
1) attraction — 왜 그 주제에 끌리는가
2) problem — 어떤 문제를 풀고 싶은가
3) method — 어떤 방법론에 흥미가 있는가
4) evidence — 그 관심을 뒷받침하는 실제 활동 경험

한 번에 질문은 하나만 한다. 이미 답한 내용은 다시 묻지 않는다.
네 층이 모두 채워졌다고 판단되면 is_complete를 true로 하고 profile을 채운다.

지금까지의 대화:
{transcript}

현재까지 파악된 프로파일:
{_profile_block(profile)}"""
    return _run(instance_id, prompt, PROFILE_INTERVIEW_SCHEMA)


def _note_block(note: str) -> str:
    """학생이 대화에서 말한 조건을 생성 프롬프트에 얹습니다."""
    return f"\n학생이 말한 조건(반드시 반영한다):\n{note}\n" if (note or '').strip() else ''


def propose_themes(instance_id: str, profile: Dict[str, Any],
                   fixed: Dict[str, Any], note: str = '') -> Dict[str, Any]:
    """Phase 2: 3년 테마 후보 2~3개를 근거와 함께 제안한다."""
    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 Phase 2(3년 테마 수립)다. 아래 프로파일을 근거로 테마 후보를 2~3개 제안한다.
각 후보에는 반드시 네 가지가 들어간다:
(1) 테마 한 줄 정의 (2) 왜 이 학생에게 맞는지 (3) 3년간 확장 가능성 (4) 입시 관점에서의 차별성

서로 실질적으로 다른 방향의 후보를 낸다. 표현만 바꾼 같은 테마를 여러 개 내지 않는다.

{_fixed_block(fixed)}
{_note_block(note)}
학생 프로파일:
{_profile_block(profile)}"""
    return _run(instance_id, prompt, THEME_SCHEMA)


def design_framework(instance_id: str, theme: Dict[str, Any], profile: Dict[str, Any],
                     fixed: Dict[str, Any], note: str = '') -> Dict[str, Any]:
    """Phase 3: 연구 프레임 + 1·2·3학년 분해."""
    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 Phase 3(연구 프레임 설계와 학년별 분해)다.
확정 테마 아래 큰 연구 틀을 세우고, 그것을 1→2→3학년으로 분해한다.

분해 원칙:
- 교육과정 정합성: 각 학년에서 실제로 배우는 과목·단원과 맞물려야 한다.
- 심화 구조: 1학년(기초 개념·문제 발견) → 2학년(방법론 습득·본격 탐구)
  → 3학년(종합·확장·독자적 결과물)의 서사적 성장이 보여야 한다.
- 각 학년에는 그 해를 대표할 앵커 프로젝트를 하나씩 둔다.
- curriculum_rationale에는 그 학년 과목·단원과 어떻게 맞물리는지 구체적으로 쓴다.

{GRADE_STRUCTURE}

{_fixed_block(fixed)}
{_note_block(note)}
선택된 테마: {theme.get('title')}
  근거: {theme.get('rationale') or '-'}
  확장: {theme.get('expansion') or '-'}

학생 프로파일:
{_profile_block(profile)}"""
    return _run(instance_id, prompt, FRAMEWORK_SCHEMA)


def narrow(instance_id: str, target_label: str, current: str, student_message: str,
           fixed: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 4: 대화형 구체화. 무조건 수용하지 않고 근거를 들어 대안을 낸다."""
    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 Phase 4(대화형 Narrowing)다. 학생의 요청을 그대로 받아 적지 마라.
학교 여건(장비, 예산, 시간, 안전, 윤리 승인)에서 비현실적인 부분이 있으면
concerns에 이유와 대안을 함께 적는다. 문제가 없으면 concerns는 빈 배열로 둔다.
질문은 한 번에 하나만 한다.

{_fixed_block(fixed)}

구체화 대상: {target_label}
현재 안:
{current}

학생의 요청:
{student_message}"""
    return _run(instance_id, prompt, NARROWING_SCHEMA)


def design_subject_plans(instance_id: str, grade: int, grade_plan: Dict[str, Any],
                         standards: List[Dict[str, Any]], fixed: Dict[str, Any],
                         subjects: Optional[List[str]] = None, note: str = '') -> Dict[str, Any]:
    """Phase 5: 앵커 프로젝트 확정 + 과목별 세특 플랜."""
    anchor = (grade_plan or {}).get('anchor_project') or {}
    subject_hint = (f"\n다룰 과목: {', '.join(subjects)}" if subjects else '')

    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 Phase 5({grade}학년 세특 구체화)다.

먼저 이 학년을 대표할 앵커 프로젝트 1개를 확정한다(이미 정해져 있으면 그것을 쓰되 근거를 밝힌다).
그 다음 과목마다 접근 전략을 판단한다:
- linked(교과 연계형): 앵커 프로젝트의 요소를 그 과목 내용과 연결
- deepening(교과 심화형): 그 과목 자체를 깊게 파는 독립 탐구
어느 쪽인지 approach_rationale에 판단 근거를 반드시 쓴다. 모든 과목을 연계형으로 몰지 마라.

성취기준은 아래 목록에 있는 코드만 쓴다. 목록에 없는 코드는 절대 지어내지 않는다.
motivation에는 수업 중 어느 지점에서 호기심이 출발했는지를 서사로 쓴다.
activity_design은 탐구 질문 → 방법 → 예상 산출물 순으로 학생이 실제로 수행할 수 있게 쓴다.

{_fixed_block(fixed)}
{_note_block(note)}
{grade}학년 계획:
  목표: {(grade_plan or {}).get('goal') or '-'}
  앵커 프로젝트: {anchor.get('title') or '(미정)'} — {anchor.get('description') or ''}{subject_hint}

사용 가능한 성취기준:
{_standards_block(standards)}"""
    return _run(instance_id, prompt, SUBJECT_PLAN_SCHEMA)


def run_experiment(instance_id: str, subject_plan: Dict[str, Any],
                   standards: List[Dict[str, Any]], fixed: Dict[str, Any]) -> Dict[str, Any]:
    """Agentic 실행: 배경 조사 → 설계 → 실행 → 결과 정리 → 보고서 초안."""
    design = subject_plan.get('activity_design') or {}
    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 Agentic 실행 단계다. 아래 탐구 계획을 실제로 수행하듯 진행하고 보고서 초안을 만든다.

단계는 이 순서로 기록한다:
1) 배경 조사 — 관련 개념과 선행 사례 정리
2) 탐구 설계 — 변인, 절차, 필요한 도구
3) 실행 — 예상되는 데이터의 형태와 분석 방법(가상의 수치를 실제 측정값처럼 단정하지 않는다)
4) 결과 정리 — 무엇을 확인할 수 있고 무엇은 확인할 수 없는지
5) 보고서 작성

보고서는 학생이 직접 수행할 수 있는 수준이어야 하고,
아직 수행하지 않은 결과를 이미 나온 것처럼 쓰지 않는다. 한계와 후속 과제를 반드시 포함한다.

{_fixed_block(fixed)}

과목: {subject_plan.get('subject')}
접근 전략: {subject_plan.get('approach')}
단원: {subject_plan.get('area_name') or '-'}
탐구 질문: {design.get('question') or '-'}
방법: {design.get('method') or '-'}
예상 산출물: {design.get('output') or '-'}

연결된 성취기준:
{_standards_block(standards)}"""
    return _run(instance_id, prompt, AGENT_RUN_SCHEMA)


# ---------- 온보딩(가입 직후 프로파일 만들기) ----------

ONBOARDING_SCHEMA = {
    'type': 'object',
    'properties': {
        'interests': {
            'type': 'array', 'items': {'type': 'string'},
            'description': '관심 도메인 키워드 2~5개',
        },
        'problem_statement': {
            'type': 'string',
            'description': '학생이 풀고 싶어하는 문제를 한 문장으로',
        },
        'aspired_track': {'type': 'string', 'description': '지망 계열'},
        'strength_subjects': {
            'type': 'array', 'items': {'type': 'string'},
            'description': '강점 교과 1~4개',
        },
        'activity_history': {
            'type': 'array', 'items': {'type': 'string'},
            'description': '지금까지 해온 관련 활동',
        },
    },
    'required': ['interests', 'problem_statement', 'aspired_track',
                 'strength_subjects', 'activity_history'],
    'additionalProperties': False,
}


def refine_onboarding(instance_id: str, answers: Dict[str, str]) -> Dict[str, Any]:
    """온보딩 자유 답변을 프로파일 필드로 정리합니다.

    학생이 쓴 표현을 존중하고, 말하지 않은 내용을 지어내지 않습니다.
    """
    prompt = f"""{BASE_SYSTEM_PROMPT}

지금은 가입 직후 온보딩이다. 학생이 4가지 질문에 자유롭게 답했다.
이 답변을 프로파일 필드로 정리한다.

규칙:
- 학생이 쓴 표현을 최대한 살린다. 멋있게 바꾸려고 내용을 부풀리지 않는다.
- 학생이 말하지 않은 활동·과목·계열을 지어내지 않는다. 답이 없으면 빈 배열로 둔다.
- problem_statement는 학생의 문제의식을 한 문장으로 다듬는다.

1) 어떤 것에 마음이 가는지:
{answers.get('interests') or '(답 없음)'}

2) 풀거나 바꾸고 싶은 것:
{answers.get('problem') or '(답 없음)'}

3) 지망 계열과 잘 맞는 과목:
{answers.get('track') or '(답 없음)'}

4) 지금까지 해본 관련 활동:
{answers.get('activity') or '(답 없음)'}"""
    return _run(instance_id, prompt, ONBOARDING_SCHEMA)


# ---------- 대화형 진행(메인 채팅 / research 미니 채팅) ----------

# AI가 말만 하는 게 아니라 다음 행동까지 정하게 한다.
# 학생이 "좀 더 환경 쪽으로" 같은 요구를 하면 note에 담아 생성 단계로 넘긴다.
CONVERSATION_SCHEMA = {
    'type': 'object',
    'properties': {
        'reply': {
            'type': 'string',
            'description': '학생에게 보여줄 답변. 한 번에 하나만 묻는다.',
        },
        'action': {
            'type': 'string',
            'enum': ['none', 'create_themes', 'select_theme', 'create_framework',
                     'create_subjects', 'run_experiment', 'open_research', 'connect_chatgpt'],
            'description': '학생의 의사가 분명할 때만 none 외의 값을 고른다.',
        },
        'target': {
            'type': 'string',
            'description': '대상 식별자. 테마 선택이면 테마 번호, 세특이면 학년. 없으면 빈 문자열.',
        },
        'note': {
            'type': 'string',
            'description': '학생이 요구한 조건(방향, 제약, 선호). 생성 단계에 그대로 전달된다. 없으면 빈 문자열.',
        },
    },
    'required': ['reply', 'action', 'target', 'note'],
    'additionalProperties': False,
}

# 단계별로 AI가 무엇을 물어야 하는지. 학생이 답하면 action으로 이어진다.
_STAGE_BRIEF = {
    'onboarding': '아직 프로파일이 없다. 관심사와 문제의식을 물어 온보딩(/welcome)으로 안내한다. '
                  '학생이 시작하겠다고 하면 action=open_research 대신 reply로 /welcome을 안내한다.',
    'themes': '프로파일은 있고 테마 후보가 없다. 3년 테마 후보를 만들지 물어본다. '
              '학생이 원하는 방향(예: 더 실험 중심으로, 환경 쪽으로)을 함께 물어 note에 담는다. '
              '동의하면 action=create_themes.',
    'select_theme': '테마 후보가 있지만 고르지 않았다. 어떤 후보가 끌리는지 묻는다. '
                    '학생이 특정 후보를 고르면 action=select_theme, target에 그 번호를 넣는다. '
                    '후보를 보고 싶다고 하면 action=open_research.',
    'framework': '테마는 정해졌고 학년별 계획이 없다. 3년 계획을 만들지 묻는다. '
                 '학생의 조건(장비, 시간, 하고 싶은 활동)을 물어 note에 담는다. 동의하면 action=create_framework.',
    'subjects': '학년 계획은 있고 과목별 세특이 없다. 어떤 과목을 어떻게 다루고 싶은지 묻는다. '
                '동의하면 action=create_subjects, target에 학년 숫자를 넣는다.',
    'experiments': '이번 학년 세특 설계는 끝났고, 이제 과목마다 실험을 직접 해야 한다. '
                   '실험은 /research 의 과목 카드에서 「실험 진행」을 눌러 전용 대화방에서 한다. '
                   '여기서 대신 만들어 주지 않는다. 로드맵을 보자고 하면 action=open_research.',
    'done': '설계가 갖춰졌다. 실험 진행이나 수정에 대해 묻는다. 로드맵을 보자고 하면 action=open_research.',
}


def converse(instance_id: str, message: str, history: List[Dict[str, str]],
             stage: str, state_summary: str, fixed: Dict[str, Any]) -> Dict[str, Any]:
    """학생과 대화하며 다음 행동을 정합니다."""
    transcript = '\n'.join(
        f"{'학생' if turn.get('role') == 'user' else '나'}: {turn.get('text', '')}"
        for turn in (history or [])[-8:] if turn.get('text')
    ) or '(첫 대화)'

    prompt = f"""{BASE_SYSTEM_PROMPT}

너는 지금 학생과 대화하며 3년 연구 서사를 함께 만들어 간다.

대화 규칙:
- 한 번에 하나만 묻는다. 여러 질문을 나열하지 않는다.
- 버튼을 누르라고 하지 말고, 말로 답하게 한다.
- 학생이 조건이나 선호를 말하면 note에 그대로 담아 다음 생성에 반영되게 한다.
- 학생의 의사가 분명할 때만 action을 고른다. 애매하면 action=none으로 두고 되묻는다.
- 짧고 자연스럽게. 세 문장을 넘기지 않는다.

지금 단계: {stage}
{_STAGE_BRIEF.get(stage, '')}

현재 상태:
{state_summary}

{_fixed_block(fixed)}

지금까지의 대화:
{transcript}

학생: {message}"""
    return _run(instance_id, prompt, CONVERSATION_SCHEMA)


# ---------- 실험 동반 학습 ----------

# 실험은 Agent가 대신 해주는 것이 아니라 학생이 직접 거치는 과정이다.
# 그래서 한 번에 끝내지 않고 아래 다섯 국면을 대화로 하나씩 넘어간다.
EXPERIMENT_PHASES = (
    ('background', '배경 조사'),
    ('design', '탐구 설계'),
    ('run', '실행 · 관찰'),
    ('analyze', '결과 정리'),
    ('conclude', '결론 · 한계'),
)
_PHASE_LABEL = dict(EXPERIMENT_PHASES)

EXPERIMENT_TURN_SCHEMA = {
    'type': 'object',
    'properties': {
        'reply': {
            'type': 'string',
            'description': '학생에게 할 말. 한 번에 하나만 묻는다. 세 문장을 넘기지 않는다.',
        },
        'phase': {
            'type': 'string',
            'enum': [key for key, _ in EXPERIMENT_PHASES],
            'description': '이번 대화가 끝난 시점에 학생이 서 있는 국면',
        },
        'is_complete': {
            'type': 'boolean',
            'description': '다섯 국면을 모두 거쳤고 학생이 결론과 한계까지 말했으면 true',
        },
        'search_query': {
            'type': 'string',
            'description': (
                '자료를 찾아야 하는데 네 웹 검색 도구를 쓸 수 없을 때만 적는 검색어. '
                '직접 검색했거나 검색이 필요 없으면 빈 문자열. '
                '검색이 안 되더라도 reply만으로 대화가 이어져야 한다.'
            ),
        },
        'image_query': {
            'type': 'string',
            'description': (
                '글로 설명하는 것보다 눈으로 봐야 이해되는데 images를 직접 채우지 '
                '못했을 때의 이미지 검색어. 직접 채웠거나 필요 없으면 빈 문자열.'
            ),
        },
        'images': {
            'type': 'array',
            'description': (
                '이해를 돕는 이미지. 웹 검색으로 실제 확인한 것만 넣는다. '
                '주소를 지어내지 않는다. 없으면 빈 배열. '
                '이미지는 대화에 바로 보이므로, reply에서 그 이미지를 보고 '
                '무엇을 확인하라고 말해 준다.'
            ),
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'description': '이 이미지가 무엇인지 한 줄'},
                    'image_url': {'type': 'string',
                                  'description': '이미지 파일의 https 주소(jpg/png/webp 등)'},
                    'page_url': {'type': 'string', 'description': '그 이미지가 실린 페이지 주소'},
                },
                'required': ['title', 'image_url', 'page_url'],
                'additionalProperties': False,
            },
        },
        'demo': {
            'type': 'object',
            'description': (
                '학생이 직접 눌러보며 확인해야 하는 화면. 만들지 않을 때는 html을 빈 문자열로 둔다. '
                '설명으로 될 일에는 만들지 않는다.'
            ),
            'properties': {
                'title': {'type': 'string', 'description': '이 화면이 무엇인지 한 줄'},
                'html': {
                    'type': 'string',
                    'description': (
                        '하나로 완결된 HTML 조각. <style>과 <script>를 안에 직접 넣는다. '
                        '외부 파일·CDN·이미지 주소를 부르지 않는다. 짧게 만든다.'
                    ),
                },
            },
            'required': ['title', 'html'],
            'additionalProperties': False,
        },
        'measure_table': {
            'type': 'object',
            'description': (
                '학생이 측정값을 적을 표의 열 정의. 실행·관찰 국면에서 반복 측정이 '
                '필요할 때만 채운다. 그 외에는 columns를 빈 배열로 둔다. '
                '값을 채워 주지 않는다 — 잰 값은 학생만 안다. 열 이름만 정한다.'
            ),
            'properties': {
                'title': {'type': 'string', 'description': '무엇을 재는 표인지 한 줄'},
                'columns': {
                    'type': 'array',
                    'description': (
                        '열 이름. 단위가 있으면 괄호로 함께 적는다. 예: '
                        '["시행", "질량(g)", "시간(s)"]. 2~5개. 첫 열은 시행 번호처럼 '
                        '무엇을 구분하는 이름으로 둔다.'
                    ),
                    'items': {'type': 'string'},
                },
                'rows': {
                    'type': 'integer',
                    'description': '처음에 보여줄 빈 행 수. 3~5 사이. 학생이 더 늘릴 수 있다.',
                },
            },
            'required': ['title', 'columns', 'rows'],
            'additionalProperties': False,
        },
    },
    'required': ['reply', 'phase', 'is_complete', 'search_query', 'image_query',
                 'images', 'demo', 'measure_table'],
    'additionalProperties': False,
}


def _experiment_context(subject_plan: Dict[str, Any], standards: List[Dict[str, Any]],
                        fixed: Dict[str, Any]) -> str:
    # 이 과목 실험이 대화의 초점이므로 맨 앞에 둔다. 테마·전체 계획은 배경으로만 뒤에 붙인다 —
    # 앞에 두면 모델이 테마 이야기로 자꾸 되돌아간다(실측된 문제).
    design = subject_plan.get('activity_design') or {}
    return f"""◆ 이번 대화의 초점 — 이 과목 실험:
과목: {subject_plan.get('subject')}
접근 전략: {subject_plan.get('approach')}
단원: {subject_plan.get('area_name') or '-'}
탐구 질문: {design.get('question') or '-'}
방법: {design.get('method') or '-'}
예상 산출물: {design.get('output') or '-'}

연결된 성취기준:
{_standards_block(standards)}

◆ 배경 맥락(참고만 한다 — 이 대화에서 다루지 않는다):
{_fixed_block(fixed)}"""


def experiment_turn(instance_id: str, subject_plan: Dict[str, Any],
                    standards: List[Dict[str, Any]], fixed: Dict[str, Any],
                    history: List[Dict[str, str]], message: str,
                    on_stage=None) -> Dict[str, Any]:
    """실험을 학생과 함께 한 걸음 진행합니다.

    대신 수행해 주면 세특으로서 의미가 없습니다. 실행·관찰·판단은 학생 몫으로 남기고,
    학생이 낸 답을 근거로 다음 국면으로 넘어갑니다.

    다만 자료 조사까지 막지는 않습니다. 학생이 찾아 달라고 하면 배경 지식과 사례를
    출처와 함께 정리해 줍니다. 그러지 않으면 학생은 막힌 자리에서 그냥 멈춥니다.
    """
    transcript = '\n'.join(
        f"{'학생' if turn.get('role') == 'user' else '나'}: {turn.get('text', '')}"
        for turn in (history or [])[-12:] if turn.get('text')
    ) or '(첫 대화)'

    phases = '\n'.join(f'{index}) {label}' for index, (_, label)
                       in enumerate(EXPERIMENT_PHASES, start=1))

    prompt = f"""{BASE_SYSTEM_PROMPT}

너는 지금 학생 옆에서 실험을 함께 진행하는 조력자다.

이 대화의 초점은 아래 '이번 대화의 초점'에 적힌 그 과목 실험 하나다.
3년 테마나 다른 학년 계획은 배경일 뿐이다 — 네가 먼저 테마 이야기를 꺼내거나,
질문·제안·책 추천을 테마 기준으로 하지 않는다. 전부 이 과목의 탐구 질문과
방법에 붙여서 한다. 학생이 테마 전체를 물어도 이 실험과 닿는 부분만 답하고
실험으로 돌아온다.

'대신 해주지 않는다'가 무엇을 뜻하는지 먼저 갈라 두자.

학생만 할 수 있는 일 — 절대 대신하지 않는다:
- 실제로 해보는 것(관찰, 측정, 설문, 시도)과 거기서 나온 수치·기록
- 그 결과를 어떻게 읽을지에 대한 학생의 판단과 결론
- 수치나 관찰 결과는 반드시 학생이 말한 것만 쓴다. 지어내지 않는다.
- 학생이 아직 하지 않은 일을 한 것처럼 정리하지 않는다.

내가 도와도 되는 일 — 학생이 부탁하면 거절하지 말고 해준다:
- 배경 지식 정리, 개념 설명, 선행 연구·사례·용어 찾아주기
- 자료를 어디서 어떻게 찾는지, 무엇을 봐야 하는지 알려주기
- 학생이 가져온 자료를 같이 읽고 정리해 주기

시각 자료는 아끼지 말고 적극적으로 보여준다:
- 학생이 부탁하기를 기다리지 않는다. 책을 추천하면 표지를, 장치·화면·구조를
  설명하면 실물 사진이나 도해를, 사례를 들면 그 화면을 — 말로 설명할 대상이
  눈에 보이는 것이면 먼저 검색해서 images에 담아 같이 보여준다.
- 글로 세 문장 설명할 것을 그림 한 장이 대신할 수 있으면 그림을 고른다.
- 단, 실제로 검색해서 확인한 이미지 주소만 쓴다. 이 원칙은 그대로다.

학생이 "찾아봐 줘", "검색해 줘"라고 하면 이 순서로 한다:
1) 너에게 웹 검색 도구가 있으면 그것부터 쓴다. 실제로 찾아보고,
   알아낸 것을 출처(매체·제목·링크)와 함께 reply에 적는다.
   이때 search_query는 빈 문자열로 둔다.
2) 웹 검색 도구를 쓸 수 없을 때만 search_query에 찾아볼 검색어를 적는다.
   그러면 내가 대신 검색해서 자료를 가져다준다.
3) 검색을 못 했을 때만 검색어 두세 개와 "무엇을 확인해야 하는지"를 알려준다.
   찾아준 경우에는 검색어를 늘어놓지 않는다. 이미 필요 없다.

- 찾지 않은 것을 찾은 것처럼 쓰거나 링크를 지어내지 않는다.
  검색으로 실제 확인한 것만 출처를 붙인다.

측정값 표(measure_table)를 여는 경우:
- 학생이 같은 것을 여러 번 재야 하는 순간(실행·관찰 국면)에 measure_table.columns에
  열 이름을 정해 준다. 그러면 화면에 표 입력기가 뜨고 학생이 폰으로 값을 넣는다.
  실험은 책상이 아니라 주방·운동장에서 하므로, 문장으로 받아 적게 하면 기록이 끊긴다.
- 열은 탐구 설계의 변인에서 가져온다. 단위를 괄호로 붙인다. 예: 시행 / 질량(g) / 시간(s).
- 값은 절대 채우지 않는다. 잰 사람은 학생이다. 예시 숫자도 넣지 않는다.
- 한 번 열었으면 학생이 기록해 올 때까지 다시 열지 않는다.
- 반복 측정이 아닌 국면(배경 조사, 결론 등)에서는 columns를 빈 배열로 둔다.

직접 눌러볼 화면(demo)을 만드는 경우:
- 학생이 "만들어 줘", "눌러보고 싶어"라고 할 때는 물론이고, 직접 만져보면
  이해가 빨라지는 순간이면 네가 먼저 만들어서 보여준다 — 버튼 문구·배치 비교,
  개념 시뮬레이션, 간단한 측정 도구 같은 것. 요청을 기다리며 아끼지 않는다.
- 실험용 화면이라면 비교하는 조건만 다르게 하고 나머지(색·크기·위치·글꼴)는 똑같이 맞춘다.
  그러지 않으면 무엇 때문에 차이가 났는지 알 수 없다.
- 학생이 스스로 기록할 수 있게 만든다. 필요하면 클릭 수나 시간을 화면 안에 표시해 준다.
  다만 그 숫자를 네가 결과라고 단정하지 않는다. 판단은 학생이 한다.
- 글꼴은 Google Fonts나 jsdelivr에서 불러와도 된다(<link>나 CSS @import).
  그 밖의 외부 주소는 부르지 않는다 — 그림·스크립트·프레임은 안에서 끝내야 한다.
  그림이 필요하면 이모지나 CSS로 그린다.
- demo를 만들었으면 reply에서 그 화면으로 무엇을 해보라고 알려준다.

출처와 이미지를 붙이는 방법:
- 출처는 본문 안에 [제목](주소) 형태로 넣는다. 화면이 작은 칩으로 바꿔 보여주므로
  주소를 그대로 늘어놓지 않아도 된다.
- 눈으로 봐야 이해되는 것(장치·화면·그래프·구조)은 images에 담는다.
  검색으로 실제 본 이미지 주소만 넣는다. 열리지 않는 주소는 화면에서 지워진다.
- 이미지를 넣었으면 reply에서 그 이미지를 보고 무엇을 확인하라고 말해 준다.
  사진만 던져놓고 끝내지 않는다.
- 끝에는 학생이 직접 확인·판단해야 할 것을 하나 남긴다.
  자료를 준 것이 실험을 대신 해준 것이 되지 않게 한다.

말투 — 이건 대화지 보고서가 아니다:
- 옆자리에서 말해 주듯 편한 반말로 쓴다. "~해", "~해볼래?", "~인 것 같아", "~더라".
- 논문체·설명문체 종결을 쓰지 않는다.
  쓰지 말 것: "~이다", "~한다", "~하는가?", "~해야 한다", "~인 셈이다".
  이렇게: "실제로 두 가지가 다 쓰이더라", "어느 쪽이 더 빠를 것 같아?"
- 학생을 '너'라고 부른다. 자기 자신을 '본 에이전트' 같은 말로 부르지 않는다.

말하는 양:
- 한 번에 하나만 묻는다. 평소에는 세 문장을 넘기지 않는다.
- 자료를 정리해 줄 때도 항목은 세 개까지다. 다 쏟아내면 학생이 읽지 않는다.
- 목록을 줬으면 마지막은 반드시 질문 하나로 끝낸다.
- 학생이 막히면 답을 주는 대신 생각할 단서를 준다.

실험은 이 다섯 국면을 순서대로 지난다:
{phases}

각 국면에서 학생이 충분히 답했다고 판단되면 다음 국면으로 넘어가고,
phase에는 이번 대화가 끝난 시점의 국면을 적는다.
다섯 국면을 모두 지나고 학생이 결론과 한계까지 말했을 때만 is_complete=true.
그 전에는 절대 true로 두지 않는다.

{_experiment_context(subject_plan, standards, fixed)}

지금까지의 대화:
{transcript}

학생: {message}"""
    # 화면이 '생각 중'과 '찾는 중'을 다르게 보여줄 수 있도록 지금 무엇을 하는지 알린다.
    def stage(name: str, label: str = '') -> None:
        if on_stage:
            on_stage(name, label)

    stage('thinking')
    result = _run(instance_id, prompt, EXPERIMENT_TURN_SCHEMA)

    # Codex가 자기 웹 검색 도구를 썼다면 답변에 링크가 들어 있다. 그러면 우리가 또 찾지 않는다.
    # 못 썼을 때만 search_query가 채워져 오고, 그때 우리가 대신 찾아 다시 답하게 한다.
    found = None
    query = (result.get('search_query') or '').strip()
    if query and web_search.available():
        stage('searching', query)
        found = web_search.search(query)
    if found:
        stage('thinking')
        result = _answer_with_sources(instance_id, prompt, result, found)

    # 눈으로 봐야 하는 것이면 이미지도 대화에 함께 놓는다.
    # Codex가 직접 찾아온 것을 먼저 쓰되, 지어낸 주소가 섞일 수 있어 열리는지 확인한다.
    images: List[Dict[str, str]] = []
    proposed = result.get('images') or []
    if proposed:
        stage('searching_images', '이미지 확인')
        images = web_search.verify_images(proposed)
    image_query = (result.get('image_query') or '').strip()
    if not images and image_query and web_search.available():
        stage('searching_images', image_query)
        images = web_search.search_images(image_query)

    stage('thinking')
    result['demo'] = _clean_demo(result.get('demo'))
    result['measure_table'] = _clean_measure_table(result.get('measure_table'))
    result['phase_label'] = _PHASE_LABEL.get(result.get('phase'), '')
    result['sources'] = ((found or {}).get('sources')
                         or _links_in(result.get('reply') or ''))
    result['images'] = images
    return result


# 측정값 표의 한계. 폰 화면에 들어가야 하고, 보고서의 HWP 표도 20행까지만 받는다.
_TABLE_MAX_COLS = 5
_TABLE_MAX_ROWS = 20


def _clean_measure_table(table: Any) -> Dict[str, Any]:
    """모델이 정한 표 열 정의를 쓸 수 있는 것만 남깁니다.

    값이 딸려 오면 버립니다. 잰 값은 학생만 아는 것이고, 모델이 채운 숫자가
    표에 미리 들어가 있으면 학생이 그걸 지우지 않고 그대로 낼 수 있습니다.
    """
    if not isinstance(table, dict):
        return {'title': '', 'columns': [], 'rows': 0}
    columns = [str(name).strip() for name in (table.get('columns') or [])
               if str(name).strip()]
    if len(columns) < 2:
        return {'title': '', 'columns': [], 'rows': 0}
    columns = columns[:_TABLE_MAX_COLS]
    try:
        rows = int(table.get('rows') or 3)
    except (TypeError, ValueError):
        rows = 3
    return {
        'title': str(table.get('title') or '').strip()[:60],
        'columns': columns,
        'rows': max(1, min(rows, _TABLE_MAX_ROWS)),
    }


# 화면 조각의 크기 상한. 대화 한 칸에 들어갈 것이고, 저장도 대화 기록에 함께 된다.
_DEMO_MAX_CHARS = 20000

# 밖으로 나가는 자원. 샌드박스 안이라 우리 쪽을 건드리진 못하지만,
# 학생 화면에서 외부로 요청이 나가는 것은 글꼴만 허용한다.
#
#   src=…      스크립트·이미지·프레임이 들어오는 통로라 외부 주소를 아예 막는다.
#   href=…     <link rel="stylesheet">로 글꼴을 부르는 자리. 글꼴 호스트만 허용한다.
#   url(…)     CSS의 @font-face·@import. 마찬가지로 글꼴 호스트만.
#
# 스타일시트로는 스크립트가 들어올 수 없으므로, 글꼴을 열어도 실행되는 코드는 늘지 않는다.
_DEMO_FONT_HOSTS = (
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    'cdn.jsdelivr.net',
    'fastly.jsdelivr.net',
)
_DEMO_SRC_RE = re.compile(r'\bsrc\s*=\s*["\']?\s*(?:https?:)?//', re.IGNORECASE)
_DEMO_REF_RE = re.compile(
    r"""(?:href\s*=\s*["']?|url\(\s*["']?|@import\s+["'])\s*((?:https?:)?//[^"'\s)>]+)""",
    re.IGNORECASE)


def _demo_font_only(html: str) -> bool:
    """바깥을 부르는 곳이 글꼴뿐인지 확인합니다."""
    if _DEMO_SRC_RE.search(html):
        return False
    for url in _DEMO_REF_RE.findall(html):
        host = url.split('//', 1)[-1].split('/', 1)[0].split('@')[-1].lower()
        if not any(host == allowed or host.endswith(f'.{allowed}')
                   for allowed in _DEMO_FONT_HOSTS):
            return False
    return True


def _clean_demo(demo: Any) -> Dict[str, str]:
    """모델이 만든 화면 조각을 쓸 수 있는 것만 남깁니다.

    비었거나, 너무 크거나, 바깥 자원을 부르면 버립니다. 화면을 못 띄운다고
    대화가 끊기지는 않습니다 — 설명은 reply에 이미 들어 있습니다.
    """
    if not isinstance(demo, dict):
        return {'title': '', 'html': ''}
    html = str(demo.get('html') or '').strip()
    if not html:
        return {'title': '', 'html': ''}
    if len(html) > _DEMO_MAX_CHARS:
        logger.info('[EXPERIMENT] 화면 조각이 너무 커서 버립니다(%s자).', len(html))
        return {'title': '', 'html': ''}
    if not _demo_font_only(html):
        logger.info('[EXPERIMENT] 글꼴 외의 바깥 자원을 부르는 화면 조각이라 버립니다.')
        return {'title': '', 'html': ''}
    return {'title': str(demo.get('title') or '').strip()[:80], 'html': html}


# 답변에 그대로 적힌 링크. Codex가 직접 검색했는지 알려면 이것 말고 단서가 없다.
_LINK_RE = re.compile(r'https?://[^\s<>()\[\]"\']+')


def _links_in(text: str) -> List[Dict[str, str]]:
    seen: List[Dict[str, str]] = []
    for url in _LINK_RE.findall(text or ''):
        url = url.rstrip('.,;')
        if all(item['url'] != url for item in seen):
            seen.append({'title': url, 'url': url})
    return seen[:web_search.MAX_RESULTS]


def _answer_with_sources(instance_id: str, prompt: str, first: Dict[str, Any],
                         found: Dict[str, Any]) -> Dict[str, Any]:
    """찾아온 자료를 주고 답을 다시 쓰게 합니다. 실패하면 첫 답변을 그대로 씁니다."""
    followup = f"""{prompt}

{web_search.as_block(found)}

위 검색 결과는 학생이 부탁해서 찾아온 것이다. 이걸 읽고 답을 다시 쓴다.
- 말투 규칙은 위에 적은 그대로다. 자료를 붙였다고 보고서 문체로 바뀌면 안 된다.
  편한 반말로, 옆에서 말해 주듯 쓴다.
- 검색 요약문에 있는 내용만 쓴다. 없는 수치·결론을 채워 넣지 않는다.
- 요약문만으로 확실하지 않으면 "요약만 봐서는 여기까지"라고 밝히고,
  어느 링크를 직접 열어 무엇을 확인해야 하는지 알려준다.
- 어디에서 나온 이야기인지 본문에서 밝힌다(링크 목록은 따로 붙으니 나열하지 않는다).
- 자료를 읽은 뒤 학생이 직접 확인하거나 판단해야 할 것을 하나 남긴다.
- search_query는 빈 문자열로 둔다(이미 찾았다).
  눈으로 봐야 하는 것이 남았으면 image_query는 채워도 된다."""
    try:
        second = _run(instance_id, followup, EXPERIMENT_TURN_SCHEMA)
    except PipelineError as exc:
        logger.info('[EXPERIMENT] 자료 반영 실패, 첫 답변을 씁니다: %s', exc.message)
        return first

    # 국면과 완료 판단은 첫 답변의 것을 유지한다. 자료를 붙였다고 진도가 나가면 안 된다.
    second['phase'] = first.get('phase')
    second['is_complete'] = bool(first.get('is_complete'))
    # 출처는 대화 기록에 남아야 보고서의 참고 자료가 된다.
    second['reply'] = (second.get('reply') or '') + web_search.as_reply_footer(found)
    return second


# ---------- 단계형 보고서 생성 ----------
#
# 보고서처럼 큰 산출물을 한 번의 호출로 만들면 어느 부분이 왜 빠졌는지 알 수 없다.
# 그래서 계획을 먼저 세우고(무슨 장을 쓸지, 무슨 그림을 넣을지),
# 장마다 별도의 턴으로 집필한다. 화면은 단계가 하나씩 끝나는 것을 보여준다.

_FIGURE_ITEM_SCHEMA = {
    'type': 'object',
    'properties': {
        'no': {'type': 'integer', 'description': '본문 [FIGURE n]과 맞출 번호'},
        'kind': {'type': 'string', 'enum': ['chart', 'image']},
        'caption': {'type': 'string',
                    'description': '그림 설명 한 줄. "Figure n." 은 붙이지 않는다'},
        'python_code': {
            'type': 'string',
            'description': (
                'kind=chart일 때만. matplotlib 코드. 데이터는 코드 안에 리터럴로 넣고, '
                "마지막에 plt.savefig(OUT_PATH, dpi=150, bbox_inches='tight') 를 부른다. "
                'OUT_PATH 변수는 주어진다. 다른 라이브러리·파일·네트워크는 쓰지 않는다.'
            ),
        },
        'image_url': {
            'type': 'string',
            'description': (
                'kind=image일 때만. 웹 검색으로 실제 확인한 이미지 파일의 https 직링크'
                '(가능하면 .jpg/.png 등으로 끝나는 주소). 지어내지 않는다.'
            ),
        },
        'image_query': {
            'type': 'string',
            'description': (
                'kind=image일 때만. image_url이 열리지 않을 때 대신 검색할 짧은 검색어. '
                'chart면 빈 문자열.'
            ),
        },
    },
    'required': ['no', 'kind', 'caption', 'python_code', 'image_url', 'image_query'],
    'additionalProperties': False,
}

REPORT_PLAN_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string', 'description': '보고서 제목. 탐구 질문이 드러나는 명사구'},
        'sections': {
            'type': 'array',
            'description': '장 목록. 로마 숫자 I~IV 순서.',
            'items': {
                'type': 'object',
                'properties': {
                    'heading': {'type': 'string', 'description': '예: I. 주제'},
                    'brief': {'type': 'string',
                              'description': '이 장에 들어갈 내용을 두세 문장으로'},
                    'figure_nos': {'type': 'array', 'items': {'type': 'integer'},
                                   'description': '이 장에 들어갈 그림 번호. 없으면 빈 배열'},
                },
                'required': ['heading', 'brief', 'figure_nos'],
                'additionalProperties': False,
            },
        },
        'figures': {'type': 'array', 'items': _FIGURE_ITEM_SCHEMA,
                    'description': '보고서 전체에 넣을 그림. 없으면 빈 배열'},
    },
    'required': ['title', 'sections', 'figures'],
    'additionalProperties': False,
}

REVISE_FIGURES_SCHEMA = {
    'type': 'object',
    'properties': {
        'figures': {'type': 'array', 'items': _FIGURE_ITEM_SCHEMA,
                    'description': '수정된 전체 그림 목록. 남길 그림도 다시 포함한다.'},
        'note': {'type': 'string', 'description': '학생에게 알릴 반영 내용 한 줄'},
    },
    'required': ['figures', 'note'],
    'additionalProperties': False,
}


def revise_figures(instance_id: str, subject: str, topic: str,
                   figures: List[Dict[str, Any]], feedback: str) -> Dict[str, Any]:
    """학생의 요청대로 그림 계획을 고칩니다.

    계획을 보여주고 받은 피드백("실제 앱 화면으로 바꿔줘", "2번은 빼줘")을
    그림 목록에 반영합니다. 본문 집필 전에 돌므로 문서와 어긋나지 않습니다.
    """
    current = '\n'.join(
        f"- 그림 {item.get('no')} [{item.get('kind')}] {item.get('caption')}"
        for item in figures) or '(없음)'
    prompt = f"""고등학생 '{subject}' 탐구 보고서({topic})의 그림 계획을 학생 요청대로 고친다.

현재 계획:
{current}

학생의 요청:
{feedback}

규칙:
- 요청을 반영해 전체 그림 목록을 다시 낸다. 남길 그림은 그대로 다시 포함한다.
- 번호는 유지하고, 새 그림은 새 번호를 쓴다.
- kind=chart의 수치는 학생이 실험 대화에서 말한 것만 쓴다. 지어내지 않는다.
- kind=image는 caption과 image_query만 충실히 적으면 된다.
  실제 주소는 다음 단계(이미지 검색)가 찾는다.

{_FIGURE_GUIDE}"""
    return _run(instance_id, prompt, REVISE_FIGURES_SCHEMA)


IMAGE_SEARCH_SCHEMA = {
    'type': 'object',
    'properties': {
        'results': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'no': {'type': 'integer', 'description': '요청 목록의 그림 번호'},
                    'image_url': {
                        'type': 'string',
                        'description': ('찾아낸 이미지 파일의 직링크. '
                                        '끝내 못 찾았으면 빈 문자열.'),
                    },
                    'page_url': {'type': 'string',
                                 'description': '그 이미지가 실린 페이지 주소. 없으면 빈 문자열'},
                    'found': {'type': 'boolean',
                              'description': '검색으로 실제 확인했으면 true'},
                },
                'required': ['no', 'image_url', 'page_url', 'found'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['results'],
    'additionalProperties': False,
}


def find_report_images(instance_id: str, subject: str, topic: str,
                       wanted: List[Dict[str, Any]]) -> Dict[int, Dict[str, str]]:
    """이미지 검색 전담 턴. 계획된 그림마다 실제 이미지 주소를 찾아옵니다.

    계획 턴에 검색까지 시키면 모델이 자주 건너뜁니다(문서 설계에 집중하느라).
    그래서 검색만 하는 별도의 턴을 둡니다 — 이 턴의 일은 검색뿐이라 빠질 수 없습니다.

    돌려주는 것: {그림 번호: {'image_url': ..., 'page_url': ...}} (찾은 것만)
    """
    if not wanted:
        return {}
    want_lines = '\n'.join(
        f"- 그림 {item.get('no')}: {item.get('caption') or ''}"
        f" (검색어 제안: {item.get('image_query') or item.get('caption') or ''})"
        for item in wanted)

    prompt = f"""너는 지금 이미지 검색만 담당한다. 문서 작성은 다른 단계가 한다.

고등학생의 '{subject}' 탐구 보고서({topic})에 넣을 이미지를 찾는다.
아래 각 그림에 대해 웹 검색을 실제로 수행해서, 브라우저로 열리는
이미지 파일 직링크(가능하면 .jpg/.png/.webp로 끝나는 주소)를 찾아라.

찾을 그림:
{want_lines}

규칙:
- 반드시 웹 검색을 수행한다. 기억으로 주소를 적지 않는다 — 그런 주소는 대부분 죽어 있다.
- 검색 결과에서 실제로 본 이미지 주소만 적는다. 못 찾았으면 found=false, 주소는 빈 문자열.
- 뉴스 기사·블로그·공식 안내 페이지에 실린 사진이 좋다. 저작권 표시가 있는 스톡 사진
  미리보기(워터마크)는 피한다.
- 각 그림마다 결과 하나씩, 요청한 번호 그대로 돌려준다."""
    result = _run(instance_id, prompt, IMAGE_SEARCH_SCHEMA)
    found: Dict[int, Dict[str, str]] = {}
    for row in result.get('results') or []:
        url = str(row.get('image_url') or '').strip()
        if row.get('found') and url.startswith(('http://', 'https://')):
            found[int(row.get('no') or 0)] = {
                'image_url': url, 'page_url': str(row.get('page_url') or '')}
    return found


REPORT_SECTION_SCHEMA = {
    'type': 'object',
    'properties': {
        'markdown': {
            'type': 'string',
            'description': (
                '이 장의 본문. # 장제목, ## 1. 소제목 마크다운. '
                '배정된 그림은 [FIGURE n] 을 그 줄에 홀로 적고 본문에서 Fig n으로 인용한다.'
            ),
        },
    },
    'required': ['markdown'],
    'additionalProperties': False,
}

# 과목마다 어울리는 그림이 다르다. 수치 실험이 아닌 탐구에 억지 그래프가 들어가면
# 문서가 오히려 이상해진다.
_FIGURE_GUIDE = """그림 계획 — 과목과 탐구 성격에 맞게 고른다:
- 학생이 수치를 말했고 그 비교가 핵심이면 그래프(kind=chart)를 쓴다.
  matplotlib 코드에 데이터를 리터럴로 넣는다. 대화에 없는 수치는 절대 넣지 않는다.
- 언어·사례·화면을 다루는 탐구(국어·사회·영어 등)는 그래프보다
  실제 사례 사진·화면(kind=image)이 훨씬 낫다. 이런 탐구라면 이미지 그림을
  한두 개는 계획하는 것이 기본이다 — 검색이 귀찮다고 figures를 비우지 않는다.
- kind=image는 지금 이 자리에서 웹 검색을 실제로 수행해 찾은 뒤 적는다.
  이미지 파일의 직링크(가능하면 .jpg/.png로 끝나는 주소)를 image_url에 넣는다.
- image_query는 항상 채운다. 주소가 죽으면 그 검색어로 대신 찾아 문서에 넣는다.
  즉 주소가 완벽하지 않아도 된다 — 검색어만 좋으면 그림은 들어간다.
- 같은 자료는 그림 하나로만 계획한다. 두 번호에 같은 이미지를 넣지 않는다.
  같은 그림을 다시 말해야 하면 본문에서 "Fig n"으로 인용만 한다.
- 마땅한 그림이 없으면 억지로 만들지 않는다. figures는 빈 배열이어도 된다."""


def report_plan(instance_id: str, subject_plan: Dict[str, Any],
                standards: List[Dict[str, Any]], fixed: Dict[str, Any],
                history: List[Dict[str, str]]) -> Dict[str, Any]:
    """1단계: 보고서의 설계도를 만듭니다. 장 구성과 그림 계획까지만 정합니다."""
    transcript = '\n'.join(
        f"{'학생' if turn.get('role') == 'user' else '조력자'}: {turn.get('text', '')}"
        for turn in (history or []) if turn.get('text')) or '(대화 없음)'

    prompt = f"""{BASE_SYSTEM_PROMPT}

아래는 학생이 실험을 진행하며 나눈 대화 전체다.
지금은 보고서를 쓰기 전, 문서의 설계도만 만든다. 본문은 다음 단계에서 장마다 따로 쓴다.

- 장은 로마 숫자로 나눈다: I. 주제(배경·문제의식) / II. 방법(설계·절차) /
  III. 결과 / IV. 해석 및 결론(한계·후속 과제 포함). 필요하면 넷 안에서 조정한다.
- 각 장의 brief에는 대화의 어떤 내용이 들어가는지 구체적으로 적는다.
- 대화에 없는 수치·관찰·출처를 계획에 넣지 않는다.

{_FIGURE_GUIDE}

{_experiment_context(subject_plan, standards, fixed)}

실험 대화 전체:
{transcript}"""
    return _run(instance_id, prompt, REPORT_PLAN_SCHEMA)


def report_section(instance_id: str, subject_plan: Dict[str, Any],
                   fixed: Dict[str, Any], history: List[Dict[str, str]],
                   plan: Dict[str, Any], section: Dict[str, Any],
                   written_tail: str,
                   standards: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """2단계: 계획된 장 하나를 집필합니다."""
    transcript = '\n'.join(
        f"{'학생' if turn.get('role') == 'user' else '조력자'}: {turn.get('text', '')}"
        for turn in (history or []) if turn.get('text')) or '(대화 없음)'

    numbers = section.get('figure_nos') or []
    figures = [figure for figure in (plan.get('figures') or [])
               if figure.get('no') in numbers]
    figure_lines = '\n'.join(
        f"- [FIGURE {figure['no']}] {figure.get('caption')}" for figure in figures
    ) or '(이 장에 배정된 그림 없음)'
    outline = '\n'.join(
        f"- {item.get('heading')}: {item.get('brief')}"
        for item in (plan.get('sections') or []))

    prompt = f"""{BASE_SYSTEM_PROMPT}

학생 탐구 보고서를 장마다 나눠 쓰고 있다. 지금은 아래 장 하나만 쓴다.

전체 구성(참고용 — 다른 장 내용을 여기서 쓰지 않는다):
{outline}

지금 쓸 장: {section.get('heading')}
이 장에 들어갈 내용: {section.get('brief')}
이 장에 배정된 그림 — 각각 [FIGURE n] 을 그 줄에 홀로 적고, 본문 문장에서 "Fig n과 같이"로 인용한다:
{figure_lines}

지켜야 할 것:
- 대화에 나온 내용만 쓴다. 수치·관찰·출처를 지어내지 않는다.
- 학생이 직접 한 일을 중심에 두고, 조력자가 찾아준 자료는 배경으로만 쓴다.
- 고등학생 보고서 문체, 종결은 '~하였다/~이다'. 과장하지 않는다.
- 마크다운은 # {section.get('heading')} 으로 시작하고, 소제목은 ## 1. 형식으로 단다.
- 학생이 말한 측정값·비교 결과처럼 행과 열로 정리되는 데이터는 마크다운 표로 쓴다
  (| 열이름 | ... | 형식, 머리글 아래 |---| 구분선). 문서에서 진짜 표로 바뀐다.
  표는 20행을 넘기지 않는다. 표로 만들 데이터가 없으면 억지로 만들지 않는다.
- 배정되지 않은 그림 번호를 쓰지 않는다.
- [FIGURE n] 은 배정된 번호마다 딱 한 번만 놓는다. 다른 장에 이미 놓인 그림을
  다시 말할 때는 [FIGURE n] 을 또 놓지 말고 본문에서 "Fig n"으로 인용만 한다.

바로 앞 장의 끝부분(이어지게 쓰되 반복하지 않는다):
{written_tail or '(첫 장이다)'}

{_experiment_context(subject_plan, standards or [], fixed)}

실험 대화 전체:
{transcript}"""
    return _run(instance_id, prompt, REPORT_SECTION_SCHEMA)


EXPERIMENT_REPORT_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string', 'description': '보고서 제목. 탐구 질문이 드러나는 명사구'},
        'report_markdown': {
            'type': 'string',
            'description': (
                '탐구 보고서 본문. 그림이 들어갈 자리에는 그 줄에 [FIGURE 1] 처럼 '
                '번호 표시만 홀로 적는다.'
            ),
        },
        'figures': {
            'type': 'array',
            'description': (
                '보고서에 넣을 그림. 본문의 [FIGURE n] 자리에 순서대로 들어간다. '
                '없으면 빈 배열.'
            ),
            'items': _FIGURE_ITEM_SCHEMA,
        },
    },
    'required': ['title', 'report_markdown', 'figures'],
    'additionalProperties': False,
}


def experiment_report(instance_id: str, subject_plan: Dict[str, Any],
                      standards: List[Dict[str, Any]], fixed: Dict[str, Any],
                      history: List[Dict[str, str]]) -> Dict[str, Any]:
    """실험 대화 전체를 탐구 보고서로 정리합니다.

    학생이 대화에서 실제로 말한 것만 재료로 씁니다. 대화에 없는 수치나 관찰을
    채워 넣으면 학생이 하지 않은 실험이 되어 버립니다.
    """
    transcript = '\n'.join(
        f"{'학생' if turn.get('role') == 'user' else '조력자'}: {turn.get('text', '')}"
        for turn in (history or []) if turn.get('text')
    ) or '(대화 없음)'

    prompt = f"""{BASE_SYSTEM_PROMPT}

아래는 학생이 실험을 진행하며 나눈 대화 전체다.
이 대화를 근거로 학생 이름의 탐구 보고서를 작성한다.

지켜야 할 것:
- 대화에 나온 내용만 쓴다. 대화에 없는 수치·관찰·출처를 지어내지 않는다.
- 학생이 직접 한 일과 조력자가 제안한 것을 구분해서, 학생이 수행한 것을 중심에 둔다.
- 조력자가 찾아준 자료는 배경이나 참고 자료로만 쓴다.
  학생이 직접 관찰·측정한 결과와 한 덩어리로 섞지 않는다.
- 결과가 불완전하면 불완전한 대로 쓰고, 한계와 후속 과제에 그 이유를 적는다.
- 고등학생이 쓴 보고서의 문체를 유지한다. 과장하지 않는다. 종결은 '~하였다/~이다'.

문서 구성 — 실제 탐구 보고서의 격식을 따른다:
- 장은 로마 숫자로 나눈다: I. 주제(배경·문제의식) / II. 방법(설계·절차) /
  III. 결과 / IV. 해석 및 결론(한계·후속 과제 포함). 장 아래 소제목은 1. 2. 로 단다.
- 마크다운 제목(#, ##)과 문단으로 구성하고, 표는 쓰지 않는다.

{_FIGURE_GUIDE}
- 본문에서 그림이 들어갈 자리에 [FIGURE 1] 처럼 그 줄에 번호만 홀로 적고,
  본문 문장에서 "Fig 1과 같이 …" 로 반드시 한 번 이상 인용한다.

{_experiment_context(subject_plan, standards, fixed)}

실험 대화 전체:
{transcript}"""
    return _run(instance_id, prompt, EXPERIMENT_REPORT_SCHEMA)


PPT_OUTLINE_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string', 'description': '발표 제목. 보고서 제목을 다듬은 것'},
        'slides': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'heading': {'type': 'string', 'description': '슬라이드 제목'},
                    'bullets': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': '요점 불릿. 각 60자 이내, 슬라이드당 6개 이내',
                    },
                    'notes': {'type': 'string',
                              'description': '발표자가 말할 내용(대본 메모). 2~4문장'},
                },
                'required': ['heading', 'bullets', 'notes'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['title', 'slides'],
    'additionalProperties': False,
}


def ppt_outline(instance_id: str, subject: str, topic: str,
                report_text: str) -> Dict[str, Any]:
    """완성된 보고서를 발표 슬라이드 개요로 추립니다.

    발표는 보고서 요약이 아니라 재구성이다. 다만 재료는 보고서에 있는 것만 쓴다 —
    보고서에 없는 수치·결론을 슬라이드에 만들어 넣으면 학생이 발표장에서 설명하지
    못한다.
    """
    prompt = f"""고등학생이 '{subject}' 탐구 보고서를 수업에서 발표하려고 한다.
보고서를 발표 슬라이드 개요로 추려라.

지켜야 할 것:
- 슬라이드는 표지를 빼고 5~10장. 흐름은 [탐구 질문 → 방법 → 결과 → 결론 → 한계와 다음 질문].
- 불릿은 문장이 아니라 요점이다. 각 60자 이내, 슬라이드당 6개 이내.
- notes에는 그 슬라이드에서 학생이 말할 내용을 발표하듯 2~4문장으로 쓴다.
  화면(불릿)에 없는 말이 notes에 오는 게 정상이다 — 화면을 읽는 발표는 나쁜 발표다.
- 보고서에 있는 내용만 쓴다. 수치·결론을 지어내지 않는다.
- 한국어로 쓴다.

탐구 질문: {topic or '-'}

보고서 본문:
{report_text[:8000]}"""
    return _run(instance_id, prompt, PPT_OUTLINE_SCHEMA)


STANDARDS_CHECK_SCHEMA = {
    'type': 'object',
    'properties': {
        'verdicts': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'code': {'type': 'string', 'description': '성취기준 코드. 주어진 것만'},
                    'reached': {'type': 'string', 'enum': ['yes', 'partial', 'no'],
                                'description': '보고서가 이 기준에 닿았는가'},
                    'evidence': {'type': 'string',
                                 'description': '근거가 된 보고서 대목 요약. 한 문장'},
                    'gap': {'type': 'string',
                            'description': '모자란 부분과 채우는 방법. 닿았으면 빈 문자열'},
                },
                'required': ['code', 'reached', 'evidence', 'gap'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['verdicts'],
    'additionalProperties': False,
}


def check_standards(instance_id: str, subject: str,
                    standards: List[Dict[str, Any]],
                    report_markdown: str) -> Dict[str, Any]:
    """완성된 보고서가 연결된 성취기준에 실제로 닿았는지 대조합니다.

    세특은 성취기준 도달을 보여주는 기록이다. 설계 때 고른 기준에 보고서가
    닿지 못했다면, 지금 알려줘야 학생이 보완할 수 있다 — 생기부에 적힌 뒤에는 늦다.
    """
    listing = '\n'.join(
        f"- {item.get('code')}: {item.get('description') or item.get('content') or '-'}"
        for item in standards) or '(연결된 성취기준 없음)'
    prompt = f"""고등학생 '{subject}' 탐구 보고서가 아래 성취기준에 닿았는지 하나씩 판정하라.

판정 기준:
- yes: 보고서에 그 기준을 채우는 활동과 결과가 구체적으로 드러난다.
- partial: 시도는 보이지만 결과나 해석이 모자라다.
- no: 근거를 찾을 수 없다.
- 관대하게 주지 않는다. 근거 없는 yes는 학생에게 해가 된다.
- evidence에는 판정의 근거가 된 보고서 대목을 한 문장으로 짚는다. 지어내지 않는다.
- gap에는 모자란 부분을 어떻게 채울지 실행 가능한 한 문장으로 쓴다.
- 주어진 코드만 다룬다. 코드를 만들어내지 않는다.

성취기준:
{listing}

보고서 본문:
{report_markdown[:8000]}"""
    return _run(instance_id, prompt, STANDARDS_CHECK_SCHEMA)


NARRATIVE_CHECK_SCHEMA = {
    'type': 'object',
    'properties': {
        'summary': {'type': 'string',
                    'description': '서사 전체에 대한 총평. 2~3문장, 반말 대화체'},
        'findings': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'kind': {'type': 'string', 'enum': ['strength', 'gap'],
                             'description': 'strength=이어짐이 좋은 곳, gap=끊긴 곳'},
                    'message': {'type': 'string',
                                'description': '어느 보고서와 어느 보고서 사이 얘기인지 '
                                               '알 수 있게. 한두 문장, 반말 대화체'},
                },
                'required': ['kind', 'message'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['summary', 'findings'],
    'additionalProperties': False,
}


def narrative_check(instance_id: str, fixed: Dict[str, Any],
                    entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """완성된 보고서들을 가로로 놓고 3년 서사가 이어지는지 봅니다.

    생기부는 단발성 활동의 나열이 아니라 하나의 테마 아래 심화되는 서사여야 한다
    (첫째 원칙). 학년별로 따로 만든 보고서들이 실제로 이어지는지는 이렇게
    한꺼번에 놓고 봐야만 보인다.
    """
    listing = '\n\n'.join(
        f"[{entry.get('grade') or '?'}학년 · {entry.get('subject')}] {entry.get('title')}\n"
        f"{(entry.get('text') or '')[:2500]}"
        for entry in entries)
    prompt = f"""{BASE_SYSTEM_PROMPT}

학생이 지금까지 만든 탐구 보고서들이다. 이것들이 하나의 서사로 이어지는지 평가하라.

봐야 할 것:
- 앞 보고서가 던진 질문·한계를 뒤 보고서가 이어받았는가.
- 같은 테마 아래에서 깊어지는가, 아니면 서로 무관한 활동의 나열인가.
- 아직 답해지지 않은 질문이 무엇이고, 다음 탐구가 그것을 어떻게 이어받으면 좋은가.

지켜야 할 것:
- 보고서에 있는 내용만 근거로 쓴다.
- findings는 3~6개. 잘 이어진 곳(strength)과 끊긴 곳(gap)을 모두 짚는다.
- 문어체(~이다/~하였다)를 쓰지 않는다. 옆에서 말해 주듯 반말 대화체로 쓴다.

{_fixed_block(fixed)}

보고서들:
{listing}"""
    return _run(instance_id, prompt, NARRATIVE_CHECK_SCHEMA)
