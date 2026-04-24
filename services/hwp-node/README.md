# hwp-node

HWP 조작 sidecar 서비스. Python FastAPI 메인 서버가 HTTP로 호출.

## 현재 상태 (STEP 2 종료 시점)

- Node 18+, ESM, `@rhwp/core@0.7.3`
- WASM 초기화: `initSync({ module: readFileSync(...rhwp_bg.wasm) })`
- `measureTextWidth` 폴리필: `scripts/bootstrap.mjs`의 naive 버전 (`text.length * 7`)
- 검증된 기능:
  - HWP 파일 열기 (`new HwpDocument(Uint8Array)`)
  - 텍스트 삽입, 단락 분리, 문자·문단 서식 (fontId 경로)
  - `exportHwp()` 왕복 저장/로드
- 미구현:
  - HTTP 서버 (STEP 3)
  - 세션 스토어 (STEP 6)
  - 원자 편집 연산 추상화 (STEP 4)
  - SVG 렌더러 (STEP 5)

## Scripts

- `node scripts/find-seed.mjs` — 레포에서 seed HWP 찾기
- `node scripts/generate-samples.mjs` — samples/ 재생성
- `node scripts/verify-samples.mjs` — 샘플 왕복 검증

## Env

- `SEED_HWP` — 샘플 생성 시 seed 파일 경로 override

## Next (STEP 3+)

- Fastify HTTP 서버, `/health` 라우트
- `src/` 디렉토리로 production 코드 이동 (scripts/는 dev utility로 유지)
- TypeScript로 전환 (현재 .mjs는 빠른 실험용)
