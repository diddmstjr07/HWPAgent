"""연구 서사 엔티티의 저장·조회와 상태 전이를 담당합니다.

상태 규칙은 models.py의 STATUS_* / can_transition에 정의되어 있고,
여기서는 그 규칙을 DB 쓰기 경로에서 강제합니다.
fixed 항목은 이후 생성 작업의 기준값이므로 명시적 unlock 없이는 되돌릴 수 없습니다.
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from models import (
    STATUS_DRAFT,
    STATUS_FIXED,
    STATUS_NARROWING,
    AgentRun,
    GradePlan,
    ResearchFramework,
    StudentProfile,
    SubjectPlan,
    Theme,
    can_transition,
)


class ResearchStateError(Exception):
    """허용되지 않은 상태 전이나 접근 위반."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now().isoformat()


def _dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class ResearchStore:
    def __init__(self, database):
        self.db = database

    # ---------- 공통 ----------

    def _fetch_row(self, table: str, row_id: int, user_id: str):
        conn = self.db.get_connection()
        try:
            return conn.execute(
                f'SELECT * FROM {table} WHERE id = ? AND user_id = ?', (row_id, user_id)
            ).fetchone()
        finally:
            conn.close()

    def set_status(self, table: str, row_id: int, user_id: str, target: str):
        """상태 전이를 검증하고 적용합니다."""
        row = self._fetch_row(table, row_id, user_id)
        if not row:
            raise ResearchStateError('항목을 찾을 수 없습니다.', 404)
        current = row['status']
        if not can_transition(current, target):
            if current == STATUS_FIXED:
                raise ResearchStateError(
                    '확정된 항목입니다. 수정하려면 먼저 확정을 해제(unlock)해 주세요.', 409)
            raise ResearchStateError(f'{current} 에서 {target} 으로 바꿀 수 없습니다.', 409)

        conn = self.db.get_connection()
        try:
            conn.execute(
                f'UPDATE {table} SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?',
                (target, _now(), row_id, user_id)
            )
            conn.commit()
        finally:
            conn.close()
        return target

    def _assert_mutable(self, table: str, row_id: int, user_id: str) -> None:
        """fixed 항목의 내용 수정을 막습니다."""
        row = self._fetch_row(table, row_id, user_id)
        if not row:
            raise ResearchStateError('항목을 찾을 수 없습니다.', 404)
        if row['status'] == STATUS_FIXED:
            raise ResearchStateError(
                '확정된 항목입니다. 수정하려면 먼저 확정을 해제(unlock)해 주세요.', 409)

    # ---------- Phase 1: StudentProfile ----------

    def get_profile(self, user_id: str) -> Optional[StudentProfile]:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                'SELECT * FROM student_profiles WHERE user_id = ?', (user_id,)
            ).fetchone()
        finally:
            conn.close()
        return StudentProfile(**dict(row)) if row else None

    def save_profile(self, user_id: str, **fields) -> StudentProfile:
        existing = self.get_profile(user_id)
        if existing and existing.status == STATUS_FIXED and fields.get('status') != STATUS_NARROWING:
            raise ResearchStateError(
                '확정된 프로파일입니다. 수정하려면 먼저 확정을 해제(unlock)해 주세요.', 409)

        payload = {
            'interests': _dump(fields.get('interests')),
            'problem_statement': fields.get('problem_statement'),
            'aspired_track': fields.get('aspired_track'),
            'strength_subjects': _dump(fields.get('strength_subjects')),
            'activity_history': _dump(fields.get('activity_history')),
            'interview_state': _dump(fields.get('interview_state')),
            'extra': _dump(fields.get('extra')),
            'status': fields.get('status') or (existing.status if existing else STATUS_DRAFT),
        }

        conn = self.db.get_connection()
        try:
            if existing:
                sets = ', '.join(f'{key} = ?' for key in payload)
                conn.execute(
                    f'UPDATE student_profiles SET {sets}, updated_at = ? WHERE user_id = ?',
                    (*payload.values(), _now(), user_id)
                )
            else:
                columns = ', '.join(payload)
                marks = ', '.join('?' * len(payload))
                conn.execute(
                    f'INSERT INTO student_profiles (user_id, {columns}, created_at, updated_at) '
                    f'VALUES (?, {marks}, ?, ?)',
                    (user_id, *payload.values(), _now(), _now())
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_profile(user_id)

    # ---------- Phase 2: Theme ----------

    def list_themes(self, user_id: str) -> List[Theme]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                'SELECT * FROM research_themes WHERE user_id = ? ORDER BY id', (user_id,)
            ).fetchall()
        finally:
            conn.close()
        return [Theme(**dict(row)) for row in rows]

    def replace_theme_candidates(self, user_id: str, candidates: List[Dict[str, Any]]) -> List[Theme]:
        """Phase 2 후보를 새로 제안합니다. 확정된 테마가 있으면 거부합니다."""
        if any(theme.status == STATUS_FIXED for theme in self.list_themes(user_id)):
            raise ResearchStateError(
                '이미 확정된 테마가 있습니다. 새 후보를 받으려면 먼저 확정을 해제해 주세요.', 409)

        conn = self.db.get_connection()
        try:
            conn.execute('DELETE FROM research_themes WHERE user_id = ?', (user_id,))
            for candidate in candidates:
                conn.execute('''
                    INSERT INTO research_themes
                        (user_id, profile_id, title, rationale, expansion, differentiation,
                         is_selected, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                ''', (
                    user_id, candidate.get('profile_id'), candidate.get('title') or '(제목 없음)',
                    candidate.get('rationale'), candidate.get('expansion'),
                    candidate.get('differentiation'), STATUS_DRAFT, _now(), _now(),
                ))
            conn.commit()
        finally:
            conn.close()
        return self.list_themes(user_id)

    def select_theme(self, user_id: str, theme_id: int) -> Theme:
        """후보 중 하나를 선택합니다(선택 != 확정)."""
        if not self._fetch_row('research_themes', theme_id, user_id):
            raise ResearchStateError('테마를 찾을 수 없습니다.', 404)
        conn = self.db.get_connection()
        try:
            conn.execute(
                'UPDATE research_themes SET is_selected = 0, updated_at = ? WHERE user_id = ?',
                (_now(), user_id))
            conn.execute(
                'UPDATE research_themes SET is_selected = 1, status = ?, updated_at = ? '
                'WHERE id = ? AND user_id = ?',
                (STATUS_NARROWING, _now(), theme_id, user_id))
            conn.commit()
        finally:
            conn.close()
        return next(theme for theme in self.list_themes(user_id) if theme.id == theme_id)

    def selected_theme(self, user_id: str) -> Optional[Theme]:
        return next((theme for theme in self.list_themes(user_id) if theme.is_selected), None)

    # ---------- Phase 3: ResearchFramework ----------

    def get_framework(self, user_id: str) -> Optional[ResearchFramework]:
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                'SELECT * FROM research_frameworks WHERE user_id = ? ORDER BY id DESC LIMIT 1',
                (user_id,)
            ).fetchone()
        finally:
            conn.close()
        return ResearchFramework(**dict(row)) if row else None

    def save_framework(self, user_id: str, **fields) -> ResearchFramework:
        existing = self.get_framework(user_id)
        if existing:
            self._assert_mutable('research_frameworks', existing.id, user_id)

        values = (
            fields.get('theme_id'),
            fields.get('core_question'),
            _dump(fields.get('sub_areas')),
            fields.get('final_destination'),
            fields.get('status') or (existing.status if existing else STATUS_DRAFT),
        )
        conn = self.db.get_connection()
        try:
            if existing:
                conn.execute('''
                    UPDATE research_frameworks
                       SET theme_id = ?, core_question = ?, sub_areas = ?,
                           final_destination = ?, status = ?, updated_at = ?
                     WHERE id = ? AND user_id = ?
                ''', (*values, _now(), existing.id, user_id))
            else:
                conn.execute('''
                    INSERT INTO research_frameworks
                        (user_id, theme_id, core_question, sub_areas, final_destination,
                         status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, *values, _now(), _now()))
            conn.commit()
        finally:
            conn.close()
        return self.get_framework(user_id)

    # ---------- Phase 3 분해: GradePlan ----------

    def list_grade_plans(self, user_id: str) -> List[GradePlan]:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                'SELECT * FROM grade_plans WHERE user_id = ? ORDER BY grade', (user_id,)
            ).fetchall()
        finally:
            conn.close()
        return [GradePlan(**dict(row)) for row in rows]

    def upsert_grade_plan(self, user_id: str, framework_id: Optional[int], grade: int,
                          **fields) -> GradePlan:
        existing = next((plan for plan in self.list_grade_plans(user_id)
                         if plan.grade == int(grade)), None)
        if existing:
            self._assert_mutable('grade_plans', existing.id, user_id)

        conn = self.db.get_connection()
        try:
            if existing:
                conn.execute('''
                    UPDATE grade_plans
                       SET goal = ?, anchor_project = ?, curriculum_alignment = ?,
                           status = ?, updated_at = ?
                     WHERE id = ? AND user_id = ?
                ''', (
                    fields.get('goal'), _dump(fields.get('anchor_project')),
                    _dump(fields.get('curriculum_alignment')),
                    fields.get('status') or existing.status, _now(), existing.id, user_id,
                ))
            else:
                conn.execute('''
                    INSERT INTO grade_plans
                        (user_id, framework_id, grade, goal, anchor_project,
                         curriculum_alignment, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    user_id, framework_id, int(grade), fields.get('goal'),
                    _dump(fields.get('anchor_project')), _dump(fields.get('curriculum_alignment')),
                    fields.get('status') or STATUS_DRAFT, _now(), _now(),
                ))
            conn.commit()
        finally:
            conn.close()
        return next(plan for plan in self.list_grade_plans(user_id) if plan.grade == int(grade))

    # ---------- Phase 5: SubjectPlan ----------

    def list_subject_plans(self, user_id: str, grade_plan_id: Optional[int] = None) -> List[SubjectPlan]:
        query = 'SELECT * FROM subject_plans WHERE user_id = ?'
        params: List[Any] = [user_id]
        if grade_plan_id is not None:
            query += ' AND grade_plan_id = ?'
            params.append(grade_plan_id)
        conn = self.db.get_connection()
        try:
            rows = conn.execute(query + ' ORDER BY subject', params).fetchall()
        finally:
            conn.close()
        return [SubjectPlan(**dict(row)) for row in rows]

    def upsert_subject_plan(self, user_id: str, grade_plan_id: int, subject: str,
                            **fields) -> SubjectPlan:
        existing = next(
            (plan for plan in self.list_subject_plans(user_id, grade_plan_id)
             if plan.subject == subject), None)
        if existing:
            self._assert_mutable('subject_plans', existing.id, user_id)

        columns = (
            fields.get('subject_uid'), fields.get('approach'), fields.get('approach_rationale'),
            fields.get('area_name'), _dump(fields.get('standard_codes')),
            fields.get('motivation'), _dump(fields.get('activity_design')),
            fields.get('status') or (existing.status if existing else STATUS_DRAFT),
        )
        conn = self.db.get_connection()
        try:
            if existing:
                conn.execute('''
                    UPDATE subject_plans
                       SET subject_uid = ?, approach = ?, approach_rationale = ?, area_name = ?,
                           standard_codes = ?, motivation = ?, activity_design = ?,
                           status = ?, updated_at = ?
                     WHERE id = ? AND user_id = ?
                ''', (*columns, _now(), existing.id, user_id))
            else:
                conn.execute('''
                    INSERT INTO subject_plans
                        (user_id, grade_plan_id, subject, subject_uid, approach,
                         approach_rationale, area_name, standard_codes, motivation,
                         activity_design, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, grade_plan_id, subject, *columns, _now(), _now()))
            conn.commit()
        finally:
            conn.close()
        return next(plan for plan in self.list_subject_plans(user_id, grade_plan_id)
                    if plan.subject == subject)

    def get_subject_plan(self, user_id: str, plan_id: int) -> Optional[SubjectPlan]:
        row = self._fetch_row('subject_plans', plan_id, user_id)
        return SubjectPlan(**dict(row)) if row else None

    def set_experiment(self, user_id: str, plan_id: int, **fields) -> SubjectPlan:
        """실험 진행 상태를 기록합니다.

        _assert_mutable을 거치지 않습니다. 실험은 세특을 확정한 뒤에 하는 일이라,
        확정된 플랜이라고 해서 실험 기록까지 막으면 아무것도 진행할 수 없습니다.
        설계 내용(탐구 질문 등)은 여기서 건드리지 않으므로 확정의 의미는 유지됩니다.
        """
        allowed = ('experiment_chat_id', 'experiment_status', 'report_file')
        updates = {key: fields[key] for key in allowed if key in fields}
        if not updates:
            return self.get_subject_plan(user_id, plan_id)

        assignments = ', '.join(f'{key} = ?' for key in updates)
        conn = self.db.get_connection()
        try:
            conn.execute(
                f'UPDATE subject_plans SET {assignments}, updated_at = ? '
                'WHERE id = ? AND user_id = ?',
                (*updates.values(), _now(), plan_id, user_id))
            conn.commit()
        finally:
            conn.close()
        return self.get_subject_plan(user_id, plan_id)

    # ---------- AgentRun ----------

    def create_agent_run(self, user_id: str, subject_plan_id: Optional[int] = None,
                         grade_plan_id: Optional[int] = None,
                         run_type: str = 'experiment') -> AgentRun:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO agent_runs
                    (user_id, subject_plan_id, grade_plan_id, run_type, status, steps, created_at)
                VALUES (?, ?, ?, ?, 'running', '[]', ?)
            ''', (user_id, subject_plan_id, grade_plan_id, run_type, _now()))
            run_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        return self.get_agent_run(user_id, run_id)

    def get_agent_run(self, user_id: str, run_id: int) -> Optional[AgentRun]:
        row = self._fetch_row('agent_runs', run_id, user_id)
        return AgentRun(**dict(row)) if row else None

    def list_agent_runs(self, user_id: str, subject_plan_id: Optional[int] = None) -> List[AgentRun]:
        query = 'SELECT * FROM agent_runs WHERE user_id = ?'
        params: List[Any] = [user_id]
        if subject_plan_id is not None:
            query += ' AND subject_plan_id = ?'
            params.append(subject_plan_id)
        conn = self.db.get_connection()
        try:
            rows = conn.execute(query + ' ORDER BY created_at DESC LIMIT 50', params).fetchall()
        finally:
            conn.close()
        return [AgentRun(**dict(row)) for row in rows]

    def append_agent_step(self, user_id: str, run_id: int, step: Dict[str, Any]) -> None:
        run = self.get_agent_run(user_id, run_id)
        if not run:
            raise ResearchStateError('실행 기록을 찾을 수 없습니다.', 404)
        steps = run.steps + [step]
        conn = self.db.get_connection()
        try:
            conn.execute('UPDATE agent_runs SET steps = ? WHERE id = ? AND user_id = ?',
                         (_dump(steps), run_id, user_id))
            conn.commit()
        finally:
            conn.close()

    def complete_agent_run(self, user_id: str, run_id: int, report_markdown: Optional[str] = None,
                           error: Optional[str] = None) -> AgentRun:
        conn = self.db.get_connection()
        try:
            conn.execute('''
                UPDATE agent_runs
                   SET status = ?, report_markdown = ?, error = ?, completed_at = ?
                 WHERE id = ? AND user_id = ?
            ''', ('failed' if error else 'done', report_markdown, error, _now(), run_id, user_id))
            conn.commit()
        finally:
            conn.close()
        return self.get_agent_run(user_id, run_id)

    # ---------- Fixed 컨텍스트 ----------

    def fixed_context(self, user_id: str) -> Dict[str, Any]:
        """확정(fixed)된 항목만 모읍니다. 이후 모든 생성 작업에 주입되는 기준값입니다."""
        profile = self.get_profile(user_id)
        theme = self.selected_theme(user_id)
        framework = self.get_framework(user_id)
        return {
            'profile': profile.to_dict() if profile and profile.status == STATUS_FIXED else None,
            'theme': theme.to_dict() if theme and theme.status == STATUS_FIXED else None,
            'framework': (framework.to_dict()
                          if framework and framework.status == STATUS_FIXED else None),
            'grade_plans': [plan.to_dict() for plan in self.list_grade_plans(user_id)
                            if plan.status == STATUS_FIXED],
            'subject_plans': [plan.to_dict() for plan in self.list_subject_plans(user_id)
                              if plan.status == STATUS_FIXED],
        }
