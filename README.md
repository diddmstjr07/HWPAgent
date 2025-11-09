# HWP Agent

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Gemini API](https://img.shields.io/badge/gemini-api-orange.svg)](https://ai.google.dev/)
[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](#license)
[![Issues](https://img.shields.io/github/issues/diddmstjr07/HWPAgent.svg)](https://github.com/diddmstjr07/HWPAgent/issues)
[![Pull Requests](https://img.shields.io/github/issues-pr/diddmstjr07/HWPAgent.svg)](https://github.com/diddmstjr07/HWPAgent/pulls)

> Gemini + LangChain 기반으로 한글(HWP/HWPX) 문서를 자동 생성하고, 실시간 편집/저장을 지원하는 멀티모달 문서 에이전트입니다.

```
┌────────────┐      ┌──────────────────┐      ┌──────────────┐      ┌─────────────┐
│ User Input │ ───▶ │ Gemini Generator │ ───▶ │ Format Layer │ ───▶ │ HWP/PDF/MD │
└────────────┘      └──────────────────┘      └──────────────┘      └─────────────┘
                                   │
                                   ▼
                           optional Image Search
```

---

## Table of Contents

- [Overview](#overview)
- [Key Highlights](#key-highlights)
- [Quickstart](#quickstart)
- [Usage](#usage)
  - [CLI Workflow](#cli-workflow)
  - [Web App](#web-app)
  - [REST API](#rest-api)
- [Architecture](#architecture)
- [Modules](#modules)
- [Configuration](#configuration)
- [Development](#development)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

HWP Agent는 한국어 문서 작성에 특화된 AI 작성 도우미입니다. 사용자는 자연어로 요청만 전달하면 Gemini API가 콘텐츠를 생성하고, LangChain 기반 워크플로가 표·이미지·스타일을 자동 구성한 뒤 한글(HWPX) 및 다양한 포맷으로 내보냅니다. Flask 웹 UI와 CLI 모두를 지원하며, 이미지 검색과 PDF 변환까지 원스톱으로 처리합니다.

### Why HWP Agent?

- **Native Korean support** — 한글 문서 구조(HWPX)를 이해하는 전용 핸들러.
- **Streaming experience** — 실시간 토큰 스트리밍으로 긴 문서도 즉시 확인.
- **Pluggable outputs** — DOCX → PDF 파이프라인, Markdown/RTF 동시 지원.
- **Context aware** — 사용자별 히스토리/컨텍스트를 DB에 저장 후 재활용 예정.

---

## Key Highlights

| Capability | Description | Source |
| --- | --- | --- |
| 🔮 AI 문서 생성 | Gemini `gemini-2.5-flash` 및 LangChain Prompt Orchestration | `modules/gemini_generator.py` |
| 🧱 포맷 자동화 | 제목, 본문, 표, 이미지 삽입 및 스타일 조정 | `modules/format_adjuster.py`, `modules/hwp_handler.py` |
| 🖼️ 이미지 검색 | BeautifulSoup/Selenium 기반 Google 이미지 스크래퍼 | `modules/image_searcher.py` |
| 📄 멀티 포맷 출력 | HWPX, DOCX, RTF, Markdown, PDF | `modules/hwp_agent.py`, `modules/pdf_handler.py` |
| 🌐 REST + Web UI | Flask + SSE 기반 스트리밍 API 및 React 스타일 프론트 | `app.py`, `templates/index.html`, `static/` |

---

## Quickstart

### 1. Clone

```bash
git clone https://github.com/diddmstjr07/HWPAgent.git
cd HWPAgent
```

### 2. Environment

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
vi .env  # GOOGLE_API_KEY, SECRET_KEY, 기타 설정 입력
```

### 4. Run

```bash
# CLI one-off
python main.py "AI 기반 업무자동화 소개서를 hwp 형식으로 작성해줘"

# Flask web app
export FLASK_APP=app.py
flask run --host=0.0.0.0 --port=8000
```

---

## Usage

### CLI Workflow

```bash
# 기본 (HWPX)
python main.py "2024 지속가능경영 보고서를 작성해줘"

# 포맷 지정
python main.py "제품 백서 작성" --format md

# 컨텍스트 + 출력 디렉토리
python main.py "분기 실적 보고" \
  --context "매출 15% 성장, 신규 파트너 3곳" \
  --output-dir ./reports/q1
```

Flags:

- `--format {hwpx,docx,md,rtf,pdf}`
- `--context "<추가 설명>"`
- `--output-dir path`
- `--interactive` 실시간 질의응답 모드

### Web App

1. 브라우저에서 `http://localhost:8000` 접속
2. 좌측 패널에 요청(프롬프트) 입력
3. 실시간 스트리밍 결과 확인 후 저장
4. 저장 시 필요한 이미지 키워드 자동 추출 및 다운로드

프론트 리소스는 `templates/index.html`, `static/css/style.css`, `static/js/app.js`에서 확인할 수 있습니다.

### REST API

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/generate` | POST | 단발성 문서 생성 |
| `/api/generate-stream` | POST | SSE 기반 토큰 스트리밍 |
| `/api/save` | POST | 문서/이미지 저장 및 변환 |

Example request:

```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"request":"스마트워크 도입 백서를 작성해줘"}'
```

---

## Architecture

```
                   ┌─────────────────────┐
                   │ Flask REST & Web UI │
                   └─────────┬──────────┘
                             │
                             ▼
┌────────────┐   ┌────────────────────┐    ┌──────────────────┐
│ User Input │ → │ GeminiContentGenerator │ → │ FormatAdjuster │
└────────────┘   └────────────────────┘    └────────┬─────────┘
                                                    │
                                                    ▼
                                            ┌──────────────┐
                                            │ HWP / DOCX / │
                                            │  PDF Handler │
                                            └──────────────┘
                                                    │
                                                    ▼
                                            Storage & Output
```

### Data Flow

1. **Request** – 사용자가 CLI, Web, API로 요청 전달
2. **Generation** – Gemini 모델이 초안 생성 (스트리밍 가능)
3. **Adjustment** – 문단/표 스타일 맞춤, 이미지 태그 추출
4. **Rendering** – HWPX/DOCX/PDF 등으로 변환 후 저장
5. **(Optional) Image Search** – Google 이미지 검색으로 자동 삽입

---

## Modules

| Path | Responsibility |
| --- | --- |
| `modules/gemini_generator.py` | Gemini API 래퍼, 스트리밍/비스트리밍 지원 |
| `modules/hwp_agent.py` | 문서 생성 오케스트레이션, 포맷 선택 |
| `modules/hwp_handler.py` | HWPX 템플릿 빌더, 본문/표/이미지 삽입 |
| `modules/docx_handler.py` | python-docx 기반 DOCX 구성 및 스타일링 |
| `modules/pdf_handler.py` | LibreOffice/win32com을 활용한 PDF 변환 |
| `modules/format_adjuster.py` | 제목/섹션/표 정리, 스타일 규칙 적용 |
| `modules/image_searcher.py` | BeautifulSoup/Selenium 기반 이미지 검색 및 다운로드 |
| `database.py`, `models.py` | SQLite ORM-lite 레이어, 사용자/히스토리 관리 (WIP) |

---

## Configuration

` .env.example ` 참고. 필수 항목:

| Key | Description |
| --- | --- |
| `GOOGLE_API_KEY` | Gemini API 키 |
| `SECRET_KEY` | Flask 세션 및 CSRF 용 |
| `LIBREOFFICE_PATH` (optional) | PDF 변환용 soffice 경로 |
| `PROXY` (optional) | 외부 네트워크 제약 시 프록시 |

Sample:

```env
GOOGLE_API_KEY=your_real_key
SECRET_KEY=change-me
DEFAULT_OUTPUT_DIR=output
MODEL_NAME=gemini-2.5-flash
```

---

## Development

```bash
# Formatting / linting
ruff check .
ruff format .

# Type checking
mypy .

# Unit tests (추가 예정)
pytest -q

# Run Flask locally
flask --app app.py run
```

> 💡 `output/`, `modules/output/`, `*.db`, `__pycache__` 등은 `.gitignore`에 포함되어 있으므로 필요 시 수동 생성하세요.

---

## Roadmap

- [x] Gemini 기반 스트리밍 문서 생성
- [x] Google 이미지 자동 검색/다운로드
- [ ] 사용자별 히스토리/검색어 캐시
- [ ] Admin 대시보드 및 통계
- [ ] 멀티모달 입력(이미지 → 텍스트) 파이프라인
- [ ] Docker 배포 스크립트 및 CI

기여하고 싶은 항목이 있다면 Issue 또는 PR을 열어주세요!

---

## Contributing

1. Fork → branch 생성 (`feature/awesome-idea`)
2. 변경 사항 반영 및 테스트
3. Conventional Commits 권장 (`feat:`, `fix:` 등)
4. Pull Request 작성 (배경/테스트 결과 포함)

Issue/PR 전 템플릿은 곧 추가될 예정입니다. 논의가 필요한 기능은 Discussion 또는 Issue로 먼저 공유해주세요.

---

## License

현재 저장소에는 별도의 LICENSE 파일이 포함되어 있지 않습니다. 기업/상업적 사용 또는 라이선스 지정이 필요하다면 [Issues](https://github.com/diddmstjr07/HWPAgent/issues)에서 논의해주세요.

---

**HWP Agent** – 한국어 문서 자동화를 가장 빠르게 구현하는 방법.  
질문이나 버그 제보는 언제든 환영합니다! 🙌
