# 레거시 문서 생성 UI 보관소

## 2026-07-29 — 문서 생성 경로 전체 제거

첫 화면을 '지금 할 일' 대시보드로 바꾸면서, **진짜 HWP가 아니었던 옛 문서 생성
기능**을 앱에서 걷어냈습니다. 그 경로는 DOCX나 HTML을 만들어 화면에 그려 주던
것이라, rhwp/hwp-node로 실제 HWP를 조립하는 지금 방식과 섞여 있을 이유가
없었습니다. 확장자만 .hwp로 바꿔 내려주다가 편집기가 못 여는 사고도 여기서 났습니다.

(아래 "이전 기록"에 적힌 대로, 그전에는 화면의 진입로만 가리고 백엔드는 살려
뒀었습니다. 이번에 그 나머지까지 정리했습니다.)

지금 화면은 이렇게 나뉩니다.

| 파일 | 맡은 일 |
|---|---|
| `static/js/shell.js` | 테마·사이드바·알림·계정·리로스쿨·캘린더 (옛 index.js에서 남긴 껍데기) |
| `static/js/home.js` | 첫 화면 — 서버가 아는 다음 할 일과 진행 단계 |
| `static/js/guide.js` | 설계·실험 대화 |
| `static/js/history.js` | 사이드바 대화 목록 |

### 보관 파일 (화면)

| 파일 | 원래 위치 | 내용 |
|---|---|---|
| `index.legacy-full.js` | `static/js/index.js` | 손대기 전 원본 전체(5632줄) |
| `index.legacy-docgen.js` | 〃 1039~4157행 | 스트리밍 문서 생성·파일 업로드·템플릿 채우기 |
| `index.legacy-canvas.js` | 〃 354~1037행 | 캔버스·문서 iframe·본문 렌더링 |
| `index.legacy-chatsession.js` | 〃 | 레거시 대화 저장·복원 |
| `index.legacy-bindings.js` | 〃 | 다운로드/템플릿/캔버스 이벤트 바인딩 |
| `index.legacy-images.js` | 〃 | 문서 안 이미지 자리표시자 로더 |
| `removed_markup_docgen.html` | `templates/index.html` | 문서 미리보기·인라인 편집·캔버스·템플릿/다운로드 모달 |
| `js/app.js`, `js/vibe-editor.js` | `static/js/` | 어느 화면에서도 부르지 않던 옛 스크립트 |
| `hwp-vibe-window.html` | `static/` | 위 vibe-editor를 쓰던 독립 실험 화면 |

`static/js/index.js`는 5632줄 → 1157줄(`shell.js`)이 됐습니다.

### 보관 파일 (서버)

한 단계 위 폴더에 있습니다.

| 파일 | 내용 |
|---|---|
| `../app_legacy_docgen_routes.py` | 걷어낸 라우트 24개 (`/api/generate`, `/api/template/*`, `/api/refine`, `/api/search-images` 등 1092줄) |
| `../app_legacy_helpers.py` | 그 라우트만 쓰던 보조 함수 20개 (364줄) |
| `../app.py.before-legacy-removal-*` | 손대기 전 app.py 전체 |

`app.py`는 3783줄 → 2317줄이 됐습니다. `modules/docx_handler.py`,
`pdf_handler.py`, `format_adjuster.py`, `image_searcher.py`는 파일로 남아 있지만
`app.py`는 더 이상 import 하지 않습니다(`docx_handler`만 보고서 폴백에서
`research_router`가 씁니다).

## 유지한 것

- **리로스쿨 연동 · 과제 캘린더** — 문서 생성과 별개 기능이라 그대로 둡니다.
- **`/editor` (rhwp/hwp-studio)** — 이쪽이 진짜 HWP를 여는 편집기입니다.
- **`v2_hwp_proxy.py`** — hwp-node 사이드카와 통신하는 현행 경로입니다.

## 되돌리려면

보관 파일은 어느 것도 앱이 import 하지 않습니다. 다시 살리려면 해당 라우트를
`app.py`에 붙이고, 마크업을 `templates/index.html`에 되돌리고, 스크립트를
`static/js/`로 옮긴 뒤 템플릿에 `<script>` 태그를 추가하면 됩니다. 다만 그 경로가
만드는 문서는 진짜 HWP가 아니므로, `/editor`에서는 열리지 않습니다.

---

## (이전 기록) 화면 진입로만 가렸던 단계

연구 서사 중심으로 전환하면서 메인 화면에서 제거했던 문서 생성 진입로입니다.

| 위치 | 항목 |
|---|---|
| 사이드바 Workspace | `수행평가 계획서` |
| 사이드바 Tools | `문서 저장` (`#btnDownloadSide`) |
| 첨부 메뉴 | `양식 선택` (`#btnSelectTemplate`), `양식 업로드` (`#btnUploadTemplate`) |

원본 마크업은 [removed_markup.html](removed_markup.html)에 있습니다.
`v2_hwp_proxy.local-backup.py`는 @rhwp/core로 옮기던 시기의 백업입니다.
