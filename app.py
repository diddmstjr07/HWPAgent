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
import asyncio
import contextlib
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
from modules.riroschool_crawler import RiroSchoolCrawler
from modules.email_service import (
    build_student_number_update_message,
    email_delivery_configured,
    send_email,
)
from modules.template_parser import extract_template_text, extract_template_html, SUPPORTED_TEMPLATE_EXTENSIONS
from modules import codex_auth, codex_generator
from modules.research_store import ResearchStore
from modules.preset_templates import DOCUMENT_PRESETS
from legacy.modules.hwpx_manager import HwpxManager
from urllib.parse import urlparse, parse_qs, urlencode
import fitz  # PyMuPDF
import time
import requests
import uvicorn
from dotenv import load_dotenv
from database import db
from models import (
    calculate_admission_year_from_student_number,
    calculate_current_grade,
    get_academic_year,
    parse_student_number,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
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
logging.getLogger('selenium').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

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
STUDENT_NUMBER_TOKEN_SERIALIZER = URLSafeTimedSerializer(
    APP_SECRET,
    salt='student-number-update',
)
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
STUDENT_NUMBER_REMINDER_INTERVAL_SECONDS = max(
    3600,
    int(os.getenv('STUDENT_NUMBER_REMINDER_INTERVAL_SECONDS', '86400')),
)
student_number_reminder_task = None


def _build_student_number_update_url(user_id: str, academic_year: int) -> str:
    token = STUDENT_NUMBER_TOKEN_SERIALIZER.dumps({
        'purpose': 'student-number-update',
        'user_id': str(user_id),
        'academic_year': int(academic_year),
    })
    public_base_url = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8080').rstrip('/')
    return f'{public_base_url}/student-number/update?{urlencode({"token": token})}'


def _process_student_number_reminders() -> Dict[str, int]:
    """새 학년도에 기존 학번이 남은 재학생에게 갱신 메일을 발송합니다."""
    summary = {'due': 0, 'sent': 0, 'failed': 0}
    if not email_delivery_configured():
        return summary

    academic_year = get_academic_year()
    due_users = db.get_due_student_number_reminders(academic_year)
    summary['due'] = len(due_users)

    for user in due_users:
        if not user.current_grade:
            continue
        if not db.claim_student_number_reminder(user.id, academic_year):
            continue
        try:
            message = build_student_number_update_message(
                recipient_email=user.email,
                recipient_name=user.name,
                academic_year=academic_year,
                current_grade=user.current_grade,
                update_url=_build_student_number_update_url(user.id, academic_year),
            )
            send_email(message)
            db.complete_student_number_reminder(user.id, academic_year)
            summary['sent'] += 1
        except Exception as exc:
            db.complete_student_number_reminder(user.id, academic_year, error=str(exc))
            summary['failed'] += 1
            logger.warning('[STUDENT NUMBER] Reminder delivery failed: %s', type(exc).__name__)
    return summary


async def _student_number_reminder_loop():
    while True:
        try:
            summary = await asyncio.to_thread(_process_student_number_reminders)
            if summary['due']:
                logger.info(
                    '[STUDENT NUMBER] Reminder run: due=%s sent=%s failed=%s',
                    summary['due'], summary['sent'], summary['failed']
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('[STUDENT NUMBER] Reminder job failed: %s', type(exc).__name__)
        await asyncio.sleep(STUDENT_NUMBER_REMINDER_INTERVAL_SECONDS)


@app.on_event('startup')
async def load_curriculum_dataset():
    """CurriculumDB가 비어 있으면 data/curriculum 산출물을 적재합니다."""
    def _load():
        if db.get_curriculum_subjects():
            return None
        return db.load_curriculum()

    try:
        summary = await asyncio.to_thread(_load)
    except Exception as exc:
        logger.warning('[CURRICULUM] 적재 실패: %s', exc)
        return
    if summary and not summary.get('skipped'):
        logger.info('[CURRICULUM] 과목 %s개 / 성취기준 %s건 적재',
                    summary['subjects'], summary['standards'])
    elif summary and summary.get('skipped'):
        logger.info('[CURRICULUM] data/curriculum 산출물이 없어 건너뜁니다. '
                    'tools/normalize_curriculum.py 를 먼저 실행하세요.')


@app.on_event('startup')
async def start_student_number_reminder_job():
    global student_number_reminder_task
    if not email_delivery_configured():
        logger.info('[STUDENT NUMBER] SMTP is not configured; reminder delivery is paused.')
        return
    student_number_reminder_task = asyncio.create_task(_student_number_reminder_loop())


@app.on_event('shutdown')
async def stop_student_number_reminder_job():
    global student_number_reminder_task
    if not student_number_reminder_task:
        return
    student_number_reminder_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await student_number_reminder_task
    student_number_reminder_task = None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded and request.client and _is_private_ip(request.client.host):
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


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
async def bind_codex_instance(request: Request, call_next):
    """요청마다 현재 사용자의 Codex 세션을 등록한다.

    v2_hwp_proxy처럼 request를 들고 다니지 않는 곳에서도 CodexTextGenerator가
    이 값을 읽어 ChatGPT 계정으로 생성할 수 있게 한다.
    """
    try:
        session = codex_auth.auth_session_from_request(request)
        codex_generator.set_current_instance(session['instance_id'] if session else None)
    except Exception:
        codex_generator.set_current_instance(None)
    return await call_next(request)


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


ensure_default_fonts()


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


def _validate_student_number(value: Any, expected_grade: Optional[int] = None):
    """학년·반·번호 형식의 4자리 학번을 검증합니다."""
    raw = str(value or '').strip()
    parsed = parse_student_number(raw)
    if not parsed:
        return None, None, '학번을 숫자 4자리로 입력하세요. 예: 2412 = 2학년 4반 12번'
    if expected_grade and parsed['grade'] != int(expected_grade):
        return (
            None,
            None,
            f'현재 {expected_grade}학년이므로 학번 첫 자리는 {expected_grade}이어야 합니다.'
        )
    admission_year = calculate_admission_year_from_student_number(raw)
    return parsed, admission_year, None


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
        student_number, admission_year, student_number_error = _validate_student_number(
            payload.get('student_number')
        )

        if not email or not password:
            return _json_response({'error': '이메일과 비밀번호를 입력하세요.'}, 400)
        if '@' not in email:
            return _json_response({'error': '유효한 이메일을 입력하세요.'}, 400)
        if student_number_error:
            return _json_response({'error': student_number_error, 'field': 'student_number'}, 400)

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
                last_login=datetime.now().isoformat(),
                admission_year=admission_year,
                student_number=student_number['value'],
                student_number_academic_year=get_academic_year(),
            )
        else:
            user = db.create_local_user(
                email,
                password_hash,
                display_name,
                picture,
                admission_year=admission_year,
                student_number=student_number['value'],
                student_number_academic_year=get_academic_year(),
            )

        _login_user(request, user)
        if is_new_user:
            _log_analytics_event(request, "signup", user_id=user.id)
        _log_analytics_event(request, "login", user_id=user.id)
        return {'success': True, 'user': user.to_dict()}
    except Exception as exc:
        print(f"[AUTH] register error: {exc}")
        return _json_response({'error': '계정 생성 중 오류가 발생했습니다.'}, 500)


def _load_student_number_update_token(token: str):
    if not token:
        return None, '학번 업데이트 링크가 필요합니다.'
    try:
        payload = STUDENT_NUMBER_TOKEN_SERIALIZER.loads(token, max_age=60 * 60 * 24 * 180)
    except SignatureExpired:
        return None, '학번 업데이트 링크가 만료되었습니다. 로그인 후 다시 시도해 주세요.'
    except BadSignature:
        return None, '유효하지 않은 학번 업데이트 링크입니다.'
    if payload.get('purpose') != 'student-number-update':
        return None, '유효하지 않은 학번 업데이트 링크입니다.'
    if int(payload.get('academic_year') or 0) != get_academic_year():
        return None, '지난 학년도의 업데이트 링크입니다.'
    return payload, None


@app.get('/student-number/update')
def student_number_update_page(request: Request):
    """프로필과 분리된 학번 등록/갱신 페이지입니다."""
    token = request.query_params.get('token', '')
    current_user = _get_current_user(request)
    token_error = None
    if token:
        token_payload, token_error = _load_student_number_update_token(token)
        if token_payload:
            current_user = db.get_user(str(token_payload.get('user_id')))
    if not current_user:
        if token_error:
            return templates.TemplateResponse(
                'student_number.html',
                {'request': request, 'user': None, 'token': '', 'error': token_error},
                status_code=400,
            )
        return RedirectResponse(url='/login?' + urlencode({'next': '/student-number/update'}))

    return templates.TemplateResponse(
        'student_number.html',
        {
            'request': request,
            'user': current_user,
            'token': token,
            'error': token_error,
            'current_grade': current_user.current_grade,
            'academic_year': get_academic_year(),
        },
    )


@app.put('/api/auth/student-number')
def update_student_number(request: Request, payload: Dict[str, Any] = Depends(_get_json)):
    """로그인 세션 또는 이메일의 서명된 링크로 학번을 갱신합니다."""
    current_user = _get_current_user(request)
    token = str(payload.get('token') or '').strip()
    if token:
        token_payload, token_error = _load_student_number_update_token(token)
        if token_error:
            return _json_response({'error': token_error}, 400)
        current_user = db.get_user(str(token_payload.get('user_id')))
    if not current_user:
        return _json_response({'error': '로그인 또는 유효한 업데이트 링크가 필요합니다.'}, 401)

    student_number, derived_admission_year, student_number_error = _validate_student_number(
        payload.get('student_number'),
        expected_grade=current_user.current_grade,
    )
    if student_number_error:
        return _json_response({'error': student_number_error, 'field': 'student_number'}, 400)

    admission_year = current_user.admission_year or derived_admission_year
    updated_user = db.update_user_student_number(
        current_user.id,
        student_number['value'],
        admission_year,
        get_academic_year(),
    )
    return {'success': True, 'user': updated_user.to_dict()}


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
    """현재 세션 로그아웃.

    ChatGPT 연결이 곧 로그인이므로 앱 세션만 비우면 안 된다. Codex 연결까지
    끊지 않으면 인증 쿠키의 instance_id가 남아 다음 로그인에서 기기 코드 창이
    뜨지 않고 이전 계정으로 곧장 되돌아간다(다른 계정으로 못 바꿈).
    """
    try:
        _logout_user(request)
        return codex_auth.disconnect(request, _json_response({'success': True}))
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
riro_sessions = {}


def _chat_user_id(request: Request) -> str:
    """대화 목록의 주인을 정합니다.

    앱 로그인이 있으면 그 계정이 주인이다. 리로스쿨 학번으로 갈아타서는 안 된다 —
    설계·실험 대화는 앱 계정(request.session['user_id'])으로 저장되기 때문에,
    리로 연동만으로 주인이 바뀌면 그동안의 대화가 목록에서 통째로 사라진다.
    실제로 그렇게 사라졌다: 사이드바 History의 설계·실험 폴더가 둘 다 0이 됐다.

    리로 학번은 앱 로그인이 없을 때만 쓴다. 그때는 IP로 임시 식별되는데,
    그것보다는 학번이 그나마 안정적인 이름이다.
    """
    user_id = get_user_id_from_request(request)
    if _get_current_user(request):
        return user_id
    payload = riro_sessions.get(user_id)
    riro_id = (payload or {}).get('riro_id')
    return str(riro_id) if riro_id else user_id


def _legacy_chat_user_id(request: Request) -> Optional[str]:
    """리로 학번으로 저장돼 버린 옛 대화의 주인.

    위 규칙을 바로잡기 전에 만들어진 대화는 학번 아래에 남아 있다. 읽기(목록·열기)에서만
    함께 봐준다. 새로 만드는 대화는 앱 계정으로만 저장한다.
    """
    if not _get_current_user(request):
        return None
    payload = riro_sessions.get(get_user_id_from_request(request))
    riro_id = (payload or {}).get('riro_id')
    return str(riro_id) if riro_id else None






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


# 온보딩 완료 여부를 판단하기 위한 스토어. 라우터의 것과 같은 db를 공유한다.
research_store = ResearchStore(db)






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

@app.get('/research', name='research_page')
def research_page(request: Request):
    """3년 연구 서사 로드맵"""
    return templates.TemplateResponse('research.html', {'request': request})

@app.get('/experiment/{plan_id}', name='experiment_page')
def experiment_page(plan_id: int, request: Request):
    """실험 전용 페이지는 없어졌다. 실험은 메인(/) 채팅방에서 진행한다.

    예전 주소를 눌러 들어온 학생을 그 실험 대화방으로 넘겨준다.
    """
    user_id = request.session.get('user_id')
    plan = research_store.get_subject_plan(user_id, plan_id) if user_id else None
    if plan and plan.experiment_chat_id:
        return RedirectResponse(f'/?chat={plan.experiment_chat_id}', status_code=302)
    return RedirectResponse('/research', status_code=302)

@app.get('/editor', name='editor_page')
def editor_page(request: Request):
    """HWP 에디터(rhwp-studio). 브라우저 WASM으로 문서를 열고 편집한다.

    /editor?file=<output의 파일명> 으로 오면 그 문서를 열어 준다.
    실험 보고서에서 "편집기에서 열기"로 넘어오는 길이다.
    """
    query = request.url.query
    target = '/static/hwp-studio/index.html'
    return RedirectResponse(f'{target}?{query}' if query else target, status_code=302)

@app.get('/welcome', name='welcome_page')
def welcome_page(request: Request):
    """가입 직후 프로파일을 만드는 온보딩"""
    current_user = _get_current_user(request)
    if not current_user:
        return RedirectResponse('/login?next=/welcome', status_code=302)
    # 이미 프로파일이 있으면 온보딩을 다시 보여주지 않는다.
    if research_store.get_profile(current_user.id):
        return RedirectResponse('/', status_code=302)
    return templates.TemplateResponse('welcome.html', {'request': request})

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
        if not school or not username or not password:
            return _json_response({
                'success': False,
                'error': '학교명, 아이디, 비밀번호를 모두 입력해주세요.'
            }, 400)
        
        current_user = _get_current_user(request)
        if not current_user:
            return _json_response({
                'success': False,
                'error': '리로스쿨 연동 전에 회원 로그인이 필요합니다.'
            }, 401)
        if not current_user.admission_year or current_user.current_grade is None:
            return _json_response({
                'success': False,
                'error': '현재 학년을 계산할 학번 정보가 필요합니다.',
                'code': 'STUDENT_NUMBER_REQUIRED',
                'setup_url': '/student-number/update',
            }, 400)

        grade = str(current_user.current_grade)
        year = str(get_academic_year())
        print(f"[RIRO API] Login request - School: {school}, Academic year: {year}, Grade: {grade}")
        user_id = str(current_user.id)
        
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
            result['academic_year'] = int(year)
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


























# ============================================
# HWP v2 프록시 엔드포인트 (Node 서버와 통신)
# ============================================

from v2_hwp_proxy import router as hwp_v2_router

app.include_router(hwp_v2_router)

# ChatGPT(Codex) 기기 코드 로그인
app.include_router(codex_auth.router)

# 연구 서사(Research Narrative)
from modules.research_router import router as research_router

app.include_router(research_router)

# 테스트 시드(개발 전용). DEV_TEST_ROUTES=1 일 때만 실제로 응답한다.
from modules.test_router import router as test_router, page_router as test_page_router

app.include_router(test_router)
app.include_router(test_page_router)








@app.get('/api/download/{filename:path}')
def download_file(filename: str):
    """파일 다운로드"""
    try:
        print(f"[DOWNLOAD] Requested file: {filename}")
        file_path = Path('output') / filename
        # output/ 밖으로 나가는 경로(../.env 등)는 파일이 있어도 내주지 않는다.
        if not file_path.resolve().is_relative_to(Path('output').resolve()):
            return _json_response({'error': '파일을 찾을 수 없습니다.'}, 404)
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
        user_id = _chat_user_id(request)
        sessions = db.get_chat_sessions(user_id)

        # 학번 아래 남아 있는 옛 대화도 같이 보여준다. 규칙을 바로잡았다고
        # 이미 만들어 둔 대화가 사라지면 그것도 똑같이 없어진 것으로 보인다.
        legacy_id = _legacy_chat_user_id(request)
        if legacy_id and legacy_id != user_id:
            sessions = sorted(
                sessions + db.get_chat_sessions(legacy_id),
                key=lambda session: session.updated_at or '',
                reverse=True,
            )

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

        user_id = _chat_user_id(request)

        session = db.create_chat_session(user_id, title, messages)
        return _json_response({'success': True, 'session': session.to_dict()}, 201)
    except Exception as exc:
        print(f"[CHAT] Create error: {exc}")
        return _json_response({'success': False, 'error': '대화 저장에 실패했습니다.'}, 500)


@app.get('/api/chat/sessions/{session_id}')
def get_chat_session(session_id: str, request: Request):
    try:
        user_id = _chat_user_id(request)

        session = db.get_chat_session(session_id, user_id)
        if not session:
            # 목록에 함께 보여준 옛 대화(학번 소유)는 열리기도 해야 한다.
            legacy_id = _legacy_chat_user_id(request)
            if legacy_id and legacy_id != user_id:
                session = db.get_chat_session(session_id, legacy_id)
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

        user_id = _chat_user_id(request)

        session = db.update_chat_session(session_id, user_id, title=title, messages=messages)
        if not session:
            # 옛 대화를 이어서 쓰는 경우. 주인을 옮기지는 않고 그 자리에 그대로 쌓는다.
            legacy_id = _legacy_chat_user_id(request)
            if legacy_id and legacy_id != user_id:
                session = db.update_chat_session(session_id, legacy_id,
                                                 title=title, messages=messages)
        if not session:
            return _json_response({'success': False, 'error': '대화를 찾을 수 없습니다.'}, 404)

        return {'success': True, 'session': session.to_dict()}
    except Exception as exc:
        print(f"[CHAT] Update error: {exc}")
        return _json_response({'success': False, 'error': '대화 저장에 실패했습니다.'}, 500)


@app.delete('/api/chat/sessions/{session_id}')
def delete_chat_session(session_id: str, request: Request):
    try:
        user_id = _chat_user_id(request)

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
        # 리로스쿨 로그인 상태라면 리로 ID 사용
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
        # 리로스쿨 로그인 상태라면 리로 ID 사용
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
        # 리로스쿨 로그인 상태라면 리로 ID 사용
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
