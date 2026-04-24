"""Archived FastAPI route implementations from the legacy hwp5/HWPX HTML pipeline.

These functions are intentionally not registered on the live FastAPI app during the
@rhwp/core migration. They are preserved here for reference only; the active
routes in app.py return HTTP 501 until v2 endpoints are wired.
"""

# NOTE: This file is not imported by app.py.
# It preserves the original function bodies for these routes:
# - POST /upload
# - POST /save
# - POST /api/template/upload
# - GET /api/template/asset/{template_id}/{asset_path:path}
# - POST /api/template/select
# - POST /api/edit-html
# - POST /api/edit-fragment

@app.post('/upload')
def upload_hwpx(template: Optional[UploadFile] = File(None)):
    """Upload .hwp/.hwpx, convert to HWPX, map nodes, and return HTML."""
    try:
        if not template or not template.filename:
            return _json_response({'success': False, 'error': '업로드할 파일을 선택해주세요.'}, 400)

        original_name = template.filename
        suffix = Path(original_name).suffix.lower()
        if suffix not in {'.hwp', '.hwpx'}:
            return _json_response({'success': False, 'error': '지원하지 않는 파일 형식입니다.'}, 400)

        session_id = secrets.token_urlsafe(16)
        session_dir = _hwpx_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Upload started: filename=%s session_id=%s", original_name, session_id)
        logger.info("Session directory created: %s", session_dir)

        safe_stem = secure_filename(Path(original_name).stem) or 'document'
        input_path = session_dir / f"{safe_stem}{suffix}"
        with input_path.open("wb") as handle:
            shutil.copyfileobj(template.file, handle)

        if suffix == '.hwp':
            hwpx_path = session_dir / f"{safe_stem}.hwpx"
            try:
                logger.info("Starting conversion: .hwp -> .hwpx")
                _convert_hwp_to_hwpx(input_path, hwpx_path)
                logger.info("Conversion successful: %s", hwpx_path)
            except Exception as exc:
                logger.error("Conversion failed: %s", exc)
                return _json_response({'success': False, 'error': f'변환 실패: {exc}'}, 500)
        else:
            hwpx_path = input_path

        extract_dir = _hwpx_extract_dir(session_id)
        mgr = HwpxManager()
        try:
            mgr.load_and_map(str(hwpx_path), extract_dir=str(extract_dir))
            html = mgr.generate_html_with_ids()
            mapping = mgr.export_mapping()
        finally:
            mgr.close()

        payload = {
            'mapping': mapping,
            'base_dir': str(extract_dir),
        }
        with _hwpx_manager_path(session_id).open("wb") as handle:
            pickle.dump(payload, handle)
        logger.info("Session pickle saved: %s", _hwpx_manager_path(session_id))

        return {
            'success': True,
            'session_id': session_id,
            'html': html
        }
    except Exception as exc:
        print(f"[HWPX UPLOAD ERROR] {exc}")
        return _json_response({'success': False, 'error': '업로드 처리 중 오류가 발생했습니다.'}, 500)


@app.post('/save')
def save_hwpx(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """Apply changes to HWPX and return the updated file."""
    session_id = (data.get('session_id') or '').strip()
    changes = data.get('changes') or []
    if not session_id:
        return _json_response({'success': False, 'error': 'session_id가 필요합니다.'}, 400)

    mgr_path = _hwpx_manager_path(session_id)
    if not mgr_path.exists():
        return _json_response({'success': False, 'error': '세션이 만료되었습니다.'}, 404)

    try:
        with mgr_path.open("rb") as handle:
            payload = pickle.load(handle)
    except Exception as exc:
        print(f"[HWPX SAVE ERROR] {exc}")
        return _json_response({'success': False, 'error': '세션 데이터를 읽을 수 없습니다.'}, 500)

    base_dir = payload.get('base_dir')
    mapping = payload.get('mapping') or {}
    if not base_dir:
        return _json_response({'success': False, 'error': '세션 데이터가 손상되었습니다.'}, 500)

    output_path = _hwpx_session_dir(session_id) / f"{session_id}.hwpx"
    mgr = HwpxManager()
    try:
        mgr.load_from_extracted(base_dir, mapping)
        mgr.update_and_save(changes, str(output_path))
    except Exception as exc:
        print(f"[HWPX SAVE ERROR] {exc}")
        return _json_response({'success': False, 'error': '저장 처리 중 오류가 발생했습니다.'}, 500)
    finally:
        mgr.close()

    return FileResponse(output_path, filename=output_path.name)


@app.post('/api/template/upload')
def upload_template(template: Optional[UploadFile] = File(None)):
    """문서 양식 파일 업로드 및 텍스트 추출"""
    try:
        if not template or not template.filename:
            return _json_response({'success': False, 'error': '업로드할 파일을 선택해주세요.'}, 400)
        original_name = template.filename
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_TEMPLATE_EXTENSIONS:
            return _json_response({
                'success': False,
                'error': '지원하지 않는 파일 형식입니다. (.docx, .hwp, .hwpx, .pdf, .txt, .md)'
            }, 400)

        safe_stem = secure_filename(Path(original_name).stem) or 'template'
        filename = f"{safe_stem}{suffix}"

        timestamp = int(time.time() * 1000)
        save_path = TEMPLATE_DIR / f"{timestamp}_{filename}"
        with save_path.open("wb") as handle:
            shutil.copyfileobj(template.file, handle)

        try:
            template_text = extract_template_text(save_path)
            template_html = extract_template_html(save_path, template_id=save_path.stem)
        except ValueError as exc:
            if save_path.exists():
                save_path.unlink()
            return _json_response({'success': False, 'error': str(exc)}, 400)

        return {
            'success': True,
            'template_name': filename,
            'template_id': save_path.stem,
            'template_text': template_text,
            'template_html': template_html,
            'template_file': str(save_path)
        }
    except Exception as exc:
        print(f"[TEMPLATE] Upload failed: {exc}")
        return _json_response({'success': False, 'error': '템플릿 업로드 중 오류가 발생했습니다.'}, 500)


@app.get('/api/template/asset/{template_id}/{asset_path:path}')
def serve_template_asset(template_id: str, asset_path: str):
    """HWP HTML 변환 시 생성된 템플릿 자산 제공"""
    base_dir = TEMPLATE_HTML_DIR / template_id
    try:
        base_resolved = base_dir.resolve()
        asset_resolved = (base_resolved / asset_path).resolve()
        asset_resolved.relative_to(base_resolved)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")

    if not asset_resolved.exists():
        raise HTTPException(status_code=404, detail="Not found")

    return FileResponse(asset_resolved)


@app.post('/api/template/select')
def select_template(data: Dict[str, Any] = Depends(_get_json)):
    """템플릿 선택 후 HTML/텍스트 반환"""
    template_id = (data.get('template_id') or '').strip()
    template_type = (data.get('template_type') or '').strip()

    if not template_id or template_type not in {'preset', 'file'}:
        return _json_response({'success': False, 'error': '템플릿 정보를 확인해주세요.'}, 400)

    if template_type == 'preset':
        if template_id not in DOCUMENT_PRESETS:
            return _json_response({'success': False, 'error': '템플릿을 찾을 수 없습니다.'}, 404)
        template_text = DOCUMENT_PRESETS[template_id]
        return {
            'success': True,
            'template_name': template_id.replace('_', ' '),
            'template_text': template_text,
            'template_markdown': template_text,
            'template_type': 'preset'
        }

    candidate = (TEMPLATE_LIBRARY_DIR / template_id).resolve()
    try:
        candidate.relative_to(TEMPLATE_LIBRARY_DIR.resolve())
    except Exception:
        return _json_response({'success': False, 'error': '잘못된 템플릿 경로입니다.'}, 400)

    if not candidate.exists():
        return _json_response({'success': False, 'error': '템플릿 파일을 찾을 수 없습니다.'}, 404)

    safe_id = secure_filename(template_id.replace('/', '_')) or candidate.stem
    try:
        template_text = extract_template_text(candidate)
        template_html = extract_template_html(candidate, template_id=safe_id)
    except ValueError as exc:
        return _json_response({'success': False, 'error': str(exc)}, 400)

    return {
        'success': True,
        'template_name': candidate.name,
        'template_text': template_text,
        'template_html': template_html,
        'template_id': safe_id,
        'template_file': str(candidate),
        'template_type': 'file'
    }


@app.post('/api/edit-html')
def edit_html(data: Dict[str, Any] = Depends(_get_json)):
    """HTML 템플릿 편집 (스트리밍)"""
    try:
        html = (data.get('html') or '').strip()
        instruction = (data.get('instruction') or '').strip()

        if not html or not instruction:
            return _json_response({'error': 'HTML과 수정 요청을 입력해주세요.'}, 400)

        def generate():
            try:
                stream = agent.content_generator.edit_html_stream(html, instruction)
                for chunk in stream:
                    if chunk:
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                print(f"[HTML EDIT ERROR] {str(e)}")
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
        print(f"[ERROR] edit_html failed: {str(e)}")
        return _json_response({'error': str(e)}, 500)


@app.post('/api/edit-fragment')
def edit_fragment(data: Dict[str, Any] = Depends(_get_json)):
    """HTML fragment 편집 (스트리밍)"""
    try:
        fragment = (data.get('fragment') or '').strip()
        instruction = (data.get('instruction') or '').strip()

        if not fragment or not instruction:
            return _json_response({'error': 'Fragment와 수정 요청을 입력해주세요.'}, 400)

        def generate():
            try:
                stream = agent.content_generator.edit_html_fragment_stream(fragment, instruction)
                for chunk in stream:
                    if chunk:
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                print(f"[FRAGMENT EDIT ERROR] {str(e)}")
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
        print(f"[ERROR] edit_fragment failed: {str(e)}")
        return _json_response({'error': str(e)}, 500)
