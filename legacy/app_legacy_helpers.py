"""레거시 문서 생성과 함께 쓸모가 없어진 app.py 보조 함수들. 2026-07-29 제거."""

def _is_local_request(request: Request) -> bool:
    client_ip = _get_client_ip(request)
    if not client_ip:
        return False
    try:
        return ipaddress.ip_address(client_ip).is_loopback
    except ValueError:
        return client_ip in {"localhost"}

def _parse_env_list(name: str) -> List[str]:
    value = os.getenv(name, "")
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]

def _admin_access_allowed(request: Request) -> bool:
    return _admin_access_check(request)[0]

def _hwpx_manager_path(session_id: str) -> Path:
    return _hwpx_session_dir(session_id) / "mgr.pkl"

def _hwpx_extract_dir(session_id: str) -> Path:
    return _hwpx_session_dir(session_id) / "hwpx"

def _convert_hwp_to_hwpx(hwp_path: Path, hwpx_path: Path) -> None:
    commands = [
        ["hwp5proc", "--format", "hwpx", "--output", str(hwpx_path), str(hwp_path)],
        ["hwp5proc", str(hwp_path), str(hwpx_path)],
    ]
    last_error = None
    for command in commands:
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            if hwpx_path.exists():
                return
            last_error = RuntimeError(result.stderr.strip() or "hwp5proc failed")
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error) if last_error else "hwp5proc conversion failed")

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

def _codex_instance_id(request: Request) -> Optional[str]:
    """ChatGPT 계정이 연결된 요청이면 Runner 세션 식별자를 반환합니다."""
    session = codex_auth.auth_session_from_request(request)
    if not session:
        return None
    instance_id = session['instance_id']
    return instance_id if codex_generator.is_available(instance_id) else None

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
