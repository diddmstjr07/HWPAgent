"""사이드바 HISTORY의 폴더 구조 — 설계/실험 대화방과 이름 규칙 검증.

실험은 전용 페이지가 아니라 메인 채팅방에서 진행되므로, 대화가 어느 폴더의
어떤 이름으로 남는지가 곧 학생이 대화를 구분하는 유일한 수단이다.
"""
import tempfile
import unittest
from pathlib import Path

from database import Database
from modules import research_router
from modules.research_store import ResearchStore


class ChatFolderTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(str(Path(tempfile.mkdtemp()) / 'folders.db'))
        self.store = ResearchStore(self.db)
        # 라우터 헬퍼는 모듈 전역 db/store를 쓴다. 테스트 DB로 갈아 끼운다.
        self._saved = (research_router.db, research_router.store)
        research_router.db = self.db
        research_router.store = self.store
        self.user_id = 'user_folder'

    def tearDown(self):
        research_router.db, research_router.store = self._saved

    # ---------- 설계 폴더 ----------

    def test_design_room_is_created_once_and_reused(self):
        first, is_first = research_router._design_session(self.user_id)
        again, _ = research_router._design_session(self.user_id)
        self.assertEqual(first, again)
        self.assertTrue(is_first)
        rooms = self.db.get_chat_sessions(self.user_id, folder=research_router.FOLDER_DESIGN)
        self.assertEqual(len(rooms), 1)

    def test_orphan_messages_belong_only_to_the_first_room(self):
        """대화방이 생기기 전에 쌓인 기록은 첫 방에서만 보인다."""
        self.db.add_research_message(self.user_id, 'user', '옛날 기록')
        first, first_flag = research_router._design_session(self.user_id)
        second = self.db.create_chat_session(
            self.user_id, '새 연구 설계', [], folder=research_router.FOLDER_DESIGN)
        _, second_flag = research_router._design_session(self.user_id, second.id)

        self.assertTrue(first_flag)
        self.assertFalse(second_flag)
        self.assertEqual(
            len(self.db.get_research_messages(
                self.user_id, session_id=first, include_orphans=first_flag)), 1)
        self.assertEqual(
            len(self.db.get_research_messages(
                self.user_id, session_id=second.id, include_orphans=second_flag)), 0)

    def test_design_title_summarises_how_far_the_talk_got(self):
        self.assertEqual(research_router._design_title(self.user_id),
                         research_router._DESIGN_DEFAULT_TITLE)

        themes = self.store.replace_theme_candidates(
            self.user_id, [{'title': '도시 열섬'}, {'title': '빗물 순환'}])
        self.assertEqual(research_router._design_title(self.user_id), '테마 고르기')

        self.store.select_theme(self.user_id, themes[0].id)
        plan = self.store.upsert_grade_plan(self.user_id, None, 1, goal='목표')
        self.assertEqual(research_router._design_title(self.user_id), '도시 열섬 · 3년 계획')

        self.store.upsert_subject_plan(self.user_id, plan.id, '공통국어')
        self.assertEqual(research_router._design_title(self.user_id), '도시 열섬 · 1학년 세특')

    # ---------- 실험 폴더 ----------

    def test_experiment_room_is_named_subject_dash_keyword(self):
        plan = self.store.upsert_grade_plan(self.user_id, None, 2, goal='목표')
        subject = self.store.upsert_subject_plan(
            self.user_id, plan.id, '공통국어',
            activity_design={'question': '사용성 실험 전달이 설명문 이해도를 바꾸는가?'})

        session_id, messages = research_router._experiment_room(self.user_id, subject)
        room = self.db.get_chat_session(session_id, self.user_id)

        self.assertEqual(messages, [])
        self.assertEqual(room.folder, research_router.FOLDER_EXPERIMENT)
        self.assertEqual(room.plan_id, subject.id)
        self.assertTrue(room.title.startswith('공통국어 - '))
        self.assertLessEqual(len(room.title.split(' - ')[1]), 16)

    def test_experiment_room_is_not_created_twice(self):
        plan = self.store.upsert_grade_plan(self.user_id, None, 1, goal='목표')
        subject = self.store.upsert_subject_plan(self.user_id, plan.id, '통합과학')

        first, _ = research_router._experiment_room(self.user_id, subject)
        reloaded = self.store.get_subject_plan(self.user_id, subject.id)
        again, _ = research_router._experiment_room(self.user_id, reloaded)

        self.assertEqual(first, again)
        self.assertEqual(
            len(self.db.get_chat_sessions(
                self.user_id, folder=research_router.FOLDER_EXPERIMENT)), 1)

    def test_keyword_falls_back_when_there_is_no_question(self):
        plan = self.store.upsert_grade_plan(self.user_id, None, 1, goal='목표')
        subject = self.store.upsert_subject_plan(
            self.user_id, plan.id, '통합사회', area_name='지역과 공간')
        self.assertEqual(research_router._experiment_title(subject), '통합사회 - 지역과 공간')

    # ---------- 학년 자리 ----------

    def test_grade_anchor_points_at_the_grade_section(self):
        self.assertEqual(research_router._grade_anchor(2), '/research#grade-2')
        self.assertEqual(research_router._grade_anchor(None), '/research')


if __name__ == '__main__':
    unittest.main()
