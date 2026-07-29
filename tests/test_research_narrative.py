"""연구 서사 데이터 모델·상태 머신·마이그레이션 검증."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database import Database
from modules.research_store import ResearchStateError
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

# 마이그레이션 이전부터 있던 테이블. 신규 스키마가 이들을 건드리면 안 된다.
LEGACY_TABLES = (
    'users', 'document_history', 'riro_documents',
    'chat_sessions', 'analytics_events', 'student_number_reminders',
)
RESEARCH_TABLES = (
    'student_profiles', 'research_themes', 'research_frameworks',
    'grade_plans', 'subject_plans', 'agent_runs',
    'curriculum_subjects', 'curriculum_standards',
)


class StatusMachineTests(unittest.TestCase):
    def test_draft_can_move_forward(self):
        self.assertTrue(can_transition(STATUS_DRAFT, STATUS_NARROWING))
        self.assertTrue(can_transition(STATUS_DRAFT, STATUS_FIXED))

    def test_fixed_requires_explicit_unlock(self):
        # fixed는 이후 생성 작업의 기준값이므로 곧바로 draft로 되돌릴 수 없다.
        self.assertFalse(can_transition(STATUS_FIXED, STATUS_DRAFT))
        self.assertTrue(can_transition(STATUS_FIXED, STATUS_NARROWING))

    def test_same_status_is_allowed(self):
        self.assertTrue(can_transition(STATUS_FIXED, STATUS_FIXED))


class ModelSerializationTests(unittest.TestCase):
    def test_json_columns_are_decoded(self):
        profile = StudentProfile(
            id=1, user_id='u1',
            interests='["기후", "에너지"]',
            strength_subjects='["통합과학1"]',
            activity_history='[]',
        )
        self.assertEqual(profile.interests, ['기후', '에너지'])
        self.assertEqual(profile.strength_subjects, ['통합과학1'])
        self.assertEqual(profile.status, STATUS_DRAFT)

    def test_malformed_json_falls_back_to_default(self):
        plan = GradePlan(id=1, user_id='u1', grade=1, anchor_project='{not json')
        self.assertEqual(plan.anchor_project, {})

    def test_to_dict_round_trips_every_entity(self):
        entities = [
            StudentProfile(id=1, user_id='u1'),
            Theme(id=1, user_id='u1', title='t'),
            ResearchFramework(id=1, user_id='u1', core_question='q'),
            GradePlan(id=1, user_id='u1', grade=1),
            SubjectPlan(id=1, user_id='u1', subject='통합과학1'),
            AgentRun(id=1, user_id='u1'),
        ]
        for entity in entities:
            payload = entity.to_dict()
            self.assertEqual(payload['user_id'], 'u1')
            # JSON 직렬화가 가능해야 API 응답으로 나갈 수 있다.
            json.dumps(payload, ensure_ascii=False)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.db_path = str(Path(tempfile.mkdtemp()) / 'migrate.db')

    def test_research_tables_are_created(self):
        Database(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        for table in RESEARCH_TABLES:
            self.assertIn(table, names)

    def test_migration_preserves_legacy_data(self):
        Database(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO users (id, email, name, created_at) VALUES (?, ?, ?, ?)",
            ('u-legacy', 'legacy@example.com', '기존사용자', '2026-01-01T00:00:00'),
        )
        conn.commit()
        # 신규 테이블을 지워 마이그레이션 이전 상태를 만든 뒤 다시 초기화한다.
        for table in RESEARCH_TABLES:
            conn.execute(f'DROP TABLE IF EXISTS {table}')
        conn.commit()
        conn.close()

        Database(self.db_path)

        conn = sqlite3.connect(self.db_path)
        try:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in LEGACY_TABLES + RESEARCH_TABLES:
                self.assertIn(table, names)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM users WHERE id='u-legacy'").fetchone()[0], 1)
        finally:
            conn.close()

    def test_init_is_idempotent(self):
        Database(self.db_path)
        Database(self.db_path)
        Database(self.db_path)


class CurriculumQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(str(Path(tempfile.mkdtemp()) / 'curriculum.db'))
        cls.result = cls.db.load_curriculum()

    def test_dataset_loaded(self):
        if self.result.get('skipped'):
            self.skipTest('data/curriculum 산출물이 없습니다.')
        self.assertGreater(self.result['standards'], 3000)

    def test_load_is_idempotent(self):
        if self.result.get('skipped'):
            self.skipTest('data/curriculum 산출물이 없습니다.')
        before = len(self.db.get_curriculum_standards())
        self.db.load_curriculum()
        self.assertEqual(len(self.db.get_curriculum_standards()), before)

    def test_first_grade_lookup_returns_common_subjects(self):
        if self.result.get('skipped'):
            self.skipTest('data/curriculum 산출물이 없습니다.')
        subjects = self.db.get_curriculum_subjects(grade_band='1')
        names = {entry['subject'] for entry in subjects}
        self.assertIn('통합과학1', names)
        self.assertIn('공통수학1', names)
        for entry in subjects:
            self.assertEqual(entry['subject_type'], '공통')

    def test_standards_lookup_by_subject_and_code(self):
        if self.result.get('skipped'):
            self.skipTest('data/curriculum 산출물이 없습니다.')
        subject = next(e for e in self.db.get_curriculum_subjects(grade_band='1')
                       if e['subject'] == '통합과학1')
        standards = self.db.get_curriculum_standards(subject_uid=subject['subject_uid'])
        self.assertEqual(len(standards), subject['standard_count'])

        code = standards[0]['code']
        by_code = self.db.get_curriculum_standards(codes=[code])
        self.assertTrue(any(row['code'] == code for row in by_code))

    def test_search_is_scoped_by_grade_band(self):
        if self.result.get('skipped'):
            self.skipTest('data/curriculum 산출물이 없습니다.')
        hits = self.db.search_curriculum_standards('탐구', grade_band='1', limit=5)
        self.assertTrue(hits)
        for hit in hits:
            self.assertEqual(hit['grade_band'], '1')


class ResearchStoreTests(unittest.TestCase):
    def setUp(self):
        from modules.research_store import ResearchStore
        self.db = Database(str(Path(tempfile.mkdtemp()) / 'store.db'))
        self.store = ResearchStore(self.db)
        self.user_id = self.db.get_or_create_codex_user('a' * 64, email='s@example.com').id

    def _fixed_theme(self):
        themes = self.store.replace_theme_candidates(
            self.user_id, [{'title': 'A'}, {'title': 'B'}])
        selected = self.store.select_theme(self.user_id, themes[0].id)
        self.store.set_status('research_themes', selected.id, self.user_id, STATUS_FIXED)
        return selected

    def test_profile_round_trips_json_fields(self):
        saved = self.store.save_profile(
            self.user_id, interests=['기후'], strength_subjects=['통합과학1'])
        self.assertEqual(saved.interests, ['기후'])
        self.assertEqual(self.store.get_profile(self.user_id).strength_subjects, ['통합과학1'])

    def test_selecting_theme_moves_it_to_narrowing_and_is_exclusive(self):
        themes = self.store.replace_theme_candidates(
            self.user_id, [{'title': 'A'}, {'title': 'B'}])
        self.store.select_theme(self.user_id, themes[0].id)
        self.store.select_theme(self.user_id, themes[1].id)
        selected = [t for t in self.store.list_themes(self.user_id) if t.is_selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].id, themes[1].id)
        self.assertEqual(selected[0].status, STATUS_NARROWING)

    def test_fixed_theme_blocks_new_candidates(self):
        self._fixed_theme()
        with self.assertRaises(ResearchStateError):
            self.store.replace_theme_candidates(self.user_id, [{'title': 'X'}])

    def test_fixed_cannot_go_straight_back_to_draft(self):
        theme = self._fixed_theme()
        with self.assertRaises(ResearchStateError):
            self.store.set_status('research_themes', theme.id, self.user_id, STATUS_DRAFT)
        # unlock은 narrowing 경유만 허용한다.
        self.store.set_status('research_themes', theme.id, self.user_id, STATUS_NARROWING)
        self.assertEqual(self.store.selected_theme(self.user_id).status, STATUS_NARROWING)

    def test_fixed_grade_plan_rejects_content_edits(self):
        plan = self.store.upsert_grade_plan(self.user_id, None, 1, goal='원본')
        self.store.set_status('grade_plans', plan.id, self.user_id, STATUS_FIXED)
        with self.assertRaises(ResearchStateError):
            self.store.upsert_grade_plan(self.user_id, None, 1, goal='변경')

    def test_grade_plan_is_unique_per_grade(self):
        self.store.upsert_grade_plan(self.user_id, None, 1, goal='첫 저장')
        self.store.upsert_grade_plan(self.user_id, None, 1, goal='덮어쓰기')
        plans = self.store.list_grade_plans(self.user_id)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].goal, '덮어쓰기')

    def test_fixed_context_only_contains_fixed_items(self):
        self.store.save_profile(self.user_id, interests=['기후'])
        plan = self.store.upsert_grade_plan(self.user_id, None, 1, goal='목표')
        context = self.store.fixed_context(self.user_id)
        self.assertIsNone(context['profile'])
        self.assertEqual(context['grade_plans'], [])

        self.store.set_status('grade_plans', plan.id, self.user_id, STATUS_FIXED)
        context = self.store.fixed_context(self.user_id)
        self.assertEqual(len(context['grade_plans']), 1)

    def test_other_users_rows_are_not_reachable(self):
        plan = self.store.upsert_grade_plan(self.user_id, None, 1, goal='내 계획')
        other = self.db.get_or_create_codex_user('b' * 64, email='other@example.com').id
        with self.assertRaises(ResearchStateError):
            self.store.set_status('grade_plans', plan.id, other, STATUS_FIXED)
        self.assertEqual(self.store.list_grade_plans(other), [])

    def test_agent_run_lifecycle(self):
        run = self.store.create_agent_run(self.user_id, run_type='experiment')
        self.assertEqual(run.status, 'running')
        self.store.append_agent_step(self.user_id, run.id, {'label': '배경 조사', 'state': 'done'})
        self.store.append_agent_step(self.user_id, run.id, {'label': '설계', 'state': 'done'})
        done = self.store.complete_agent_run(self.user_id, run.id, report_markdown='# 보고서')
        self.assertEqual(done.status, 'done')
        self.assertEqual(len(done.steps), 2)
        self.assertTrue(done.report_markdown.startswith('#'))

    def test_failed_agent_run_records_error(self):
        run = self.store.create_agent_run(self.user_id)
        failed = self.store.complete_agent_run(self.user_id, run.id, error='timeout')
        self.assertEqual(failed.status, 'failed')
        self.assertEqual(failed.error, 'timeout')


class PipelineParsingTests(unittest.TestCase):
    def test_parses_plain_and_fenced_json(self):
        from modules.research_pipeline import _parse
        self.assertEqual(_parse('{"a": 1}'), {'a': 1})
        self.assertEqual(_parse('```json\n{"a": 2}\n```'), {'a': 2})

    def test_rejects_unparseable_output(self):
        from modules.research_pipeline import PipelineError, _parse
        with self.assertRaises(PipelineError):
            _parse('그냥 평문')

    def test_fixed_block_marks_items_as_immutable(self):
        from modules.research_pipeline import _fixed_block
        block = _fixed_block({
            'theme': {'title': '도시 열섬', 'rationale': '근거'},
            'framework': {'core_question': 'Q?', 'sub_areas': [{'name': '관측'}],
                          'final_destination': '설계안'},
            'grade_plans': [{'grade': 1, 'goal': '기초', 'anchor_project': {'title': '관측'}}],
            'subject_plans': [],
            'profile': None,
        })
        self.assertIn('[FIXED]', block)
        self.assertIn('도시 열섬', block)
        self.assertIn('바꿀 수 없는 기준값', block)

    def test_empty_fixed_context_is_stated_explicitly(self):
        from modules.research_pipeline import _fixed_block
        self.assertIn('아직 확정된 항목이 없다', _fixed_block({}))

    def test_standards_block_lists_only_supplied_codes(self):
        from modules.research_pipeline import _standards_block
        block = _standards_block([
            {'code': '[10통과1-01-01]', 'subject': '통합과학1',
             'area_name': '과학의 기초', 'statement': '문구'},
        ])
        self.assertIn('[10통과1-01-01]', block)
        self.assertIn('통합과학1', block)
        self.assertEqual(_standards_block([]), '(제공된 성취기준 없음)')


class CodeNormalizationTests(unittest.TestCase):
    def test_bracketed_and_bare_codes_match(self):
        from modules.research_router import _normalize_code
        # 모델이 대괄호를 떼고 돌려줘도 DB 표기와 대조되어야 한다.
        self.assertEqual(_normalize_code('10통과1-01-01'), _normalize_code('[10통과1-01-01]'))
        self.assertEqual(_normalize_code(' [10통과1-01-01] '), '10통과1-01-01')

    def test_distinct_codes_do_not_collide(self):
        from modules.research_router import _normalize_code
        self.assertNotEqual(_normalize_code('[10통과1-01-01]'), _normalize_code('[10통과1-01-02]'))

    def test_handles_none(self):
        from modules.research_router import _normalize_code
        self.assertEqual(_normalize_code(None), '')


if __name__ == '__main__':
    unittest.main()
