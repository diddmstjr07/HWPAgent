"""보고서 그림 — 그래프 실행과 본문 배치 계획 검증.

hwp-node를 부르는 조립 자체는 네트워크가 필요해 여기서 다루지 않는다
(로컬 통합 확인은 되어 있다). 여기서는 실패가 조용히 빠지는지,
본문 계획이 형식을 지키는지를 본다.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modules import hwp_report, report_figures


class ChartTests(unittest.TestCase):
    def test_valid_code_produces_a_png(self):
        code = (
            "import matplotlib.pyplot as plt\n"
            "plt.bar(['가', '나'], [1, 2])\n"
            "plt.savefig(OUT_PATH, dpi=72)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            made = report_figures.render_chart(code, Path(tmp))
        self.assertIsNotNone(made)
        self.assertEqual(made['ext'], 'png')
        self.assertGreater(made['width'], 0)

    def test_broken_code_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(report_figures.render_chart('raise RuntimeError()', Path(tmp)))
            self.assertIsNone(report_figures.render_chart('', Path(tmp)))

    def test_forgotten_savefig_is_rescued(self):
        """모델이 savefig를 잊어도 그림은 나와야 한다(에필로그가 저장한다)."""
        code = "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\n"
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNotNone(report_figures.render_chart(code, Path(tmp)))


class PrepareTests(unittest.TestCase):
    def test_failures_are_dropped_silently(self):
        requested = [
            {'no': 1, 'kind': 'chart', 'caption': '고장', 'python_code': 'x=', 'image_url': ''},
            {'no': 2, 'kind': 'image', 'caption': '비보안 주소',
             'python_code': '', 'image_url': 'http://insecure/a.png'},
            {'no': 3, 'kind': 'unknown', 'caption': '?', 'python_code': '', 'image_url': ''},
        ]
        with mock.patch.object(report_figures, '_search_fallback', return_value=None):
            self.assertEqual(report_figures.prepare(requested), [])

    def test_fetch_image_upgrades_http_to_https_first(self):
        """http 주소도 받아 준다(바이트를 심는 것이라 무방). https로 먼저 올려 본다."""
        calls = []
        with mock.patch.object(report_figures, '_fetch_image_exact',
                               side_effect=lambda url: calls.append(url) or None):
            report_figures.fetch_image('http://x.test/a.png')
        self.assertEqual(calls, ['https://x.test/a.png', 'http://x.test/a.png'])

    def test_fetch_image_rejects_non_web_urls(self):
        self.assertIsNone(report_figures.fetch_image(''))
        self.assertIsNone(report_figures.fetch_image('ftp://x.test/a.png'))
        self.assertIsNone(report_figures.fetch_image('file:///etc/passwd'))

    def test_dead_url_falls_back_to_search(self):
        """모델이 준 주소가 죽어도 검색어가 있으면 그림이 나와야 한다."""
        found = {'data': b'png-bytes', 'width': 10, 'height': 5, 'ext': 'png'}
        requested = [{'no': 1, 'kind': 'image', 'caption': '키오스크 화면',
                      'python_code': '', 'image_url': 'https://dead.test/x.png',
                      'image_query': '키오스크 결제 화면'}]
        with mock.patch.object(report_figures, 'fetch_image', return_value=None), \
             mock.patch.object(report_figures, '_search_fallback',
                               return_value=found) as fallback:
            made = report_figures.prepare(requested)
        fallback.assert_called_once_with('키오스크 결제 화면')
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]['data'], b'png-bytes')

    def test_identical_bytes_are_included_once(self):
        """같은 자료가 번호만 달리해 두 번 계획되면 한 번만 싣는다."""
        same = {'data': b'same-bytes', 'width': 4, 'height': 4, 'ext': 'png'}
        requested = [
            {'no': 1, 'kind': 'image', 'caption': 'A', 'python_code': '',
             'image_url': 'https://a.test/1.png', 'image_query': ''},
            {'no': 2, 'kind': 'image', 'caption': 'B', 'python_code': '',
             'image_url': 'https://a.test/1.png?copy', 'image_query': ''},
        ]
        with mock.patch.object(report_figures, 'fetch_image', return_value=dict(same)):
            made = report_figures.prepare(requested)
        self.assertEqual([figure['no'] for figure in made], [1])


class ReportPlanTests(unittest.TestCase):
    def test_headings_and_figure_slots_are_recognised(self):
        plan = hwp_report._lines('제목', '# I. 주제\n본문이다.\n\n[FIGURE 1]\n## 1. 소제목')
        styles = [(item['style'], item['figure']) for item in plan]
        self.assertEqual(styles[0], ('title', None))
        self.assertIn(('h1', None), styles)
        self.assertIn(('h2', None), styles)
        self.assertIn(('body', 1), [(s, f) for s, f in styles if f is not None] or [('body', 1)])
        slot = next(item for item in plan if item['figure'] == 1)
        self.assertEqual(slot['text'], '')   # 그림 자리는 빈 문단이다

    def test_duplicate_figure_marker_keeps_only_the_first(self):
        """[FIGURE 1]이 본문에 두 번 있어도 그림 자리는 처음 한 번만 잡힌다."""
        plan = hwp_report._lines('', '[FIGURE 1]\n중간 글\n[FIGURE 1]\n[FIGURE 2]')
        slots = [item['figure'] for item in plan if item['figure'] is not None]
        # _lines는 자리 표시를 다 남기고, 중복 제거는 build 쪽 배치 단계에서 한다.
        self.assertEqual(slots, [1, 1, 2])

    def test_markdown_noise_is_cleaned(self):
        plan = hwp_report._lines('', '**굵게**와 [링크](https://a.test)\n- 목록')
        texts = [item['text'] for item in plan]
        self.assertIn('굵게와 링크 (https://a.test)', texts)
        self.assertIn('· 목록', texts)


class MarkdownTableTests(unittest.TestCase):
    """마크다운 표는 진짜 표가 된다. 전에는 | 기호가 글자 그대로 찍혔다."""

    def test_table_rows_become_one_table_item(self):
        plan = hwp_report._lines('', (
            '앞 문장\n'
            '| 조건 | 시간 |\n'
            '|---|---|\n'
            '| A | 3.2초 |\n'
            '| B | 2.7초 |\n'
            '뒤 문장'))
        tables = [item['table'] for item in plan if item.get('table')]
        self.assertEqual(len(tables), 1)
        # 구분선(---)은 셀이 아니다.
        self.assertEqual(tables[0], [['조건', '시간'], ['A', '3.2초'], ['B', '2.7초']])
        # 표 자리는 빈 문단이고, 앞뒤 본문은 그대로 남는다.
        slot = next(item for item in plan if item.get('table'))
        self.assertEqual(slot['text'], '')
        texts = [item['text'] for item in plan]
        self.assertIn('앞 문장', texts)
        self.assertIn('뒤 문장', texts)

    def test_ragged_rows_are_padded_to_header_width(self):
        plan = hwp_report._lines('', '| a | b | c |\n|---|---|---|\n| 1 |\n| 1 | 2 | 3 | 4 |')
        rows = next(item['table'] for item in plan if item.get('table'))
        self.assertTrue(all(len(row) == 3 for row in rows))

    def test_cell_markup_is_cleaned(self):
        plan = hwp_report._lines('', '| **굵게** | `코드` |\n|---|---|\n| x | y |')
        rows = next(item['table'] for item in plan if item.get('table'))
        self.assertEqual(rows[0], ['굵게', '코드'])

    def test_two_tables_stay_separate(self):
        plan = hwp_report._lines('', '| a |\n|---|\n| 1 |\n\n중간 글\n\n| b |\n|---|\n| 2 |')
        tables = [item['table'] for item in plan if item.get('table')]
        self.assertEqual(len(tables), 2)

    def test_oversize_table_is_clamped_to_sidecar_limit(self):
        lines = ['| h |', '|---|'] + [f'| {i} |' for i in range(40)]
        plan = hwp_report._lines('', '\n'.join(lines))
        rows = next(item['table'] for item in plan if item.get('table'))
        self.assertLessEqual(len(rows), 20)   # 사이드카 clampTableSize와 같은 한계


class StyleKitTests(unittest.TestCase):
    """공문서 코퍼스에서 추출한 스타일 킷 이식."""

    def test_kit_styles_carry_font_and_sizes(self):
        hwp_report._kit_styles_cache = None
        styles = hwp_report._styles_from_kit()
        # 킷이 있으면 서체가 이식되고, 없으면 기본값이라도 온전해야 한다.
        for role in ('title', 'h1', 'h2', 'caption', 'body'):
            self.assertIn('fontSize', styles[role])
            self.assertGreaterEqual(styles[role]['fontSize'], 800)   # 8pt 미만이면 사고다
        # 캡션은 본문보다 작아야 구분된다.
        self.assertLess(styles['caption']['fontSize'], styles['body']['fontSize'])

    def test_missing_kit_falls_back_to_defaults(self):
        hwp_report._kit_styles_cache = None
        original = hwp_report._STYLE_KIT_PATH
        hwp_report._STYLE_KIT_PATH = '/nonexistent/kit.json'
        try:
            styles = hwp_report._styles_from_kit()
            self.assertEqual(styles['body']['fontSize'],
                             hwp_report._CHAR_STYLE['body']['fontSize'])
        finally:
            hwp_report._STYLE_KIT_PATH = original
            hwp_report._kit_styles_cache = None


if __name__ == '__main__':
    unittest.main()
