# HWP Agent v2 통합 가이드

## 개요

이 프로젝트는 FastAPI 백엔드와 Node.js sidecar (hwp-node)를 통해 HWP 문서 편집 기능을 제공합니다.

## 아키텍처

```
┌─────────────────────────────────────────────────────┐
│ 브라우저 (Canvas UI)                                   │
│ static/js/index.js                                   │
└────────────────┬────────────────────────────────────┘
                 │ HTTP/REST
                 ▼
┌─────────────────────────────────────────────────────┐
│ FastAPI Server (app.py)                             │
│ - /api/v2/hwp/* (프록시)                             │
│ - /api/chat-stream (채팅)                            │
│ - /api/generate-stream (문서 생성)                   │
└────────────────┬────────────────────────────────────┘
                 │ HTTP (프록시)
                 ▼
┌─────────────────────────────────────────────────────┐
│ Node.js HWP Server (services/hwp-node)              │
│ - POST /sessions (파일 업로드)                       │
│ - GET /sessions/:id/pages/:idx (렌더링)              │
│ - POST /sessions/:id/ops (편집)                      │
│ - GET /sessions/:id/export (내보내기)                │
└─────────────────────────────────────────────────────┘
```

## 환경 설정

### 1. Node 서버 설정

**services/hwp-node/.env** (필요하면 생성):
```bash
NODE_ENV=development
PORT=3000
API_KEY=dev-api-key
```

### 2. FastAPI 설정

**프로젝트 루트 .env**:
```bash
# HWP Node 서버 설정
HWP_NODE_URL=http://localhost:3000
HWP_NODE_API_KEY=dev-api-key

# Gemini API (문서 생성용)
GOOGLE_GENERATIVEAI_API_KEY=your-api-key

# 기타 설정
SKIP_FONT_DOWNLOAD=0
TEST_MODE=0
```

## 시작 방법

### 1단계: Node 서버 시작

```bash
cd services/hwp-node
npm install  # 필요시만
npm start
# 포트 3000에서 실행됨
```

### 2단계: FastAPI 서버 시작

```bash
# 프로젝트 루트에서
python -m pip install -r requirements.txt  # 필요시만
python app.py
# 포트 8000에서 실행됨
```

### 3단계: 브라우저 접속

```
http://localhost:8000
```

## API 통합 테스트

### 1. Node 서버 상태 확인

```bash
curl http://localhost:3000/health
# 응답: {"ok": true, "service": "hwp-node"}
```

### 2. FastAPI 프록시 상태 확인

```bash
curl http://localhost:8000/api/v2/hwp/health
# 응답: {"ok": true, "service": "hwp-node"}
```

### 3. HWP 파일 업로드 테스트

```bash
curl -F "file=@/path/to/document.hwp" \
  http://localhost:8000/api/v2/hwp/sessions
# 응답: {"success": true, "sessionId": "xxx", "pageCount": 10, "fileName": "document.hwp"}
```

### 4. 페이지 렌더링 테스트

```bash
curl http://localhost:8000/api/v2/hwp/sessions/{sessionId}/pages/0 \
  -o page.svg
```

### 5. 문서 편집 테스트

```bash
curl -X POST http://localhost:8000/api/v2/hwp/sessions/{sessionId}/edit \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "insert_text",
    "sec": 0,
    "para": 0,
    "offset": 0,
    "text": "안녕하세요"
  }'
```

## 프론트엔드 캔버스 편집 기능

### 준비된 것:
- ✅ API 엔드포인트 정의 (API_ENDPOINTS)
- ✅ FastAPI 프록시 구현
- ✅ Node 서버 연결

### 구현 필요한 것:
- ❌ Canvas UI에서 HWP 파일 업로드 처리
- ❌ 페이지 렌더링 표시 (SVG)
- ❌ 실시간 텍스트 편집 (insert_text, delete_text, replace_text)
- ❌ 문서 저장 (export)

### 프론트엔드 구현 예시 (pseduo code):

```javascript
// 1. 파일 업로드
async function uploadHWP(file) {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch('/api/v2/hwp/sessions', {
    method: 'POST',
    body: formData
  });
  const data = await response.json();
  return data.sessionId;
}

// 2. 페이지 렌더링
async function renderPage(sessionId, pageIndex) {
  const response = await fetch(
    `/api/v2/hwp/sessions/${sessionId}/pages/${pageIndex}`
  );
  const svg = await response.text();
  document.querySelector('#canvas').innerHTML = svg;
}

// 3. 텍스트 편집
async function insertText(sessionId, section, para, offset, text) {
  const response = await fetch(
    `/api/v2/hwp/sessions/${sessionId}/edit`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind: 'insert_text',
        sec: section,
        para: para,
        offset: offset,
        text: text
      })
    }
  );
  const data = await response.json();
  return data.affectedPages;
}

// 4. 문서 다운로드
async function downloadHWP(sessionId) {
  const response = await fetch(
    `/api/v2/hwp/sessions/${sessionId}/export`
  );
  const blob = await response.blob();
  // 파일 다운로드 처리
}
```

## 시스템 요구사항

- Python 3.8+
- Node.js 16+
- @rhwp/core 패키지 (Node 서버용)

## 문제 해결

### Node 서버가 연결되지 않음

1. Node 서버가 실행 중인지 확인:
```bash
curl http://localhost:3000/health
```

2. 방화벽 확인 (포트 3000 허용)

3. 환경변수 HWP_NODE_URL 확인

### HWP 파일이 업로드되지 않음

1. 파일 형식 확인 (.hwp 또는 .hwpx)
2. 파일 크기 확인
3. 서버 로그 확인: 터미널의 Flask/FastAPI 로그

### 렌더링이 느림

1. 큰 문서는 페이지 렌더링이 느릴 수 있음
2. SVG 캐시 확인 (이미 렌더링된 페이지는 빠름)

## 추가 작업

마이그레이션을 완전히 완료하려면:

1. **Canvas 편집 UI**: 프론트엔드에 실제 텍스트 편집 인터페이스 추가
2. **실시간 협업**: WebSocket을 통한 다중 사용자 편집 지원
3. **undo/redo**: 연산 기록 저장 및 취소/재실행
4. **스타일 편집**: 폰트, 색상, 정렬 등 서식 편집

## 참고 링크

- [Node HWP 서버 상세 문서](../services/hwp-node/README.md)
- [FastAPI 통합 문서](../docs/migration-plan.md)
- [Canvas 편집 아키텍처](../docs/CANVAS_ARCHITECTURE.md)

## 연락처 및 지원

문제 발생 시:
1. 로그 확인 (터미널)
2. 포트 확인 (3000, 8000)
3. 환경변수 확인
4. 이슈 등록
