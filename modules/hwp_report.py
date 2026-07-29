"""탐구 보고서를 진짜 HWP 파일로 만듭니다.

지금까지 보고서는 DOCX를 만들고 확장자만 .hwp로 바꿔 저장했습니다. 내려받아
한글에서 열면 열리긴 하지만, 우리 HWP 편집기(rhwp)는 그것을 열지 못합니다.
학생이 보고서를 편집기에서 이어 손볼 수 있으려면 실제 HWP여야 합니다.

문서 조립은 이미 쓰고 있는 hwp-node 사이드카에 맡깁니다.
    POST /sessions/blank      빈 문서
    POST /sessions/{id}/ops   문단마다 글자 넣고 줄 나누기
    GET  /sessions/{id}/export  완성된 HWP 바이트

사이드카가 없거나 실패하면 None을 돌려주고, 호출부가 기존 방식으로 넘어갑니다.
"""
import logging
import os
import re
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = float(os.getenv('HWP_NODE_TIMEOUT_MS', '20000')) / 1000

# 문단이 너무 많으면 조립에 그만큼 왕복이 생긴다. 보고서 한 편 분량으로 끊는다.
_MAX_PARAGRAPHS = 400


def _base_url() -> Optional[str]:
    url = (os.getenv('HWP_NODE_URL') or '').strip().rstrip('/')
    return url or None


def _headers() -> dict:
    key = (os.getenv('HWP_NODE_API_KEY') or '').strip()
    return {'X-API-Key': key} if key else {}


# 마크다운 표시는 한글 문서에서 글자 그대로 보이면 지저분하다.
# 서식으로 옮기는 건 나중 일이고, 지금은 읽는 데 방해되는 기호만 걷어낸다.
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)]+)\)')
_MD_MARK_RE = re.compile(r'\*\*|__|`')


def _plain(line: str) -> str:
    text = _MD_LINK_RE.sub(r'\1 (\2)', line)
    text = _MD_MARK_RE.sub('', text)
    text = re.sub(r'^#{1,6}\s*', '', text)      # 제목 기호
    text = re.sub(r'^\s*[-*]\s+', '· ', text)   # 목록 기호
    return text.rstrip()


# HWP 5.0은 MS 복합 문서(CFB) 컨테이너다. 이 여덟 바이트로 시작한다.
_CFB_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def is_hwp(path) -> bool:
    """이 파일이 편집기(rhwp)가 열 수 있는 진짜 HWP인지 봅니다.

    이름만 믿으면 안 된다. 확장자만 .hwp로 바꾼 DOCX가 실제로 만들어졌고,
    편집기는 그것을 zip으로 보고 HWPX로 읽으려다
    "필수 파일 누락: Contents/content.hpf"로 멈췄다. 내용을 보고 판단한다.
    """
    try:
        with open(path, 'rb') as handle:
            return handle.read(8) == _CFB_MAGIC
    except OSError:
        return False


def verify(path) -> Dict:
    """만들어진 문서를 다시 열어 사람 눈에 보이는 문서인지 확인합니다.

    글자 크기 단위가 어긋나면 '데이터는 있는데 아무것도 안 보이는' 문서가
    나온다(실제로 겪었다). 데이터 검사만으로는 그걸 못 잡으므로,
    첫 페이지를 실제로 그려 본문 글자가 보이는 크기(5px 이상)인지 본다.
    """
    base = _base_url()
    if not base:
        return {'ok': False, 'reason': '확인용 서버 없음'}

    session_id = None
    try:
        with requests.Session() as http:
            http.headers.update(_headers())
            with open(path, 'rb') as handle:
                created = http.post(f'{base}/sessions', timeout=_TIMEOUT,
                                    files={'file': ('report.hwp', handle)})
            created.raise_for_status()
            session_id = created.json()['sessionId']

            document = http.get(f'{base}/sessions/{session_id}/document',
                                timeout=_TIMEOUT).json()
            text_paragraphs = sum(
                1 for section in document.get('sections') or []
                for paragraph in section.get('paragraphs') or []
                if (paragraph.get('text') or '').strip())

            page = http.get(f'{base}/sessions/{session_id}/pages/0', timeout=_TIMEOUT)
            page.raise_for_status()
            sizes = [float(value) for value in
                     re.findall(r'font-size="([\d.]+)"', page.text)]
            visible = max(sizes) if sizes else 0.0

            ok = text_paragraphs >= 3 and visible >= 5.0
            return {'ok': ok, 'text_paragraphs': text_paragraphs,
                    'max_font_px': round(visible, 2)}
    except (requests.RequestException, ValueError, KeyError, OSError) as exc:
        return {'ok': False, 'reason': type(exc).__name__}
    finally:
        if session_id:
            try:
                requests.delete(f'{base}/sessions/{session_id}',
                                headers=_headers(), timeout=_TIMEOUT)
            except requests.RequestException:
                pass


# 본문에서 그림이 들어갈 자리 표시. 모델이 [FIGURE 1] 처럼 그 줄에 홀로 적는다.
_FIGURE_MARK_RE = re.compile(r'^\s*\[FIGURE\s*(\d+)\]\s*$', re.IGNORECASE)

# 마크다운 표의 행(| a | b |)과 구분선(|---|:--:|). 구분선은 셀이 아니다.
_TABLE_ROW_RE = re.compile(r'^\s*\|.*\|\s*$')
_TABLE_RULE_RE = re.compile(r'^\s*\|\s*:?-{2,}.*\|\s*$')

# 사이드카가 표 크기를 20×20으로 자른다(clampTableSize). 넘겨 봐야 잘리기만 한다.
_TABLE_MAX = 20


def _table_cells(row: str) -> List[str]:
    """| a | b | 한 줄을 셀 목록으로. 굵게(**) 같은 표시는 걷어낸다."""
    return [_plain(cell.strip()) for cell in row.strip().strip('|').split('|')]


def _lines(title: str, markdown: str) -> List[Dict]:
    """본문을 문단 계획으로 바꿉니다.

    각 항목: {'text': str, 'style': ..., 'figure': no|None, 'table': rows|None}
    그림·표 자리는 빈 문단으로 잡아 두고 나중에 채웁니다.

    마크다운 표는 진짜 표(create_table)로 만든다. 전에는 | 기호가 글자 그대로
    문서에 찍혔다 — 실험 데이터(측정값)가 문장으로만 남는 게 아까워서 표로 올린다.
    """
    plan: List[Dict] = []

    def put(text: str, style: str = 'body', figure=None, table=None):
        plan.append({'text': text, 'style': style, 'figure': figure, 'table': table})

    if title.strip():
        put(title.strip(), 'title')
        put('')

    rows: List[List[str]] = []          # 지금 모으는 중인 표의 행들

    def flush_table():
        if not rows:
            return
        # 열 수는 첫 행 기준으로 맞춘다. 모자란 셀은 빈 칸으로 채워야 표가 안 찌그러진다.
        cols = min(len(rows[0]), _TABLE_MAX)
        trimmed = [(row + [''] * cols)[:cols] for row in rows[:_TABLE_MAX]]
        put('', table=trimmed)
        rows.clear()

    for raw in (markdown or '').splitlines():
        if _TABLE_ROW_RE.match(raw):
            if not _TABLE_RULE_RE.match(raw):
                rows.append(_table_cells(raw))
            continue
        flush_table()
        mark = _FIGURE_MARK_RE.match(raw)
        if mark:
            put('', figure=int(mark.group(1)))
            continue
        style = 'body'
        if re.match(r'^\s*#\s', raw):
            style = 'h1'
        elif re.match(r'^\s*#{2,6}\s', raw):
            style = 'h2'
        text = _plain(raw)
        # 빈 줄이 여러 개 이어지면 문서에 빈 문단만 쌓인다. 하나로 줄인다.
        if not text and plan and not plan[-1]['text'] and plan[-1]['figure'] is None \
                and plan[-1]['table'] is None:
            continue
        put(text, style)
    flush_table()
    return plan[:_MAX_PARAGRAPHS]


def _figure_width_mm(natural_width_px: int, natural_height_px: int) -> float:
    """그림이 문서에 놓일 폭(mm)을 비율에 맞게 정합니다.

    폭만 고정(130mm)하면 세로로 긴 그림이 페이지를 통째로 삼킨다.
    - 높이가 110mm를 넘지 않도록 폭을 줄인다(본문 흐름 속에 들어갈 크기).
    - 작은 원본을 무리하게 늘리면 흐려지므로, 96dpi 기준 원본의 2배까지만 키운다.
    """
    width_px = max(1, natural_width_px)
    height_px = max(1, natural_height_px)

    width = 130.0
    max_height = 110.0
    if width * height_px / width_px > max_height:
        width = max_height * width_px / height_px

    natural_mm = width_px / 96 * 25.4
    width = min(width, natural_mm * 2)
    return round(max(width, 40.0), 1)


# 문단 종류별 글자 서식.
#
# fontSize는 pt가 아니라 HWP 원시 단위(pt × 100)다. 16을 넣으면 0.16pt가 되어
# 글자가 있어도 눈에 보이지 않는 문서가 나온다(실제로 그랬다).
# 빈 문서의 기본 글자 크기도 같은 이유로 깨져 있어서(11 = 0.11pt),
# 본문을 포함한 모든 문단에 크기를 명시해야 한다.
_CHAR_STYLE = {
    'title': {'fontSize': 1600, 'bold': True},
    'h1': {'fontSize': 1300, 'bold': True},
    'h2': {'fontSize': 1150, 'bold': True},
    'caption': {'fontSize': 900},
    'body': {'fontSize': 1100},
}

# 실제 공문서 코퍼스(기상청 보도자료 50건)에서 추출한 스타일 킷.
# 학생 보고서에 그 서체·크기 체계를 이식한다 — 있으면 쓰고, 없으면 기본값으로 산다.
_STYLE_KIT_PATH = 'data/hwp_corpus/kma_press/style_kit.json'
_KIT_ROLE = {'title': 'cover_title', 'h1': 'section_heading', 'h2': 'sub_heading',
             'caption': 'table_caption', 'body': 'body'}
_kit_styles_cache: Optional[Dict[str, Dict]] = None


def _styles_from_kit() -> Dict[str, Dict]:
    """스타일 킷의 서체·크기를 문단 종류별 서식으로 옮깁니다. 실패하면 기본값."""
    global _kit_styles_cache
    if _kit_styles_cache is not None:
        return _kit_styles_cache
    styles = {role: dict(props) for role, props in _CHAR_STYLE.items()}
    try:
        import json
        presets = json.load(open(_STYLE_KIT_PATH, encoding='utf-8'))['style_presets']
        for role, preset_name in _KIT_ROLE.items():
            char = (presets.get(preset_name) or {}).get('char') or {}
            if char.get('fontName'):
                styles[role]['fontName'] = char['fontName']
            # 킷의 fontSize도 pt×100. 캡션이 본문과 같은 크기면 구분이 안 되므로
            # 캡션만은 본문보다 작게 유지한다.
            if isinstance(char.get('fontSize'), int) and role != 'caption':
                styles[role]['fontSize'] = char['fontSize']
            if char.get('bold'):
                styles[role]['bold'] = True
    except (OSError, ValueError, KeyError) as exc:
        logger.info('[REPORT] 스타일 킷 없음, 기본 서식으로: %s', type(exc).__name__)
    _kit_styles_cache = styles
    return styles


def build_hwp(title: str, markdown: str, out_path,
              figures: Optional[List[Dict]] = None) -> Optional[str]:
    """보고서를 HWP로 저장하고 경로를 돌려줍니다. 못 만들면 None.

    figures는 report_figures.prepare()가 만든 목록입니다. 본문의 [FIGURE n] 자리에
    그림이 들어가고 바로 아래에 'Figure n. 캡션' 문단이 붙습니다.
    """
    base = _base_url()
    if not base:
        return None

    from modules import report_figures
    by_no = {figure['no']: figure for figure in (figures or [])}

    # 그림 자리 다음에 캡션 줄을 끼워 넣는다(문단 계획 단계에서).
    # 같은 그림은 문서에 한 번만 놓는다. 본문이 [FIGURE 1]을 두 번 적어도
    # 두 번째부터는 그림을 다시 놓지 않는다 — 재언급은 글의 "Fig 1"만으로 충분하다.
    plan: List[Dict] = []
    placed = set()
    for item in _lines(title, markdown):
        figure = by_no.get(item['figure']) if item['figure'] is not None else None
        if item['figure'] is not None and (not figure or item['figure'] in placed):
            continue   # 실패했거나 이미 놓인 그림 자리는 빈 문단으로도 남기지 않는다
        plan.append(item)
        if figure:
            placed.add(figure['no'])
            plan.append({'text': f"Figure {figure['no']}. {figure['caption']}".strip(),
                         'style': 'caption', 'figure': None, 'table': None})

    # 준비는 됐는데 본문이 [FIGURE n] 자리를 안 만든 그림은 문서 끝에 붙인다.
    # 찾아 놓은 그림을 조용히 버리는 것보다 낫다 — 학생이 편집기에서 옮기면 된다.
    for number in sorted(by_no):
        if number in placed:
            continue
        figure = by_no[number]
        plan.append({'text': '', 'style': 'body', 'figure': number, 'table': None})
        plan.append({'text': f"Figure {number}. {figure['caption']}".strip(),
                     'style': 'caption', 'figure': None, 'table': None})

    session_id = None
    try:
        with requests.Session() as http:
            http.headers.update(_headers())

            def op(payload: Dict) -> None:
                response = http.post(f'{base}/sessions/{session_id}/ops',
                                     timeout=_TIMEOUT, json=payload)
                response.raise_for_status()

            created = http.post(f'{base}/sessions/blank', timeout=_TIMEOUT)
            created.raise_for_status()
            session_id = created.json()['sessionId']

            # 1) 글 골격부터 세운다. 그림 자리는 빈 문단으로 남는다.
            for index, item in enumerate(plan):
                text = item['text']
                if text:
                    op({'kind': 'insert_text', 'sec': 0, 'para': index,
                        'offset': 0, 'text': text})
                    # 본문까지 전부 명시한다. 기본값에 맡기면 0.11pt짜리 문서가 된다.
                    styles = _styles_from_kit()
                    style = styles.get(item['style']) or styles['body']
                    op({'kind': 'set_char_format', 'sec': 0, 'para': index,
                        'start': 0, 'end': len(text), 'props': style})
                    # 정렬도 문단마다 명시한다. 빈 문서의 문단들은 기본 서식을 공유해서,
                    # 한 문단만 가운데로 바꾸면 지정하지 않은 문단들이 따라 움직인다.
                    # (키는 align이 아니라 alignment다 — wasm이 읽는 이름. align은 무시된다.)
                    op({'kind': 'set_para_format', 'sec': 0, 'para': index,
                        'props': {'alignment': 'center'
                                  if item['style'] in ('title', 'caption')
                                  else 'justify'}})
                op({'kind': 'split_paragraph', 'sec': 0, 'para': index,
                    'offset': len(text)})

            # 2) 그림을 제자리에 넣는다. 새 문단을 만들지 않으므로 번호가 밀리지 않는다.
            for index, item in enumerate(plan):
                figure = by_no.get(item['figure']) if item['figure'] is not None else None
                if not figure:
                    continue
                op({'kind': 'insert_image', 'sec': 0, 'para': index, 'offset': 0,
                    'dataBase64': report_figures.as_base64(figure),
                    'naturalWidthPx': figure['width'],
                    'naturalHeightPx': figure['height'],
                    'widthMm': _figure_width_mm(figure['width'], figure['height']),
                    'ext': figure['ext'],
                    'description': figure['caption']})
                op({'kind': 'set_para_format', 'sec': 0, 'para': index,
                    'props': {'alignment': 'center'}})

            # 3) 표는 맨 마지막에, 뒤에서부터 놓는다. 표 하나가 문단을 하나
            #    늘리는 것을 실측했다 — 앞에서부터 놓으면 뒤 표의 번호가 다 밀린다.
            for index in range(len(plan) - 1, -1, -1):
                rows = plan[index].get('table')
                if not rows:
                    continue
                created = http.post(
                    f'{base}/sessions/{session_id}/ops', timeout=_TIMEOUT,
                    json={'kind': 'create_table', 'sec': 0, 'para': index,
                          'offset': 0, 'rows': len(rows), 'cols': len(rows[0]),
                          'cells': rows})
                created.raise_for_status()
                anchor = (created.json().get('data') or {})
                # 머리글 행은 굵게. 어떤 열이 무엇인지 한눈에 갈리게 한다.
                for col in range(len(rows[0])):
                    if not rows[0][col]:
                        continue
                    op({'kind': 'set_char_format_in_cell', 'sec': 0,
                        'para': anchor.get('paraIdx', index),
                        'controlIdx': anchor.get('controlIdx', 0),
                        'cellIdx': col, 'cellPara': 0,
                        'start': 0, 'end': len(rows[0][col]),
                        'props': {'bold': True}})

            exported = http.get(f'{base}/sessions/{session_id}/export', timeout=_TIMEOUT)
            exported.raise_for_status()
            if not exported.content:
                raise ValueError('빈 파일')

            with open(out_path, 'wb') as handle:
                handle.write(exported.content)
            return str(out_path)
    except (requests.RequestException, ValueError, KeyError, OSError) as exc:
        # 이유까지 남긴다. 예전에는 예외 이름만 찍어서, 사이드카가 죽어 있는지
        # 문서 조립이 틀렸는지 로그만 보고는 가릴 수 없었다.
        logger.warning('[REPORT] HWP 조립 실패(%s → DOCX): %s: %s',
                       base, type(exc).__name__, exc)
        return None
    finally:
        if session_id:
            # 세션을 남기면 사이드카 메모리에 문서가 계속 떠 있는다.
            try:
                requests.delete(f'{base}/sessions/{session_id}',
                                headers=_headers(), timeout=_TIMEOUT)
            except requests.RequestException:
                pass
