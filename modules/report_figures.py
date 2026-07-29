"""보고서에 들어갈 그림(Figure)을 준비합니다.

두 종류가 있습니다.
  chart — Codex가 쓴 matplotlib 코드를 실행해 그래프 PNG를 만든다.
          수치는 학생이 대화에서 말한 것만 쓰라고 프롬프트가 강제한다.
  image — Codex가 웹 검색으로 실제 확인한 이미지 주소를 내려받는다.
          지어낸 주소는 내려받기가 실패하므로 여기서 자연히 걸러진다.

어느 쪽이든 실패하면 그 그림만 조용히 빠진다. 그림 하나 때문에
보고서 생성이 통째로 실패하면 안 된다.
"""
import base64
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_CHART_TIMEOUT_SECONDS = float(os.getenv('CHART_TIMEOUT_MS', '30000')) / 1000
_IMAGE_TIMEOUT_SECONDS = 15
_MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_FIGURES = 8

# 모델 코드 앞에 붙는 준비 코드. 화면 없는 백엔드와 한글 폰트를 강제한다.
# 이게 없으면 서버에서 GUI 백엔드를 열려다 죽거나, 한글이 전부 네모로 나온다.
_CHART_PREAMBLE = """\
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family'] = ['AppleGothic', 'NanumGothic', 'Malgun Gothic', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False
OUT_PATH = {out_path!r}
"""

# 그래프 코드가 마지막에 저장을 잊는 경우가 흔하다. 저장이 안 됐으면 우리가 저장한다.
_CHART_EPILOGUE = """
import os as _os
if not _os.path.exists(OUT_PATH):
    plt.savefig(OUT_PATH, dpi=150, bbox_inches='tight')
"""


def _png_size(data: bytes) -> Optional[tuple]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:  # noqa: BLE001 - 이미지가 아니면 그림으로 못 쓴다는 뜻이다.
        return None


def render_chart(code: str, workdir: Path) -> Optional[Dict[str, Any]]:
    """matplotlib 코드를 별도 프로세스에서 돌려 PNG를 만듭니다.

    모델이 만든 코드라 이 프로세스 안에서 exec하지 않습니다. 자식 프로세스를
    -I(격리 모드)로 띄우고, 제한 시간을 걸고, 작업 폴더를 임시 디렉터리로 둡니다.
    """
    code = (code or '').strip()
    if not code:
        return None

    out_path = workdir / f'chart_{os.urandom(4).hex()}.png'
    script = workdir / f'{out_path.stem}.py'
    script.write_text(
        _CHART_PREAMBLE.format(out_path=str(out_path)) + code + _CHART_EPILOGUE,
        encoding='utf-8')

    try:
        run = subprocess.run(
            [sys.executable, '-I', str(script)],
            cwd=str(workdir), timeout=_CHART_TIMEOUT_SECONDS,
            capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        logger.info('[FIGURE] 그래프 코드가 제한 시간을 넘겨 버립니다.')
        return None
    finally:
        script.unlink(missing_ok=True)

    if run.returncode != 0 or not out_path.exists():
        logger.info('[FIGURE] 그래프 코드 실패: %s', (run.stderr or '')[-300:])
        return None

    data = out_path.read_bytes()
    size = _png_size(data)
    if not size:
        return None
    return {'data': data, 'width': size[0], 'height': size[1], 'ext': 'png'}


# 낯선 User-Agent는 CDN·이미지 호스트가 자주 막는다. 브라우저처럼 보이게 요청한다.
_BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'),
    'Accept': 'image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5',
}


def fetch_image(url: str) -> Optional[Dict[str, Any]]:
    """웹 이미지를 내려받아 진짜 이미지인지 확인합니다.

    바이트를 문서 안에 심는 것이라 http 주소여도 된다(화면과 달리 혼합 콘텐츠
    문제가 없다). 다만 https로 먼저 올려 시도한다 — 요즘은 그쪽이 살아 있는
    경우가 대부분이다.
    """
    url = str(url or '').strip()
    if url.startswith('http://'):
        return (fetch_image('https://' + url[7:])
                or _fetch_image_exact(url))
    return _fetch_image_exact(url)


def _fetch_image_exact(url: str) -> Optional[Dict[str, Any]]:
    if not url.startswith(('https://', 'http://')):
        return None
    headers = dict(_BROWSER_HEADERS)
    try:
        # 핫링크 차단은 대부분 Referer를 본다. 그 이미지가 있는 사이트에서 온 것처럼 보낸다.
        origin = url.split('/', 3)
        headers['Referer'] = f'{origin[0]}//{origin[2]}/'
    except IndexError:
        pass
    try:
        response = requests.get(url, timeout=_IMAGE_TIMEOUT_SECONDS, headers=headers)
    except requests.RequestException:
        return None
    if not response.ok or len(response.content) > _MAX_IMAGE_BYTES:
        logger.info('[FIGURE] 이미지 내려받기 실패(%s): HTTP %s',
                    url[:60], response.status_code if response is not None else '?')
        return None
    size = _png_size(response.content)
    if not size:
        logger.info('[FIGURE] 이미지가 아닌 응답: %s',
                    response.headers.get('Content-Type', '?'))
        return None
    ext = 'png'
    content_type = response.headers.get('Content-Type', '').lower()
    if 'jpeg' in content_type or 'jpg' in content_type or url.lower().endswith(('.jpg', '.jpeg')):
        ext = 'jpg'
    return {'data': response.content, 'width': size[0], 'height': size[1], 'ext': ext}


def _search_fallback(query: str) -> Optional[Dict[str, Any]]:
    """모델이 준 주소가 죽었을 때, 검색으로 대신 찾은 이미지를 내려받습니다."""
    if not (query or '').strip():
        return None
    from modules import web_search
    if not web_search.available():
        return None
    for candidate in web_search.search_images(query.strip()):
        image = fetch_image(candidate.get('image_url') or '')
        if image:
            return image
    return None


def prepare(figures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """모델이 요청한 그림 목록을 실제 이미지 바이트로 바꿉니다.

    돌려주는 각 항목: {no, caption, data, width, height, ext}
    만들지 못한 그림은 목록에서 빠집니다.
    """
    import hashlib

    made: List[Dict[str, Any]] = []
    seen_bytes = set()
    with tempfile.TemporaryDirectory(prefix='report_figures_') as tmp:
        workdir = Path(tmp)
        for figure in (figures or [])[:MAX_FIGURES]:
            if not isinstance(figure, dict):
                continue
            kind = figure.get('kind')
            if kind == 'chart':
                image = render_chart(figure.get('python_code') or '', workdir)
            elif kind == 'image':
                image = fetch_image(figure.get('image_url') or '')
                if not image:
                    # 모델이 준 주소가 죽는 일은 흔하다. 검색어가 있으면 대신 찾아본다.
                    image = _search_fallback(figure.get('image_query')
                                             or figure.get('caption') or '')
            else:
                image = None
            if not image:
                continue
            # 같은 자료가 번호만 달리해 두 번 계획되는 일이 있다. 내용이 같으면 한 번만 싣는다.
            digest = hashlib.sha1(image['data']).hexdigest()
            if digest in seen_bytes:
                logger.info('[FIGURE] 같은 이미지가 두 번 계획되어 하나만 싣습니다.')
                continue
            seen_bytes.add(digest)
            made.append({
                'no': int(figure.get('no') or (len(made) + 1)),
                'caption': re.sub(r'\s+', ' ', str(figure.get('caption') or '')).strip(),
                **image,
            })
    return made


def as_base64(figure: Dict[str, Any]) -> str:
    return base64.b64encode(figure['data']).decode('ascii')
