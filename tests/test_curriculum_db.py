"""정규화된 2022 개정 교육과정 데이터셋(data/curriculum/)의 무결성 검증.

원본 PDF 코퍼스 없이도 돌도록 산출물 JSON만 읽는다.
"""
import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_DIR = PROJECT_ROOT / 'data' / 'curriculum'

# 1학년 공통 과목. Phase 5(1학년 세특 구체화)가 이 목록을 기준으로 동작한다.
EXPECTED_COMMON_SUBJECTS = {
    '공통국어1', '공통국어2', '공통수학1', '공통수학2', '공통영어1', '공통영어2',
    '기본수학1', '기본수학2', '기본영어1', '기본영어2',
    '통합과학1', '통합과학2', '과학탐구실험1', '과학탐구실험2',
    '통합사회1', '통합사회2', '한국사1', '한국사2',
}


def _load(name):
    return json.loads((CURRICULUM_DIR / name).read_text(encoding='utf-8'))


class CurriculumDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.standards = _load('achievement_standards.json')
        cls.subjects = _load('subjects.json')
        cls.records = cls.standards['records']

    def test_dataset_is_not_empty(self):
        self.assertGreater(len(self.records), 3000)
        self.assertGreater(len(self.subjects['subjects']), 200)

    def test_required_fields_are_populated(self):
        required = ('uid', 'code', 'code_prefix', 'subject', 'subject_type',
                    'statement', 'grade_band', 'curriculum_area', 'volume')
        for record in self.records:
            for field in required:
                self.assertTrue(record.get(field), f"{record.get('code')} 의 {field} 누락")

    def test_uid_is_unique_even_though_code_is_not(self):
        uids = [r['uid'] for r in self.records]
        self.assertEqual(len(uids), len(set(uids)))
        # 12스문(스포츠 문화 / 스페인어권 문화)처럼 서로 다른 과목이 같은 코드를 쓴다.
        codes = [r['code'] for r in self.records]
        self.assertLess(len(set(codes)), len(codes))

    def test_code_prefix_maps_to_one_subject_within_a_volume(self):
        # 접두사도 전국 단위로는 유일하지 않다(12스문 = 스포츠 문화 / 스페인어권 문화).
        # 과목을 특정하는 키는 (별책, 접두사)다.
        by_prefix = {}
        for record in self.records:
            key = (record['volume'], record['code_prefix'])
            by_prefix.setdefault(key, set()).add(record['subject'])
        for key, names in by_prefix.items():
            self.assertEqual(len(names), 1, f'{key} 가 여러 과목명에 걸침: {names}')

    def test_bare_code_prefix_is_not_globally_unique(self):
        by_prefix = {}
        for record in self.records:
            by_prefix.setdefault(record['code_prefix'], set()).add(record['subject'])
        collisions = {p: n for p, n in by_prefix.items() if len(n) > 1}
        self.assertIn('12스문', collisions, '접두사 충돌 전제가 깨졌다면 키 설계를 재검토해야 한다')

    def test_common_subjects_cover_first_grade(self):
        first_grade = {r['subject'] for r in self.records if r['grade_band'] == '1'}
        self.assertEqual(first_grade, EXPECTED_COMMON_SUBJECTS)

    def test_subject_types_are_known_values(self):
        allowed = {'공통', '일반선택', '진로선택', '융합선택'}
        self.assertTrue({r['subject_type'] for r in self.records}.issubset(allowed))

    def test_statements_look_like_sentences(self):
        for record in self.records:
            statement = record['statement']
            self.assertGreaterEqual(len(statement), 10, record['code'])
            self.assertNotIn('[', statement, f"{record['code']} 문구에 코드가 섞임")

    def test_subjects_index_matches_standards(self):
        counted = {}
        for record in self.records:
            key = f"{record['volume']}:{record['code_prefix']}"
            counted[key] = counted.get(key, 0) + 1
        entries = self.subjects['subjects']
        self.assertEqual(len({e['subject_uid'] for e in entries}), len(entries))
        for entry in entries:
            self.assertEqual(entry['standard_count'], counted[entry['subject_uid']])


if __name__ == '__main__':
    unittest.main()
