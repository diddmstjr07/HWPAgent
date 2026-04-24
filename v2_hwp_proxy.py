"""
HWP Node v2 프록시 엔드포인트
FastAPI에서 Node 서버(services/hwp-node)로 요청을 전달합니다.
"""
import os
import io
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
import requests
from pathlib import Path

# Node 서버 설정
HWP_NODE_URL = os.getenv('HWP_NODE_URL', 'http://localhost:3000')
HWP_NODE_API_KEY = os.getenv('HWP_NODE_API_KEY', 'dev-api-key')

router = APIRouter(prefix='/api/v2/hwp', tags=['HWP v2'])

def _node_headers() -> dict:
    """Node 서버 인증 헤더"""
    return {'X-API-Key': HWP_NODE_API_KEY}


@router.post('/sessions')
async def upload_hwp_session(file: UploadFile = File(...)):
    """
    HWP/HWPX 파일 업로드 → Node 세션 생성
    
    Returns:
        {
            "sessionId": "session-uuid",
            "pageCount": 10,
            "fileName": "document.hwp"
        }
    """
    try:
        if not file or not file.filename:
            raise HTTPException(status_code=400, detail='파일을 업로드해주세요.')
        
        # 파일 타입 검증
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {'.hwp', '.hwpx'}:
            raise HTTPException(status_code=400, detail='HWP 또는 HWPX 파일만 지원합니다.')
        
        # Node 서버로 업로드
        url = f'{HWP_NODE_URL}/sessions'
        files = {'file': (file.filename, await file.read(), 'application/octet-stream')}
        
        resp = requests.post(
            url,
            files=files,
            headers=_node_headers(),
            timeout=30
        )
        resp.raise_for_status()
        
        result = resp.json()
        return {
            'success': True,
            'sessionId': result.get('sessionId'),
            'pageCount': result.get('pageCount'),
            'fileName': file.filename
        }
    
    except requests.RequestException as e:
        print(f'[HWP v2] Node 서버 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')
    except Exception as e:
        print(f'[HWP v2] 업로드 오류: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.delete('/sessions/{session_id}')
async def delete_hwp_session(session_id: str):
    """세션 삭제"""
    try:
        url = f'{HWP_NODE_URL}/sessions/{session_id}'
        resp = requests.delete(
            url,
            headers=_node_headers(),
            timeout=10
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        
        resp.raise_for_status()
        return {'success': True}
    
    except requests.RequestException as e:
        print(f'[HWP v2] 세션 삭제 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.get('/sessions/{session_id}/pages/{page_index}')
async def render_page(session_id: str, page_index: int):
    """
    문서 페이지를 SVG로 렌더링
    
    Returns: SVG 이미지 (image/svg+xml)
    """
    try:
        if page_index < 0:
            raise HTTPException(status_code=400, detail='페이지 인덱스가 유효하지 않습니다.')
        
        url = f'{HWP_NODE_URL}/sessions/{session_id}/pages/{page_index}'
        resp = requests.get(
            url,
            headers=_node_headers(),
            timeout=15
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션 또는 페이지를 찾을 수 없습니다.')
        
        resp.raise_for_status()
        
        return StreamingResponse(
            iter([resp.content]),
            media_type='image/svg+xml; charset=utf-8'
        )
    
    except requests.RequestException as e:
        print(f'[HWP v2] 렌더링 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.post('/sessions/{session_id}/edit')
async def edit_document(session_id: str, request: Request):
    """
    문서 편집 연산 적용
    
    Request body:
        {
            "kind": "insert_text",
            "sec": 0,
            "para": 0,
            "offset": 0,
            "text": "추가될 텍스트"
        }
    
    Returns:
        {
            "affectedPages": [0, 1],
            "data": null or any
        }
    """
    try:
        body = await request.json()
        
        url = f'{HWP_NODE_URL}/sessions/{session_id}/ops'
        resp = requests.post(
            url,
            json=body,
            headers=_node_headers(),
            timeout=15
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        elif resp.status_code == 422:
            detail = resp.json().get('error', '연산 실행 실패')
            raise HTTPException(status_code=422, detail=detail)
        
        resp.raise_for_status()
        return resp.json()
    
    except requests.RequestException as e:
        print(f'[HWP v2] 편집 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')
    except Exception as e:
        print(f'[HWP v2] 요청 처리 오류: {e}')
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/sessions/{session_id}/export')
async def export_document(session_id: str):
    """
    현재 세션의 HWP 파일 다운로드
    
    Returns: HWP 파일 (application/octet-stream)
    """
    try:
        url = f'{HWP_NODE_URL}/sessions/{session_id}/export'
        resp = requests.get(
            url,
            headers=_node_headers(),
            timeout=30,
            stream=True
        )
        
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail='세션을 찾을 수 없습니다.')
        
        resp.raise_for_status()
        
        # Content-Disposition 헤더에서 파일명 추출
        filename = 'document.hwp'
        disp = resp.headers.get('Content-Disposition', '')
        if 'filename=' in disp:
            filename = disp.split('filename=')[-1].strip('"')
        
        return StreamingResponse(
            resp.iter_content(chunk_size=8192),
            media_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
    
    except requests.RequestException as e:
        print(f'[HWP v2] 내보내기 오류: {e}')
        raise HTTPException(status_code=500, detail='Node 서버 통신 실패')


@router.get('/health')
async def health_check():
    """Node 서버 상태 확인"""
    try:
        url = f'{HWP_NODE_URL}/health'
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except:
        raise HTTPException(status_code=503, detail='Node 서버 연결 불가')


@router.get('/version')
async def version_info():
    """Node 서버 버전 정보"""
    try:
        url = f'{HWP_NODE_URL}/version'
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except:
        raise HTTPException(status_code=503, detail='Node 서버 연결 불가')
