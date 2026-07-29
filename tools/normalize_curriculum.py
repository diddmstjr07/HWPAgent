"""2022 개정 교육과정 별책 PDF에서 과목·영역·성취기준을 구조화된 JSON으로 추출합니다.

원본 코퍼스(data/reference_sources/raw/)는 용량이 커서 저장소에 포함하지 않으므로,
이 스크립트는 코퍼스가 있는 환경에서 실행해 data/curriculum/ 산출물을 생성합니다.

사용법:
    .venv/bin/python tools/normalize_curriculum.py
    .venv/bin/python tools/normalize_curriculum.py --volume 8      # 특정 별책만

알려진 한계:
    본문이 양쪽 정렬이라 한 단어가 줄바꿈으로 갈리면('참여한다' -> '참여' + '한다')
    PDF 콘텐츠 스트림에 공백 문자가 남지 않는다. 어느 추출 방식으로도 원래 띄어쓰기를
    복원할 수 없어, 줄을 공백으로 이어 붙인다. 의미는 보존되지만 일부 문구에
    '참여 한다'처럼 불필요한 공백이 남을 수 있다.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_ROOT = PROJECT_ROOT / 'data/reference_sources/raw/curriculum_2022_original/ncic_highschool_individual'
AMENDMENT_ROOT = PROJECT_ROOT / 'data/reference_sources/raw/curriculum_amendments/2024-3/ncic_consolidated_annexes'
OUTPUT_DIR = PROJECT_ROOT / 'data/curriculum'

# 고등학교 보통교과 + 계열 선택 별책. 전문 교과(별책23~39)는 특성화고 대상이라 제외한다.
TARGET_VOLUMES: Dict[int, str] = {
    5: '국어', 6: '도덕', 7: '사회', 8: '수학', 9: '과학',
    10: '기술·가정/정보', 11: '체육', 12: '음악', 13: '미술', 14: '영어',
    16: '제2외국어', 17: '한문', 19: '교양',
    20: '과학 계열 선택', 21: '체육 계열 선택', 22: '예술 계열 선택',
}

# 2024-3 일부개정이 원고시를 덮어쓰는 별책. manifest.json의 source_of_truth_rule을 따른다.
AMENDED_VOLUMES = {7, 12, 19}

# 성취기준 코드: [10공수1-01-01], [12대수01-01] 처럼 접두사 뒤 대시가 있을 수도 없을 수도 있다.
CODE_RE = re.compile(r'\[(((?:10|12)[^\]\s]{1,16}?)-?(\d{2})-(\d{2}))\]')
CODE_AT_LINE_START_RE = re.compile(r'^\s*' + CODE_RE.pattern)
# (1) 다항식 / (2) 방정식과 부등식 -- 영역(단원) 머리글
AREA_RE = re.compile(r'^\s*\((\d{1,2})\)\s*(\S[^\n]{0,60})$')
# (가) 성취기준 해설 / (나) 성취기준 적용 시 고려 사항 -- 성취기준 정의 블록의 종료 신호
SUBSECTION_RE = re.compile(r'^\s*\([가-힣]\)')
# 가. 내용 체계 / 나. 성취기준 / 1. 성격 및 목표 -- 상위 절 머리글
SECTION_RE = re.compile(r'^\s*(?:[가-힣]\.|\d+\.)\s*\S')
STANDARDS_HEADING_RE = re.compile(r'^\s*나\.\s*성취기준')
RUNNING_HEADER_RE = re.compile(r'^\s*(?:선택\s*중심\s*교육과정|공통\s*교육과정|.{0,20}교육과정)\s*[–\-—]?\s*(?:.{0,14}과목)?\s*[–\-—]?\s*$')
PAGE_NUMBER_RE = re.compile(r'^\s*\d{1,4}\s*$')

# 모든 과목 절은 '1. 성격 및 목표'로 시작한다. 과목 경계를 잡는 기준 앵커다.
ANCHOR_RE = re.compile(r'^\s*1\.\s*성격\s*및\s*목표')
# 공통 과목 절은 '수학' 같은 교과 표지 대신 [공통수학1] 형태의 대괄호 머리글을 쓰기도 한다.
SUBJECT_BRACKET_RE = re.compile(r'^\s*\[([^\]]{2,24})\]\s*$')
STRUCTURAL_LABELS = {
    '공통 교육과정', '선택 중심 교육과정', '공통 과목',
    '일반 선택 과목', '진로 선택 과목', '융합 선택 과목',
}
STRUCTURAL_LABEL_RE = re.compile(r'(교육과정|과목 구조|설계의 개요|^초등학교|^중학교|^고등학교|^별표|^차\s*례)')
# 내용 체계 표의 범주 칸이 과목명과 같은 크기로 조판된 별책이 있어 함께 걸러낸다.
CATEGORY_LABELS = {
    '지식⋅이해', '과정⋅기능', '가치⋅태도', '핵심 아이디어',
    '내용 요소', '구분', '범주', '영역',
}

# 별책9 공통 과목처럼 과목별 머리글 없이 '통합과학1, 통합과학2' 표지만 있는 경우를 보정한다.
# 성취기준 코드 접두사와 과목명은 1:1이므로 접두사를 키로 쓴다.
SUBJECT_NAME_OVERRIDES = {
    '10통과1': '통합과학1', '10통과2': '통합과학2',
    '10과탐1': '과학탐구실험1', '10과탐2': '과학탐구실험2',
}

# 러닝 헤더는 '선택 중심 교육과정 – 일반 선택 과목 -' 또는 '일반 선택 - 독일어'처럼
# 별책마다 표기가 달라 '과목' 없이도 인식되도록 느슨하게 맞춘다. 구체적인 것부터 검사한다.
SUBJECT_TYPE_PATTERNS = [
    ('융합 선택', '융합선택'),
    ('진로 선택', '진로선택'),
    ('일반 선택', '일반선택'),
    ('공통 과목', '공통'),
]

# 해설·고려 사항의 인용은 불릿으로 시작한다. 정의부와 구분하기 위해 배제한다.
BULLET_PREFIXES = ('•', '⋅', '·', '-', '‧')

# 코드 접두사 앞 두 자리는 학교급/학년 계열을 뜻한다. 10=공통(1학년), 12=선택(2~3학년).
# 과목 표지 제목으로 인정할 최소 글자 크기(별책 전반에서 21pt 이상으로 조판된다).
SUBJECT_TITLE_MIN_SIZE = 18.0

GRADE_BAND_BY_PREFIX = {'10': '1', '12': '2-3'}


def _volume_number(path: Path) -> Optional[int]:
    match = re.search(r'\[?별책\s*(\d+)\]?', path.name)
    return int(match.group(1)) if match else None


def _collect_volume_files() -> Dict[int, Path]:
    """별책 번호별로 사용할 PDF 경로를 고른다. 2024-3 개정본이 있으면 그쪽을 우선한다."""
    files: Dict[int, Path] = {}
    for path in sorted(ORIGINAL_ROOT.glob('*/*.pdf')):
        number = _volume_number(path)
        if number in TARGET_VOLUMES:
            files.setdefault(number, path)

    for path in sorted(AMENDMENT_ROOT.glob('*/*.pdf')):
        number = _volume_number(path)
        if number in TARGET_VOLUMES and number in AMENDED_VOLUMES:
            files[number] = path
    return files


def _largest_line(page: fitz.Page, min_size: float = 0.0) -> Optional[str]:
    """페이지에서 가장 큰 글자로 조판된 줄을 반환한다(구조 라벨·쪽번호는 제외)."""
    best_size = 0.0
    best_text: Optional[str] = None
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            spans = line.get('spans', [])
            if not spans:
                continue
            text = ''.join(span['text'] for span in spans).strip()
            # '가. 성격', '2. 내용 체계' 같은 절 머리글과 쪽번호는 과목명이 아니다.
            if len(text) < 2 or ANCHOR_RE.match(text) or SECTION_RE.match(text):
                continue
            if PAGE_NUMBER_RE.match(text):
                continue
            if text in CATEGORY_LABELS or text in STRUCTURAL_LABELS or STRUCTURAL_LABEL_RE.search(text):
                continue
            size = max(span['size'] for span in spans)
            if size > best_size:
                best_size, best_text = size, text
    return best_text if best_size >= min_size else None


def _subject_sections(doc: fitz.Document) -> Dict[int, List[str]]:
    """과목 절이 시작하는 페이지 번호 -> 과목명 목록을 반환한다.

    별책마다 머리글 글자 크기가 달라 크기만으로는 과목명을 특정할 수 없다.
    대신 모든 과목 절이 '1. 성격 및 목표'로 시작한다는 구조를 앵커로 쓴다.
    '공통국어1, 공통국어2'처럼 두 과목이 한 절을 공유하면 목록으로 돌려준다.
    """
    sections: Dict[int, List[str]] = {}
    latest_title: Optional[str] = None
    for index, page in enumerate(doc):
        # 별책19처럼 과목 표지와 '1. 성격 및 목표'가 여러 쪽 떨어진 경우가 있어
        # 제목 후보를 계속 갱신하다가 앵커를 만나면 가장 최근 후보를 채택한다.
        title = _largest_line(page, min_size=SUBJECT_TITLE_MIN_SIZE)
        if title:
            latest_title = title
        lines = page.get_text('text', sort=True).splitlines()
        if not any(ANCHOR_RE.match(line) for line in lines):
            continue
        if latest_title:
            sections[index] = [part.strip() for part in latest_title.split(',') if part.strip()]
    return sections


def _page_subject_type(page_text: str) -> Optional[str]:
    for needle, label in SUBJECT_TYPE_PATTERNS:
        if needle in page_text:
            return label
    return None


def _clean_statement(raw: str) -> str:
    """줄바꿈으로 끊긴 성취기준 문구를 한 줄로 복원하고 페이지 머리글/쪽번호를 제거한다."""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if PAGE_NUMBER_RE.match(stripped) or RUNNING_HEADER_RE.match(stripped):
            continue
        lines.append(stripped)
    text = ' '.join(lines)
    text = re.sub(r'\s+', ' ', text).strip()
    # 수식이 사설 영역(Private Use Area) 글리프로 깨져 들어오는 경우를 제거한다.
    text = re.sub(r'[-]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def parse_volume(volume: int, path: Path) -> List[Dict]:
    """별책 하나를 파싱해 성취기준 레코드 목록을 반환한다."""
    doc = fitz.open(path)
    sections = _subject_sections(doc)

    records: List[Dict] = []
    section_titles: List[str] = []
    subject_by_prefix: Dict[str, str] = {}
    current_subject: Optional[str] = None
    current_subject_type: Optional[str] = None
    current_area_no: Optional[str] = None
    current_area_name: Optional[str] = None
    in_standards = False
    seen_standards_heading = False
    pending: Optional[Dict] = None
    buffer: List[str] = []

    def flush() -> None:
        nonlocal pending, buffer
        if pending is not None:
            statement = _clean_statement('\n'.join(buffer))
            if statement:
                pending['statement'] = statement
                records.append(pending)
        pending = None
        buffer = []

    for page_no, page in enumerate(doc):
        # 별책은 2단 조판이라 기본 블록 순서가 읽기 순서와 어긋난다. sort=True로 좌표 기준 정렬한다.
        page_text = page.get_text('text', sort=True)
        subject_type = _page_subject_type(page_text)
        if subject_type:
            current_subject_type = subject_type

        if page_no in sections:
            flush()
            section_titles = sections[page_no]
            subject_by_prefix = {}
            current_subject = section_titles[0]
            current_area_no = current_area_name = None
            in_standards = False
            seen_standards_heading = False

        for line in page_text.splitlines():
            bracket_match = SUBJECT_BRACKET_RE.match(line)
            if bracket_match:
                label = bracket_match.group(1).strip()
                if (label not in STRUCTURAL_LABELS
                        and not STRUCTURAL_LABEL_RE.search(label)
                        and not CODE_RE.match(f'[{label}]')):
                    # [한국사 1]처럼 '나. 성취기준' 뒤에 오는 하위 과목 구분자도 있으므로
                    # 성취기준 블록 상태는 건드리지 않고 과목명과 영역만 갱신한다.
                    flush()
                    current_subject = label
                    current_area_no = current_area_name = None
                    continue

            if STANDARDS_HEADING_RE.match(line):
                flush()
                in_standards = True
                seen_standards_heading = True
                continue

            area_match = AREA_RE.match(line)
            if area_match and not CODE_AT_LINE_START_RE.match(line):
                flush()
                current_area_no = area_match.group(1).zfill(2)
                current_area_name = area_match.group(2).strip()
                # 영역은 '(가) 해설 → (2) 다음 영역' 순으로 반복되므로 성취기준 블록을 다시 연다.
                in_standards = seen_standards_heading
                continue

            if SUBSECTION_RE.match(line):
                flush()
                in_standards = False
                continue

            code_match = CODE_AT_LINE_START_RE.match(line)
            if code_match and in_standards and not line.lstrip().startswith(BULLET_PREFIXES):
                flush()
                code, prefix, area_no, seq = code_match.groups()
                # '공통국어1, 공통국어2'처럼 한 절이 여러 과목을 담으면 코드 접두사가 등장한
                # 순서대로 과목명을 배분한다(접두사와 과목은 1:1이다).
                if prefix not in subject_by_prefix and section_titles:
                    index = min(len(subject_by_prefix), len(section_titles) - 1)
                    subject_by_prefix[prefix] = section_titles[index]
                resolved_subject = subject_by_prefix.get(prefix, current_subject)
                pending = {
                    'code': f'[{code}]',
                    'code_prefix': prefix,
                    'volume': volume,
                    'curriculum_area': TARGET_VOLUMES[volume],
                    'subject': resolved_subject,
                    'subject_type': current_subject_type,
                    'grade_band': GRADE_BAND_BY_PREFIX.get(prefix[:2]),
                    'seq_no': seq,
                    'area_no': area_no,
                    'area_name': current_area_name,
                    'source_pdf': str(path.relative_to(PROJECT_ROOT)),
                }
                buffer = [line.strip()[line.strip().index(']') + 1:]]
                continue

            if pending is not None:
                if SECTION_RE.match(line) or not line.strip():
                    flush()
                else:
                    buffer.append(line)

        flush()

    doc.close()

    # 같은 코드가 두 번 잡히면 정의부가 앞서므로 첫 번째만 남긴다(해설의 줄바꿈 인용 방어).
    deduped: List[Dict] = []
    seen: set = set()
    for record in records:
        if record['code'] in seen:
            continue
        seen.add(record['code'])
        record['subject'] = SUBJECT_NAME_OVERRIDES.get(record['code_prefix'], record['subject'])
        # 성취기준 코드는 전국 단위로 유일하지 않다. 예를 들어 12스문은 '스포츠 문화'(별책11)와
        # '스페인어권 문화'(별책16)가, 12심독은 '심화 영어 독해와 작문'과 '심화 독일어'가 함께 쓴다.
        record['uid'] = f"{record['volume']}:{record['code']}"
        deduped.append(record)
    return deduped


def build_subjects(records: List[Dict]) -> List[Dict]:
    """성취기준 레코드에서 과목 목록을 집계한다."""
    subjects: Dict[tuple, Dict] = {}
    for record in records:
        # 코드 접두사도 전국 단위로 유일하지 않다. 12스문은 '스포츠 문화'(별책11)와
        # '스페인어권 문화'(별책16)가 함께 쓰므로 별책까지 묶어야 과목이 특정된다.
        key = (record['volume'], record['code_prefix'])
        entry = subjects.setdefault(key, {
            'subject_uid': f"{record['volume']}:{record['code_prefix']}",
            'code_prefix': record['code_prefix'],
            'subject': record['subject'],
            'subject_type': record['subject_type'],
            'curriculum_area': record['curriculum_area'],
            'volume': record['volume'],
            'grade_band': record['grade_band'],
            'areas': {},
            'standard_count': 0,
        })
        entry['standard_count'] += 1
        if record['area_name']:
            entry['areas'].setdefault(record['area_no'], record['area_name'])

    result = []
    for entry in subjects.values():
        entry['areas'] = [
            {'area_no': no, 'area_name': name}
            for no, name in sorted(entry['areas'].items())
        ]
        result.append(entry)
    return sorted(result, key=lambda item: (item['volume'], item['code_prefix']))


def main() -> None:
    parser = argparse.ArgumentParser(description='2022 개정 교육과정 성취기준 정규화')
    parser.add_argument('--volume', type=int, action='append', help='특정 별책 번호만 처리')
    args = parser.parse_args()

    volume_files = _collect_volume_files()
    if args.volume:
        volume_files = {k: v for k, v in volume_files.items() if k in args.volume}

    if not volume_files:
        raise SystemExit(
            '별책 PDF를 찾지 못했습니다. data/reference_sources/raw/ 코퍼스를 먼저 내려받으세요 '
            '(tools/download_research_narrative_sources.py).'
        )

    all_records: List[Dict] = []
    for volume in sorted(volume_files):
        path = volume_files[volume]
        records = parse_volume(volume, path)
        source = '2024-3 개정' if volume in AMENDED_VOLUMES else '2022-33 원고시'
        print(f'[CURRICULUM] 별책{volume:<3} {TARGET_VOLUMES[volume]:<12} '
              f'성취기준 {len(records):>4}건  ({source})')
        all_records.extend(records)

    subjects = build_subjects(all_records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'curriculum': '2022 개정 교육과정',
        'composition': '2022-33 원고시 + 2024-3 일부개정(사회·음악·교양)',
        'volumes': {str(k): TARGET_VOLUMES[k] for k in sorted(volume_files)},
        'standard_count': len(all_records),
        'subject_count': len(subjects),
    }

    (OUTPUT_DIR / 'achievement_standards.json').write_text(
        json.dumps({'meta': meta, 'records': all_records}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    (OUTPUT_DIR / 'subjects.json').write_text(
        json.dumps({'meta': meta, 'subjects': subjects}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    print(f'[CURRICULUM] 총 성취기준 {len(all_records)}건 / 과목 {len(subjects)}개')
    print(f'[CURRICULUM] 저장 위치: {OUTPUT_DIR.relative_to(PROJECT_ROOT)}/')


if __name__ == '__main__':
    main()
