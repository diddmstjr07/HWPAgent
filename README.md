# HWP Agent

<p align="center">
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/badge/python-3.10+-blue.svg"></a>
  <a href="https://flask.palletsprojects.com/"><img alt="Flask" src="https://img.shields.io/badge/flask-3.x-green.svg"></a>
  <a href="https://ai.google.dev/"><img alt="Gemini API" src="https://img.shields.io/badge/gemini-api-orange.svg"></a>
  <a href="#configuration"><img alt="License" src="https://img.shields.io/badge/license-TBD-lightgrey.svg"></a>
  <a href="https://github.com/diddmstjr07/HWPAgent/issues"><img alt="Issues" src="https://img.shields.io/github/issues/diddmstjr07/HWPAgent.svg"></a>
  <a href="https://github.com/diddmstjr07/HWPAgent/pulls"><img alt="Pull Requests" src="https://img.shields.io/github/issues-pr/diddmstjr07/HWPAgent.svg"></a>
</p>

> Gemini + LangChain 기반으로 한국어 HWP/HWPX 문서를 자동 생성·포맷·저장하는 경량 문서 에이전트입니다.

## Features
- Gemini `gemini-2.5-flash` 기반 제목/본문/표/이미지 설명 생성
- HWPX·DOCX·Markdown·PDF 출력, SSE 스트리밍, 이미지 자동 검색
- Flask REST API + Web UI, CLI, SQLite 기록(추가 예정)

## Tech Stack
| Layer | Tool |
| --- | --- |
| Generation | Google Gemini API, LangChain |
| Backend | Flask, Flask-CORS |
| Formats | python-docx, custom HWPX builder, LibreOffice bridge |
| Assets | Selenium/BeautifulSoup image scraper |

## Installation
```bash
git clone https://github.com/diddmstjr07/HWPAgent.git
cd HWPAgent
python3 -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # GOOGLE_API_KEY 등 채우기
flask --app app.py run
```

## CLI Examples
```bash
# 기본 HWPX
python main.py "AI 보고서를 작성해줘"

# 포맷 / 컨텍스트 / 출력 경로
python main.py "분기 보고서" \
  --format md \
  --context "매출 +15%, 신규 파트너 3곳" \
  --output-dir ./reports/q1

# 인터랙티브 모드
python main.py --interactive
```

## REST API
| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/generate` | POST | 단발성 문서 생성 (JSON 반환) |
| `/api/generate-stream` | POST | SSE 기반 스트리밍 생성 |
| `/api/save` | POST | 문서 저장 및 이미지 다운로드 |

Example:
```bash
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"request": "스마트워크 도입 백서를 작성해줘"}'
```

## Configuration
| Key | Purpose |
| --- | --- |
| `GOOGLE_API_KEY` | Gemini 호출용 API 키 |
| `SECRET_KEY` | Flask 세션/CSRF |
| `DEFAULT_OUTPUT_DIR` | 결과 파일 기본 경로 |
| `MODEL_NAME` | 사용할 Gemini 모델명 (기본: `gemini-2.5-flash`) |

## Development
- Lint/format: `ruff check . && ruff format .`
- Tests (추가 예정): `pytest`
- Run web app: `flask --app app.py run`

## Contribution & License
- Issue/PR 모두 환영합니다. Conventional Commits 권장.
- 라이선스는 확정 전이며, 사용 전 문의 부탁드립니다.
