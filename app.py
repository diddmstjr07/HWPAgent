#!/usr/bin/env python3
"""
HWP Agent Web App - ChatGPT Canvas 스타일의 실시간 문서 편집기
"""
from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import os
import json
import io
import base64
from pathlib import Path
from modules import HWPAgent
from modules.docx_handler import DOCXHandler
from modules.pdf_handler import PDFHandler
from modules.format_adjuster import FormatAdjuster
from modules.image_searcher import ImageSearcher
from urllib.parse import urlparse, parse_qs
import fitz  # PyMuPDF
import time
from dotenv import load_dotenv
from database import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
CORS(app, supports_credentials=True)

# IP 주소 기반 사용자 ID 생성
def get_user_id_from_request():
    """세션 또는 IP 주소를 기반으로 사용자 ID 생성"""
    ip = request.remote_addr or 'unknown'
    # X-Forwarded-For 헤더 확인 (프록시 후방 대응)
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return f"user_{ip.replace('.', '_').replace(':', '_')}"

# 전역 에이전트
agent = HWPAgent(output_dir="output")
docx_handler = DOCXHandler(output_dir="output")
pdf_handler = PDFHandler(output_dir="output")
format_adjuster = FormatAdjuster()
image_searcher = ImageSearcher()

def _clean_google_url(url: str) -> str:
    """Google redirect URL 정제"""
    if url and url.startswith("https://www.google.com/url?"):
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "q" in qs:
            return qs["q"][0]
    return url

def _contains_invalid_url(images: list) -> bool:
    """Facebook Lookaside 등 비정상 링크가 포함되어 있는지 검사"""
    invalid_domains = ["lookaside.fbsbx.com", "fbcdn.net", "googleusercontent.com", "instagram", "facebook"]
    for img in images:
        url = img.get("url", "")
        if any(domain in url for domain in invalid_domains):
            return True
    return False

def _filter_invalid_images(images: list) -> list:
    """비정상 링크 제거"""
    invalid_domains = ["lookaside.fbsbx.com", "fbcdn.net", "googleusercontent.com"]
    return [
        img for img in images
        if not any(domain in img.get("url", "") for domain in invalid_domains)
    ]

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/api/generate', methods=['POST'])
def generate_content():
    """AI 콘텐츠 생성"""
    try:
        data = request.json
        user_request = data.get('request', '')
        
        if not user_request:
            return jsonify({'error': '요청 내용을 입력해주세요.'}), 400
        
        # 콘텐츠 생성
        result = agent.process_request(user_request)
        
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
        user_request = data.get('request', '')
        
        if not user_request:
            return jsonify({'error': '요청 내용을 입력해주세요.'}), 400
        
        def generate():
            full_text = ""
            chunk_count = 0
            try:
                # 스트리밍 모드로 생성
                stream = agent.content_generator.generate_document_content(user_request, stream=True)
                
                for chunk in stream:
                    if chunk:  # 빈 청크 무시
                        full_text += chunk
                        chunk_count += 1
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                
                # 모든 청크가 처리된 후
                print(f"\n[STREAM] All chunks processed, waiting for finalization...")
                import time
                time.sleep(0.5)  # 추가 대기
                
                # 스트리밍 완료 로그
                print(f"\n{'='*60}")
                print(f"[STREAM COMPLETE] Received {chunk_count} chunks")
                print(f"[STREAM COMPLETE] Total length: {len(full_text)} characters")
                print(f"[STREAM COMPLETE] First 300 chars:\n{full_text[:300]}")
                print(f"[STREAM COMPLETE] Last 300 chars:\n{full_text[-300:]}")
                print(f"{'='*60}\n")
                
                # 파싱: 제목 추출
                parsed = agent.content_generator._parse_generated_content(full_text)
                print(f"[PARSED] Title: {parsed.get('title', 'NO TITLE')}")
                print(f"[PARSED] Body length: {len(parsed.get('body', ''))} characters")
                
                # 중요: full_text 전체를 body로 사용 (파싱 실패 방지)
                final_result = {
                    'title': parsed.get('title', '문서'),
                    'body': full_text,  # 파싱된 body 대신 원본 사용
                    'images_needed': parsed.get('images_needed', []),
                    'tables_needed': parsed.get('tables_needed', [])
                }
                
                print(f"[FINAL] Sending body length: {len(final_result['body'])} characters\n")
                
                yield f"data: {json.dumps({'done': True, 'result': final_result})}\n\n"
                
            except Exception as e:
                print(f"[ERROR] Stream generation failed: {str(e)}")
                import traceback
                traceback.print_exc()
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

@app.route('/api/save', methods=['POST'])
def save_document():
    """문서 저장 (이미지 자동 검색 및 삽입 포함)"""
    try:
        data = request.json
        title = data.get('title', '문서')
        content = data.get('content', '')
        format_type = data.get('format', 'docx')
        style_config = data.get('style', {})
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
        
        # 이미지 자동 다운로드 ([gen_img] 태그 기반)
        downloaded_images = []
        if images_needed and len(images_needed) > 0:
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
                        
                        if not url:
                            print(f"[IMAGE] No URL for keyword: {keyword}")
                            continue
                        
                        # 파일명에서 특수문자 제거
                        safe_filename = keyword.replace(' ', '_').replace('/', '_').replace('\\', '_')[:50]
                        img_filename = f"{safe_filename}.jpg"
                        img_path = f"output/images/{img_filename}"
                        
                        print(f"[IMAGE] Downloading from frontend URL: {url[:100]}...")
                        downloaded_path = image_searcher.download_image(
                            url,
                            img_path,
                            max_width=1200
                        )
                        
                        if downloaded_path:
                            downloaded_images.append(downloaded_path)
                            print(f"[IMAGE] ✅ Downloaded: {keyword} -> {downloaded_path}")
                        else:
                            # Fallback: Lorem Picsum 사용
                            print(f"[IMAGE] ❌ Failed to download: {keyword}, trying fallback...")
                            fallback_url = f"https://picsum.photos/seed/{abs(hash(keyword))%1000}/800/600"
                            fallback_path = image_searcher.download_image(
                                fallback_url,
                                img_path,
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
                        images = image_searcher.search_images_google(keyword, count=1)
                        if images:
                            # 파일명에서 특수문자 제거
                            safe_filename = keyword.replace(' ', '_').replace('/', '_').replace('\\', '_')[:50]
                            img_filename = f"{safe_filename}.jpg"
                            img_path = f"output/images/{img_filename}"
                            print(images)
                            downloaded_path = image_searcher.download_image(
                                images[0]['url'],
                                img_path,
                                max_width=1200
                            )
                            if downloaded_path:
                                downloaded_images.append(downloaded_path)
                                print(f"[IMAGE] ✅ Downloaded: {keyword} -> {downloaded_path}")
                            else:
                                print(f"[IMAGE] ❌ Failed to download: {keyword}")
                        else:
                            print(f"[IMAGE] ❌ No results for: {keyword}")
                
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
                style_config=style_config if style_config else None,
                images=downloaded_images if downloaded_images else None,
                filename=f"{title}_temp.docx"
            )
            
            # DOCX를 PDF로 변환
            print(f"[PDF] Converting DOCX to PDF...")
            file_path = pdf_handler.convert_docx_to_pdf(
                temp_docx,
                output_filename=f"{title}.pdf"
            )
        elif format_type == 'hwp':
            # HWP는 DOCX를 확장자만 .hwp로 변경하여 저장 (이미지 포함)
            temp_path = docx_handler.create_document(
                title=title,
                content=content,
                style_config=style_config if style_config else None,
                images=downloaded_images if downloaded_images else None,
                filename=f"{title}_temp.docx"
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
                style_config=style_config if style_config else None,
                images=downloaded_images if downloaded_images else None,
                filename=f"{title}.docx"
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
        count = data.get('count', 3)

        if not query:
            return jsonify({'error': '검색 키워드를 입력해주세요.'}), 400

        MAX_RETRY = True  # 최대 3회 재검색
        attempt = 0
        images = []

        while True:
            images = image_searcher.search_images_google(query, count=count)
            print(f"[{attempt+1}회차 결과] {len(images)}개 이미지 검색됨")

            # URL 정제
            for img in images:
                img["url"] = _clean_google_url(img.get("url", ""))
                img["thumb_url"] = _clean_google_url(img.get("thumb_url", ""))

            # 비정상 링크 포함 시 재검색
            if _contains_invalid_url(images):
                print(f"[WARN] 비정상 링크 발견 (lookaside/fbcdn 등) → 재검색 시도 {attempt+1}/{MAX_RETRY}")
                attempt += 1
                time.sleep(1.2)  # Google API rate limit 방지
                continue
            else:
                break

        # 최종적으로 비정상 이미지 제거
        images = _filter_invalid_images(images)

        return jsonify({
            'success': True,
            'query': query,
            'count': len(images),
            'images': images
        })

    except Exception as e:
        print(f"[ERROR] search_images: {str(e)}")
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
    """사용자의 문서 목록 조회 (IP 기반)"""
    try:
        user_id = get_user_id_from_request()
        documents = db.get_user_documents(user_id)
        return jsonify({
            'success': True,
            'documents': [doc.to_dict() for doc in documents]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/documents/<int:doc_id>', methods=['GET'])
def get_document(doc_id):
    """특정 문서 조회 (IP 기반)"""
    try:
        user_id = get_user_id_from_request()
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
    """문서를 히스토리에 저장 (IP 기반)"""
    try:
        user_id = get_user_id_from_request()
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
    """문서 삭제 (IP 기반)"""
    try:
        user_id = get_user_id_from_request()
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
