"""문서 점검자 검증. 네트워크 없이 문단 검사(check_paragraphs)만 본다."""
import unittest

from modules import hwp_inspect


def _para(text, alignment='justify'):
    return {'text': text, 'style': {'alignment': alignment}}


class InspectorTests(unittest.TestCase):
    def test_clean_document_has_no_findings(self):
        paragraphs = [
            _para('제목', 'center'), _para(''),
            _para('I. 주제'), _para('본문에서 Fig 1과 같이 확인하였다.'),
            _para('Figure 1. 실험 장면', 'center'),
            _para('II. 방법'), _para('본문이다.'),
        ]
        self.assertEqual(hwp_inspect.check_paragraphs(paragraphs), [])

    def test_unmentioned_figure_is_flagged(self):
        paragraphs = [_para('I. 주제'), _para('본문이다.'),
                      _para('Figure 2. 결과 그래프', 'center')]
        findings = hwp_inspect.check_paragraphs(paragraphs)
        self.assertTrue(any('Figure 2' in f['message'] and f['level'] == 'warn'
                            for f in findings))

    def test_mention_without_figure_is_flagged(self):
        paragraphs = [_para('I. 주제'), _para('Fig 3과 같이 나타났다.')]
        findings = hwp_inspect.check_paragraphs(paragraphs)
        self.assertTrue(any('Fig 3' in f['message'] for f in findings))

    def test_skipped_chapter_number_is_flagged(self):
        paragraphs = [_para('I. 주제'), _para('본문'), _para('III. 결론')]
        findings = hwp_inspect.check_paragraphs(paragraphs)
        self.assertTrue(any('건너뛰어요' in f['message'] for f in findings))

    def test_long_empty_run_is_flagged(self):
        paragraphs = [_para('I. 주제'), _para(''), _para(''), _para(''),
                      _para('본문')]
        findings = hwp_inspect.check_paragraphs(paragraphs)
        self.assertTrue(any('빈 문단' in f['message'] for f in findings))

    def test_centered_body_is_flagged_but_caption_is_not(self):
        long_text = '가운데 정렬이 된 긴 본문 문단이다. ' * 3
        paragraphs = [_para('제목', 'center'), _para(''), _para('I. 주제'),
                      _para(long_text, 'center'),
                      _para('Figure 1. 캡션', 'center'),
                      _para('Fig 1과 같다.')]
        findings = hwp_inspect.check_paragraphs(paragraphs)
        self.assertTrue(any('가운데 정렬' in f['message'] for f in findings))
        self.assertFalse(any('캡션' in f['message'] for f in findings))


if __name__ == '__main__':
    unittest.main()
