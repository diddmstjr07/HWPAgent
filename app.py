#!/usr/bin/env python3
"""
HWP Agent Web App - ChatGPT Canvas 스타일의 실시간 문서 편집기
"""
from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context, abort, send_from_directory, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os
import json
import io
import base64
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from modules import HWPAgent
from modules.docx_handler import DOCXHandler
from modules.pdf_handler import PDFHandler
from modules.format_adjuster import FormatAdjuster
from modules.image_searcher import ImageSearcher
from modules.riroschool_crawler import RiroSchoolCrawler
from modules.template_parser import extract_template_text, SUPPORTED_TEMPLATE_EXTENSIONS
from urllib.parse import urlparse, parse_qs
import fitz  # PyMuPDF
import time
import requests
from dotenv import load_dotenv
from database import db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
CORS(app, supports_credentials=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'
login_manager.session_protection = 'strong'


@login_manager.user_loader
def load_user(user_id):
    return db.get_user(user_id)

BLOCKED_IPS = {"61.52.38.120"}


def _get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


@app.before_request
def block_blocklisted_ips():
    client_ip = _get_client_ip()
    if client_ip in BLOCKED_IPS:
        abort(403)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR = OUTPUT_DIR / "templates"
FONT_DIR = OUTPUT_DIR / "fonts"
IMAGE_DIR = OUTPUT_DIR / "images"
TEMPLATE_DIR.mkdir(exist_ok=True)
FONT_DIR.mkdir(exist_ok=True)
IMAGE_DIR.mkdir(exist_ok=True)
IMAGE_CACHE_DIR = IMAGE_DIR / "cache"
IMAGE_CACHE_DIR.mkdir(exist_ok=True)


def ensure_default_fonts():
    for preset in FONT_PRESETS:
        target = FONT_DIR / preset['filename']
        if target.exists():
            continue
        try:
            print(f"[FONT] Downloading {preset['display_name']}...")
            response = requests.get(preset['url'], timeout=45)
            response.raise_for_status()
            target.write_bytes(response.content)
            print(f"[FONT] ✅ Saved {preset['display_name']}")
        except Exception as exc:
            print(f"[FONT] ❌ Failed to download {preset['display_name']}: {exc}")


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
def get_user_id_from_request():
    """세션 또는 IP 주소를 기반으로 사용자 ID 생성"""
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            return str(current_user.id)
    except Exception:
        pass
    ip = request.remote_addr or 'unknown'
    # X-Forwarded-For 헤더 확인 (프록시 후방 대응)
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return f"user_{ip.replace('.', '_').replace(':', '_')}"


def _normalize_email(value: str) -> str:
    return str(value or '').strip().lower()


# ============================================
# 인증/세션 API
# ============================================

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    """이메일/비밀번호 기반 계정 생성"""
    try:
        payload = request.get_json(silent=True) or {}
        email = _normalize_email(payload.get('email'))
        password = payload.get('password') or ''
        name = (payload.get('name') or '').strip()

        if not email or not password:
            return jsonify({'error': '이메일과 비밀번호를 입력하세요.'}), 400
        if '@' not in email:
            return jsonify({'error': '유효한 이메일을 입력하세요.'}), 400

        existing = db.get_user_credentials(email)
        if existing and existing.get('password_hash'):
            return jsonify({'error': '이미 가입된 이메일입니다.'}), 400

        password_hash = generate_password_hash(password)
        display_name = name or (existing.get('name') if existing else '') or email.split('@')[0]
        picture = payload.get('picture') or (existing.get('picture') if existing else None)

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

        login_user(user)
        return jsonify({'success': True, 'user': user.to_dict()})
    except Exception as exc:
        print(f"[AUTH] register error: {exc}")
        return jsonify({'error': '계정 생성 중 오류가 발생했습니다.'}), 500


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    """이메일/비밀번호 로그인"""
    try:
        payload = request.get_json(silent=True) or {}
        email = _normalize_email(payload.get('email'))
        password = payload.get('password') or ''

        if not email or not password:
            return jsonify({'error': '이메일과 비밀번호를 입력하세요.'}), 400

        record = db.get_user_credentials(email)
        if not record or not record.get('password_hash'):
            return jsonify({'error': '이메일 또는 비밀번호가 올바르지 않습니다.'}), 401
        if not check_password_hash(record['password_hash'], password):
            return jsonify({'error': '이메일 또는 비밀번호가 올바르지 않습니다.'}), 401

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

        login_user(user)
        return jsonify({'success': True, 'user': user.to_dict()})
    except Exception as exc:
        print(f"[AUTH] login error: {exc}")
        return jsonify({'error': '로그인 처리 중 문제가 발생했습니다.'}), 500


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """현재 세션 로그아웃"""
    try:
        logout_user()
        return jsonify({'success': True})
    except Exception as exc:
        print(f"[AUTH] logout error: {exc}")
        return jsonify({'error': '로그아웃에 실패했습니다.'}), 500


@app.route('/api/auth/me', methods=['GET'])
def whoami():
    """세션 확인용"""
    if current_user and getattr(current_user, "is_authenticated", False):
        return jsonify({'authenticated': True, 'user': current_user.to_dict()})
    return jsonify({'authenticated': False})

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


def _build_riro_context_text(user_id: Optional[str] = None) -> Optional[str]:
    """리로스쿨 세션의 수행평가/과제 정보를 요약하여 텍스트로 반환"""
    lookup_id = user_id or get_user_id_from_request()
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

@app.route('/')
@app.route('/index.html')
def index():
    """메인 페이지"""
    return render_template('index.html')


@app.route('/login')
def login_page():
    """독립 로그인 페이지"""
    if current_user and getattr(current_user, "is_authenticated", False):
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/offline.html')
def offline():
    """오프라인용 단순 페이지"""
    return render_template('offline.html')

@app.route('/manifest.json')
def manifest():
    """PWA manifest 파일"""
    response = send_from_directory('static', 'manifest.json')
    response.headers['Cache-Control'] = 'no-cache'
    response.mimetype = 'application/manifest+json'
    return response

@app.route('/icons/<path:filename>')
def pwa_icons(filename):
    """PWA 아이콘 전달"""
    icon_dir = Path(app.static_folder) / "icons"
    return send_from_directory(icon_dir, filename)

@app.route('/service-worker.js')
def service_worker():
    """서비스 워커 스크립트"""
    response = send_from_directory('static', 'service-worker.js')
    response.headers['Cache-Control'] = 'no-cache'
    response.mimetype = 'application/javascript'
    return response

@app.route('/bet')
def bet_page():
    """달팽이 경주 토토 페이지"""
    return render_template('bet.html')

@app.route('/riroschool')
def riroschool_page():
    """리로스쿨 계정 입력 페이지"""
    return render_template('riroschool.html')

@app.route('/riroschool/docs')
def riroschool_docs_page():
    """리로스쿨 문서 목록 페이지"""
    return render_template('riro_docs.html')

@app.route('/riroschool/docs/<int:doc_id>')
def riroschool_doc_detail_page(doc_id):
    """리로스쿨 문서 상세 페이지"""
    return render_template('riro_doc_view.html', doc_id=doc_id)

@app.route('/api/riroschool/login', methods=['POST'])
def riroschool_login():
    """리로스쿨 로그인 및 이벤트 가져오기"""
    try:
        data = request.json
        school = data.get('school', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        grade = data.get('grade', '1')
        year = data.get('year', '2025')
        
        if not school or not username or not password:
            return jsonify({
                'success': False,
                'error': '학교명, 아이디, 비밀번호를 모두 입력해주세요.'
            }), 400
        
        print(f"[RIRO API] Login request - School: {school}, User: {username}, Grade: {grade}")
        user_id = get_user_id_from_request()
        
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
        
        return jsonify(result)
        
    except Exception as e:
        print(f"[RIRO API ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/riroschool/guide', methods=['POST'])
def riroschool_guide():
    """리로스쿨 일정에서 과제 가이드라인 추출"""
    try:
        payload = request.json or {}
        events = payload.get('events') or []
        event_url = payload.get('eventUrl')
        date = payload.get('date')
        user_id = get_user_id_from_request()
        session_payload = riro_sessions.get(user_id)
        
        if not session_payload:
            return jsonify({'success': False, 'error': '로그인 세션이 만료되었습니다.'}), 401
        
        if not event_url:
            for event in events:
                candidate = (event or {}).get('url') or (event or {}).get('link')
                if candidate:
                    event_url = candidate
                    break
        
        if not event_url and not date:
            return jsonify({'success': False, 'error': '가져올 이벤트 URL이 없습니다.'}), 400
        
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
            return jsonify({'success': False, 'error': '가이드 라인이 없습니다.'})
        
        return jsonify({
            'success': True,
            'guide': guide_entry.get('guide', '').strip(),
            'source': guide_entry.get('source', event_url)
        })
    except Exception as exc:
        print(f"[RIRO GUIDE ERROR] {exc}")
        return jsonify({'success': False, 'error': str(exc)}), 500

@app.route('/api/riroschool/logout', methods=['POST'])
def riroschool_logout():
    """리로스쿨 세션 초기화"""
    user_id = get_user_id_from_request()
    if user_id in riro_sessions:
        riro_sessions.pop(user_id, None)
    return jsonify({'success': True})

@app.route('/api/riroschool/documents', methods=['GET'])
def riro_documents_list():
    """리로스쿨 사용자 문서 목록"""
    user_id = get_user_id_from_request()
    session_payload = riro_sessions.get(user_id)
    if not session_payload:
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 401
    docs = db.get_riro_documents(session_payload['riro_id'])
    return jsonify({
        'success': True,
        'documents': [doc.to_dict() for doc in docs]
    })

@app.route('/api/riroschool/documents', methods=['POST'])
def riro_documents_save():
    """리로스쿨 사용자 문서 저장"""
    user_id = get_user_id_from_request()
    session_payload = riro_sessions.get(user_id)
    if not session_payload:
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 401
    data = request.json or {}
    title = (data.get('title') or '문서').strip()
    content = (data.get('content') or '').strip()
    image_urls = data.get('image_urls') or []
    if not content:
        return jsonify({'success': False, 'error': '내용이 비어있습니다.'}), 400
    doc = db.save_riro_document(session_payload['riro_id'], title, content, image_urls)
    return jsonify({'success': True, 'document': doc.to_dict()})

@app.route('/api/riroschool/documents/<int:doc_id>', methods=['GET'])
def riro_documents_detail(doc_id):
    user_id = get_user_id_from_request()
    session_payload = riro_sessions.get(user_id)
    if not session_payload:
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 401
    doc = db.get_riro_document(doc_id, session_payload['riro_id'])
    if not doc:
        return jsonify({'success': False, 'error': '문서를 찾을 수 없습니다.'}), 404
    return jsonify({'success': True, 'document': doc.to_dict()})


@app.route('/api/template/upload', methods=['POST'])
def upload_template():
    """문서 양식 파일 업로드 및 텍스트 추출"""
    try:
        file = request.files.get('template')
        if not file or not file.filename:
            return jsonify({'success': False, 'error': '업로드할 파일을 선택해주세요.'}), 400
        original_name = file.filename
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_TEMPLATE_EXTENSIONS:
            return jsonify({
                'success': False,
                'error': '지원하지 않는 파일 형식입니다. (.docx, .hwp, .pdf, .txt, .md)'
            }), 400

        safe_stem = secure_filename(Path(original_name).stem) or 'template'
        filename = f"{safe_stem}{suffix}"

        timestamp = int(time.time() * 1000)
        save_path = TEMPLATE_DIR / f"{timestamp}_{filename}"
        file.save(save_path)

        try:
            template_text = extract_template_text(save_path)
        except ValueError as exc:
            if save_path.exists():
                save_path.unlink()
            return jsonify({'success': False, 'error': str(exc)}), 400

        return jsonify({
            'success': True,
            'template_name': filename,
            'template_id': save_path.stem,
            'template_text': template_text,
            'template_file': str(save_path)
        })
    except Exception as exc:
        print(f"[TEMPLATE] Upload failed: {exc}")
        return jsonify({'success': False, 'error': '템플릿 업로드 중 오류가 발생했습니다.'}), 500


@app.route('/api/font/upload', methods=['POST'])
def upload_font():
    """사용자 지정 폰트 업로드"""
    try:
        font_file = request.files.get('font')
        if not font_file or not font_file.filename:
            return jsonify({'success': False, 'error': '업로드할 폰트를 선택해주세요.'}), 400

        suffix = Path(font_file.filename).suffix.lower()
        if suffix not in {'.ttf', '.otf'}:
            return jsonify({'success': False, 'error': 'TTF 또는 OTF 형식만 지원합니다.'}), 400

        safe_stem = secure_filename(Path(font_file.filename).stem) or 'font'
        timestamp = int(time.time() * 1000)
        save_path = FONT_DIR / f"{timestamp}_{safe_stem}{suffix}"
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        font_file.save(save_path)

        display_name = request.form.get('fontName') or Path(font_file.filename).stem

        return jsonify({
            'success': True,
            'font_id': save_path.stem,
            'font_name': display_name,
            'font_path': str(save_path)
        })
    except Exception as exc:
        print(f"[FONT] Upload failed: {exc}")
        return jsonify({'success': False, 'error': '폰트 업로드 중 오류가 발생했습니다.'}), 500


@app.route('/api/fonts', methods=['GET'])
def get_fonts():
    try:
        fonts = list_available_fonts()
        return jsonify({'success': True, 'fonts': fonts})
    except Exception as exc:
        print(f"[FONT] Catalog error: {exc}")
        return jsonify({'success': False, 'error': '폰트 목록을 불러오지 못했습니다.'}), 500


@app.route('/api/formats', methods=['GET'])
def get_available_formats():
    return jsonify({'success': True, 'formats': EXPORT_FORMATS})

@app.route('/api/interact', methods=['POST'])
def interact_auto():
    """자동 의도 파악 및 스트리밍"""
    try:
        data = request.json
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []  # 대화 기록 추출
        user_id = get_user_id_from_request()
        riro_context_text = _build_riro_context_text(user_id)
        
        if not user_request:
             return jsonify({'error': '요청 내용을 입력해주세요.'}), 400

        def generate():
            # 1. 의도 파악 (템플릿이 있어도 사용자의 요청에 따라 판단)
            try:
                intent = agent.content_generator.classify_intent(user_request)
            except Exception as e:
                print(f"[INTENT ERROR] {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

            print(f"[INTENT DETECTED] {intent}")
            
            # 2. 모드 정보 전송
            yield f"data: {json.dumps({'type': 'mode', 'mode': intent})}\n\n"
            
            # 3. 해당 모드로 스트리밍 위임
            if intent == "document":
                # 문서 생성 시에도 이전 대화 맥락을 context로 주입
                history_text = ""
                if chat_history:
                    # 최근 10개 대화만
                    recent_history = chat_history[-10:]
                    history_text = "\n".join([f"[{msg.get('role', 'user')}]: {msg.get('text', '')}" for msg in recent_history])

                context_data = {'previous_conversation': history_text}
                if riro_context_text:
                    context_data['riroschool_assignments'] = riro_context_text
                if riro_context_text:
                    context_data['riroschool_assignments'] = riro_context_text

                full_text = ""
                chunk_count = 0
                try:
                    stream = agent.content_generator.generate_document_content(
                        user_request,
                        context=context_data, # 컨텍스트 전달
                        stream=True,
                        document_template=document_template
                    )
                    
                    for chunk in stream:
                        if chunk:
                            full_text += chunk
                            chunk_count += 1
                            yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                    
                    # 파싱 및 완료 처리
                    parsed = agent.content_generator._parse_generated_content(full_text)
                    final_result = {
                        'title': parsed.get('title', '문서'),
                        'body': full_text,
                        'images_needed': parsed.get('images_needed', []),
                        'tables_needed': parsed.get('tables_needed', [])
                    }
                    yield f"data: {json.dumps({'done': True, 'result': final_result})}\n\n"
                    
                except Exception as e:
                    print(f"[DOC STREAM ERROR] {str(e)}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
            else:
                # 채팅 모드: 히스토리 전달
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
                    stream = agent.content_generator.generate_chat_stream(chat_prompt, history=chat_history)
                    for chunk in stream:
                        if chunk:
                            full_text += chunk
                            yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                    yield f"data: {json.dumps({'done': True, 'result': {'body': full_text}})}\n\n"
                except Exception as e:
                    print(f"[CHAT STREAM ERROR] {str(e)}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        print(f"[ERROR] interact endpoint failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate', methods=['POST'])
def generate_content():
    """AI 콘텐츠 생성"""
    try:
        data = request.json
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request()
        riro_context_text = _build_riro_context_text(user_id)

        if not user_request:
            if document_template:
                user_request = "제공된 문서 양식의 모든 항목을 알맞은 내용으로 채워 완성된 문서를 작성하세요."
            else:
                return jsonify({'error': '요청 내용 또는 양식을 입력해주세요.'}), 400
        
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
            return jsonify({'error': result.get('error', 'Unknown error')}), 500
            
        return jsonify({
            'success': True,
            'title': result.get('title', ''),
            'body': result.get('body', ''),
            'images_needed': result.get('images_needed', []),
            'tables_needed': result.get('tables_needed', [])
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-stream', methods=['POST'])
def generate_content_stream():
    """스트리밍 AI 콘텐츠 생성"""
    try:
        data = request.json
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request()
        riro_context_text = _build_riro_context_text(user_id)

        if not user_request:
            if document_template:
                user_request = "제공된 문서 양식을 기반으로 모든 항목을 충실하게 작성하세요."
            else:
                return jsonify({'error': '요청 내용 또는 양식을 입력해주세요.'}), 400
        
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
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
        
    except Exception as e:
        print(f"[ERROR] API endpoint failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat-stream', methods=['POST'])
def chat_stream():
    """프리픽스 없이 채팅형 응답 스트리밍"""
    try:
        data = request.json
        user_request = (data.get('request') or '').strip()
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request()
        riro_context_text = _build_riro_context_text(user_id)
        
        if not user_request:
            return jsonify({'error': '요청 내용을 입력해주세요.'}), 400

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

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
    except Exception as e:
        print(f"[ERROR] chat_stream failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/save', methods=['POST'])
def save_document():
    """문서 저장 (이미지 자동 검색 및 삽입 포함)"""
    try:
        data = request.json
        title = data.get('title', '문서')
        content = data.get('content', '')
        format_type = data.get('format', 'docx')
        style_config = normalize_style_config(data.get('style'))
        template_file = (data.get('template_file') or '').strip()
        images_needed = data.get('images_needed', [])  # AI가 제안한 이미지 키워드들
        image_urls = data.get('image_urls', [])  # 프론트엔드에서 검색한 이미지 URL
        
        # 디버깅: 받은 콘텐츠 길이 로그
        print(f"[DEBUG] Save request - Title: {title}")
        print(f"[DEBUG] Content length: {len(content)} characters")
        print(f"[DEBUG] Content preview (first 200 chars): {content[:200]}...")
        print(f"[DEBUG] Content preview (last 200 chars): ...{content[-200:]}")
        print(f"[DEBUG] Images needed: {images_needed}")
        print(f"[DEBUG] Image URLs from frontend: {len(image_urls)} URLs")
        
        if not content:
            return jsonify({'error': '내용이 비어있습니다.'}), 400

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
        if treat_images_as_text:
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
        if format_type == 'pdf':
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
            # HWP는 DOCX를 확장자만 .hwp로 변경하여 저장 (이미지 포함)
            temp_path = docx_handler.create_document(
                title=title,
                content=content,
                style_config=style_config,
                images=downloaded_images if downloaded_images else None,
                filename=f"{title}_temp.docx",
                template_path=template_path
            )
            # 확장자를 .hwp로 변경
            import shutil
            from pathlib import Path
            hwp_path = Path('output') / f"{title}.hwp"
            shutil.copy2(temp_path, hwp_path)
            Path(temp_path).unlink()  # 임시 파일 삭제
            file_path = str(hwp_path)
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
        
        return jsonify({
            'success': True,
            'file_path': file_path,
            'format': format_type,
            'images_count': len(downloaded_images)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refine', methods=['POST'])
def refine_content():
    """콘텐츠 수정/개선"""
    try:
        data = request.json
        original_content = data.get('content', '')
        refinement_request = data.get('request', '')
        
        if not original_content or not refinement_request:
            return jsonify({'error': '내용과 수정 요청을 입력해주세요.'}), 400
        
        # 콘텐츠 수정
        refined = agent.content_generator.refine_content(
            original_content,
            refinement_request
        )
        
        return jsonify({
            'success': True,
            'content': refined
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refine-stream', methods=['POST'])
def refine_content_stream():
    """콘텐츠 수정/개선 (스트리밍)"""
    try:
        data = request.json
        original_content = data.get('content', '')
        refinement_request = data.get('request', '')
        
        if not original_content or not refinement_request:
            def error_stream():
                yield f"data: {{\"error\": \"내용과 수정 요청을 입력해주세요.\"}}\n\n"
            return Response(error_stream(), mimetype='text/event-stream')
        
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
        
        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/adjust-format', methods=['POST'])
def adjust_format():
    """서식 조정 (자연어 요청 기반)"""
    try:
        data = request.json
        content = data.get('content', '')
        format_request = data.get('request', '')
        
        if not content or not format_request:
            return jsonify({'error': '내용과 서식 조정 요청을 입력해주세요.'}), 400
        
        print(f"[FORMAT ADJUST] Request: {format_request}")
        print(f"[FORMAT ADJUST] Content length: {len(content)}")
        
        # 서식 조정
        adjusted = format_adjuster.adjust_format(content, format_request)
        
        print(f"[FORMAT ADJUST] Adjusted length: {len(adjusted)}")
        
        return jsonify({
            'success': True,
            'content': adjusted
        })
        
    except Exception as e:
        print(f"[FORMAT ADJUST ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<path:filename>')
def download_file(filename):
    """파일 다운로드"""
    try:
        print(f"[DOWNLOAD] Requested file: {filename}")
        file_path = Path('output') / filename
        print(f"[DOWNLOAD] Full path: {file_path}")
        print(f"[DOWNLOAD] File exists: {file_path.exists()}")
        
        if file_path.exists():
            print(f"[DOWNLOAD] Sending file: {file_path}")
            return send_file(file_path, as_attachment=True)
        else:
            print(f"[DOWNLOAD ERROR] File not found: {file_path}")
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404
    except Exception as e:
        print(f"[DOWNLOAD ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/view-pdf/<path:filename>')
def view_pdf(filename):
    """파일 보기 (브라우저에서 열기)"""
    try:
        file_path = Path('output') / filename
        if file_path.exists():
            return send_file(file_path, mimetype='application/pdf')
        else:
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/search-images', methods=['POST'])
def search_images():
    """이미지 검색 API"""
    try:
        data = request.json
        query = data.get('query', '')
        count = int(data.get('count', 3) or 3)

        if not query:
            return jsonify({'success': False, 'error': '검색 키워드를 입력해주세요.'}), 400

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
            return jsonify({
                'success': False,
                'error': 'Google 이미지에서 해당 키워드의 이미지를 찾지 못했습니다.'
            }), 200

        return jsonify({
            'success': True,
            'query': query,
            'count': len(enriched_images),
            'images': enriched_images
        })

    except Exception as e:
        print(f"[ERROR] search_images: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/search-images/test', methods=['GET'])
def search_images_test():
    """수동 테스트용 이미지 검색 (query 파라미터)"""
    try:
        query = request.args.get('query') or request.args.get('q') or ''
        count = int(request.args.get('count') or 3)
        count = max(1, min(count, 10))

        if not query:
            return jsonify({
                'success': False,
                'error': 'query 파라미터를 입력하세요.',
                'usage': '/api/search-images/test?query=검색어&count=3'
            }), 400

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

        return jsonify({
            'success': True,
            'query': query,
            'count': len(enriched_images),
            'images': enriched_images
        })
    except Exception as e:
        print(f"[ERROR] search_images_test: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/pdf-to-images/<path:filename>')
def pdf_to_images(filename):
    """파일 PDF를 이미지로 변환하여 JSON으로 반환"""
    try:
        file_path = Path('output') / filename
        if not file_path.exists():
            return jsonify({'error': '파일을 찾을 수 없습니다.'}), 404
        
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
        
        return jsonify({
            'success': True,
            'pages': len(images),
            'images': images
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# IP 기반 사용자 API
# ============================================

@app.route('/api/user-id')
def get_user_id():
    """현재 사용자의 IP 기반 ID 반환"""
    user_id = get_user_id_from_request()
    return jsonify({
        'success': True,
        'user_id': user_id
    })

# ============================================
# 문서 히스토리 API (IP 기반)
# ============================================

@app.route('/api/documents', methods=['GET'])
def get_user_documents():
    """사용자의 문서 목록 조회 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request()
        # 리로스쿨 로그인 상태라면 리로 ID 사용
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']
            
        documents = db.get_user_documents(user_id)
        return jsonify({
            'success': True,
            'documents': [doc.to_dict() for doc in documents]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<int:doc_id>', methods=['GET'])
def get_document(doc_id):
    """특정 문서 조회 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request()
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        document = db.get_document(doc_id, user_id)
        if document:
            return jsonify({
                'success': True,
                'document': document.to_dict()
            })
        else:
            return jsonify({'error': '문서를 찾을 수 없습니다.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents', methods=['POST'])
def save_document_to_history():
    """문서를 히스토리에 저장 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request()
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        data = request.json
        title = data.get('title', '문서')
        content = data.get('content', '')
        
        if not content:
            return jsonify({'error': '내용이 비어있습니다.'}), 400
        
        document = db.save_document(user_id, title, content)
        
        return jsonify({
            'success': True,
            'document': document.to_dict()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<int:doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """문서 삭제 (IP 기반 또는 리로스쿨 ID 기반)"""
    try:
        user_id = get_user_id_from_request()
        if user_id in riro_sessions:
            user_id = riro_sessions[user_id]['riro_id']

        deleted = db.delete_document(doc_id, user_id)
        
        if deleted:
            return jsonify({'success': True})
        else:
            return jsonify({'error': '문서를 찾을 수 없거나 삭제 권한이 없습니다.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("""
╭════════════════════════════════════════════════════════════╮
║                                                            ║
║   🚀 HWP Agent - 실시간 문서 편집기                             ║
║   ChatGPT Canvas 스타일의 웹 기반 인터페이스                      ║
║                                                            ║
║   📝 브라우저에서 접속: http://localhost:8080                   ║
║   🔐 Google OAuth 로그인 기능 활성화                          ║
║                                                            ║
╰════════════════════════════════════════════════════════════╯
    """)
    app.run(debug=True, host='0.0.0.0', port=8080)
