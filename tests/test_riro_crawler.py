import unittest

from modules.riroschool_crawler import RiroSchoolCrawler


class RiroDateParsingTests(unittest.TestCase):
    def setUp(self):
        self.crawler = RiroSchoolCrawler()

    def test_parses_supported_date_formats(self):
        cases = {
            '07-23': '2026-07-23',
            '2026-07-23': '2026-07-23',
            '26-07-23': '2026-07-23',
            '2026.07.23': '2026-07-23',
            '07.23 마감': '2026-07-23',
        }
        for raw_date, expected in cases.items():
            with self.subTest(raw_date=raw_date):
                self.assertEqual(self.crawler._parse_date(raw_date, '2026'), expected)

    def test_rejects_invalid_date(self):
        self.assertIsNone(self.crawler._parse_date('2026-13-40', '2026'))

    def test_grade_filter_includes_shared_events(self):
        self.assertTrue(self.crawler._matches_grade('2학년 수학 수행평가', '2'))
        self.assertTrue(self.crawler._matches_grade('전학년 과학 공지', '2'))
        self.assertTrue(self.crawler._matches_grade('전교생 행사 안내', '2'))
        self.assertFalse(self.crawler._matches_grade('1학년 영어 수행평가', '2'))


if __name__ == '__main__':
    unittest.main()
