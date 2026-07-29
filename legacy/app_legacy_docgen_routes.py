"""2026-07-29에 app.py에서 걷어낸 레거시 문서 생성 라우트.

DOCX·HTML을 만들어 내려주던 경로다. 진짜 HWP(rhwp/hwp-node) 조립으로
옮겨 오면서 화면과 함께 쓸모가 없어졌다. 참고용으로만 남긴다 —
이 파일은 app.py가 import 하지 않는다.
"""

# --- /upload (원래 app.py 2400~2459행) ---
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

# --- /save (원래 app.py 2462~2497행) ---
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

# --- /api/template/upload (원래 app.py 2500~2540행) ---
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

# --- /api/template/fill-guide (원래 app.py 2543~2575행) ---
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

# --- /api/template/asset/{template_id}/{asset_path:path} (원래 app.py 2578~2592행) ---
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

# --- /api/templates (원래 app.py 2595~2621행) ---
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

# --- /api/template/select (원래 app.py 2624~2669행) ---
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

# --- /api/font/upload (원래 app.py 2672~2700행) ---
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

# --- /api/fonts (원래 app.py 2703~2710행) ---
@app.get('/api/fonts')
def get_fonts():
    try:
        fonts = list_available_fonts()
        return {'success': True, 'fonts': fonts}
    except Exception as exc:
        print(f"[FONT] Catalog error: {exc}")
        return _json_response({'success': False, 'error': '폰트 목록을 불러오지 못했습니다.'}, 500)

# --- /api/formats (원래 app.py 2713~2715행) ---
@app.get('/api/formats')
def get_available_formats():
    return {'success': True, 'formats': EXPORT_FORMATS}

# --- /api/interact (원래 app.py 2717~2803행) ---
@app.post('/api/interact')
def interact_auto(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """자동 의도 파악 및 스트리밍"""
    try:
        user_request = (data.get('request') or '').strip()
        document_template = (data.get('template') or '').strip() or None
        chat_history = data.get('history') or []  # 대화 기록 추출
        user_id = get_user_id_from_request(request)
        riro_context_text = _build_riro_context_text(request, user_id)
        codex_instance_id = _codex_instance_id(request)

        if not user_request:
             return _json_response({'error': '요청 내용을 입력해주세요.'}, 400)

        def generate():
            # 1. 의도 파악 (템플릿이 있어도 사용자의 요청에 따라 판단)
            try:
                # Codex는 턴 단가가 높아 의도 분류에 한 턴을 더 쓰지 않는다.
                intent = (codex_generator.classify_intent(user_request) if codex_instance_id
                          else agent.content_generator.classify_intent(user_request))
            except Exception as e:
                print(f"[INTENT ERROR] {str(e)}")
                intent = "chat"  # 분류 실패가 답변 자체를 막지 않도록 한다.

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

            try:
                system_prompt = DOC_INTAKE_SYSTEM_PROMPT if use_doc_intake else None
                # ChatGPT 계정이 연결돼 있으면 그 계정의 토큰으로 생성한다.
                if codex_instance_id:
                    context_parts = [part for part in (
                        riro_context_text,
                        (f"업로드된 문서/양식 내용:\n{document_template}"
                         if document_template else None),
                    ) if part]
                    stream = codex_generator.generate_chat_stream(
                        codex_instance_id,
                        user_request,
                        history=chat_history,
                        system_prompt=system_prompt,
                        context='\n\n'.join(context_parts) or None,
                    )
                else:
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

# --- /api/generate (원래 app.py 2805~2850행) ---
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

# --- /api/generate-stream (원래 app.py 2852~2918행) ---
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

# --- /api/chat-stream (원래 app.py 2920~2969행) ---
@app.post('/api/chat-stream')
def chat_stream(request: Request, data: Dict[str, Any] = Depends(_get_json)):
    """프리픽스 없이 채팅형 응답 스트리밍"""
    try:
        user_request = (data.get('request') or '').strip()
        chat_history = data.get('history') or []
        user_id = get_user_id_from_request(request)
        riro_context_text = _build_riro_context_text(request, user_id)
        codex_instance_id = _codex_instance_id(request)

        if not user_request:
            return _json_response({'error': '요청 내용을 입력해주세요.'}, 400)

        def generate():
            full_text = ""
            try:
                # ChatGPT 계정이 연결돼 있으면 그 계정의 토큰으로 생성하고,
                # 아니면 기존 Gemini 경로를 그대로 쓴다.
                if codex_instance_id:
                    stream = codex_generator.generate_chat_stream(
                        codex_instance_id,
                        user_request,
                        history=chat_history,
                        context=riro_context_text,
                    )
                else:
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

# --- /api/edit-html (원래 app.py 2994~3025행) ---
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

# --- /api/edit-fragment (원래 app.py 3028~3059행) ---
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

# --- /api/save (원래 app.py 3061~3297행) ---
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
                temp_docx = docx_handler.create_document_from_html(
                    html_content=content,
                    title=title,
                    style_config=style_config,
                    filename=temp_filename
                )
                hwp_path = Path('output') / f"{title}.hwp"
                shutil.copy2(temp_docx, hwp_path)
                Path(temp_docx).unlink(missing_ok=True)
                file_path = str(hwp_path)
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

# --- /api/refine (원래 app.py 3299~3321행) ---
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

# --- /api/refine-stream (원래 app.py 3323~3356행) ---
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

# --- /api/adjust-format (원래 app.py 3358~3385행) ---
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

# --- /api/view-pdf/{filename:path} (원래 app.py 3411~3421행) ---
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

# --- /api/search-images (원래 app.py 3423~3487행) ---
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

# --- /api/search-images/test (원래 app.py 3489~3532행) ---
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

# --- /api/pdf-to-images/{filename:path} (원래 app.py 3534~3571행) ---
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
