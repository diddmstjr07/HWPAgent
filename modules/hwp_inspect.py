"""완성된 보고서를 다시 열어 고칠 곳을 짚어 주는 점검자.

문서를 고쳐 쓰지 않습니다 — 이 앱의 원칙(AI가 대신 해주지 않는다)은 보고서
본문에도 적용됩니다. 점검자는 서식과 구조의 어긋남을 찾아 알려주기만 하고,
고치는 것은 학생이 편집기에서 합니다.

hwp-node의 문서 모델(GET /sessions/{id}/document)이 주는 것은 문단 텍스트와
정렬뿐이므로(실측), 검사도 그 위에서 합니다:
  - 그림 번호와 본문 인용이 서로 맞는가 (캡션만 있고 언급 없는 그림, 그 반대)
  - 제목 위계가 순서대로인가 (I. 없이 1. 이 먼저 나오는가, 로마 숫자 건너뜀)
  - 빈 문단이 여럿 이어져 헐거워 보이는 곳
  - 본문 문단이 가운데 정렬로 어긋난 곳
  - 첫 페이지가 사람 눈에 보이는 문서인가 (hwp_report.verify 재사용)
"""
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import requests

from modules import hwp_report

logger = logging.getLogger(__name__)

_TIMEOUT = float(os.getenv('HWP_NODE_TIMEOUT_MS', '20000')) / 1000

# 보고서가 쓰는 표기들. hwp_report가 만드는 형식과 맞춰 둔다.
_CAPTION_RE = re.compile(r'^Figure\s*(\d+)\.', re.IGNORECASE)
_MENTION_RE = re.compile(r'Fig(?:ure)?\.?\s*(\d+)', re.IGNORECASE)
_H1_RE = re.compile(r'^([IVX]+|[Ⅰ-Ⅻ])\.\s')
_H2_RE = re.compile(r'^(\d+)\.\s')

_ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7,
          'VIII': 8, 'IX': 9, 'X': 10,
          'Ⅰ': 1, 'Ⅱ': 2, 'Ⅲ': 3, 'Ⅳ': 4, 'Ⅴ': 5, 'Ⅵ': 6, 'Ⅶ': 7,
          'Ⅷ': 8, 'Ⅸ': 9, 'Ⅹ': 10}


def _finding(level: str, message: str, para: Optional[int] = None) -> Dict:
    item = {'level': level, 'message': message}
    if para is not None:
        item['para'] = para
    return item


def check_paragraphs(paragraphs: List[Dict]) -> List[Dict]:
    """문단 목록만 보고 할 수 있는 검사 전부. 네트워크 없이 순수 로직이다(테스트 대상)."""
    findings: List[Dict] = []

    captions: Dict[int, int] = {}      # 그림 번호 -> 캡션 문단
    mentions: Dict[int, int] = {}      # 그림 번호 -> 첫 언급 문단
    h1_values: List[int] = []
    seen_h1 = False
    empty_run = 0
    empty_run_start = 0

    for index, paragraph in enumerate(paragraphs):
        text = (paragraph.get('text') or '').strip()
        style = paragraph.get('style') or {}

        if not text:
            if empty_run == 0:
                empty_run_start = index
            empty_run += 1
            continue
        if empty_run >= 3:
            findings.append(_finding(
                'info', f'빈 문단이 {empty_run}개 이어져요. 줄이면 문서가 단단해 보여요.',
                empty_run_start))
        empty_run = 0

        caption = _CAPTION_RE.match(text)
        if caption:
            captions.setdefault(int(caption.group(1)), index)
        else:
            for number in _MENTION_RE.findall(text):
                mentions.setdefault(int(number), index)

        h1 = _H1_RE.match(text)
        if h1:
            seen_h1 = True
            value = _ROMAN.get(h1.group(1))
            if value:
                h1_values.append(value)
        elif _H2_RE.match(text) and not seen_h1 and index > 2:
            findings.append(_finding(
                'warn', f'큰 장(I. …)이 나오기 전에 소제목({text[:20]})이 먼저 나와요.',
                index))

        # 제목(문서 첫 문단)과 캡션은 가운데가 맞다. 그 밖의 긴 본문이 가운데면 어긋난 것.
        if (style.get('alignment') == 'center' and index > 1
                and not caption and len(text) > 40):
            findings.append(_finding(
                'info', f'본문 문단이 가운데 정렬이에요: "{text[:24]}…"', index))

    # 장 번호가 순서대로인가 (I → II → III …)
    for position in range(1, len(h1_values)):
        if h1_values[position] != h1_values[position - 1] + 1:
            findings.append(_finding(
                'warn',
                f'장 번호가 건너뛰어요: {h1_values[position - 1]} 다음에 '
                f'{h1_values[position]}이 나와요.'))
            break

    # 그림 번호와 본문 인용이 서로 맞는가.
    for number in sorted(set(captions) - set(mentions)):
        findings.append(_finding(
            'warn',
            f'Figure {number}이(가) 본문에서 한 번도 언급되지 않았어요. '
            f'"Fig {number}과 같이 …" 한 문장을 넣어 주면 그림이 글에 붙어요.',
            captions[number]))
    for number in sorted(set(mentions) - set(captions)):
        findings.append(_finding(
            'warn',
            f'본문이 Fig {number}을(를) 말하는데 그 그림(캡션)이 문서에 없어요.',
            mentions[number]))

    return findings


def inspect(path) -> Dict:
    """보고서를 열어 점검하고 {'ok', 'findings', 'render'}를 돌려줍니다."""
    base = (os.getenv('HWP_NODE_URL') or '').strip().rstrip('/')
    if not base:
        return {'ok': False, 'error': '점검용 서버가 꺼져 있어요.'}
    if not hwp_report.is_hwp(path):
        return {'ok': False,
                'error': 'HWP가 아닌 파일이라 점검할 수 없어요. 문서를 다시 만들어 보세요.'}

    headers = {}
    key = (os.getenv('HWP_NODE_API_KEY') or '').strip()
    if key:
        headers['X-API-Key'] = key

    session_id = None
    try:
        with requests.Session() as http:
            http.headers.update(headers)
            with open(path, 'rb') as handle:
                created = http.post(f'{base}/sessions', timeout=_TIMEOUT,
                                    files={'file': ('report.hwp', handle)})
            created.raise_for_status()
            session_id = created.json()['sessionId']

            document = http.get(f'{base}/sessions/{session_id}/document',
                                timeout=_TIMEOUT).json()
            paragraphs = [paragraph
                          for section in document.get('sections') or []
                          for paragraph in section.get('paragraphs') or []]
    except (requests.RequestException, ValueError, KeyError, OSError) as exc:
        logger.warning('[INSPECT] 문서 열기 실패: %s: %s', type(exc).__name__, exc)
        return {'ok': False, 'error': '문서를 여는 데 실패했어요.'}
    finally:
        if session_id:
            try:
                requests.delete(f'{base}/sessions/{session_id}',
                                headers=headers, timeout=_TIMEOUT)
            except requests.RequestException:
                pass

    findings = check_paragraphs(paragraphs)
    render = hwp_report.verify(Path(path))
    if not render.get('ok'):
        findings.insert(0, _finding(
            'warn', '첫 페이지를 그려 봤더니 글자가 안 보일 수 있어요. 문서를 다시 만들어 보세요.'))

    return {'ok': True, 'findings': findings, 'render': render,
            'paragraph_count': len(paragraphs)}
