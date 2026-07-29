"""실험 한 턴 — 검색·이미지·진행 상태 알림 검증.

Codex는 부르지 않는다. _run을 갈아 끼워 '모델이 이렇게 답했을 때'만 확인한다.
"""
import copy
import unittest
from unittest import mock

from modules import research_pipeline as rp

PLAN = {'subject': '공통국어', 'approach': 'linked', 'area_name': '매체',
        'activity_design': {'question': '버튼 문구가 오입력을 바꾸는가?'}}


def _turn(**overrides):
    base = {'reply': '알겠어.', 'phase': 'background', 'is_complete': False,
            'search_query': '', 'image_query': '', 'images': []}
    base.update(overrides)
    return base


class ExperimentTurnTests(unittest.TestCase):
    def _call(self, runs, **env):
        """_run이 순서대로 runs를 돌려주게 하고 한 턴을 돌린다."""
        stages = []
        with mock.patch.object(rp, '_run', side_effect=list(runs)):
            result = rp.experiment_turn(
                'inst', PLAN, [], {}, [], '찾아봐 줘',
                on_stage=lambda name, label='': stages.append((name, label)))
        return result, stages

    def test_no_search_request_means_one_model_call(self):
        with mock.patch.object(rp.web_search, 'available', return_value=True):
            result, stages = self._call([_turn()])
        self.assertEqual(result['reply'], '알겠어.')
        self.assertEqual(result['images'], [])
        self.assertEqual([name for name, _ in stages], ['thinking', 'thinking'])

    def test_search_request_runs_search_then_answers_again(self):
        found = {'query': '버튼 문구', 'provider': 'brave',
                 'results': [{'title': 'T', 'url': 'https://e.org/a', 'snippet': 's'}],
                 'sources': [{'title': 'T', 'url': 'https://e.org/a'}]}
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'search', return_value=found) as search:
            result, stages = self._call([
                _turn(search_query='버튼 문구'),
                _turn(reply='찾아보니 이렇대.'),
            ])

        search.assert_called_once_with('버튼 문구')
        self.assertIn('찾아보니 이렇대.', result['reply'])
        self.assertIn('https://e.org/a', result['reply'])   # 출처가 대화에 남는다
        self.assertEqual(result['sources'], found['sources'])
        # 찾는 중 → 다시 생각 중 순서로 알려야 화면이 그렇게 그린다.
        self.assertEqual([name for name, _ in stages],
                         ['thinking', 'searching', 'thinking', 'thinking'])
        self.assertIn(('searching', '버튼 문구'), stages)

    def test_search_failure_keeps_the_first_answer(self):
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'search', return_value=None):
            result, _ = self._call([_turn(reply='이렇게 찾아봐.', search_query='무엇')])
        self.assertEqual(result['reply'], '이렇게 찾아봐.')
        self.assertEqual(result['sources'], [])

    def test_search_is_skipped_when_no_provider(self):
        with mock.patch.object(rp.web_search, 'available', return_value=False), \
             mock.patch.object(rp.web_search, 'search') as search:
            result, stages = self._call([_turn(search_query='무엇', image_query='사진')])
        search.assert_not_called()
        self.assertNotIn('searching', [name for name, _ in stages])
        self.assertEqual(result['images'], [])

    def test_codex_supplied_images_are_verified_before_showing(self):
        """모델이 그럴듯한 주소를 지어낼 수 있다. 열리는 것만 대화에 남아야 한다."""
        proposed = [{'title': '키오스크', 'image_url': 'https://e.org/real.jpg',
                     'page_url': 'https://e.org/p'},
                    {'title': '가짜', 'image_url': 'https://e.org/made-up.jpg',
                     'page_url': 'https://e.org/q'}]
        verified = [proposed[0]]
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'verify_images',
                               return_value=verified) as verify, \
             mock.patch.object(rp.web_search, 'search_images') as search_images:
            result, stages = self._call([_turn(images=proposed)])

        verify.assert_called_once_with(proposed)
        search_images.assert_not_called()      # 직접 찾아왔으면 또 찾지 않는다
        self.assertEqual(result['images'], verified)
        self.assertIn('searching_images', [name for name, _ in stages])

    def test_image_query_is_the_fallback_when_codex_found_none(self):
        images = [{'title': 'A', 'image_url': 'https://e.org/a.jpg', 'page_url': 'https://e.org/a'}]
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'verify_images', return_value=[]), \
             mock.patch.object(rp.web_search, 'search_images', return_value=images) as search:
            result, _ = self._call([_turn(images=[{'image_url': 'http://bad'}],
                                          image_query='키오스크 화면')])
        search.assert_called_once_with('키오스크 화면')
        self.assertEqual(result['images'], images)

    def test_images_are_attached_and_announced(self):
        images = [{'title': 'A', 'image_url': 'https://e.org/a.jpg', 'page_url': 'https://e.org/a'}]
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'search_images', return_value=images):
            result, stages = self._call([_turn(image_query='키오스크 화면')])
        self.assertEqual(result['images'], images)
        self.assertIn(('searching_images', '키오스크 화면'), stages)
        # 이미지를 찾은 뒤에도 마지막은 '생각 중'으로 돌아온다.
        self.assertEqual(stages[-1][0], 'thinking')

    def test_codex_own_links_count_as_sources(self):
        """Codex가 스스로 검색했으면 답변에 링크가 박혀 온다. 그때는 우리가 또 찾지 않는다."""
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'search') as search:
            result, _ = self._call([_turn(reply='참고: https://e.org/x 를 봐.')])
        search.assert_not_called()
        self.assertEqual(result['sources'], [{'title': 'https://e.org/x', 'url': 'https://e.org/x'}])

    def test_phase_is_not_advanced_by_the_second_call(self):
        """자료를 붙였다고 국면이 넘어가면 안 된다. 진도는 학생이 낸다."""
        found = {'query': 'q', 'provider': 'brave',
                 'results': [{'title': 'T', 'url': 'https://e.org/a', 'snippet': 's'}],
                 'sources': [{'title': 'T', 'url': 'https://e.org/a'}]}
        with mock.patch.object(rp.web_search, 'available', return_value=True), \
             mock.patch.object(rp.web_search, 'search', return_value=found):
            result, _ = self._call([
                _turn(phase='background', search_query='q'),
                _turn(phase='conclude', is_complete=True),
            ])
        self.assertEqual(result['phase'], 'background')
        self.assertFalse(result['is_complete'])


class DemoTests(unittest.TestCase):
    """직접 눌러볼 화면 — 쓸 수 있는 것만 남긴다."""

    def test_plain_fragment_is_kept(self):
        demo = rp._clean_demo({'title': '버튼 비교', 'html': '<button>결제</button>'})
        self.assertEqual(demo['title'], '버튼 비교')
        self.assertIn('<button>', demo['html'])

    def test_empty_html_is_dropped(self):
        self.assertEqual(rp._clean_demo({'title': '있음', 'html': '  '}),
                         {'title': '', 'html': ''})
        self.assertEqual(rp._clean_demo(None), {'title': '', 'html': ''})

    def test_outside_resources_are_refused(self):
        """글꼴 말고 바깥으로 요청이 나가는 화면은 띄우지 않는다."""
        for html in ('<img src="https://x.test/a.png">',
                     "<script src='//cdn.test/x.js'></script>",
                     '<link href="http://x.test/a.css">',
                     '<style>@import "https://evil.test/a.css";</style>',
                     '<style>@font-face{src:url(https://evil.test/a.woff2)}</style>',
                     # 글꼴 호스트처럼 보이지만 남의 도메인이다.
                     '<link href="https://fonts.googleapis.com.evil.test/x.css">'):
            self.assertEqual(rp._clean_demo({'title': 't', 'html': html})['html'], '', html)

    def test_web_fonts_are_allowed(self):
        """글꼴은 허용한다. 스타일시트로는 스크립트가 들어올 수 없다."""
        for html in ('<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">',
                     "<style>@import url('https://fonts.googleapis.com/css2?family=Noto');</style>",
                     '<style>@font-face{src:url("https://fonts.gstatic.com/s/a.woff2")}</style>',
                     '<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard.css">'):
            self.assertNotEqual(rp._clean_demo({'title': 't', 'html': html})['html'], '', html)

    def test_font_host_still_cannot_deliver_a_script(self):
        """허용 호스트라도 src= 로는 못 들어온다. 그 통로는 스크립트가 지나는 곳이다."""
        html = '<script src="https://cdn.jsdelivr.net/npm/x.js"></script>'
        self.assertEqual(rp._clean_demo({'title': 't', 'html': html})['html'], '')

    def test_oversized_fragment_is_refused(self):
        huge = {'title': 't', 'html': '<p>가</p>' * 5000}
        self.assertEqual(rp._clean_demo(huge)['html'], '')

    def test_turn_carries_the_cleaned_demo(self):
        demo = {'title': '결제 버튼', 'html': '<button>결제하기</button>'}
        with mock.patch.object(rp.web_search, 'available', return_value=False), \
             mock.patch.object(rp, '_run', return_value=_turn(demo=demo)):
            result = rp.experiment_turn('inst', PLAN, [], {}, [], '만들어 줘')
        self.assertEqual(result['demo']['html'], '<button>결제하기</button>')


class StagedReportTests(unittest.TestCase):
    """단계형 보고서 생성 — 계획 → 장별 집필 → 그림 순서와 진행판 검증."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from database import Database
        from modules import research_router as rr
        from modules.research_store import ResearchStore

        self.rr = rr
        self.db = Database(str(Path(tempfile.mkdtemp()) / 'staged.db'))
        self._saved = (rr.db, rr.store)
        rr.db = self.db
        rr.store = ResearchStore(self.db)
        self.user_id = 'user_staged'
        grade = rr.store.upsert_grade_plan(self.user_id, None, 1, goal='목표')
        self.plan = rr.store.upsert_subject_plan(self.user_id, grade.id, '공통국어')

    def tearDown(self):
        self.rr.db, self.rr.store = self._saved

    OUTLINE = {
        'title': '버튼 문구 보고서',
        'sections': [
            {'heading': 'I. 주제', 'brief': '배경', 'figure_nos': []},
            {'heading': 'III. 결과', 'brief': '수치', 'figure_nos': [1]},
        ],
        'figures': [{'no': 1, 'kind': 'image', 'caption': '사례 화면',
                     'python_code': '', 'image_url': 'https://e.org/a.png'}],
    }

    def test_sections_are_written_one_by_one_and_steps_advance(self):
        progress = {}
        with mock.patch.object(self.rr.research_pipeline, 'report_plan',
                               return_value=copy.deepcopy(self.OUTLINE)), \
             mock.patch.object(self.rr, '_ask_figures', return_value=''), \
             mock.patch.object(self.rr.research_pipeline, 'find_report_images',
                               return_value={1: {'image_url': 'https://found.test/a.jpg',
                                                 'page_url': 'https://found.test'}}) as hunt, \
             mock.patch.object(self.rr.research_pipeline, 'report_section',
                               side_effect=[{'markdown': '# I. 주제\n배경이다.'},
                                            {'markdown': '# III. 결과\n[FIGURE 1]'}]) as write, \
             mock.patch.object(self.rr.report_figures, 'prepare',
                               return_value=[{'no': 1, 'caption': '사례 화면',
                                              'data': b'x', 'width': 1, 'height': 1,
                                              'ext': 'png'}]) as prepare:
            title, body, figures = self.rr._compose_report(
                self.user_id, 'inst', self.plan, [], [], progress)

        self.assertEqual(title, '버튼 문구 보고서')
        self.assertEqual(write.call_count, 2)          # 장마다 별도의 턴
        self.assertIn('# I. 주제', body)
        self.assertIn('[FIGURE 1]', body)
        self.assertEqual(len(figures), 1)
        # 검색 전담 턴이 찾아온 주소가 그림 계획에 반영된 채 준비로 넘어간다.
        hunt.assert_called_once()
        handed = prepare.call_args[0][0]
        self.assertEqual(handed[0]['image_url'], 'https://found.test/a.jpg')
        labels = [(row['label'], row['status']) for row in progress['steps']]
        self.assertEqual(labels[0], ('문서 계획 세우기', 'done'))
        self.assertIn(('이미지 검색 — 1건', 'done'), labels)
        self.assertIn(('본문 쓰기 — I. 주제', 'done'), labels)
        self.assertIn(('본문 쓰기 — III. 결과', 'done'), labels)
        self.assertEqual(labels[-1][0], '그림 준비')

    def test_image_search_turn_failure_keeps_planned_urls(self):
        from modules.research_pipeline import PipelineError
        progress = {}
        with mock.patch.object(self.rr.research_pipeline, 'report_plan',
                               return_value=copy.deepcopy(self.OUTLINE)), \
             mock.patch.object(self.rr, '_ask_figures', return_value=''), \
             mock.patch.object(self.rr.research_pipeline, 'find_report_images',
                               side_effect=PipelineError('검색 턴 죽음')), \
             mock.patch.object(self.rr.research_pipeline, 'report_section',
                               side_effect=[{'markdown': '# I. 주제\n.'},
                                            {'markdown': '# III. 결과\n[FIGURE 1]'}]), \
             mock.patch.object(self.rr.report_figures, 'prepare',
                               return_value=[]) as prepare:
            self.rr._compose_report(self.user_id, 'inst', self.plan, [], [], progress)

        # 계획에 적혀 있던 주소가 그대로 준비 단계로 넘어간다(폴백 검색도 그쪽에 있다).
        handed = prepare.call_args[0][0]
        self.assertEqual(handed[0]['image_url'], 'https://e.org/a.png')
        statuses = {row['label']: row['status'] for row in progress['steps']}
        self.assertEqual(statuses['이미지 검색 — 1건'], 'failed')

    def test_failed_section_is_marked_but_the_rest_is_delivered(self):
        from modules.research_pipeline import PipelineError
        progress = {}
        with mock.patch.object(self.rr.research_pipeline, 'report_plan',
                               return_value=copy.deepcopy(self.OUTLINE)), \
             mock.patch.object(self.rr, '_ask_figures', return_value=''), \
             mock.patch.object(self.rr.research_pipeline, 'find_report_images',
                               return_value={}), \
             mock.patch.object(self.rr.research_pipeline, 'report_section',
                               side_effect=[PipelineError('죽음'),
                                            {'markdown': '# III. 결과\n수치.'}]), \
             mock.patch.object(self.rr.report_figures, 'prepare', return_value=[]):
            _, body, _ = self.rr._compose_report(
                self.user_id, 'inst', self.plan, [], [], progress)

        self.assertIn('이 장은 만들지 못했습니다', body)
        self.assertIn('# III. 결과', body)
        statuses = {row['label']: row['status'] for row in progress['steps']}
        self.assertEqual(statuses['본문 쓰기 — I. 주제'], 'failed')
        self.assertEqual(statuses['본문 쓰기 — III. 결과'], 'done')

    def test_feedback_revises_the_figure_plan(self):
        """학생이 요청을 적으면 그림 계획이 수정된 채로 이어진다."""
        progress = {}
        revised = {'figures': [{'no': 1, 'kind': 'image', 'caption': '실제 앱 화면',
                                'python_code': '', 'image_url': '', 'image_query': '앱 화면'}],
                   'note': '앱 화면으로 교체'}
        with mock.patch.object(self.rr.research_pipeline, 'report_plan',
                               return_value=copy.deepcopy(self.OUTLINE)), \
             mock.patch.object(self.rr, '_ask_figures',
                               return_value='2번 말고 실제 앱 화면으로') as ask, \
             mock.patch.object(self.rr.research_pipeline, 'revise_figures',
                               return_value=revised) as revise, \
             mock.patch.object(self.rr.research_pipeline, 'find_report_images',
                               return_value={}), \
             mock.patch.object(self.rr.research_pipeline, 'report_section',
                               side_effect=[{'markdown': '# I'}, {'markdown': '# III'}]), \
             mock.patch.object(self.rr.report_figures, 'prepare', return_value=[]) as prepare:
            self.rr._compose_report(self.user_id, 'inst', self.plan, [], [], progress)

        ask.assert_called_once()
        revise.assert_called_once()
        self.assertEqual(prepare.call_args[0][0][0]['caption'], '실제 앱 화면')
        statuses = {row['label']: (row['status'], row['note'])
                    for row in progress['steps']}
        self.assertEqual(statuses['그림 계획 확인'], ('done', '앱 화면으로 교체'))

    def test_no_answer_proceeds_with_the_plan(self):
        """답이 없으면(시간 초과) 계획대로 진행한다. 기다리다 멈추면 안 된다."""
        progress = {}
        with mock.patch.object(self.rr.research_pipeline, 'report_plan',
                               return_value=copy.deepcopy(self.OUTLINE)), \
             mock.patch.object(self.rr, '_ask_figures', return_value=None), \
             mock.patch.object(self.rr.research_pipeline, 'revise_figures') as revise, \
             mock.patch.object(self.rr.research_pipeline, 'find_report_images',
                               return_value={}), \
             mock.patch.object(self.rr.research_pipeline, 'report_section',
                               side_effect=[{'markdown': '# I'}, {'markdown': '# III'}]), \
             mock.patch.object(self.rr.report_figures, 'prepare', return_value=[]):
            self.rr._compose_report(self.user_id, 'inst', self.plan, [], [], progress)
        revise.assert_not_called()
        statuses = {row['label']: row['note'] for row in progress['steps']}
        self.assertEqual(statuses['그림 계획 확인'], '응답 없어 계획대로 진행')

    def test_ask_figures_wakes_on_answer(self):
        """폴링이 실어 나른 질문에 답이 오면 작업 스레드가 깨어난다."""
        import threading
        progress = {}
        result = {}

        def worker():
            result['answer'] = self.rr._ask_figures(
                progress, self.plan.id,
                [{'no': 1, 'kind': 'image', 'caption': '사례'}], timeout=5)

        thread = threading.Thread(target=worker)
        thread.start()
        for _ in range(100):                     # 질문이 걸릴 때까지 잠깐 기다린다
            if progress.get('question'):
                break
            thread.join(0.02)
        question = progress['question']
        self.assertEqual(question['figures'][0]['caption'], '사례')

        entry = self.rr._PLAN_QUESTIONS[question['id']]
        entry['answer'] = '사진으로 바꿔줘'
        entry['event'].set()
        thread.join(3)
        self.assertEqual(result['answer'], '사진으로 바꿔줘')
        self.assertNotIn('question', progress)   # 걷혔다
        self.assertNotIn(question['id'], self.rr._PLAN_QUESTIONS)

    def test_plan_failure_falls_back_to_single_call(self):
        from modules.research_pipeline import PipelineError
        progress = {}
        single = {'title': '한 번에', 'report_markdown': '# 본문', 'figures': []}
        with mock.patch.object(self.rr.research_pipeline, 'report_plan',
                               side_effect=PipelineError('계획 실패')), \
             mock.patch.object(self.rr.research_pipeline, 'experiment_report',
                               return_value=single) as fallback, \
             mock.patch.object(self.rr.report_figures, 'prepare', return_value=[]):
            title, body, _ = self.rr._compose_report(
                self.user_id, 'inst', self.plan, [], [], progress)

        fallback.assert_called_once()
        self.assertEqual(title, '한 번에')
        self.assertEqual(body, '# 본문')


class RegenerateTests(unittest.TestCase):
    """다시 생성 — 마지막 답변만 걷어내고 같은 질문으로 다시 만든다."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from database import Database
        from modules import research_router as rr
        from modules.research_store import ResearchStore

        self.rr = rr
        self.db = Database(str(Path(tempfile.mkdtemp()) / 'regen.db'))
        self._saved = (rr.db, rr.store)
        rr.db = self.db
        rr.store = ResearchStore(self.db)
        self.user_id = 'user_regen'
        grade = rr.store.upsert_grade_plan(self.user_id, None, 1, goal='목표')
        self.plan = rr.store.upsert_subject_plan(self.user_id, grade.id, '공통국어')

    def tearDown(self):
        self.rr.db, self.rr.store = self._saved

    def _room(self, messages):
        session_id, _ = self.rr._experiment_room(self.user_id, self.plan)
        self.db.update_chat_session(session_id, self.user_id, messages=messages)
        return session_id

    def test_last_answer_is_dropped_and_the_question_is_reused(self):
        session_id = self._room([
            {'role': 'user', 'text': '첫 질문'},
            {'role': 'assistant', 'text': '첫 답'},
            {'role': 'user', 'text': '찾아봐 줘'},
            {'role': 'assistant', 'text': '마음에 안 드는 답'},
        ])
        with mock.patch.object(self.rr, '_experiment_answer',
                               return_value={'ok': True, 'payload': {}}) as answer:
            self.rr._experiment_regenerate(self.user_id, 'inst', self.plan.id)

        _, _, _, _, messages, message, _ = answer.call_args[0]
        self.assertEqual(message, '찾아봐 줘')                  # 같은 질문을 다시 쓴다
        self.assertEqual(messages[-1]['text'], '찾아봐 줘')      # 답변은 걷어냈다
        self.assertEqual(len(messages), 3)
        # 저장까지 끝나 있어야 새로고침해도 지운 답이 되살아나지 않는다.
        saved = self.db.get_chat_session(session_id, self.user_id).messages
        self.assertEqual([turn['role'] for turn in saved],
                         ['user', 'assistant', 'user'])

    def test_report_is_rebuilt_from_the_same_conversation(self):
        """대화는 그대로 두고 문서만 다시 뽑는다."""
        self._room([
            {'role': 'user', 'text': '결론은 이래'},
            {'role': 'assistant', 'text': '좋아, 끝났어'},
        ])
        made = {'report_file': '보고서.hwp', 'report_title': '보고서',
                'redirect': '/research#grade-1'}
        with mock.patch.object(self.rr, '_finish_experiment', return_value=made) as finish:
            result = self.rr._rebuild_report(self.user_id, 'inst', self.plan.id)

        self.assertTrue(result['ok'])
        self.assertEqual(result['payload']['kind'], 'report')   # 대화를 늘리지 않는다
        self.assertEqual(result['payload']['report_file'], '보고서.hwp')
        # 보고서는 지금까지의 대화 전체를 재료로 삼는다.
        self.assertEqual(len(finish.call_args[0][4]), 2)

    def test_rebuild_needs_a_conversation(self):
        self._room([])
        result = self.rr._rebuild_report(self.user_id, 'inst', self.plan.id)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 409)

    def test_nothing_to_regenerate_is_rejected(self):
        self._room([{'role': 'assistant', 'text': '먼저 건넨 인사'}])
        result = self.rr._experiment_regenerate(self.user_id, 'inst', self.plan.id)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 409)


class MeasureTableTests(unittest.TestCase):
    """측정값 표는 열만 받는다. 잰 값은 학생만 안다."""

    def test_columns_and_rows_pass_through(self):
        table = rp._clean_measure_table(
            {'title': '풍선 로켓', 'columns': ['시행', '질량(g)', '시간(s)'], 'rows': 4})
        self.assertEqual(table['columns'], ['시행', '질량(g)', '시간(s)'])
        self.assertEqual(table['rows'], 4)

    def test_single_column_is_dropped(self):
        # 열 하나짜리 표는 표가 아니다. 그냥 말로 받으면 된다.
        self.assertEqual(rp._clean_measure_table(
            {'title': 'x', 'columns': ['시행'], 'rows': 3})['columns'], [])

    def test_sizes_are_clamped(self):
        wide = rp._clean_measure_table(
            {'title': 'x', 'columns': list('abcdefgh'), 'rows': 999})
        self.assertEqual(len(wide['columns']), rp._TABLE_MAX_COLS)
        self.assertEqual(wide['rows'], rp._TABLE_MAX_ROWS)

    def test_missing_or_malformed_is_empty(self):
        for value in (None, {}, [], 'table', {'columns': None}):
            self.assertEqual(rp._clean_measure_table(value)['columns'], [])

    def test_model_supplied_values_are_not_carried(self):
        """모델이 값까지 채워 보내도 표에 실리지 않는다.

        미리 채워진 숫자가 있으면 학생이 그걸 지우지 않고 그대로 낼 수 있다.
        """
        table = rp._clean_measure_table({
            'title': 'x', 'columns': ['시행', '시간(s)'], 'rows': 3,
            'values': [['1', '3.2'], ['2', '4.1']],
        })
        self.assertNotIn('values', table)
        self.assertEqual(sorted(table), ['columns', 'rows', 'title'])

    def test_blank_column_names_are_removed(self):
        table = rp._clean_measure_table(
            {'title': 'x', 'columns': ['시행', '  ', '시간(s)'], 'rows': 3})
        self.assertEqual(table['columns'], ['시행', '시간(s)'])


class MeasureTableToReportTests(unittest.TestCase):
    """입력기가 보낸 마크다운 표가 보고서에서 진짜 표가 되는지."""

    def test_submitted_table_becomes_a_report_table(self):
        from modules import hwp_report
        # guide.js measureCard가 만드는 것과 같은 형식
        text = ('풍선 로켓 측정값이야.\n\n'
                '| 시행 | 질량(g) | 시간(s) |\n'
                '| --- | --- | --- |\n'
                '| 1 | 20 | 3.2 |\n'
                '| 2 | 40 | 4.1 |')
        rows = next(item['table'] for item in hwp_report._lines('', text)
                    if item.get('table'))
        self.assertEqual(rows[0], ['시행', '질량(g)', '시간(s)'])
        self.assertEqual(rows[-1], ['2', '40', '4.1'])


if __name__ == '__main__':
    unittest.main()
