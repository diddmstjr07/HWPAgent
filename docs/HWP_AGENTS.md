# AGENTS.md

## Repo Shape
- Root Python app is not a JS workspace; root `package-lock.json` is empty. Run npm only inside `services/hwp-node`, `services/hwp-studio`, `electron`, or `mobile`.
- Main runtime is `app.py`: FastAPI + Jinja templates + `static/`, with the HWP v2 proxy mounted from `v2_hwp_proxy.py` at `/api/v2/hwp/*`.
- `main.py` is the CLI wrapper around `modules.HWPAgent`; document generation uses `modules/`, while older HWP/HWPX handlers under `legacy/modules/` are still imported.
- `services/hwp-node` is the Node sidecar for real HWP editing/rendering: ESM TypeScript, Hono, `@rhwp/core`, in-memory sessions with a 30 minute TTL.
- `services/hwp-studio` is the Vite/TypeScript editor source; `npm run build` writes generated assets to `static/hwp-studio` and empties that output directory.

## Setup And Run
- Python setup: `python3 -m venv venv && source venv/bin/activate`, then `pip install -r requirements.txt`.
- Web app: `python app.py` or `uvicorn app:app --host 0.0.0.0 --port 8080`; `app.py` defaults to `HWP_AGENT_HOST=0.0.0.0`, `HWP_AGENT_PORT=8080`, `HWP_AGENT_RELOAD=false`.
- CLI generation: `python main.py "request" --format hwpx --context "extra" --output-dir output` or `python main.py --interactive`.
- HWP sidecar: `cd services/hwp-node && npm install && npm run dev` for watch mode, or `npm run build && npm start` for `dist/index.js`.
- Full v2 flow needs both servers: `services/hwp-node` on port `3100`, then the Python app on port `8080`.

## Environment
- Root `.env` is loaded from `HWP_AGENT_ROOT/.env`, then the repo root `.env`, then cwd; there is no root `.env.example` even though `README.md` mentions one.
- Content generation requires `GOOGLE_API_KEY` or `OPENAI_API_KEY`; if `OPENAI_API_KEY` exists, `modules/gemini_generator.py` uses OpenAI as the default provider.
- FastAPI talks to the sidecar with `HWP_NODE_URL` default `http://localhost:3100` and `HWP_NODE_API_KEY` default `dev-api-key`.
- Sidecar auth expects `HWP_API_KEY` and checks `X-API-Key`/`api_key`; if `HWP_API_KEY` is unset, sidecar `/sessions*` routes run open. `services/hwp-node/.env.example` sets `HWP_API_KEY=dev-api-key` and `PORT=3100`.
- Do not read or copy values from the real root `.env`; it is ignored and may contain live tokens.

## Verification
- There is no active root pytest/lint config, and CI only has a release PyPI workflow with placeholder build commands.
- Python syntax smoke check for touched files: `python3 -m py_compile app.py main.py v2_hwp_proxy.py modules/*.py legacy/modules/*.py`.
- HWP sidecar build/test: `cd services/hwp-node && npm run build && npm test`.
- Single sidecar test file: `cd services/hwp-node && npx vitest run test/server.test.ts`; tests use `samples/text.hwp`, `samples/form.hwp`, and `samples/table.hwp` from the repo root.
- Regenerate/verify HWP sidecar samples from `services/hwp-node`: `npm run samples:generate` and `npm run samples:verify`; `samples:generate` defaults `SEED_HWP` to `../../output/templates/1766728379269_2.hwp` unless overridden.
- HWP Studio build: `cd services/hwp-studio && npm run build`. Install `services/hwp-node` first because Studio depends on `file:../hwp-node/node_modules/@rhwp/core`.
- HWP Studio e2e: start `npm run dev` in `services/hwp-studio` on port `7700`, then run `node e2e/text-flow.test.mjs` or another `e2e/*.test.mjs`; default mode connects to `CHROME_CDP` (`http://172.21.192.1:19222`), while `--mode=headless` uses a hard-coded Linux Chrome path.

## HWP Editing Gotchas
- In Node code, `src/bootstrap.ts` must run before anything touches `@rhwp/core`; keep imports routed through `src/hwp-helper.ts` or the test setup so WASM and `measureTextWidth` are initialized.
- `@rhwp/core` does not treat `\n` as paragraph breaks for edits; use `split_paragraph` explicitly for multi-paragraph insertion.
- For official document generation/editing, `v2_hwp_proxy.py` loads `docs/HWP_OFFICIAL_SKILL.md` plus `data/hwp_corpus/kma_press/style_profile.md` and `style_kit.json`; update those files when changing the prompt-level document style rules.
- Prefer sidecar operations designed for the template: `fill_report_template`, `design_template`, `read_document` + `edit_paragraphs`, `set_document_font`, and `set_font_size` are often safer than raw `insert_text`/`replace_text`.
- `.hwp` to `.hwpx` upload conversion in `app.py` shells out to `hwp5proc`; DOCX/PDF handling can require LibreOffice and Poppler, which the Dockerfile installs.

## Stale Docs To Avoid
- `docs/HWP_V2_INTEGRATION.md` has outdated details: current code uses Hono, port `3100`, sidecar env `HWP_API_KEY`, Python app port `8080`, and `/sessions/:id/ops` in the sidecar.
- `services/hwp-node/README.md` still says the HTTP server/session/renderer work is unfinished; trust `services/hwp-node/src/*`, `package.json`, and tests instead.
