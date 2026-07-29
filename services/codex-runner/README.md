# Codex Runner (DOC Agent 전용)

앱의 AI 호출을 받아 사용자의 ChatGPT 계정으로 Codex를 돌리는 사이드카입니다.
`modules/codex_runner.py`가 HTTP로만 이 서비스를 부릅니다.

원래 YC 5-Day Ideation Sprint용 러너를 함께 쓰고 있었지만, 그쪽은 프롬프트에서
**웹 브라우징을 금지**하고 있어 실험 대화에서 검색이 되지 않았습니다.
그래서 복제해 이 프로젝트 전용으로 두고, 두 가지를 바꿨습니다.

| 무엇 | YC 러너 | 여기 |
|---|---|---|
| `AGENTS.md` | "Never … browse the web" | 웹 검색을 쓰도록 명시. 검색 결과는 신뢰할 수 없는 입력으로 다루게 함 |
| `CODEX_HOME/config.toml` | 없음(기본값) | `web_search = "live"` |
| clientInfo / serviceName | `five_day_ideation_sprint` | `doc_agent_research` |

`web_search` 키는 codex **0.144.1과 0.145.0 양쪽에서 확인**했습니다.
값이 틀리면 codex가 "config could not be loaded"로 아예 뜨지 않으므로,
서버가 알 수 없는 값을 받으면 조용히 `live`로 되돌립니다.

## 동작 방식

세션(= 브라우저 하나)마다 `$AI_RUNNER_DATA_DIR/sessions/<id>/` 아래에
독립된 `codex-home`과 `workspace`를 만들고, 거기에 `codex app-server`를 띄웁니다.
로그인 토큰도 그 안에만 있으므로 세션끼리 계정이 섞이지 않습니다.

샌드박스는 `read-only`, 승인 정책은 `never`입니다. 셸 실행·파일 쓰기·MCP는
모두 거절되고, 웹 검색만 열려 있습니다. 웹 검색은 Responses API가 서버 쪽에서
실행하는 내장 도구라 컨테이너 네트워크 권한과 무관하게 동작합니다.

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `CODEX_RUNNER_SHARED_SECRET` | (필수, 32자 이상) | 앱과 공유하는 시크릿. 앱의 같은 이름 값과 일치해야 합니다 |
| `CODEX_WEB_SEARCH` | `live` | `disabled` / `cached` / `indexed` / `live` |
| `AI_RUNNER_DATA_DIR` | `/data` | 세션 디렉터리를 두는 곳 |
| `PORT` | `8787` | |
| `AI_RUNNER_IDLE_MS` | 30분 | 이 시간 동안 안 쓰면 app-server를 내림 |
| `AI_RUNNER_TURN_TIMEOUT_MS` | 180000 | 한 턴 제한 시간 |

## 로컬에서 띄우기

```bash
cd services/codex-runner
CODEX_RUNNER_SHARED_SECRET=$(openssl rand -hex 24) \
AI_RUNNER_DATA_DIR=/tmp/runner-data PORT=8788 node server.mjs
```

`codex` CLI가 PATH에 있어야 합니다(`CODEX_BIN`으로 경로를 바꿀 수 있습니다).
확인:

```bash
curl -s http://127.0.0.1:8788/health
```

앱이 이 러너를 보게 하려면 `.env`에서:

```
CODEX_RUNNER_URL=http://127.0.0.1:8788
CODEX_RUNNER_SHARED_SECRET=<위에서 만든 값>
```

세션의 `codex-home`이 새로 만들어지므로 **ChatGPT 연결을 다시 해야 합니다**
(앱에서 기기 코드 로그인).

## 배포

Railway용 `Dockerfile` / `railway.toml`이 함께 있습니다. 지금 쓰는 러너와 별도의
서비스로 올린 뒤, 앱의 `CODEX_RUNNER_URL`을 새 주소로 바꾸면 됩니다.
`CODEX_RUNNER_SHARED_SECRET`은 앱과 러너 양쪽에 같은 값을 넣어야 합니다.

Dockerfile은 `@openai/codex@0.144.1`을 고정합니다. 버전을 올릴 때는
`web_search` 설정 키가 그대로인지 먼저 확인하세요:

```bash
npx -y @openai/codex@<버전> -c web_search=bogus doctor   # 설정 오류가 나야 정상(=키가 살아 있음)
```
