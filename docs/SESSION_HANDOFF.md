# HWPAgent — 프로젝트 설명 및 작업 인수인계 (2026-07-26)

이 문서는 새 세션/다른 에이전트에게 그대로 건네도 되는 컨텍스트입니다.
"무엇을 만드는 앱인가 → 어떻게 돌아가는가 → 이번 세션에 무엇을 바꿨는가 →
지금 상태와 남은 일" 순으로 적혀 있습니다.

---

## 1. 이 앱은 무엇인가

고등학생이 **3년치 생기부(세특)를 하나의 연구 서사로 설계하고, 실제로 탐구를
수행하고, 그 결과를 한글(HWP) 보고서로 남기도록** 돕는 웹 앱입니다.

핵심 원칙 두 가지가 코드 전체를 지배합니다.

1. **AI가 대신 해주지 않는다.** 관찰·측정·판단은 학생 몫이고, Agent는 배경 자료와
   진행을 돕습니다. 대화에 없는 수치는 보고서에도 들어가지 않습니다.
2. **학생 계정의 AI를 쓴다.** ChatGPT 계정을 기기 코드로 연결하고, 그 계정의
   사용 한도로 Codex가 돌아갑니다. 연결이 곧 로그인입니다.

### 사용자 흐름

```
/welcome  온보딩(4문답) → 프로파일
   ↓
/         메인 채팅 = '설계' 대화
          테마 후보 → 테마 선택 → 3년 계획 → N학년 과목별 세특 설계
   ↓      (설계 완료 시 /research#grade-N 으로 이동)
/research 3년 로드맵. 과목 카드마다 [실험 진행]
   ↓
/         메인 채팅 = '실험' 대화 (?chat=<대화방>)
          다섯 국면: 배경 조사 → 탐구 설계 → 실행·관찰 → 결과 정리 → 결론·한계
   ↓
          완료 → HWP 보고서 자동 생성 → 카드에 문서 아이콘
   ↓
/editor?file=<파일명>  브라우저 WASM HWP 편집기에서 이어서 손보기
```

---

## 2. 구조

### 프로세스 3개 (모두 로컬에서 동시 실행 중)

| 포트 | 무엇 | 비고 |
|---|---|---|
| 8080 | FastAPI 본체 (`app.py`) | `--host 0.0.0.0` — LAN(`192.168.0.15:8080`) 접속 가능 |
| 8788 | **Codex Runner** (`services/codex-runner/server.mjs`) | 세션마다 `codex app-server` 를 띄움 |
| 3100 | **hwp-node** (`services/hwp-node/`) | rhwp WASM. HWP 열기/편집/렌더/내보내기 |

앱 → 러너/사이드카는 **서버 내부 호출**이라 `127.0.0.1`에 묶여 있습니다.
브라우저는 8080만 봅니다.

### 코드 지도

```
app.py                      FastAPI 본체. 페이지 라우트 + 레거시 API
modules/
  research_router.py        연구 서사·실험 API 전부 (APIRouter, /api/research/*)
  research_pipeline.py      Codex 프롬프트와 출력 스키마 (한 파일에 모두)
  research_store.py         연구 서사 DB 접근 + 상태 머신(draft/narrowing/fixed)
  codex_runner.py           Runner HTTP 클라이언트
  codex_auth.py             ChatGPT 기기 코드 로그인 (= 앱 로그인)
  codex_generator.py        일반 채팅·문서 생성용 Codex 어댑터 (Gemini 폴백 있음)
  web_search.py             ★신규 검색(텍스트/이미지). Brave/Google CSE/네이버/위키미디어
  hwp_report.py             ★신규 보고서 → 진짜 HWP 조립 (hwp-node 사용)
  report_figures.py         ★신규 그림 준비 (matplotlib 실행 / 웹 이미지 내려받기)
static/js/
  index.js (223KB)          기존 문서 생성 UI. 되도록 건드리지 않는다
  guide.js                  ★대폭 확장 설계 대화 + 실험 대화 + 라이트박스 + 데모 + 단계판
  history.js                ★신규 사이드바 HISTORY(폴더)
  research.js               /research 로드맵
templates/index.html        메인 페이지 + 모든 CSS(인라인)
services/codex-runner/      ★신규 HWP 전용 Codex Runner (YC 러너에서 복제)
```

---

## 3. 이번 세션에 바꾼 것

### 3-1. 실험을 메인 채팅으로 통합 + HISTORY 폴더

- `/experiment/{id}` **전용 페이지 폐지**. 실험은 메인(`/?chat=<대화방>`)에서 진행.
  옛 주소는 해당 대화방으로 리디렉션.
- 사이드바에 **HISTORY** 섹션. 폴더는 `설계` / `실험` 둘 (+ 폴더 없는 옛 대화는 `기타`).
- DB: `chat_sessions`에 `folder`, `plan_id` 컬럼 / `research_messages`에 `session_id` 컬럼.
  기존 실험방은 시작 시 1회 백필.
- 대화방 이름: 실험은 `과목명 - 키워드`, 설계는 **진행 상태 요약**
  (예: `키오스크 UI 설계 · 1학년 세특`). 모델을 추가로 부르지 않고 상태에서 만든다.
- 설계 완료 → `/research#grade-N` 으로 그 학년 위치까지 이동.

### 3-2. Codex 웹 검색 (진짜 원인은 프롬프트였다)

- 원인: YC와 공유하던 러너의 `AGENTS.md`에 **"Never … browse the web"** 이 박혀 있었음.
- `services/codex-runner/` 로 **복제**해 HWP 전용으로 분리하고:
  - AGENTS.md에서 브라우징 금지 해제 (셸/파일/MCP 금지는 유지)
  - 세션 `CODEX_HOME/config.toml` 에 `web_search = "live"` 기록
  - `web_search` 키가 codex **0.144.1 / 0.145.0 양쪽에서 유효함을 확인**
    (`codex -c web_search=bogus doctor` → config 오류가 나면 유효한 키)
- 앱 쪽 폴백: `modules/web_search.py` (Brave/Google CSE/네이버, 키 없으면 위키미디어).
  **LLM은 Codex 하나만 씁니다** — 검색은 검색 엔진이 하고 읽는 건 Codex가 합니다.
- 실험 대화에서 학생이 "찾아봐 줘"라고 하면: Codex 자체 검색 1순위 → 안 되면 앱 검색 →
  그것도 없으면 검색어와 확인 포인트를 알려줌.

### 3-3. 실험 대화 UX

- **검색 상태 UI**: '생각 중'(점 세 개)과 '찾는 중'(돋보기+검색어) 구분, 끝나면 복귀.
- **이미지**: 대화에 가로 스트립으로. 클릭 시 **라이트박스**(중앙 확대, X/ESC/바깥 클릭).
- **직접 눌러볼 화면(demo)**: Codex가 만든 HTML을 `sandbox="allow-scripts"` iframe으로.
  `allow-same-origin` 없음 → 부모 DOM·쿠키 접근 불가. 외부 자원은 **글꼴만** 허용.
  클립보드는 프레임 안에서 막히므로 postMessage로 부모가 대신 복사.
- **다시 생성**: 마지막 답변만 지우고 같은 질문으로 재생성.
- **말투 규칙**: 문어체(~이다/~하는가) 금지, 반말 대화체 강제.
- 알림(toast) **전 페이지 통일** — 상단 중앙 `.app-toast` 하나로.

### 3-4. 보고서를 "진짜 HWP"로

- 이전엔 DOCX를 만들고 확장자만 `.hwp`였음 → 편집기가 못 열었음.
- 이제 hwp-node로 조립: `POST /sessions/blank` → `ops`(insert_text/split_paragraph/
  set_char_format/set_para_format/**insert_image**) → `GET /export`.
- **hwp-node에 `insert_image` op 신설** (rhwp `insertPicture`, mm→HWPUNIT 환산).
- 함정 두 개(둘 다 실측으로 발견):
  - `fontSize`는 **pt×100** (11pt = `1100`). 모르고 `11`을 넣으면 0.11pt라
    "글자가 없는 것처럼 보이는" 문서가 나온다.
  - 정렬 키는 `align`이 아니라 **`alignment`**(값도 소문자). 그리고 **모든 문단에
    명시**해야 한다 — 한 문단만 바꾸면 지정 안 한 문단이 따라 움직인다.
- **검수 단계**: 만든 문서를 다시 열어 첫 페이지를 렌더하고, 글자가 보이는 크기인지
  (5px 이상) 확인해 단계판에 남긴다.
- 그림 크기: 폭 130mm 기본, **높이 110mm 초과 시 비율 유지하며 축소**,
  작은 원본은 96dpi 기준 2배까지만 확대.

### 3-5. 문서 생성 = 계획 → 단계 실행 파이프라인

```
① 문서 계획 세우기      (장 구성 + 그림 계획)
② 그림 계획 확인        ★ 사용자에게 묻고 답을 기다림 (5분 타임아웃)
③ 이미지 검색           ★ 검색 전담 Codex 턴 (계획 턴에 맡기면 건너뛴다)
④ 본문 쓰기 — 장마다 별도 턴
⑤ 그림 준비             (matplotlib 실행 / 이미지 내려받기)
⑥ HWP 문서 조립
⑦ 문서 검수
```

- 채팅에 **단계 점검표**가 뜨고 각 단계가 ○→⟳→✓ 로 진행됩니다(1.2초 폴링).
- ②에서 채팅에 질문 카드가 뜹니다: `[이대로 진행]` 또는 요청 입력
  (예: "2번은 실제 앱 화면으로"). 답하면 `revise_figures` 턴이 계획을 고칩니다.
  무응답 5분이면 계획대로 진행 — **기다리다 멈추지 않습니다.**
- 한 장이 실패해도 나머지는 완성되고, 계획 자체가 실패하면 예전 단일 호출로 폴백.
- **문서 다시 만들기**: 대화는 그대로 두고 보고서만 재생성 (`POST …/report`).

### 3-6. 로딩 속도

- 부팅의 **고정 900ms 지연 제거**.
- `templates/index.html` `<head>`에 **프리페치 스크립트**(`window.__boot`) 추가 —
  index.js(223KB) 파싱을 기다리지 않고 첫 화면 데이터를 미리 요청.
  guide.js/history.js가 그 결과를 받아 씁니다(1회만 소비, 이후 갱신은 새로 요청).
- 직렬 왕복 5회 → 병렬 2회.

### 3-7. 기타

- LAN 접속: `--host 0.0.0.0`, `PUBLIC_BASE_URL=http://192.168.0.15:8080`.
- 쿠키는 주소별로 다르므로 `127.0.0.1`↔`192.168.x` 사이에 **로그인이 공유되지 않습니다.**
  비로그인이면 화면이 조용히 비지 않고 "ChatGPT 연결하기" 안내가 뜹니다.
- 러너 동시 실행 충돌(`Another turn is already running`)을 409 + 친절한 문구로 정정하고,
  앱 쪽 잠금도 방 단위 → **사용자 단위**로 교정(러너가 로그인당 1턴만 처리하므로).

---

## 4. 지금 상태

- 테스트 **133개 전부 통과** (`.venv/bin/python -m unittest discover -s tests`).
- 프로세스 3개 모두 실행 중 (8080 / 8788 / 3100).
- 백업: `hwp_agent.db.bak-20260726-064113`, `.env.bak-20260726-073738`.

### 확인된 제약

- **검색 API 키 없음.** `.env`의 `BRAVE_SEARCH_API_KEY` 등이 비어 있어 앱 폴백 검색은
  위키미디어만 동작합니다. Codex 자체 검색은 살아 있습니다.
- `GOOGLE_API_KEY`가 `PLACEHOLDER_REPLACE_ME` — Gemini 폴백 경로는 죽어 있습니다
  (Codex만 쓰므로 현재 문제 없음).
- **`services/codex-runner`는 로컬 실행 중이고 배포되지 않았습니다.** 학생들이 쓰려면
  Railway 등에 별도 서비스로 올리고 `CODEX_RUNNER_URL`을 바꿔야 합니다.

### 남은 일 / 다음 후보

1. codex-runner 배포 (README에 절차 있음)
2. 검색 API 키 발급 (Brave 무료 2000/월 추천, 국내 자료는 네이버 병행)
3. 설계 채팅에도 단계 파이프라인 적용 (인프라는 범용으로 만들어 둠)
4. 보고서에 표(table) 지원 — hwp-node에 `create_table` op는 이미 있음

---

## 5. 작업할 때 알아둘 것

- **추측하지 말고 실측하세요.** 이번 세션의 큰 버그 두 개(글자 0.11pt, 정렬 무시)는
  데이터 검사로는 안 잡히고 **페이지를 렌더해서 눈으로 봐야** 발견됐습니다.
  `GET /sessions/{id}/pages/0` (SVG) → `qlmanage -t` 로 PNG 변환해 확인하는 방법을 씁니다.
- 사용자는 **Claude Computer Use / 브라우저 MCP를 쓰지 말라**고 했습니다.
  시각 확인은 사용자 몫이며, 서버 측 렌더 검증은 위 방법을 사용합니다.
- 정적 파일을 고치면 `templates/*.html`의 `?v=` 캐시 버전을 올려야 반영됩니다.
- 앱을 재시작하면 러너에 진행 중이던 턴이 최대 180초간 남아 새 요청을 막습니다.
  그때는 잠시 기다렸다 다시 시도하면 됩니다.
- 코드 주석은 **왜 그렇게 했는지**를 한국어로 적는 관례입니다. 그대로 따라 주세요.
