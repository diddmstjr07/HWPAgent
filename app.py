#!/usr/bin/env python3
"""
HWP Agent Web App - ChatGPT Canvas 스타일의 실시간 문서 편집기
"""
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse, FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import os
import json
import base64
import shutil
import pickle
import secrets
import hmac
import hashlib
import ipaddress
import re
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from collections import deque
from modules import HWPAgent
from modules.docx_handler import DOCXHandler
from modules.pdf_handler import PDFHandler
from modules.format_adjuster import FormatAdjuster
from modules.image_searcher import ImageSearcher
from modules.riroschool_crawler import RiroSchoolCrawler
from modules.template_parser import extract_template_text, extract_template_html, SUPPORTED_TEMPLATE_EXTENSIONS
from modules.preset_templates import DOCUMENT_PRESETS
from urllib.parse import urlparse, parse_qs, urlencode
import fitz  # PyMuPDF
import time
import requests
import uvicorn
from dotenv import load_dotenv
from database import db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from bs4 import BeautifulSoup
from xml.sax.saxutils import escape as xml_escape

try:
    import psutil
except Exception:
    psutil = None

def _load_env() -> None:
    env_root = os.getenv("HWP_AGENT_ROOT")
    candidates = []
    if env_root:
        candidates.append(Path(env_root) / ".env")
    candidates.append(Path(__file__).resolve().parent / ".env")
    candidates.append(Path.cwd() / ".env")

    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path, override=True)
            return
    load_dotenv(override=True)


_load_env()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
MIGRATING_TO_V2_DETAIL = "Migrating to v2"

LOGO_GRADIENT_START = (0, 194, 255)
LOGO_GRADIENT_END = (255, 179, 71)

DOC_AGENT_ART = r""" ██████╗   ██████╗   ██████╗    
 ██╔══██╗ ██╔═══██╗ ██╔════╝    
 ██║  ██║ ██║   ██║ ██║         
 ██║  ██║ ██║   ██║ ██║         
 ██████╔╝ ╚██████╔╝ ╚██████╗    
 ╚═════╝   ╚═════╝   ╚═════╝    

  █████╗   ██████╗  ███████╗ ███╗   ██╗ ████████╗
 ██╔══██╗ ██╔════╝  ██╔════╝ ████╗  ██║ ╚══██╔══╝
 ███████║ ██║  ███╗ █████╗   ██╔██╗ ██║    ██║   
 ██╔══██║ ██║   ██║ ██╔══╝   ██║╚██╗██║    ██║   
 ██║  ██║ ╚██████╔╝ ███████╗ ██║ ╚████║    ██║   
 ╚═╝  ╚═╝  ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝    ╚═╝   
"""

def _apply_gradient(text: str, start: tuple[int, int, int], end: tuple[int, int, int]) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    width = max(len(line) for line in lines) or 1
    colored_lines = []
    for line in lines:
        if not line:
            colored_lines.append("")
            continue
        out = []
        for i, ch in enumerate(line):
            ratio = i / (width - 1) if width > 1 else 0
            r = int(start[0] + (end[0] - start[0]) * ratio)
            g = int(start[1] + (end[1] - start[1]) * ratio)
            b = int(start[2] + (end[2] - start[2]) * ratio)
            out.append(f"\033[38;2;{r};{g};{b}m{ch}")
        colored_lines.append("".join(out))
    return "\n".join(colored_lines) + "\033[0m"

CLI_BANNER = _apply_gradient(DOC_AGENT_ART, LOGO_GRADIENT_START, LOGO_GRADIENT_END)

app = FastAPI(docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json")
APP_SECRET = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
DEFAULT_ADMIN_ACCESS_TOKEN = "5avD9wIGFW6Pdl-Oqhx3-vB03Ei4Xd6Jig0w1XWIEe8"
DEFAULT_ADMIN_SIGNATURE_SECRET = "Y4hAErFTUX8ZSrkcqi13O3tpsALWN0PLAmuDfR3Xo1UPyylDrAKJXbxzdzC0cR9E"
DEFAULT_ADMIN_APP_TOKEN = "G9zPjvkdeQQa3kLaJwlhHNamz0UgkN4lMBj-TWXrCxI"

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")
STATIC_DIR = Path("static")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc: Exception):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

BLOCKED_IPS = {"61.52.38.120"}

def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

TEST_MODE_ENABLED = _env_flag("TEST_MODE", False)
TEST_MODE_ALLOWED_NETWORKS = [
    ipaddress.ip_network("192.168.0.0/24"),
]
APP_TOKEN_COOKIE_NAME = "app_token"
ANALYTICS_ENABLED = _env_flag("ANALYTICS_ENABLED", True)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded and request.client and _is_private_ip(request.client.host):
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""

def _is_local_request(request: Request) -> bool:
    client_ip = _get_client_ip(request)
    if not client_ip:
        return False
    try:
        return ipaddress.ip_address(client_ip).is_loopback
    except ValueError:
        return client_ip in {"localhost"}

def _get_session_id(request: Request) -> Optional[str]:
    if not hasattr(request, "session"):
        return None
    session_id = request.session.get("sid")
    if not session_id:
        session_id = secrets.token_urlsafe(16)
        request.session["sid"] = session_id
    return session_id

def _normalize_referrer(request: Request) -> str:
    raw = (request.headers.get("referer") or request.headers.get("referrer") or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw[:200]
    if not parsed.scheme or not parsed.netloc:
        return raw[:200]
    host = (request.headers.get("host") or "").lower()
    if parsed.netloc.lower() == host:
        ref_path = parsed.path or "/"
        if parsed.query:
            ref_path += f"?{parsed.query}"
        return ref_path[:200]
    return f"{parsed.scheme}://{parsed.netloc}"[:200]

def _should_log_page_view(request: Request, response: Response) -> bool:
    if request.method != "GET":
        return False
    path = request.url.path
    if (
        path.startswith("/static/")
        or path.startswith("/api/")
        or path.startswith("/icons/")
        or path == "/service-worker.js"
        or path in {"/favicon.ico", "/manifest.json"}
    ):
        return False
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" not in accept and "application/xhtml+xml" not in accept:
        return False
    return response.status_code >= 200

def _log_analytics_event(
    request: Request,
    event_type: str,
    *,
    user_id: Optional[str] = None,
    path: Optional[str] = None,
    referrer: Optional[str] = None,
    status_code: Optional[int] = None,
) -> None:
    if not ANALYTICS_ENABLED:
        return
    try:
        current_user = _get_current_user(request)
        resolved_user = user_id or (current_user.id if current_user else None)
        session_id = _get_session_id(request)
        db.log_analytics_event(
            event_type=event_type,
            user_id=resolved_user,
            session_id=session_id,
            path=path or request.url.path,
            referrer=referrer if referrer is not None else _normalize_referrer(request),
            ip=_get_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:200],
            status_code=status_code,
        )
    except Exception as exc:
        print(f"[ANALYTICS] log failed: {exc}")

def _is_test_mode_allowed(request: Request) -> bool:
    client_ip = _get_client_ip(request)
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip in {"localhost"}
    if ip.is_loopback:
        return True
    for network in TEST_MODE_ALLOWED_NETWORKS:
        if ip.version == network.version and ip in network:
            return True
    return False

def _parse_env_list(name: str) -> List[str]:
    value = os.getenv(name, "")
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]

def _get_current_user(request: Request):
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        return None
    return db.get_user(user_id)

def _login_user(request: Request, user) -> None:
    if hasattr(request, "session"):
        request.session["user_id"] = user.id

def _logout_user(request: Request) -> None:
    if hasattr(request, "session"):
        request.session.pop("user_id", None)

async def _get_json(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
        if isinstance(payload, dict):
            return payload
        return {}
    except Exception:
        return {}

def _json_response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code)

def _expected_app_tokens() -> List[str]:
    expected_env = os.getenv("ADMIN_APP_TOKEN")
    return [token for token in {expected_env, DEFAULT_ADMIN_APP_TOKEN} if token]

def _app_token_matches(provided: Optional[str]) -> bool:
    if not provided:
        return False
    expected_tokens = _expected_app_tokens()
    return any(secrets.compare_digest(provided, token) for token in expected_tokens)

def _admin_app_token_check(request: Request) -> tuple[bool, str]:
    expected_tokens = _expected_app_tokens()
    if not expected_tokens:
        return True, "App token not required"
    provided = request.headers.get("X-App-Token") or request.cookies.get(APP_TOKEN_COOKIE_NAME)
    if not provided:
        print(f"[ADMIN] app token missing: expected_set={bool(expected_tokens)} provided=None")
        return False, "Missing app token header"
    if not _app_token_matches(provided):
        print(f"[ADMIN] app token mismatch: provided={provided}")
        return False, "App token mismatch"
    return True, "OK"

def _is_private_ip(value: str) -> bool:
    if not value:
        return False
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local)

def _admin_access_check(request: Request) -> tuple[bool, str]:
    client_ip = _get_client_ip(request)
    if not client_ip:
        return False, "Client IP missing"
    if not _is_private_ip(client_ip):
        return False, "Client IP not allowlisted"
    app_allowed, app_reason = _admin_app_token_check(request)
    if not app_allowed:
        return False, app_reason
    return True, "OK"

def _admin_access_allowed(request: Request) -> bool:
    return _admin_access_check(request)[0]

def _require_admin_access(request: Request) -> None:
    allowed, reason = _admin_access_check(request)
    if not allowed:
        print(f"[ADMIN] access denied: {reason}")
        raise HTTPException(status_code=404, detail="Not found")

def _resolve_admin_log_path() -> Optional[Path]:
    explicit = os.getenv("ADMIN_LOG_PATH") or os.getenv("APP_LOG_PATH")
    if explicit:
        return Path(explicit)
    candidates = [Path("app.log"), Path("app_background.log")]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None

def _is_safe_identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value or ""))

def _get_table_columns(table: str) -> List[str]:
    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f'PRAGMA table_info("{table}")')
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [row["name"] for row in rows]

def _list_db_tables() -> List[str]:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()
    return tables

def _fetch_table_rows(table: str, limit: int, offset: int) -> Dict[str, Any]:
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(f'SELECT * FROM "{table}" LIMIT ? OFFSET ?', (limit, offset))
    rows = [dict(row) for row in cursor.fetchall()]
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    conn.close()
    return {"columns": columns, "rows": rows}

def _build_oauth_redirect_uri(request: Request, provider: str) -> str:
    explicit = os.getenv(f"{provider.upper()}_REDIRECT_URI")
    if explicit:
        return explicit
    public_base = os.getenv("PUBLIC_BASE_URL")
    if public_base:
        path = app.url_path_for('social_callback', provider=provider)
        return public_base.rstrip("/") + str(path)
    return str(request.url_for('social_callback', provider=provider))

def _is_safe_redirect(target: Optional[str]) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return False
    return target.startswith("/")


@app.middleware("http")
async def block_blocklisted_ips(request: Request, call_next):
    client_ip = _get_client_ip(request)
    if client_ip in BLOCKED_IPS:
        return Response(status_code=403)
    return await call_next(request)

@app.middleware("http")
async def docs_local_gate(request: Request, call_next):
    path = request.url.path
    if path == "/openapi.json" or path.startswith("/docs") or path.startswith("/redoc"):
        client_ip = _get_client_ip(request)
        if not _is_private_ip(client_ip):
            return Response(status_code=404)
    return await call_next(request)

@app.middleware("http")
async def app_token_cookie_bridge(request: Request, call_next):
    response = await call_next(request)
    provided = request.headers.get("X-App-Token")
    if _app_token_matches(provided):
        secure_cookie = request.url.scheme == "https"
        response.set_cookie(
            APP_TOKEN_COOKIE_NAME,
            provided,
            httponly=True,
            secure=secure_cookie,
            samesite="Lax",
        )
    return response

@app.middleware("http")
async def ready_gate(request: Request, call_next):
    if not TEST_MODE_ENABLED:
        return await call_next(request)

    path = request.url.path
    if (
        path == "/ready"
        or path.startswith("/ready/")
        or path.startswith("/static/")
        or path.startswith("/icons/")
        or path == "/service-worker.js"
        or path in {"/favicon.ico", "/manifest.json"}
    ):
        return await call_next(request)

    if _is_test_mode_allowed(request):
        return await call_next(request)

    return RedirectResponse(url="/ready", status_code=302)

@app.middleware("http")
async def analytics_page_view(request: Request, call_next):
    response = await call_next(request)
    if ANALYTICS_ENABLED and _should_log_page_view(request, response):
        _log_analytics_event(
            request,
            "page_view",
            status_code=response.status_code,
        )
    return response

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR = OUTPUT_DIR / "templates"
FONT_DIR = OUTPUT_DIR / "fonts"
IMAGE_DIR = OUTPUT_DIR / "images"
TEMPLATE_HTML_DIR = OUTPUT_DIR / "templates_html"
TEMPLATE_LIBRARY_DIR = Path("template_library")
TEMPLATE_DIR.mkdir(exist_ok=True)
FONT_DIR.mkdir(exist_ok=True)
IMAGE_DIR.mkdir(exist_ok=True)
TEMPLATE_HTML_DIR.mkdir(exist_ok=True)
TEMPLATE_LIBRARY_DIR.mkdir(exist_ok=True)
IMAGE_CACHE_DIR = IMAGE_DIR / "cache"
IMAGE_CACHE_DIR.mkdir(exist_ok=True)
HWPX_SESSION_ROOT = Path("temp")
HWPX_SESSION_ROOT.mkdir(exist_ok=True)


def _hwpx_session_dir(session_id: str) -> Path:
    return HWPX_SESSION_ROOT / session_id


def _hwpx_manager_path(session_id: str) -> Path:
    return _hwpx_session_dir(session_id) / "mgr.pkl"


def _hwpx_extract_dir(session_id: str) -> Path:
    return _hwpx_session_dir(session_id) / "hwpx"


def _convert_hwp_to_hwpx(hwp_path: Path, hwpx_path: Path) -> None:
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


def ensure_default_fonts():
    for preset in FONT_PRESETS:
        target = FONT_DIR / preset['filename']
        if target.exists():
            continue
        try:
            response = requests.get(preset['url'], timeout=45)
            response.raise_for_status()
            target.write_bytes(response.content)
        except Exception:
            pass


def list_available_fonts() -> List[Dict[str, Any]]:
    primary_font = DEFAULT_STYLE_CONFIG['font_name']
    fonts: List[Dict[str, Any]] = [{
        'id': PRIMARY_FONT_ID,
        'display_name': f"{primary_font} (기본)",
        'docx_name': primary_font,
        'docx_english_name': DEFAULT_STYLE_CONFIG.get('font_name_english', primary_font),
        'font_path': '',
        'source': 'system',
        'downloaded': True
    }]

    preset_paths = set()
    for preset in FONT_PRESETS:
        target = FONT_DIR / preset['filename']
        downloaded = target.exists()
        entry = {
            'id': preset['id'],
            'display_name': preset['display_name'],
            'docx_name': preset['docx_name'],
            'docx_english_name': preset.get('docx_name', preset['display_name']),
            'font_path': str(target) if downloaded else '',
            'source': 'preset',
            'downloaded': downloaded
        }
        fonts.append(entry)
        if downloaded:
            try:
                preset_paths.add(target.resolve())
            except Exception:
                pass

    for font_file in FONT_DIR.glob('*'):
        if not font_file.is_file():
            continue
        try:
            resolved = font_file.resolve()
        except Exception:
            resolved = None
        if resolved and resolved in preset_paths:
            continue
        fonts.append({
            'id': font_file.stem,
            'display_name': font_file.stem,
            'docx_name': font_file.stem,
            'docx_english_name': font_file.stem,
            'font_path': str(font_file),
            'source': 'uploaded',
            'downloaded': True
        })
    return fonts

FONT_PRESETS: List[Dict[str, str]] = [
    {
        'id': 'noto-sans-kr',
        'display_name': 'Noto Sans KR',
        'docx_name': 'Noto Sans KR',
        'filename': 'NotoSansKR-Regular.otf',
        'url': 'https://github.com/notofonts/noto-cjk-kr/raw/main/OTF/NotoSansCJKkr-Regular.otf'
    },
    {
        'id': 'noto-serif-kr',
        'display_name': 'Noto Serif KR',
        'docx_name': 'Noto Serif KR',
        'filename': 'NotoSerifKR-Regular.otf',
        'url': 'https://github.com/notofonts/noto-cjk-kr/raw/main/OTF/NotoSerifCJKkr-Regular.otf'
    },
    {
        'id': 'pretendard',
        'display_name': 'Pretendard',
        'docx_name': 'Pretendard',
        'filename': 'Pretendard-Regular.otf',
        'url': 'https://github.com/orioncactus/pretendard/raw/main/packages/pretendard/dist/public/static/Pretendard-Regular.otf'
    },
    {
        'id': 'gothic-a1',
        'display_name': 'Gothic A1',
        'docx_name': 'Gothic A1',
        'filename': 'GothicA1-Regular.ttf',
        'url': 'https://github.com/google/fonts/raw/main/ofl/gothica1/GothicA1-Regular.ttf'
    }
]

EXPORT_FORMATS: List[Dict[str, Any]] = [
    {
        'id': 'docx',
        'label': 'Microsoft Word (.docx)',
        'extension': '.docx',
        'description': '워드/한글에서 모두 열 수 있는 기본 형식',
        'default': True
    },
    {
        'id': 'hwp',
        'label': '한글 (.hwp)',
        'extension': '.hwp',
        'description': '한글 워드프로세서 최적화 형식'
    },
    {
        'id': 'pdf',
        'label': 'PDF (.pdf)',
        'extension': '.pdf',
        'description': '읽기 전용 배포용 문서'
    }
]

DEFAULT_STYLE_CONFIG: Dict[str, Any] = {
    'font_name': '함초롬바탕',
    'font_name_english': 'HCR Batang',
    'heading_font_name': '함초롬바탕',
    'title_font_name': '함초롬바탕',
    'font_size': 11,
    'title_size': 22,
    'heading_level1_size': 16,
    'heading_level2_size': 14,
    'heading_level3_size': 13,
    'line_spacing': 1.3,
    'paragraph_spacing': 6,
    'margin_top': 2.5,
    'margin_bottom': 2.5,
    'margin_left': 2.5,
    'margin_right': 2.5,
    'font_file_path': '',
    'heading_font_file_path': '',
    'title_font_file_path': '',
    'font_file_id': '',
    'heading_font_file_id': '',
    'title_font_file_id': '',
    'font_id': '',
    'prepared_by': os.getenv('DOCUMENT_PREPARED_BY', 'HWP Agent AI'),
    'organization': os.getenv('DOCUMENT_ORGANIZATION', 'HWP Agent Lab'),
    'treat_images_as_text': False,
    'image_placeholder_text': '※ 참고 이미지: {keyword}'
}


PRIMARY_FONT_ID = f"primary-{DEFAULT_STYLE_CONFIG['font_name']}"
DEFAULT_STYLE_CONFIG['font_id'] = PRIMARY_FONT_ID

if os.environ.get("SKIP_FONT_DOWNLOAD") != "1":
    ensure_default_fonts()
else:
    logger.info("[startup] SKIP_FONT_DOWNLOAD=1 - skipping font bootstrap")


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _resolve_uploaded_font_path(font_path: str) -> Optional[str]:
    try:
        resolved = Path(font_path).expanduser().resolve()
        fonts_root = FONT_DIR.resolve()
        resolved.relative_to(fonts_root)
        return str(resolved)
    except Exception:
        return None


def _save_image_from_data_url(data_url: str, destination: str) -> Optional[str]:
    if not data_url:
        return None
    try:
        if ',' in data_url:
            _, encoded = data_url.split(',', 1)
        else:
            encoded = data_url
        binary = base64.b64decode(encoded)
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(binary)
        print(f"[IMAGE] Saved from data URL -> {dest_path}")
        return str(dest_path)
    except Exception as exc:
        print(f"[IMAGE] Failed to decode data URL: {exc}")
        return None


def _download_backend_image(keyword: str, base_path: str, max_alternatives: int = 3) -> Optional[str]:
    try:
        print(f"[IMAGE] Backend search fallback for: {keyword}")
        results = image_searcher.search_images_google(keyword, count=max_alternatives)
        base = Path(base_path)
        for idx, entry in enumerate(results):
            candidate_path = base if idx == 0 else base.with_stem(f"{base.stem}_alt{idx+1}")
            downloaded = image_searcher.download_image(
                entry.get('url'),
                str(candidate_path),
                max_width=1200
            )
            if downloaded:
                print(f"[IMAGE] ✅ Backend downloaded: {keyword} -> {downloaded}")
                return downloaded
    except Exception as exc:
            print(f"[IMAGE] Backend fallback failed for {keyword}: {exc}")
    return None


def _copy_local_image(src: str, dest: str) -> Optional[str]:
    """캐시된 이미지가 있으면 복사"""
    try:
        src_path = Path(src)
        dest_path = Path(dest)
        if not src_path.exists():
            return None
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        print(f"[IMAGE] Copied cached image -> {dest_path}")
        return str(dest_path)
    except Exception as exc:
        print(f"[IMAGE] Failed to copy cached image: {exc}")
        return None


def _prepare_image_preview(keyword: str, url: str, index: int = 0) -> Dict[str, str]:
    """검색된 이미지를 서버 측에서 미리 다운로드/인코딩하여 브라우저 CORS 문제를 우회"""
    result = {"local_path": "", "data": ""}
    if not url:
        return result
    try:
        safe_keyword = secure_filename(keyword) or "image"
        hash_suffix = abs(hash(url)) % 100000
        cache_filename = f"{safe_keyword}_{index}_{hash_suffix}.jpg"
        cache_path = IMAGE_CACHE_DIR / cache_filename
        saved = image_searcher.download_image(
            url,
            str(cache_path),
            max_width=1200,
            allow_fallback=False
        )
        if saved and Path(saved).exists():
            encoded = base64.b64encode(Path(saved).read_bytes()).decode("utf-8")
            result["local_path"] = saved
            result["data"] = f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:
        print(f"[IMAGE] Preview cache failed for {keyword}: {exc}")
    return result


def _extract_html_paragraphs(html_content: str) -> List[str]:
    soup = BeautifulSoup(html_content or "", "html.parser")
    root = soup.body if soup.body else soup

    for tag in root.find_all(["script", "style"]):
        tag.decompose()

    for br in root.find_all("br"):
        br.replace_with("\n")

    for li in root.find_all("li"):
        li.insert_before("- ")

    for table in root.find_all("table"):
        table_lines: List[str] = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if cells:
                table_lines.append(" | ".join(cells))
        table.replace_with("\n".join(table_lines))

    text = root.get_text("\n")
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


def _build_hwpx_xml(paragraphs: List[str], title: str) -> str:
    lines: List[str] = []
    clean_title = (title or "").strip()
    if clean_title and (not paragraphs or paragraphs[0] != clean_title):
        lines.append(clean_title)
    lines.extend(paragraphs)

    body = "\n".join(
        f"  <hp:p><hp:run><hp:t>{xml_escape(text)}</hp:t></hp:run></hp:p>"
        for text in lines
        if text
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/section">\n'
        f"{body}\n"
        "</hp:section>\n"
    )


def _save_hwpx_xml(title: str, content: str, is_html_content: bool) -> str:
    if is_html_content:
        paragraphs = _extract_html_paragraphs(content)
    else:
        lines = [line.strip() for line in (content or "").splitlines()]
        paragraphs = [line for line in lines if line]

    hwpx_xml = _build_hwpx_xml(paragraphs, title)
    safe_title = (title or "document").strip() or "document"
    safe_title = safe_title.replace("/", "_").replace("\\", "_")
    file_path = OUTPUT_DIR / f"{safe_title}_hwpx.xml"
    file_path.write_text(hwpx_xml, encoding="utf-8")
    return str(file_path)


def _get_font_entry_by_id(font_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not font_id:
        return None
    normalized = str(font_id).strip()
    if not normalized:
        return None
    if normalized == PRIMARY_FONT_ID:
        return {
            'id': PRIMARY_FONT_ID,
            'docx_name': DEFAULT_STYLE_CONFIG['font_name'],
            'docx_english_name': DEFAULT_STYLE_CONFIG.get('font_name_english', DEFAULT_STYLE_CONFIG['font_name']),
            'font_path': ''
        }
    for preset in FONT_PRESETS:
        if preset['id'] == normalized:
            target = FONT_DIR / preset['filename']
            return {
                'id': normalized,
                'docx_name': preset['docx_name'],
                'docx_english_name': preset.get('docx_name', preset['display_name']),
                'font_path': str(target) if target.exists() else ''
            }
    for font_file in FONT_DIR.glob('*'):
        if not font_file.is_file():
            continue
        if font_file.stem == normalized or font_file.name == normalized:
            return {
                'id': normalized,
                'docx_name': font_file.stem,
                'docx_english_name': font_file.stem,
                'font_path': str(font_file)
            }
    return None


def normalize_style_config(style_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    config = DEFAULT_STYLE_CONFIG.copy()
    input_cfg = style_config or {}

    def _as_float(key: str, default: float) -> float:
        value = input_cfg.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _as_bool(key: str, default: bool) -> bool:
        value = input_cfg.get(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ('1', 'true', 'yes', 'y', 'on'):
                return True
            if lowered in ('0', 'false', 'no', 'n', 'off'):
                return False
        return default

    requested_font_id = str(input_cfg.get('font_id') or input_cfg.get('font_file_id') or '').strip()
    chosen_font_id = requested_font_id or config.get('font_id', PRIMARY_FONT_ID)
    font_entry = _get_font_entry_by_id(chosen_font_id)
    if not font_entry and chosen_font_id != PRIMARY_FONT_ID:
        chosen_font_id = PRIMARY_FONT_ID
        font_entry = _get_font_entry_by_id(PRIMARY_FONT_ID)

    base_font_name = font_entry.get('docx_name') if font_entry else config['font_name']
    base_latin_name = font_entry.get('docx_english_name') if font_entry else config.get('font_name_english', config['font_name'])

    primary_font = (input_cfg.get('font_name') or base_font_name or config['font_name']).strip() or config['font_name']
    latin_font = (input_cfg.get('font_name_english') or base_latin_name or primary_font).strip() or primary_font
    font_file_id_value = str(input_cfg.get('font_file_id', config.get('font_file_id', ''))).strip()
    if (not font_file_id_value) and font_entry and font_entry.get('font_path'):
        font_file_id_value = chosen_font_id

    config.update({
        'font_id': chosen_font_id,
        'font_name': primary_font,
        'font_name_english': latin_font,
        'heading_font_name': primary_font,
        'title_font_name': primary_font,
        'font_size': _as_float('font_size', config['font_size']),
        'title_size': _as_float('title_size', config['title_size']),
        'heading_level1_size': _as_float('heading_level1_size', input_cfg.get('heading_size', config['heading_level1_size'])),
        'heading_level2_size': _as_float('heading_level2_size', config['heading_level2_size']),
        'heading_level3_size': _as_float('heading_level3_size', config['heading_level3_size']),
        'line_spacing': _as_float('line_spacing', config['line_spacing']),
        'paragraph_spacing': _as_float('paragraph_spacing', config['paragraph_spacing']),
        'margin_top': _as_float('margin_top', config['margin_top']),
        'margin_bottom': _as_float('margin_bottom', config['margin_bottom']),
        'margin_left': _as_float('margin_left', config['margin_left']),
        'margin_right': _as_float('margin_right', config['margin_right']),
        'font_file_id': font_file_id_value,
        'heading_font_file_id': font_file_id_value,
        'title_font_file_id': font_file_id_value
    })

    body_size = _clamp(config['font_size'], 8, 24)
    heading3 = _clamp(max(body_size + 0.5, config['heading_level3_size']), body_size + 0.5, 48)
    heading2 = _clamp(max(heading3 + 0.5, config['heading_level2_size']), heading3 + 0.5, 54)
    heading1 = _clamp(max(heading2 + 0.5, config['heading_level1_size']), heading2 + 0.5, 60)
    title_size = _clamp(max(heading1 + 1, config['title_size']), heading1 + 1, 80)

    config['font_size'] = body_size
    config['heading_level3_size'] = heading3
    config['heading_level2_size'] = heading2
    config['heading_level1_size'] = heading1
    config['title_size'] = title_size

    font_path_override = (font_entry.get('font_path') if font_entry else '') or ''
    primary_font_path_raw = font_path_override or input_cfg.get('font_file_path') or input_cfg.get('font_path') or config.get('font_file_path') or ''
    if primary_font_path_raw:
        safe_path = _resolve_uploaded_font_path(primary_font_path_raw)
        primary_font_path = safe_path or ''
    else:
        primary_font_path = ''
    config['font_file_path'] = primary_font_path
    config['heading_font_file_path'] = primary_font_path
    config['title_font_file_path'] = primary_font_path

    config['treat_images_as_text'] = _as_bool('treat_images_as_text', config.get('treat_images_as_text', False))
    placeholder_value = input_cfg.get('image_placeholder_text') or config.get('image_placeholder_text')
    if placeholder_value:
        config['image_placeholder_text'] = str(placeholder_value)
    else:
        config['image_placeholder_text'] = '※ 참고 이미지: {keyword}'

    return config

# IP 주소 기반 사용자 ID 생성
def get_user_id_from_request(request: Request) -> str:
    """세션 또는 IP 주소를 기반으로 사용자 ID 생성"""
    current_user = _get_current_user(request)
    if current_user:
        return str(current_user.id)
    ip = _get_client_ip(request) or 'unknown'
    return f"user_{ip.replace('.', '_').replace(':', '_')}"


def _normalize_email(value: str) -> str:
    return str(value or '').strip().lower()


# ============================================
# 인증/세션 API
# ============================================

@app.post('/api/auth/register')
def register_user(request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    """이메일/비밀번호 기반 계정 생성"""
    try:
        email = _normalize_email(payload.get('email'))
        password = payload.get('password') or ''
        name = (payload.get('name') or '').strip()

        if not email or not password:
            return _json_response({'error': '이메일과 비밀번호를 입력하세요.'}, 400)
        if '@' not in email:
            return _json_response({'error': '유효한 이메일을 입력하세요.'}, 400)

        existing = db.get_user_credentials(email)
        if existing and existing.get('password_hash'):
            return _json_response({'error': '이미 가입된 이메일입니다.'}, 400)

        password_hash = generate_password_hash(password)
        display_name = name or (existing.get('name') if existing else '') or email.split('@')[0]
        picture = payload.get('picture') or (existing.get('picture') if existing else None)

        is_new_user = existing is None
        if existing:
            user = db.create_or_update_user(
                existing['id'],
                email,
                display_name,
                picture,
                password_hash=password_hash,
                last_login=datetime.now().isoformat()
            )
        else:
            user = db.create_local_user(email, password_hash, display_name, picture)

        _login_user(request, user)
        if is_new_user:
            _log_analytics_event(request, "signup", user_id=user.id)
        _log_analytics_event(request, "login", user_id=user.id)
        return {'success': True, 'user': user.to_dict()}
    except Exception as exc:
        print(f"[AUTH] register error: {exc}")
        return _json_response({'error': '계정 생성 중 오류가 발생했습니다.'}, 500)


@app.post('/api/auth/login')
def auth_login(request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    """이메일/비밀번호 로그인"""
    try:
        email = _normalize_email(payload.get('email'))
        password = payload.get('password') or ''

        if not email or not password:
            return _json_response({'error': '이메일과 비밀번호를 입력하세요.'}, 400)

        record = db.get_user_credentials(email)
        if not record or not record.get('password_hash'):
            return _json_response({'error': '이메일 또는 비밀번호가 올바르지 않습니다.'}, 401)
        if not check_password_hash(record['password_hash'], password):
            return _json_response({'error': '이메일 또는 비밀번호가 올바르지 않습니다.'}, 401)

        user = db.get_user(record['id'])
        if not user:
            user = db.create_or_update_user(
                record['id'],
                record['email'],
                record['name'] or email.split('@')[0],
                record.get('picture'),
                password_hash=record['password_hash'],
                last_login=datetime.now().isoformat()
            )
        else:
            db.update_last_login(user.id)

        _login_user(request, user)
        _log_analytics_event(request, "login", user_id=user.id)
        return {'success': True, 'user': user.to_dict()}
    except Exception as exc:
        print(f"[AUTH] login error: {exc}")
        return _json_response({'error': '로그인 처리 중 문제가 발생했습니다.'}, 500)


@app.post('/api/auth/logout')
def logout(request: Request):
    """현재 세션 로그아웃"""
    try:
        _logout_user(request)
        return {'success': True}
    except Exception as exc:
        print(f"[AUTH] logout error: {exc}")
        return _json_response({'error': '로그아웃에 실패했습니다.'}, 500)


@app.get('/api/auth/me')
def whoami(request: Request):
    """세션 확인용"""
    current_user = _get_current_user(request)
    if current_user:
        return {'authenticated': True, 'user': current_user.to_dict()}
    return {'authenticated': False}


# ============================================
# 소셜 로그인 API (OAuth 2.0 / Mock)
# ============================================

@app.get('/api/auth/social/{provider}')
def social_login(provider: str, request: Request):
    provider = provider.lower()

    next_url = request.query_params.get("next")
    if _is_safe_redirect(next_url):
        request.session["oauth_next"] = next_url
    else:
        request.session.pop("oauth_next", None)

    if provider == 'google':
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

        redirect_uri = _build_oauth_redirect_uri(request, provider)

        print("=== OAUTH DEBUG (START) ===")
        print("provider      :", provider)
        print("redirect_uri  :", redirect_uri)
        print("request.host  :", request.headers.get("host"))
        print("request.scheme:", request.url.scheme)
        print("==========================")

        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        scope = "openid email profile"
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
            "include_granted_scopes": "true",
            "prompt": "select_account"
        }
        final_url = f"{auth_url}?{urlencode(params)}"
        
        print("=== GOOGLE AUTH URL ===")
        print(final_url)
        print("=======================")
        
        return RedirectResponse(url=f"{auth_url}?{urlencode(params)}")

    # 환경변수에서 Client ID 조회 (Google 외)
    client_id = os.getenv(f"{provider.upper()}_CLIENT_ID")
    if provider == 'kakao' and not client_id:
        client_id = os.getenv("KAKAO_API_KEY") or os.getenv("KAKAO_REST_API_KEY")
    redirect_uri = _build_oauth_redirect_uri(request, provider)
    
    # 키가 없으면 데모 로그인 처리 (프로토타입용)
    if not client_id:
        print(f"[AUTH] {provider.upper()}_CLIENT_ID not set. Using DEMO/MOCK login.")
        # 가짜 유저로 즉시 로그인 처리
        mock_id = f"{provider}_{int(time.time())}"
        user = db.create_or_update_user(
            mock_id,
            f"demo_{provider}@example.com",
            f"{provider.capitalize()} User",
            None, # picture
            last_login=datetime.now().isoformat()
        )
        _login_user(request, user)
        _log_analytics_event(request, "signup", user_id=user.id)
        _log_analytics_event(request, "login", user_id=user.id)
        # 홈으로 리다이렉트
        return RedirectResponse(url=str(app.url_path_for('index')))

    # 실제 OAuth 리다이렉트 URL 생성
    if provider == 'kakao':
        auth_url = "https://kauth.kakao.com/oauth/authorize"
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": "account_email,profile_nickname,profile_image"
        }
        return RedirectResponse(url=f"{auth_url}?{urlencode(params)}")
    
    elif provider == 'naver':
        auth_url = "https://nid.naver.com/oauth2.0/authorize"
        state = os.urandom(8).hex()
        return RedirectResponse(url=f"{auth_url}?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&state={state}")
    
    return PlainTextResponse("Unsupported provider", status_code=400)


@app.get('/api/auth/social/{provider}/callback', name='social_callback')
def social_callback(provider: str, request: Request):
    """소셜 로그인 콜백"""
    provider = provider.lower()
    error = request.query_params.get('error')
    if error:
        return PlainTextResponse(f"Login failed: {error}", status_code=400)

    if provider == 'google':
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        expected_state = request.session.pop("oauth_state", None)
        if not code:
            return PlainTextResponse("Login failed: No code received", status_code=400)
        if not expected_state or state != expected_state:
            return PlainTextResponse("Login failed: Invalid state", status_code=400)

        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        if not client_id or not client_secret:
            return PlainTextResponse("Google OAuth 환경변수가 설정되지 않았습니다.", status_code=500)

        redirect_uri = _build_oauth_redirect_uri(request, provider)
        token_url = "https://oauth2.googleapis.com/token"
        try:
            token_res = requests.post(
                token_url,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code"
                },
                timeout=10
            )
            token_res.raise_for_status()
            token_data = token_res.json()
        except Exception as exc:
            print(f"[AUTH] Google token exchange failed: {exc}")
            return PlainTextResponse("Login failed: Token exchange error", status_code=400)

        access_token = token_data.get("access_token")
        if not access_token:
            return PlainTextResponse("Login failed: No access token", status_code=400)

        userinfo_url = "https://openidconnect.googleapis.com/v1/userinfo"
        try:
            userinfo_res = requests.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
            userinfo_res.raise_for_status()
            userinfo = userinfo_res.json()
        except Exception as exc:
            print(f"[AUTH] Google userinfo fetch failed: {exc}")
            return PlainTextResponse("Login failed: Userinfo error", status_code=400)

        email = _normalize_email(userinfo.get("email"))
        if not email:
            return PlainTextResponse("Login failed: No email", status_code=400)
        if userinfo.get("email_verified") is False:
            return PlainTextResponse("Login failed: Email not verified", status_code=400)

        name = (userinfo.get("name") or userinfo.get("given_name") or email.split("@")[0]).strip()
        picture = userinfo.get("picture")
        subject = userinfo.get("sub") or userinfo.get("id")
        if not subject:
            return PlainTextResponse("Login failed: Missing user id", status_code=400)

        existing = db.get_user_by_email(email)
        user_id = existing.id if existing else f"google_{subject}"
        user = db.create_or_update_user(
            user_id,
            email,
            name,
            picture,
            last_login=datetime.now().isoformat()
        )
        _login_user(request, user)
        if not existing:
            _log_analytics_event(request, "signup", user_id=user.id)
        _log_analytics_event(request, "login", user_id=user.id)

        next_url = request.session.pop("oauth_next", None)
        if _is_safe_redirect(next_url):
            return RedirectResponse(url=next_url)
        return RedirectResponse(url=str(app.url_path_for('index')))

    if provider == 'kakao':
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        expected_state = request.session.pop("oauth_state", None)
        if not code:
            return PlainTextResponse("Login failed: No code received", status_code=400)
        if not expected_state or state != expected_state:
            return PlainTextResponse("Login failed: Invalid state", status_code=400)

        client_id = os.getenv("KAKAO_CLIENT_ID") or os.getenv("KAKAO_API_KEY") or os.getenv("KAKAO_REST_API_KEY")
        client_secret = os.getenv("KAKAO_CLIENT_SECRET")
        if not client_id:
            return PlainTextResponse("Kakao OAuth 환경변수가 설정되지 않았습니다.", status_code=500)

        redirect_uri = _build_oauth_redirect_uri(request, provider)
        token_url = "https://kauth.kakao.com/oauth/token"
        token_payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code": code
        }
        if client_secret:
            token_payload["client_secret"] = client_secret
        try:
            token_res = requests.post(token_url, data=token_payload, timeout=10)
            token_res.raise_for_status()
            token_data = token_res.json()
        except Exception as exc:
            print(f"[AUTH] Kakao token exchange failed: {exc}")
            return PlainTextResponse("Login failed: Token exchange error", status_code=400)

        access_token = token_data.get("access_token")
        if not access_token:
            return PlainTextResponse("Login failed: No access token", status_code=400)

        userinfo_url = "https://kapi.kakao.com/v2/user/me"
        try:
            userinfo_res = requests.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
            userinfo_res.raise_for_status()
            userinfo = userinfo_res.json()
        except Exception as exc:
            print(f"[AUTH] Kakao userinfo fetch failed: {exc}")
            return PlainTextResponse("Login failed: Userinfo error", status_code=400)

        kakao_id = userinfo.get("id")
        if not kakao_id:
            return PlainTextResponse("Login failed: Missing user id", status_code=400)

        kakao_account = userinfo.get("kakao_account") or {}
        email = _normalize_email(kakao_account.get("email"))
        if not email:
            return PlainTextResponse("Login failed: No email (account_email scope required)", status_code=400)
        if kakao_account.get("is_email_valid") is False or kakao_account.get("is_email_verified") is False:
            return PlainTextResponse("Login failed: Email not verified", status_code=400)

        profile = kakao_account.get("profile") or {}
        name = (profile.get("nickname") or email.split("@")[0]).strip()
        picture = profile.get("profile_image_url") or profile.get("thumbnail_image_url")

        existing = db.get_user_by_email(email)
        user_id = existing.id if existing else f"kakao_{kakao_id}"
        user = db.create_or_update_user(
            user_id,
            email,
            name,
            picture,
            last_login=datetime.now().isoformat()
        )
        _login_user(request, user)
        if not existing:
            _log_analytics_event(request, "signup", user_id=user.id)
        _log_analytics_event(request, "login", user_id=user.id)

        next_url = request.session.pop("oauth_next", None)
        if _is_safe_redirect(next_url):
            return RedirectResponse(url=next_url)
        return RedirectResponse(url=str(app.url_path_for('index')))

    return PlainTextResponse("Unsupported provider", status_code=400)


# 전역 에이전트
agent = HWPAgent(output_dir="output")
docx_handler = DOCXHandler(output_dir="output")
pdf_handler = PDFHandler(output_dir="output")
format_adjuster = FormatAdjuster()
image_searcher = ImageSearcher()
riro_sessions = {}

def _clean_google_url(url: str) -> str:
    """Google redirect URL 정제 및 imgres 링크에서 실제 이미지 URL 추출"""
    if not url:
        return url

    if url.startswith("https://www.google.com/"):
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        # 일반 redirect 형태 (?q=)
        if "q" in qs and qs["q"]:
            return qs["q"][0]
        # 이미지 상세 페이지 링크 (?imgurl=)
        if "imgurl" in qs and qs["imgurl"]:
            return qs["imgurl"][0]
    return url

def _contains_invalid_url(images: list) -> bool:
    """Facebook Lookaside 등 비정상 링크가 포함되어 있는지 검사"""
    invalid_domains = ["lookaside.fbsbx.com", "fbcdn.net", "instagram", "facebook"]
    for img in images:
        url = img.get("url", "")
        if any(domain in url for domain in invalid_domains):
            return True
    return False

def _filter_invalid_images(images: list) -> list:
    """비정상 링크 제거"""
    invalid_domains = ["lookaside.fbsbx.com", "fbcdn.net"]
    return [
        img for img in images
        if not any(domain in img.get("url", "") for domain in invalid_domains)
    ]


def _normalize_riro_events(events_payload: Any) -> List[Dict[str, Any]]:
    """리로스쿨 이벤트 페이로드를 단일 리스트로 정규화"""
    if not events_payload:
        return []
    normalized: List[Dict[str, Any]] = []
    if isinstance(events_payload, list):
        for item in events_payload:
            if not item:
                continue
            entry = dict(item)
            if entry.get("date") and isinstance(entry["date"], str):
                entry["date"] = entry["date"]
            normalized.append(entry)
    elif isinstance(events_payload, dict):
        for date_key, value in events_payload.items():
            if isinstance(value, list):
                for item in value:
                    if not item:
                        continue
                    entry = dict(item)
                    entry.setdefault("date", date_key)
                    normalized.append(entry)
            elif isinstance(value, dict):
                entry = dict(value)
                entry.setdefault("date", date_key)
                normalized.append(entry)
    try:
        normalized.sort(key=lambda x: x.get("date") or "")
    except Exception:
        pass
    return normalized


def _build_riro_context_text(request: Request, user_id: Optional[str] = None) -> Optional[str]:
    """리로스쿨 세션의 수행평가/과제 정보를 요약하여 텍스트로 반환"""
    lookup_id = user_id or get_user_id_from_request(request)
    session_payload = riro_sessions.get(lookup_id)
    if not session_payload:
        return None

    guides_map = session_payload.get("guides") or {}
    events = session_payload.get("events_list") or _normalize_riro_events(session_payload.get("events"))
    if not events:
        return None

    lines: List[str] = []
    for evt in events[:8]:
        date = evt.get("date") or "날짜 미정"
        title = evt.get("title") or "제목 없음"
        guide_text = evt.get("guide")
        if not guide_text and guides_map:
            key = evt.get("url") or date
            guide_text = (guides_map.get(key) or guides_map.get(date) or {}).get("guide")
        preview = ""
        if guide_text:
            snippet = guide_text.strip()
            if len(snippet) > 180:
                snippet = snippet[:180].rstrip() + "..."
            preview = f" — {snippet}"
        lines.append(f"- {date}: {title}{preview}")

    if not lines:
        return None

    return (
        "리로스쿨에서 불러온 수행평가/과제 일정 요약입니다. 학생의 일정과 제출 가이드를 고려해 답변하세요.\n"
        + "\n".join(lines)
    )


DOC_INTAKE_SYSTEM_PROMPT = """
너는 수행평가/보고서 작성 전 상담을 진행하는 코치다.
다음 흐름을 반드시 지켜 답한다:
1) 주제를 함께 탐구/구상: 과목/학년/단원, 주제 키워드, 목표(평가 기준), 형식/분량을 질문한다.
2) 수행평가 양식(템플릿) 유무를 확인한다.
3) 사용자가 양식이 있다고 답하면 파일 업로드를 요청한다. (클립 아이콘 → 파일 업로드 안내)
중요:
- 템플릿 업로드 전에는 문서 본문을 작성하지 않는다.
- 한 번에 한 단계씩만 진행한다.
- 이전 대화에서 이미 답한 정보나 완료된 단계는 반복하지 않는다.
- 사용자가 "양식 없음"을 명확히 답하면 그 다음부터는 일반 문서 작성 안내로 전환한다.
- 불필요하게 길게 설명하지 말고 짧고 명확하게 질문한다.
""".strip()

FILL_GUIDE_SYSTEM_PROMPT = """
너는 DOC Agent다. 사용자와 대화하듯 짧고 자연스럽게 안내한다.
다음 규칙을 지켜 한국어로 1~2문장, 질문형으로 마무리한다.
- 업로드된 문서가 비어 있는 양식임을 간단히 알린다.
- 총 항목 수와 첫 번째로 물어볼 항목명을 포함한다.
- 나머지 항목은 AI가 자동으로 작성함을 알려준다.
- 불릿/번호/코드블록 없이 짧고 명확하게 작성한다.
""".strip()

_TEMPLATE_YES_PATTERN = re.compile(r"(양식|템플릿).*(있|있어|있습니다|있음)")
_TEMPLATE_NO_PATTERN = re.compile(r"(양식|템플릿).*(없|없어|없습니다|없음|없다)")


def _text_has_template_yes(text: str) -> bool:
    if not text:
        return False
    return bool(_TEMPLATE_YES_PATTERN.search(text))


def _text_has_template_no(text: str) -> bool:
    if not text:
        return False
    return bool(_TEMPLATE_NO_PATTERN.search(text))


def _history_has_template_signal(chat_history: List[Dict[str, Any]], want: str) -> bool:
    if not chat_history:
        return False
    for msg in reversed(chat_history):
        if msg.get("role") != "user":
            continue
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        if want == "yes" and _text_has_template_yes(text):
            return True
        if want == "no" and _text_has_template_no(text):
            return True
    return False


def _should_run_doc_intake(user_request: str, document_template: Optional[str], chat_history: List[Dict[str, Any]]) -> bool:
    if document_template:
        return False
    if _history_has_template_signal(chat_history, "no"):
        return False
    if _history_has_template_signal(chat_history, "yes"):
        return True
    if _text_has_template_no(user_request) or _text_has_template_yes(user_request):
        return True
    return True


def _build_fill_guide_prompt(fields: List[str], first_field: str, total: int) -> str:
    trimmed_fields = [field.strip() for field in (fields or []) if isinstance(field, str) and field.strip()]
    preview = ", ".join(trimmed_fields[:12])
    lines = [
        f"총 항목 수: {total}",
        f"첫 번째 항목: {first_field}"
    ]
    if preview:
        lines.append(f"항목 목록: {preview}")
    return "\n".join(lines)

@app.get('/', name='index')
@app.get('/index.html')
def index(request: Request):
    """메인 페이지"""
    return templates.TemplateResponse('index.html', {'request': request})


@app.get('/login')
def login_page(request: Request):
    """독립 로그인 페이지"""
    current_user = _get_current_user(request)
    if current_user:
        return RedirectResponse(url=str(app.url_path_for('index')))
    return templates.TemplateResponse('login.html', {'request': request})

@app.get('/admin')
def admin_page(request: Request):
    """관리자 전용 페이지"""
    _require_admin_access(request)
    current_user = _get_current_user(request)
    user_name = getattr(current_user, "name", "") or "Admin"
    user_email = getattr(current_user, "email", "")
    user_initial = (user_name.strip() or user_email or "A")[0].upper()
    return templates.TemplateResponse(
        'admin.html',
        {
            'request': request,
            'user_name': user_name,
            'user_email': user_email,
            'user_initial': user_initial,
            'client_ip': _get_client_ip(request),
            'access_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )

@app.get('/api/admin/db/tables')
def admin_db_tables(request: Request):
    _require_admin_access(request)
    return {"tables": _list_db_tables()}

@app.get('/api/admin/db/table/{table_name}')
def admin_db_table(table_name: str, request: Request):
    _require_admin_access(request)
    tables = _list_db_tables()
    if table_name not in tables:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        limit = int(request.query_params.get("limit", 200))
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        return _json_response({"error": "Invalid limit/offset"}, 400)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    payload = _fetch_table_rows(table_name, limit, offset)
    payload["table"] = table_name
    payload["limit"] = limit
    payload["offset"] = offset
    return payload

@app.post('/api/admin/db/table/{table_name}/row')
def admin_db_insert_row(table_name: str, request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    _require_admin_access(request)
    if not _is_safe_identifier(table_name) or table_name not in _list_db_tables():
        return _json_response({"error": "Table not found"}, 404)

    data = payload.get("data")
    if not isinstance(data, dict) or not data:
        return _json_response({"error": "Missing data"}, 400)

    columns = _get_table_columns(table_name)
    allowed = {key: value for key, value in data.items() if key in columns}
    if not allowed:
        return _json_response({"error": "No valid columns provided"}, 400)

    col_sql = ", ".join(f'"{col}"' for col in allowed.keys())
    placeholders = ", ".join(["?"] * len(allowed))
    values = list(allowed.values())

    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f'INSERT INTO "{table_name}" ({col_sql}) VALUES ({placeholders})', values)
        conn.commit()
        return {"success": True, "affected": cursor.rowcount, "id": cursor.lastrowid}
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)
    finally:
        conn.close()

@app.patch('/api/admin/db/table/{table_name}/row')
def admin_db_update_row(table_name: str, request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    _require_admin_access(request)
    if not _is_safe_identifier(table_name) or table_name not in _list_db_tables():
        return _json_response({"error": "Table not found"}, 404)

    data = payload.get("data")
    where = payload.get("where")
    if not isinstance(data, dict) or not data:
        return _json_response({"error": "Missing data"}, 400)
    if not isinstance(where, dict) or not where:
        return _json_response({"error": "Missing where clause"}, 400)

    columns = _get_table_columns(table_name)
    updates = {key: value for key, value in data.items() if key in columns}
    conditions = {key: value for key, value in where.items() if key in columns}
    if not updates:
        return _json_response({"error": "No valid update columns provided"}, 400)
    if not conditions:
        return _json_response({"error": "No valid where columns provided"}, 400)

    set_parts = [f'"{col}" = ?' for col in updates.keys()]
    where_parts = []
    values: list[Any] = list(updates.values())
    for col, value in conditions.items():
        if value is None:
            where_parts.append(f'"{col}" IS NULL')
        else:
            where_parts.append(f'"{col}" = ?')
            values.append(value)

    set_sql = ", ".join(set_parts)
    where_sql = " AND ".join(where_parts)

    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f'UPDATE "{table_name}" SET {set_sql} WHERE {where_sql}', values)
        conn.commit()
        return {"success": True, "affected": cursor.rowcount}
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)
    finally:
        conn.close()

@app.delete('/api/admin/db/table/{table_name}/row')
def admin_db_delete_row(table_name: str, request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    _require_admin_access(request)
    if not _is_safe_identifier(table_name) or table_name not in _list_db_tables():
        return _json_response({"error": "Table not found"}, 404)

    where = payload.get("where")
    if not isinstance(where, dict) or not where:
        return _json_response({"error": "Missing where clause"}, 400)

    columns = _get_table_columns(table_name)
    conditions = {key: value for key, value in where.items() if key in columns}
    if not conditions:
        return _json_response({"error": "No valid where columns provided"}, 400)

    where_parts = []
    values: list[Any] = []
    for col, value in conditions.items():
        if value is None:
            where_parts.append(f'"{col}" IS NULL')
        else:
            where_parts.append(f'"{col}" = ?')
            values.append(value)

    where_sql = " AND ".join(where_parts)

    conn = db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f'DELETE FROM "{table_name}" WHERE {where_sql}', values)
        conn.commit()
        return {"success": True, "affected": cursor.rowcount}
    except Exception as exc:
        return _json_response({"error": str(exc)}, 500)
    finally:
        conn.close()

@app.get('/api/admin/system/metrics')
def admin_system_metrics(request: Request):
    _require_admin_access(request)
    if not psutil:
        return {"available": False}
    cpu_percent = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory()._asdict()
    disk = psutil.disk_usage("/")._asdict()
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "available": True,
        "cpu": {"percent": cpu_percent, "count": psutil.cpu_count()},
        "memory": memory,
        "disk": disk,
        "load_avg": load_avg,
        "gpu": None
    }

@app.get('/api/admin/analytics/summary')
def admin_analytics_summary(request: Request):
    _require_admin_access(request)
    try:
        days = int(request.query_params.get("days", 14))
    except Exception:
        days = 14
    days = max(1, min(days, 60))
    summary = db.fetch_analytics_summary(days=days, top_limit=8, recent_limit=24)
    return _json_response(summary)

@app.get('/api/admin/logs/stream')
def admin_logs_stream(request: Request):
    _require_admin_access(request)
    log_path = _resolve_admin_log_path()
    if not log_path or not log_path.exists():
        return _json_response({"error": "Log file not found"}, 404)
    try:
        tail = int(request.query_params.get("tail", 200))
    except ValueError:
        tail = 200
    tail = max(0, min(tail, 1000))

    def _tail_lines(path: Path, count: int) -> List[str]:
        if count <= 0:
            return []
        lines = deque(maxlen=count)
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                lines.append(line.rstrip("\n"))
        return list(lines)

    def generate():
        for line in _tail_lines(log_path, tail):
            yield f"data: {line}\n\n"

        while True:
            try:
                with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(0, os.SEEK_END)
                    current_inode = os.fstat(handle.fileno()).st_ino
                    while True:
                        line = handle.readline()
                        if line:
                            yield f"data: {line.rstrip()}\n\n"
                        else:
                            time.sleep(0.5)
                            try:
                                if log_path.exists() and os.stat(log_path).st_ino != current_inode:
                                    break
                            except FileNotFoundError:
                                yield "event: error\ndata: log file missing\n\n"
                                time.sleep(1)
                                break
            except FileNotFoundError:
                yield "event: error\ndata: log file missing\n\n"
                time.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.get('/api/admin/test-mode')
def admin_get_test_mode(request: Request):
    _require_admin_access(request)
    return _json_response({
        'enabled': TEST_MODE_ENABLED
    })

@app.post('/api/admin/test-mode')
def admin_set_test_mode(request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    _require_admin_access(request)
    enabled = bool(payload.get('enabled'))
    global TEST_MODE_ENABLED
    TEST_MODE_ENABLED = enabled
    return _json_response({
        'enabled': TEST_MODE_ENABLED
    })

@app.get('/offline.html')
def offline(request: Request):
    """오프라인용 단순 페이지"""
    return templates.TemplateResponse('offline.html', {'request': request})

@app.get('/manifest.json')
def manifest():
    """PWA manifest 파일"""
    response = FileResponse(STATIC_DIR / 'manifest.json', media_type='application/manifest+json')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.get('/icons/{filename:path}')
def pwa_icons(filename: str):
    """PWA 아이콘 전달"""
    icon_dir = (STATIC_DIR / "icons").resolve()
    try:
        icon_path = (icon_dir / filename).resolve()
        icon_path.relative_to(icon_dir)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not icon_path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(icon_path)

@app.get('/service-worker.js')
def service_worker():
    """서비스 워커 스크립트"""
    response = FileResponse(STATIC_DIR / 'service-worker.js', media_type='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.get('/bet')
def bet_page(request: Request):
    """달팽이 경주 토토 페이지"""
    return templates.TemplateResponse('bet.html', {'request': request})

@app.get('/ready')
def ready_page(request: Request):
    """출시 준비중 페이지"""
    return templates.TemplateResponse('ready.html', {'request': request})

@app.get('/riroschool')
def riroschool_page(request: Request):
    """리로스쿨 계정 입력 페이지"""
    return templates.TemplateResponse('riroschool.html', {'request': request})

@app.get('/riroschool/docs')
def riroschool_docs_page(request: Request):
    """리로스쿨 문서 목록 페이지"""
    return templates.TemplateResponse('riro_docs.html', {'request': request})

@app.get('/riroschool/docs/{doc_id}')
def riroschool_doc_detail_page(doc_id: int, request: Request):
    """리로스쿨 문서 상세 페이지"""
    return templates.TemplateResponse('riro_doc_view.html', {'request': request, 'doc_id': doc_id})

@app.post('/api/riroschool/login')
def riroschool_login(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """리로스쿨 로그인 및 이벤트 가져오기"""
    try:
        school = data.get('school', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        grade = data.get('grade', '1')
        year = data.get('year', '2025')
        
        if not school or not username or not password:
            return _json_response({
                'success': False,
                'error': '학교명, 아이디, 비밀번호를 모두 입력해주세요.'
            }, 400)
        
        print(f"[RIRO API] Login request - School: {school}, User: {username}, Grade: {grade}")
        user_id = get_user_id_from_request(request)
        
        # 크롤러 실행
        crawler = RiroSchoolCrawler()
        result = crawler.login_and_get_events(
            school_name=school,
            username=username,
            password=password,
            grade=grade,
            year=year
        )
        
        if result['success']:
            events_list = _normalize_riro_events(result.get('events'))
            events_by_date = result.get('events_by_date') or {}
            if not events_by_date and events_list:
                for evt in events_list:
                    date_key = evt.get('date')
                    if not date_key:
                        continue
                    events_by_date.setdefault(date_key, []).append(evt)

            print(f"[RIRO API] Success - Found {len(events_list)} events")
            session_payload = {
                'school': school,
                'riro_id': username,
                'grade': grade,
                'year': year,
                'base_url': result.get('base_url'),
                'cookies': result.get('cookies'),
                'events': events_by_date,
                'events_list': events_list,
                'guides': result.get('guides', {}),
                'updated_at': time.time()
            }
            riro_sessions[user_id] = session_payload
            result.pop('cookies', None)
            result.pop('base_url', None)
            result.pop('guides', None)
            result['events'] = events_list
            result['events_by_date'] = events_by_date
            result['event_count'] = len(events_list)
            result['riro_id'] = username
        else:
            print(f"[RIRO API] Failed - {result['error']}")
        
        return result
        
    except Exception as e:
        print(f"[RIRO API ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return _json_response({
            'success': False,
            'error': str(e)
        }, 500)

@app.post('/api/riroschool/guide')
def riroschool_guide(request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    """리로스쿨 일정에서 과제 가이드라인 추출"""
    try:
        events = payload.get('events') or []
        event_url = payload.get('eventUrl')
        date = payload.get('date')
        user_id = get_user_id_from_request(request)
        session_payload = riro_sessions.get(user_id)
        
        if not session_payload:
            return _json_response({'success': False, 'error': '로그인 세션이 만료되었습니다.'}, 401)
        
        if not event_url:
            for event in events:
                candidate = (event or {}).get('url') or (event or {}).get('link')
                if candidate:
                    event_url = candidate
                    break
        
        if not event_url and not date:
            return _json_response({'success': False, 'error': '가져올 이벤트 URL이 없습니다.'}, 400)
        
        guides_map = session_payload.get('guides') or {}
        guide_entry = None
        if date and date in guides_map:
            guide_entry = guides_map[date]
        if not guide_entry and event_url:
            if event_url in guides_map:
                guide_entry = guides_map[event_url]
        if not guide_entry and event_url:
            guide_entry = next(
                (info for info in guides_map.values() if info.get('source') == event_url),
                None
            )
        
        if not guide_entry:
            return {'success': False, 'error': '가이드 라인이 없습니다.'}
        
        return {
            'success': True,
            'guide': guide_entry.get('guide', '').strip(),
            'source': guide_entry.get('source', event_url)
        }
    except Exception as exc:
        print(f"[RIRO GUIDE ERROR] {exc}")
        return _json_response({'success': False, 'error': str(exc)}, 500)

@app.post('/api/riroschool/logout')
def riroschool_logout(request: Request):
    """리로스쿨 세션 초기화"""
    user_id = get_user_id_from_request(request)
    if user_id in riro_sessions:
        riro_sessions.pop(user_id, None)
    return {'success': True}

@app.get('/api/riroschool/documents')
def riro_documents_list(request: Request):
    """리로스쿨 사용자 문서 목록"""
    user_id = get_user_id_from_request(request)
    session_payload = riro_sessions.get(user_id)
    if not session_payload:
        return _json_response({'success': False, 'error': '로그인이 필요합니다.'}, 401)
    docs = db.get_riro_documents(session_payload['riro_id'])
    return {
        'success': True,
        'documents': [doc.to_dict() for doc in docs]
    }

@app.post('/api/riroschool/documents')
def riro_documents_save(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """리로스쿨 사용자 문서 저장"""
    user_id = get_user_id_from_request(request)
    session_payload = riro_sessions.get(user_id)
    if not session_payload:
        return _json_response({'success': False, 'error': '로그인이 필요합니다.'}, 401)
    title = (data.get('title') or '문서').strip()
    content = (data.get('content') or '').strip()
    image_urls = data.get('image_urls') or []
    if not content:
        return _json_response({'success': False, 'error': '내용이 비어있습니다.'}, 400)
    doc = db.save_riro_document(session_payload['riro_id'], title, content, image_urls)
    return {'success': True, 'document': doc.to_dict()}

@app.get('/api/riroschool/documents/{doc_id}')
def riro_documents_detail(doc_id: int, request: Request):
    user_id = get_user_id_from_request(request)
    session_payload = riro_sessions.get(user_id)
    if not session_payload:
        return _json_response({'success': False, 'error': '로그인이 필요합니다.'}, 401)
    doc = db.get_riro_document(doc_id, session_payload['riro_id'])
    if not doc:
        return _json_response({'success': False, 'error': '문서를 찾을 수 없습니다.'}, 404)
    return {'success': True, 'document': doc.to_dict()}


@app.post('/upload')
def upload_hwpx(template: Optional[UploadFile] = File(None)):
    """Deprecated legacy HWPX upload endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


@app.post('/save')
def save_hwpx(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """Deprecated legacy HWPX save endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


@app.post('/api/template/upload')
def upload_template(template: Optional[UploadFile] = File(None)):
    """Deprecated legacy template upload endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


@app.post('/api/template/fill-guide')
def template_fill_guide(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """빈 양식 안내 문구 생성"""
    try:
        fields = data.get('fields') or []
        first_field = (data.get('first_field') or '').strip()
        total = data.get('total')
        chat_history = data.get('history') or []
        if not first_field and fields:
            first_field = str(fields[0]).strip()
        if not first_field:
            return _json_response({'success': False, 'error': '첫 번째 항목이 필요합니다.'}, 400)
        if not isinstance(total, int):
            total = len(fields) if isinstance(fields, list) else 1
        total = max(1, total)

        prompt = _build_fill_guide_prompt(fields, first_field, total)
        message = ""
        stream = agent.content_generator.generate_chat_stream(
            prompt,
            history=chat_history,
            system_prompt=FILL_GUIDE_SYSTEM_PROMPT
        )
        for chunk in stream:
            if chunk:
                message += chunk
        message = (message or "").strip()
        if not message:
            return _json_response({'success': False, 'error': '안내 문구 생성 실패'}, 500)
        return {'success': True, 'message': message}
    except Exception as exc:
        print(f"[FILL GUIDE ERROR] {exc}")
        return _json_response({'success': False, 'error': '안내 문구 생성 중 오류가 발생했습니다.'}, 500)


@app.get('/api/template/asset/{template_id}/{asset_path:path}')
def serve_template_asset(template_id: str, asset_path: str):
    """Deprecated hwp5html asset endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


@app.get('/api/templates')
def list_templates():
    """내장 및 로컬 템플릿 목록 제공"""
    templates = []

    for key in sorted(DOCUMENT_PRESETS.keys()):
        templates.append({
            'id': key,
            'name': key.replace('_', ' '),
            'type': 'preset'
        })

    if TEMPLATE_LIBRARY_DIR.exists():
        for path in sorted(TEMPLATE_LIBRARY_DIR.rglob('*')):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_TEMPLATE_EXTENSIONS:
                continue
            rel_path = path.relative_to(TEMPLATE_LIBRARY_DIR).as_posix()
            templates.append({
                'id': rel_path,
                'name': path.stem,
                'type': 'file',
                'extension': path.suffix.lower()
            })

    return {'success': True, 'templates': templates}


@app.post('/api/template/select')
def select_template(data: Dict[str, Any] = Depends(_get_json)):
    """Deprecated legacy template selection endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


@app.post('/api/font/upload')
def upload_font(font: Optional[UploadFile] = File(None), fontName: Optional[str] = Form(None)):
    """사용자 지정 폰트 업로드"""
    try:
        if not font or not font.filename:
            return _json_response({'success': False, 'error': '업로드할 폰트를 선택해주세요.'}, 400)

        suffix = Path(font.filename).suffix.lower()
        if suffix not in {'.ttf', '.otf'}:
            return _json_response({'success': False, 'error': 'TTF 또는 OTF 형식만 지원합니다.'}, 400)

        safe_stem = secure_filename(Path(font.filename).stem) or 'font'
        timestamp = int(time.time() * 1000)
        save_path = FONT_DIR / f"{timestamp}_{safe_stem}{suffix}"
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        with save_path.open("wb") as handle:
            shutil.copyfileobj(font.file, handle)

        display_name = fontName or Path(font.filename).stem

        return {
            'success': True,
            'font_id': save_path.stem,
            'font_name': display_name,
            'font_path': str(save_path)
        }
    except Exception as exc:
        print(f"[FONT] Upload failed: {exc}")
        return _json_response({'success': False, 'error': '폰트 업로드 중 오류가 발생했습니다.'}, 500)


@app.get('/api/fonts')
def get_fonts():
    try:
        fonts = list_available_fonts()
        return {'success': True, 'fonts': fonts}
    except Exception as exc:
        print(f"[FONT] Catalog error: {exc}")
        return _json_response({'success': False, 'error': '폰트 목록을 불러오지 못했습니다.'}, 500)


@app.get('/api/formats')
def get_available_formats():
    return {'success': True, 'formats': EXPORT_FORMATS}

@app.post('/api/interact')
def interact_auto(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """자동 의도 파악 및 스트리밍"""
    try:
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []  # 대화 기록 추출
        user_id = get_user_id_from_request(request)
        riro_context_text = _build_riro_context_text(request, user_id)
        
        if not user_request:
             return _json_response({'error': '요청 내용을 입력해주세요.'}, 400)

        def generate():
            # 1. 의도 파악 (템플릿이 있어도 사용자의 요청에 따라 판단)
            try:
                intent = agent.content_generator.classify_intent(user_request)
            except Exception as e:
                print(f"[INTENT ERROR] {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

            print(f"[INTENT DETECTED] {intent}")

            use_doc_intake = False
            if intent == "document":
                use_doc_intake = _should_run_doc_intake(user_request, document_template, chat_history)
            
            # 2. 모드 정보 전송
            yield f"data: {json.dumps({'type': 'mode', 'mode': 'chat'})}\n\n"
            
            # 3. 해당 모드로 스트리밍 위임
            # 채팅 모드만 사용: 문서 생성 스트림 비활성화
            full_text = ""

            # [수정] 템플릿이 있다면 컨텍스트에 추가
            chat_prompt = user_request
            if document_template:
                 chat_prompt = f"다음은 사용자가 업로드한 문서/양식의 내용입니다. 질문에 답변할 때 참고하세요.\n\n[문서 내용 시작]\n{document_template}\n[문서 내용 끝]\n\n사용자 요청: {user_request}"
            if riro_context_text:
                chat_prompt = f"{riro_context_text}\n\n{chat_prompt}"
            if riro_context_text:
                chat_prompt = f"{riro_context_text}\n\n{chat_prompt}"

            try:
                system_prompt = DOC_INTAKE_SYSTEM_PROMPT if use_doc_intake else None
                stream = agent.content_generator.generate_chat_stream(
                    chat_prompt,
                    history=chat_history,
                    system_prompt=system_prompt
                )
                for chunk in stream:
                    if chunk:
                        full_text += chunk
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                yield f"data: {json.dumps({'done': True, 'result': {'body': full_text}})}\n\n"
            except Exception as e:
                print(f"[CHAT STREAM ERROR] {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            generate(),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        print(f"[ERROR] interact endpoint failed: {str(e)}")
        return _json_response({'error': str(e)}, 500)

@app.post('/api/generate')
def generate_content(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """AI 콘텐츠 생성"""
    try:
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request(request)
        riro_context_text = _build_riro_context_text(request, user_id)

        if not user_request:
            if document_template:
                user_request = "제공된 문서 양식의 모든 항목을 알맞은 내용으로 채워 완성된 문서를 작성하세요."
            else:
                return _json_response({'error': '요청 내용 또는 양식을 입력해주세요.'}, 400)
        
        # 문서 생성 컨텍스트 구성
        history_text = ""
        if chat_history:
             recent = chat_history[-10:]
             history_text = "\n".join([f"[{msg.get('role', 'user')}]: {msg.get('text', '')}" for msg in recent])

        context_payload = {'previous_conversation': history_text}
        if riro_context_text:
            context_payload['riroschool_assignments'] = riro_context_text
        
        # 콘텐츠 생성
        result = agent.process_request(
            user_request, 
            document_template=document_template,
            context=context_payload
        )
        
        if not result.get('success', True):
            return _json_response({'error': result.get('error', 'Unknown error')}, 500)
            
        return {
            'success': True,
            'title': result.get('title', ''),
            'body': result.get('body', ''),
            'images_needed': result.get('images_needed', []),
            'tables_needed': result.get('tables_needed', [])
        }
        
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.post('/api/generate-stream')
def generate_content_stream(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """스트리밍 AI 콘텐츠 생성"""
    try:
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request(request)
        riro_context_text = _build_riro_context_text(request, user_id)

        if not user_request:
            if document_template:
                user_request = "제공된 문서 양식을 기반으로 모든 항목을 충실하게 작성하세요."
            else:
                return _json_response({'error': '요청 내용 또는 양식을 입력해주세요.'}, 400)
        
        history_text = ""
        if chat_history:
             recent = chat_history[-10:]
             history_text = "\n".join([f"[{msg.get('role', 'user')}]: {msg.get('text', '')}" for msg in recent])

        def generate():
            full_text = ""
            chunk_count = 0
            try:
                # 스트리밍 모드로 생성
                stream = agent.content_generator.generate_document_content(
                    user_request,
                    stream=True,
                    document_template=document_template,
                    context={'previous_conversation': history_text}
                )
                
                for chunk in stream:
                    if chunk:  # 빈 청크 무시
                        full_text += chunk
                        chunk_count += 1
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                
                # ... (중략) ...
                
                parsed = agent.content_generator._parse_generated_content(full_text)
                final_result = {
                    'title': parsed.get('title', '문서'),
                    'body': full_text,
                    'images_needed': parsed.get('images_needed', []),
                    'tables_needed': parsed.get('tables_needed', [])
                }
                
                yield f"data: {json.dumps({'done': True, 'result': final_result})}\n\n"
                
            except Exception as e:
                print(f"[ERROR] Stream generation failed: {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
        
    except Exception as e:
        print(f"[ERROR] API endpoint failed: {str(e)}")
        return _json_response({'error': str(e)}, 500)

@app.post('/api/chat-stream')
def chat_stream(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """프리픽스 없이 채팅형 응답 스트리밍"""
    try:
        user_request = (data.get('request') or '').strip()
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request(request)
        riro_context_text = _build_riro_context_text(request, user_id)
        
        if not user_request:
            return _json_response({'error': '요청 내용을 입력해주세요.'}, 400)

        def generate():
            full_text = ""
            try:
                chat_prompt = user_request
                if riro_context_text:
                    chat_prompt = f"{riro_context_text}\n\n{user_request}"
                stream = agent.content_generator.generate_chat_stream(chat_prompt, history=chat_history)
                for chunk in stream:
                    if chunk:
                        full_text += chunk
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                yield f"data: {json.dumps({'done': True, 'result': {'body': full_text}})}\n\n"
            except Exception as e:
                print(f"[CHAT STREAM ERROR] {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            generate(),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
    except Exception as e:
        print(f"[ERROR] chat_stream failed: {str(e)}")
        return _json_response({'error': str(e)}, 500)


@app.post('/api/edit-html')
def edit_html(data: Dict[str, Any] = Depends(_get_json)):
    """Deprecated legacy HTML editing endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)


@app.post('/api/edit-fragment')
def edit_fragment(data: Dict[str, Any] = Depends(_get_json)):
    """Deprecated legacy HTML fragment editing endpoint."""
    raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)

@app.post('/api/save')
def save_document(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """문서 저장 (이미지 자동 검색 및 삽입 포함)"""
    try:
        title = data.get('title', '문서')
        content = data.get('content', '')
        content_type = (data.get('content_type') or 'text').lower()
        format_type = (data.get('format') or 'docx').lower()
        style_config = normalize_style_config(data.get('style'))
        template_file = (data.get('template_file') or '').strip()
        images_needed = data.get('images_needed', [])  # AI가 제안한 이미지 키워드들
        image_urls = data.get('image_urls', [])  # 프론트엔드에서 검색한 이미지 URL
        is_html_content = content_type == 'html'
        
        # 디버깅: 받은 콘텐츠 길이 로그
        print(f"[DEBUG] Save request - Title: {title}")
        print(f"[DEBUG] Content length: {len(content)} characters")
        print(f"[DEBUG] Content preview (first 200 chars): {content[:200]}...")
        print(f"[DEBUG] Content preview (last 200 chars): ...{content[-200:]}")
        print(f"[DEBUG] Images needed: {images_needed}")
        print(f"[DEBUG] Image URLs from frontend: {len(image_urls)} URLs")
        
        if not content:
            return _json_response({'error': '내용이 비어있습니다.'}, 400)

        template_path = None
        if template_file:
            try:
                candidate = Path(template_file).resolve()
                TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
                candidate.relative_to(TEMPLATE_DIR.resolve())
                if candidate.exists():
                    template_path = str(candidate)
                else:
                    print(f"[TEMPLATE] Provided template not found: {candidate}")
            except Exception:
                print(f"[TEMPLATE] Invalid template path: {template_file}")
        
        # 이미지 자동 다운로드 ([gen_img] 태그 기반)
        downloaded_images = []
        treat_images_as_text = style_config.get('treat_images_as_text', False)
        if is_html_content:
            print("[IMAGE] HTML content - skipping image downloads.")
        elif treat_images_as_text:
            print("[IMAGE] Textual placeholders enabled - skipping downloads.")
        elif images_needed and len(images_needed) > 0:
            print(f"[IMAGE] Found {len(images_needed)} image tags")
            print(f"[IMAGE] Keywords: {images_needed}")
            try:
                # 프론트엔드에서 받은 URL 우선 사용
                if image_urls and len(image_urls) > 0:
                    print(f"[IMAGE] Using {len(image_urls)} pre-fetched URLs from frontend")
                    for i, img_data in enumerate(image_urls[:5]):  # 최대 5개
                        if img_data is None:
                            print(f"[IMAGE] Skipping null image data at index {i}")
                            continue
                            
                        keyword = img_data.get('keyword', f'image_{i}')
                        url = img_data.get('url')
                        data_url = img_data.get('data')
                        local_path = img_data.get('local_path')

                        if not url and not data_url and not local_path:
                            print(f"[IMAGE] No URL or data for keyword: {keyword}")
                            continue

                        # 파일명에서 특수문자 제거
                        safe_filename = keyword.replace(' ', '_').replace('/', '_').replace('\\', '_')[:50]
                        img_filename = f"{safe_filename}.jpg"
                        img_path = str(IMAGE_DIR / img_filename)

                        saved_path = None
                        if data_url:
                            saved_path = _save_image_from_data_url(data_url, img_path)

                        if not saved_path and local_path:
                            saved_path = _copy_local_image(local_path, img_path)

                        if not saved_path and url:
                            print(f"[IMAGE] Downloading from frontend URL: {url[:100]}...")
                            saved_path = image_searcher.download_image(
                                url,
                                img_path,
                                max_width=1200
                            )

                        if not saved_path:
                            saved_path = _download_backend_image(keyword, img_path)

                        if saved_path:
                            downloaded_images.append(saved_path)
                            print(f"[IMAGE] ✅ Linked: {keyword} -> {saved_path}")
                        else:
                            print(f"[IMAGE] ❌ Failed to persist: {keyword}, using generic fallback...")
                            fallback_url = f"https://picsum.photos/seed/{abs(hash(keyword))%1000}/800/600"
                            fallback_path = image_searcher.download_image(
                                fallback_url,
                                str(IMAGE_DIR / f"fallback_{img_filename}"),
                                max_width=1200
                            )
                            if fallback_path:
                                downloaded_images.append(fallback_path)
                                print(f"[IMAGE] ✅ Fallback downloaded: {keyword} -> {fallback_path}")
                else:
                    # 폴백: 프론트엔드 URL이 없으면 직접 검색
                    print(f"[IMAGE] No frontend URLs, searching images...")
                    for keyword in images_needed[:5]:  # 최대 5개
                        print(f"[IMAGE] Searching: {keyword}")
                        safe_filename = keyword.replace(' ', '_').replace('/', '_').replace('\\', '_')[:50]
                        img_filename = f"{safe_filename}.jpg"
                        img_path = str(IMAGE_DIR / img_filename)
                        downloaded_path = _download_backend_image(keyword, img_path)
                        if downloaded_path:
                            downloaded_images.append(downloaded_path)
                        else:
                            print(f"[IMAGE] ❌ No usable results for: {keyword}")
                
                print(f"[IMAGE] Total downloaded: {len(downloaded_images)}/{len(images_needed)} images")
            except Exception as e:
                print(f"[IMAGE ERROR] Failed to download images: {str(e)}")
                import traceback
                traceback.print_exc()
                # 이미지 다운로드 실패해도 문서는 생성
        
        # 파일 저장 (이미지 포함)
        if is_html_content:
            temp_filename = f"{title}_temp.docx"
            if format_type == 'hwpx_xml':
                file_path = _save_hwpx_xml(title, content, is_html_content=True)
            elif format_type == 'pdf':
                try:
                    base_url = str(request.base_url)
                    file_path = pdf_handler.convert_html_to_pdf(
                        html_content=content,
                        output_filename=f"{title}.pdf",
                        base_url=base_url
                    )
                except Exception as exc:
                    print(f"[PDF HTML] Failed, falling back to DOCX conversion: {exc}")
                    temp_docx = docx_handler.create_document_from_html(
                        html_content=content,
                        title=title,
                        style_config=style_config,
                        filename=temp_filename
                    )
                    file_path = pdf_handler.convert_docx_to_pdf(
                        temp_docx,
                        output_filename=f"{title}.pdf",
                        style_config=style_config
                    )
            elif format_type == 'hwp':
                raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)
            else:
                file_path = docx_handler.create_document_from_html(
                    html_content=content,
                    title=title,
                    style_config=style_config,
                    filename=f"{title}.docx"
                )
        elif format_type == 'pdf':
            # PDF 생성: DOCX 먼저 만들고 PDF로 변환
            print(f"[PDF] Creating DOCX first...")
            temp_docx = docx_handler.create_document(
                title=title,
                content=content,
                style_config=style_config,
                images=downloaded_images if downloaded_images else None,
                filename=f"{title}_temp.docx",
                template_path=template_path
            )
            
            # DOCX를 PDF로 변환
            print(f"[PDF] Converting DOCX to PDF...")
            file_path = pdf_handler.convert_docx_to_pdf(
                temp_docx,
                output_filename=f"{title}.pdf",
                style_config=style_config
            )
        elif format_type == 'hwp':
            raise HTTPException(status_code=501, detail=MIGRATING_TO_V2_DETAIL)
        elif format_type == 'hwpx_xml':
            file_path = _save_hwpx_xml(title, content, is_html_content=False)
        elif format_type == 'docx':
            file_path = docx_handler.create_document(
                title=title,
                content=content,
                style_config=style_config,
                images=downloaded_images if downloaded_images else None,
                filename=f"{title}.docx",
                template_path=template_path
            )
        elif format_type == 'md':
            file_path = agent.hwp_handler.create_markdown_document(
                title=title,
                content=content,
                filename=f"{title}.md"
            )
        else:
            file_path = agent.hwp_handler.create_rich_text_document(
                title=title,
                content=content,
                filename=f"{title}.rtf"
            )
        
        return {
            'success': True,
            'file_path': file_path,
            'format': format_type,
            'images_count': len(downloaded_images)
        }
        
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.post('/api/refine')
def refine_content(data: Dict[str, Any] = Depends(_get_json)):
    """콘텐츠 수정/개선"""
    try:
        original_content = data.get('content', '')
        refinement_request = data.get('request', '')
        
        if not original_content or not refinement_request:
            return _json_response({'error': '내용과 수정 요청을 입력해주세요.'}, 400)
        
        # 콘텐츠 수정
        refined = agent.content_generator.refine_content(
            original_content,
            refinement_request
        )
        
        return {
            'success': True,
            'content': refined
        }
        
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.post('/api/refine-stream')
def refine_content_stream(data: Dict[str, Any] = Depends(_get_json)):
    """콘텐츠 수정/개선 (스트리밍)"""
    try:
        original_content = data.get('content', '')
        refinement_request = data.get('request', '')
        
        if not original_content or not refinement_request:
            def error_stream():
                yield f"data: {{\"error\": \"내용과 수정 요청을 입력해주세요.\"}}\n\n"
            return StreamingResponse(error_stream(), media_type='text/event-stream')
        
        def generate():
            try:
                # 스트리밍으로 수정된 콘텐츠 받기
                for chunk in agent.content_generator.refine_content_stream(
                    original_content,
                    refinement_request
                ):
                    yield f"data: {{\"chunk\": {json.dumps(chunk)}}}\n\n"
                
                # 완료 신호
                yield f"data: {{\"done\": true}}\n\n"
                
            except Exception as e:
                print(f"[REFINE STREAM ERROR] {str(e)}")
                import traceback
                traceback.print_exc()
                yield f"data: {{\"error\": {json.dumps(str(e))}}}\n\n"
        
        return StreamingResponse(generate(), media_type='text/event-stream')
        
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.post('/api/adjust-format')
def adjust_format(data: Dict[str, Any] = Depends(_get_json)):
    """서식 조정 (자연어 요청 기반)"""
    try:
        content = data.get('content', '')
        format_request = data.get('request', '')
        
        if not content or not format_request:
            return _json_response({'error': '내용과 서식 조정 요청을 입력해주세요.'}, 400)
        
        print(f"[FORMAT ADJUST] Request: {format_request}")
        print(f"[FORMAT ADJUST] Content length: {len(content)}")
        
        # 서식 조정
        adjusted = format_adjuster.adjust_format(content, format_request)
        
        print(f"[FORMAT ADJUST] Adjusted length: {len(adjusted)}")
        
        return {
            'success': True,
            'content': adjusted
        }
        
    except Exception as e:
        print(f"[FORMAT ADJUST ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return _json_response({'error': str(e)}, 500)

@app.get('/api/download/{filename:path}')
def download_file(filename: str):
    """파일 다운로드"""
    try:
        print(f"[DOWNLOAD] Requested file: {filename}")
        file_path = Path('output') / filename
        print(f"[DOWNLOAD] Full path: {file_path}")
        print(f"[DOWNLOAD] File exists: {file_path.exists()}")
        
        if file_path.exists():
            print(f"[DOWNLOAD] Sending file: {file_path}")
            return FileResponse(file_path, filename=file_path.name)
        else:
            print(f"[DOWNLOAD ERROR] File not found: {file_path}")
            return _json_response({'error': '파일을 찾을 수 없습니다.'}, 404)
    except Exception as e:
        print(f"[DOWNLOAD ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return _json_response({'error': str(e)}, 500)

@app.get('/api/view-pdf/{filename:path}')
def view_pdf(filename: str):
    """파일 보기 (브라우저에서 열기)"""
    try:
        file_path = Path('output') / filename
        if file_path.exists():
            return FileResponse(file_path, media_type='application/pdf')
        else:
            return _json_response({'error': '파일을 찾을 수 없습니다.'}, 404)
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.post('/api/search-images')
def search_images(data: Dict[str, Any] = Depends(_get_json)):
    """이미지 검색 API"""
    try:
        query = data.get('query', '')
        count = int(data.get('count', 3) or 3)

        if not query:
            return _json_response({'success': False, 'error': '검색 키워드를 입력해주세요.'}, 400)

        MAX_RETRY = 3  # 최대 3회 재검색
        attempt = 0
        images = []

        while attempt < MAX_RETRY:
            images = image_searcher.search_images_google(query, count=count)
            print(f"[IMAGE SEARCH] {attempt+1}회차 결과: {len(images)}개 이미지 검색됨")

            # URL 정제
            for img in images:
                img["url"] = _clean_google_url(img.get("url", ""))
                img["thumb_url"] = _clean_google_url(img.get("thumb_url", ""))

            # 비정상 링크 포함 시 재검색 (최대 MAX_RETRY회)
            if _contains_invalid_url(images):
                print(f"[WARN] 비정상 링크 포함 → 재검색 시도 {attempt+1}/{MAX_RETRY}")
                attempt += 1
                time.sleep(1.2)  # Google API rate limit 방지
                continue
            break

        # 최종적으로 비정상 이미지 제거 (Google 외 도메인 필터링용) + 캐시/인코딩
        enriched_images = []
        for idx, img in enumerate(_filter_invalid_images(images)):
            url = img.get("url", "")
            thumb = img.get("thumb_url", "")
            preview = _prepare_image_preview(query, url, idx)
            enriched_images.append({
                **img,
                "url": url,
                "thumb_url": thumb,
                "local_path": preview.get("local_path", ""),
                "data": preview.get("data", "")
            })

        # Google 이미지 페이지에서 유효한 이미지를 찾지 못한 경우
        if not enriched_images:
            print("[IMAGE SEARCH] Google 이미지 페이지에서 유효한 이미지를 찾지 못했습니다.")
            return {
                'success': False,
                'error': 'Google 이미지에서 해당 키워드의 이미지를 찾지 못했습니다.'
            }

        return {
            'success': True,
            'query': query,
            'count': len(enriched_images),
            'images': enriched_images
        }

    except Exception as e:
        print(f"[ERROR] search_images: {str(e)}")
        import traceback
        traceback.print_exc()
        return _json_response({'error': str(e)}, 500)

@app.get('/api/search-images/test')
def search_images_test(request: Request):
    """수동 테스트용 이미지 검색 (query 파라미터)"""
    try:
        query = request.query_params.get('query') or request.query_params.get('q') or ''
        count = int(request.query_params.get('count') or 3)
        count = max(1, min(count, 10))

        if not query:
            return _json_response({
                'success': False,
                'error': 'query 파라미터를 입력하세요.',
                'usage': '/api/search-images/test?query=검색어&count=3'
            }, 400)

        images = image_searcher.search_images_google(query, count=count)

        for img in images:
            img["url"] = _clean_google_url(img.get("url", ""))
            img["thumb_url"] = _clean_google_url(img.get("thumb_url", ""))

        enriched_images = []
        for idx, img in enumerate(_filter_invalid_images(images)):
            url = img.get("url", "")
            preview = _prepare_image_preview(query, url, idx)
            enriched_images.append({
                **img,
                "url": url,
                "thumb_url": img.get("thumb_url", ""),
                "local_path": preview.get("local_path", ""),
                "data": preview.get("data", "")
            })

        return {
            'success': True,
            'query': query,
            'count': len(enriched_images),
            'images': enriched_images
        }
    except Exception as e:
        print(f"[ERROR] search_images_test: {str(e)}")
        import traceback
        traceback.print_exc()
        return _json_response({'error': str(e)}, 500)

@app.get('/api/pdf-to-images/{filename:path}')
def pdf_to_images(filename: str):
    """파일 PDF를 이미지로 변환하여 JSON으로 반환"""
    try:
        file_path = Path('output') / filename
        if not file_path.exists():
            return _json_response({'error': '파일을 찾을 수 없습니다.'}, 404)
        
        # PDF를 열고 각 페이지를 이미지로 변환
        pdf_document = fitz.open(str(file_path))
        images = []
        
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            # 페이지를 고해상도 이미지로 변환 (2x 확대)
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            
            # PNG 데이터로 변환
            img_data = pix.tobytes("png")
            
            # Base64 인코딩
            img_base64 = base64.b64encode(img_data).decode('utf-8')
            images.append({
                'page': page_num + 1,
                'image': f'data:image/png;base64,{img_base64}'
            })
        
        pdf_document.close()
        
        return {
            'success': True,
            'pages': len(images),
            'images': images
        }
        
    except Exception as e:
        return _json_response({'error': str(e)}, 500)


# ============================================
# IP 기반 사용자 API
# ============================================

@app.get('/api/user-id')
def get_user_id(request: Request):
    """현재 사용자의 IP 기반 ID 반환"""
    user_id = get_user_id_from_request(request)
    return {
        'success': True,
        'user_id': user_id
    }

# ============================================
# 채팅 세션 API (IP 기반)
# ============================================

@app.get('/api/chat/sessions')
def list_chat_sessions(request: Request):
    try:
        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        sessions = db.get_chat_sessions(user_id)
        return {
            'success': True,
            'sessions': [session.to_dict(include_messages=False) for session in sessions]
        }
    except Exception as exc:
        print(f"[CHAT] List error: {exc}")
        return _json_response({'success': False, 'error': '대화 목록을 불러오지 못했습니다.'}, 500)


@app.post('/api/chat/sessions')
def create_chat_session(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    try:
        title = (data.get('title') or '새로운 대화').strip() or '새로운 대화'
        messages = data.get('messages') or []
        if not isinstance(messages, list):
            return _json_response({'success': False, 'error': 'messages 형식이 올바르지 않습니다.'}, 400)

        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        session = db.create_chat_session(user_id, title, messages)
        return _json_response({'success': True, 'session': session.to_dict()}, 201)
    except Exception as exc:
        print(f"[CHAT] Create error: {exc}")
        return _json_response({'success': False, 'error': '대화 저장에 실패했습니다.'}, 500)


@app.get('/api/chat/sessions/{session_id}')
def get_chat_session(session_id: str, request: Request):
    try:
        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        session = db.get_chat_session(session_id, user_id)
        if not session:
            return _json_response({'success': False, 'error': '대화를 찾을 수 없습니다.'}, 404)

        return {'success': True, 'session': session.to_dict()}
    except Exception as exc:
        print(f"[CHAT] Get error: {exc}")
        return _json_response({'success': False, 'error': '대화를 불러오지 못했습니다.'}, 500)


@app.put('/api/chat/sessions/{session_id}')
def update_chat_session(session_id: str, request: Request, data: Dict[str, Any] = Depends(_get_json)):
    try:
        title = data.get('title')
        messages = data.get('messages')

        if messages is not None and not isinstance(messages, list):
            return _json_response({'success': False, 'error': 'messages 형식이 올바르지 않습니다.'}, 400)

        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        session = db.update_chat_session(session_id, user_id, title=title, messages=messages)
        if not session:
            return _json_response({'success': False, 'error': '대화를 찾을 수 없습니다.'}, 404)

        return {'success': True, 'session': session.to_dict()}
    except Exception as exc:
        print(f"[CHAT] Update error: {exc}")
        return _json_response({'success': False, 'error': '대화 저장에 실패했습니다.'}, 500)


@app.delete('/api/chat/sessions/{session_id}')
def delete_chat_session(session_id: str, request: Request):
    try:
        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        deleted = db.delete_chat_session(session_id, user_id)
        if deleted:
            return {'success': True}
        return _json_response({'success': False, 'error': '대화를 찾을 수 없거나 삭제 권한이 없습니다.'}, 404)
    except Exception as exc:
        print(f"[CHAT] Delete error: {exc}")
        return _json_response({'success': False, 'error': '대화를 삭제하지 못했습니다.'}, 500)

# ============================================
# 문서 히스토리 API (IP 기반)
# ============================================

@app.get('/api/documents')
def get_user_documents(request: Request):
    """사용자의 문서 목록 조회 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request(request)
        # 리로스쿨 로그인 상태라면 리로 ID 사용
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']
            
        documents = db.get_user_documents(user_id)
        return {
            'success': True,
            'documents': [doc.to_dict() for doc in documents]
        }
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.get('/api/documents/{doc_id}')
def get_document(doc_id: int, request: Request):
    """특정 문서 조회 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        document = db.get_document(doc_id, user_id)
        if document:
            return {
                'success': True,
                'document': document.to_dict()
            }
        else:
            return _json_response({'error': '문서를 찾을 수 없습니다.'}, 404)
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.post('/api/documents')
def save_document_to_history(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """문서를 히스토리에 저장 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        title = data.get('title', '문서')
        content = data.get('content', '')
        
        if not content:
            return _json_response({'error': '내용이 비어있습니다.'}, 400)
        
        document = db.save_document(user_id, title, content)
        
        return {
            'success': True,
            'document': document.to_dict()
        }
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

@app.delete('/api/documents/{doc_id}')
def delete_document(doc_id: int, request: Request):
    """문서 삭제 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request(request)
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        deleted = db.delete_document(doc_id, user_id)
        
        if deleted:
            return {'success': True}
        else:
            return _json_response({'error': '문서를 찾을 수 없거나 삭제 권한이 없습니다.'}, 404)
    except Exception as e:
        return _json_response({'error': str(e)}, 500)

if __name__ == '__main__':
    print(CLI_BANNER)
    debug_mode = _env_flag("HWP_AGENT_DEBUG", True)
    use_reloader = _env_flag("HWP_AGENT_RELOAD", False)
    host = os.getenv("HWP_AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("HWP_AGENT_PORT", "8080"))
    # CLI: uvicorn app:app --host 0.0.0.0 --port 8080
    uvicorn.run("app:app", host=host, port=port, reload=use_reloader, log_level="debug" if debug_mode else "info")
