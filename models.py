"""
데이터베이스 모델 정의
"""
from datetime import date, datetime
import json
import re


ACADEMIC_YEAR_START_MONTH = 3
STUDENT_NUMBER_PATTERN = re.compile(r'^([1-3])([1-9])(\d{2})$')


def get_academic_year(at_date=None) -> int:
    """한국 학교 학사연도(3월 시작)를 반환합니다."""
    reference = at_date or date.today()
    return reference.year if reference.month >= ACADEMIC_YEAR_START_MONTH else reference.year - 1


def calculate_current_grade(admission_year, at_date=None):
    """입학연도로 현재 고등학교 학년을 계산하고 재학 범위가 아니면 None을 반환합니다."""
    try:
        year = int(admission_year)
    except (TypeError, ValueError):
        return None
    grade = get_academic_year(at_date) - year + 1
    return grade if 1 <= grade <= 3 else None


def parse_student_number(value):
    """4자리 학번을 학년/반/번호로 분리합니다. 예: 2412 -> 2학년 4반 12번."""
    raw = str(value or '').strip()
    match = STUDENT_NUMBER_PATTERN.fullmatch(raw)
    if not match:
        return None
    grade, classroom, number = map(int, match.groups())
    if not 1 <= number <= 99:
        return None
    return {
        'value': raw,
        'grade': grade,
        'classroom': classroom,
        'number': number,
    }


def calculate_admission_year_from_student_number(student_number, at_date=None):
    """학번 첫 자리 학년과 입력 시점의 학사연도로 입학연도를 계산합니다."""
    parsed = parse_student_number(student_number)
    if not parsed:
        return None
    return get_academic_year(at_date) - parsed['grade'] + 1


def should_update_student_number(
    student_number,
    student_number_academic_year,
    admission_year,
    at_date=None,
):
    """새 학년이 되었지만 학번이 이전 학년도 값이면 True를 반환합니다."""
    academic_year = get_academic_year(at_date)
    current_grade = calculate_current_grade(admission_year, at_date)
    try:
        number_year = int(student_number_academic_year)
    except (TypeError, ValueError):
        return False
    return bool(student_number and current_grade and number_year < academic_year)

class User:
    """사용자 모델"""
    def __init__(
        self,
        id,
        email,
        name,
        picture=None,
        password_hash=None,
        admission_year=None,
        student_number=None,
        student_number_academic_year=None,
    ):
        self.id = id
        self.email = email
        self.name = name
        self.picture = picture
        self.password_hash = password_hash
        self.admission_year = int(admission_year) if admission_year not in (None, '') else None
        self.student_number = str(student_number) if student_number not in (None, '') else None
        self.student_number_academic_year = (
            int(student_number_academic_year)
            if student_number_academic_year not in (None, '')
            else None
        )

    @property
    def current_grade(self):
        return calculate_current_grade(self.admission_year)

    @property
    def student_number_needs_update(self):
        return should_update_student_number(
            self.student_number,
            self.student_number_academic_year,
            self.admission_year,
        )

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'picture': self.picture,
            'admission_year': self.admission_year,
            'current_grade': self.current_grade,
            'academic_year': get_academic_year(),
            'has_student_number': bool(self.student_number),
            'student_number_academic_year': self.student_number_academic_year,
            'student_number_needs_update': self.student_number_needs_update,
        }

class DocumentHistory:
    """문서 히스토리 모델"""
    def __init__(self, id, user_id, title, content, created_at=None, updated_at=None):
        self.id = id
        self.user_id = user_id
        self.title = title
        self.content = content
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'content': self.content,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }

class ChatSession:
    """채팅 세션 모델"""
    def __init__(self, id, user_id, title, messages=None, created_at=None, updated_at=None,
                 folder=None, plan_id=None):
        self.id = id
        self.user_id = user_id
        self.title = title
        self.messages = messages or []
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()
        # 사이드바 HISTORY의 폴더('설계' / '실험'). 그 밖의 대화는 None.
        self.folder = folder
        # 실험 대화가 어느 과목 플랜의 것인지.
        self.plan_id = plan_id

    def to_dict(self, include_messages=True):
        payload = {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'folder': self.folder,
            'plan_id': self.plan_id
        }
        if include_messages:
            payload['messages'] = self.messages
        return payload

class RiroDocument:
    """리로스쿨 사용자 문서"""
    def __init__(self, id, riro_id, title, content, image_urls=None, created_at=None):
        self.id = id
        self.riro_id = riro_id
        self.title = title
        self.content = content
        self.image_urls = image_urls or []
        self.created_at = created_at or datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'id': self.id,
            'riro_id': self.riro_id,
            'title': self.title,
            'content': self.content,
            'image_urls': self.image_urls,
            'created_at': self.created_at
        }


# ============ 연구 서사(Research Narrative) ============

# 항목 상태 머신: 초안 -> 좁히는 중 -> 확정.
# fixed 항목은 이후 생성 작업의 불변 기준이 되며, 되돌리려면 명시적 unlock이 필요하다.
STATUS_DRAFT = 'draft'
STATUS_NARROWING = 'narrowing'
STATUS_FIXED = 'fixed'
RESEARCH_STATUSES = (STATUS_DRAFT, STATUS_NARROWING, STATUS_FIXED)

# 허용된 상태 전이. unlock은 fixed -> narrowing 을 뜻한다.
STATUS_TRANSITIONS = {
    STATUS_DRAFT: (STATUS_NARROWING, STATUS_FIXED),
    STATUS_NARROWING: (STATUS_DRAFT, STATUS_FIXED),
    STATUS_FIXED: (STATUS_NARROWING,),
}

# Phase 5의 과목별 접근 전략
APPROACH_LINKED = 'linked'      # 교과 연계형: 앵커 프로젝트 요소를 해당 과목과 연결
APPROACH_DEEPENING = 'deepening'  # 교과 심화형: 해당 과목 자체를 깊게 파는 독립 탐구
SUBJECT_APPROACHES = (APPROACH_LINKED, APPROACH_DEEPENING)


def can_transition(current, target):
    """상태 전이가 허용되는지 검사합니다."""
    if current == target:
        return True
    return target in STATUS_TRANSITIONS.get(current, ())


def _json_load(value, default):
    """DB의 TEXT 컬럼에 저장된 JSON을 파이썬 값으로 되돌립니다."""
    if value in (None, ''):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class StudentProfile:
    """Phase 1 산출물. 향후 진로 탐색 플랫폼과 연결할 수 있도록 extra로 확장 여지를 둔다."""
    def __init__(
        self,
        id,
        user_id,
        interests=None,
        problem_statement=None,
        aspired_track=None,
        strength_subjects=None,
        activity_history=None,
        interview_state=None,
        extra=None,
        status=STATUS_DRAFT,
        created_at=None,
        updated_at=None,
    ):
        self.id = id
        self.user_id = user_id
        self.interests = _json_load(interests, [])
        self.problem_statement = problem_statement
        self.aspired_track = aspired_track
        self.strength_subjects = _json_load(strength_subjects, [])
        self.activity_history = _json_load(activity_history, [])
        self.interview_state = _json_load(interview_state, {})
        self.extra = _json_load(extra, {})
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'interests': self.interests,
            'problem_statement': self.problem_statement,
            'aspired_track': self.aspired_track,
            'strength_subjects': self.strength_subjects,
            'activity_history': self.activity_history,
            'interview_state': self.interview_state,
            'extra': self.extra,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class Theme:
    """Phase 2 산출물. 후보 2~3개를 만들고 학생이 하나를 선택한다."""
    def __init__(
        self,
        id,
        user_id,
        profile_id=None,
        title=None,
        rationale=None,
        expansion=None,
        differentiation=None,
        is_selected=0,
        status=STATUS_DRAFT,
        created_at=None,
        updated_at=None,
    ):
        self.id = id
        self.user_id = user_id
        self.profile_id = profile_id
        self.title = title
        self.rationale = rationale          # 왜 이 학생에게 맞는지
        self.expansion = expansion          # 3년간 확장 가능성
        self.differentiation = differentiation  # 입시 관점 차별성
        self.is_selected = bool(is_selected)
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'profile_id': self.profile_id,
            'title': self.title,
            'rationale': self.rationale,
            'expansion': self.expansion,
            'differentiation': self.differentiation,
            'is_selected': self.is_selected,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class ResearchFramework:
    """Phase 3 산출물. 확정 테마 아래의 큰 연구 틀."""
    def __init__(
        self,
        id,
        user_id,
        theme_id=None,
        core_question=None,
        sub_areas=None,
        final_destination=None,
        status=STATUS_DRAFT,
        created_at=None,
        updated_at=None,
    ):
        self.id = id
        self.user_id = user_id
        self.theme_id = theme_id
        self.core_question = core_question
        self.sub_areas = _json_load(sub_areas, [])
        self.final_destination = final_destination
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'theme_id': self.theme_id,
            'core_question': self.core_question,
            'sub_areas': self.sub_areas,
            'final_destination': self.final_destination,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class GradePlan:
    """Phase 3 분해 산출물. 학년별 목표와 앵커 프로젝트."""
    def __init__(
        self,
        id,
        user_id,
        framework_id=None,
        grade=None,
        goal=None,
        anchor_project=None,
        curriculum_alignment=None,
        status=STATUS_DRAFT,
        created_at=None,
        updated_at=None,
    ):
        self.id = id
        self.user_id = user_id
        self.framework_id = framework_id
        self.grade = int(grade) if grade not in (None, '') else None
        self.goal = goal
        self.anchor_project = _json_load(anchor_project, {})
        self.curriculum_alignment = _json_load(curriculum_alignment, [])
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'framework_id': self.framework_id,
            'grade': self.grade,
            'goal': self.goal,
            'anchor_project': self.anchor_project,
            'curriculum_alignment': self.curriculum_alignment,
            'status': self.status,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class SubjectPlan:
    """Phase 5 산출물. 과목별 세특 플랜."""
    def __init__(
        self,
        id,
        user_id,
        grade_plan_id=None,
        subject=None,
        subject_uid=None,
        approach=None,
        approach_rationale=None,
        area_name=None,
        standard_codes=None,
        motivation=None,
        activity_design=None,
        status=STATUS_DRAFT,
        experiment_chat_id=None,
        experiment_status=None,
        report_file=None,
        created_at=None,
        updated_at=None,
    ):
        self.id = id
        self.user_id = user_id
        self.grade_plan_id = grade_plan_id
        self.subject = subject
        self.subject_uid = subject_uid  # CurriculumDB의 '별책:접두사' 키
        self.approach = approach
        self.approach_rationale = approach_rationale
        self.area_name = area_name
        self.standard_codes = _json_load(standard_codes, [])
        self.motivation = motivation           # 수업 중 호기심이 출발한 지점의 서사
        self.activity_design = _json_load(activity_design, {})  # 탐구 질문 -> 방법 -> 예상 산출물
        self.status = status
        # 실험 동반 학습: 학생이 Agent와 함께 진행한 대화방과 그 결과물
        self.experiment_chat_id = experiment_chat_id
        self.experiment_status = experiment_status  # None / running / done
        self.report_file = report_file              # output/ 아래의 .hwp 파일명
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'grade_plan_id': self.grade_plan_id,
            'subject': self.subject,
            'subject_uid': self.subject_uid,
            'approach': self.approach,
            'approach_rationale': self.approach_rationale,
            'area_name': self.area_name,
            'standard_codes': self.standard_codes,
            'motivation': self.motivation,
            'activity_design': self.activity_design,
            'status': self.status,
            'experiment_chat_id': self.experiment_chat_id,
            'experiment_status': self.experiment_status,
            'report_file': self.report_file,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


class AgentRun:
    """Agentic 실행 기록. 단계별 로그와 산출 보고서를 담는다."""
    def __init__(
        self,
        id,
        user_id,
        subject_plan_id=None,
        grade_plan_id=None,
        run_type='experiment',
        status='running',
        steps=None,
        report_markdown=None,
        error=None,
        created_at=None,
        completed_at=None,
    ):
        self.id = id
        self.user_id = user_id
        self.subject_plan_id = subject_plan_id
        self.grade_plan_id = grade_plan_id
        self.run_type = run_type
        self.status = status  # running / done / failed
        self.steps = _json_load(steps, [])
        self.report_markdown = report_markdown
        self.error = error
        self.created_at = created_at or datetime.now().isoformat()
        self.completed_at = completed_at

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'subject_plan_id': self.subject_plan_id,
            'grade_plan_id': self.grade_plan_id,
            'run_type': self.run_type,
            'status': self.status,
            'steps': self.steps,
            'report_markdown': self.report_markdown,
            'error': self.error,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
        }
