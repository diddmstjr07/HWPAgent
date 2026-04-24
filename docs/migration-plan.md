# HWP Vibe Editing Migration Plan

This file tracks the staged migration from the legacy hwp5/HWPX HTML editing
pipeline to a FastAPI + Node `@rhwp/core` sidecar architecture.

## Current Decisions

- Keep the existing FastAPI server.
- Add a Node sidecar under `services/hwp-node`.
- Keep Jinja + vanilla JS; do not introduce a frontend framework.
- Keep the existing Gemini REST client and add function calling by extending the
  REST payload.
- Serve new HWP APIs under `/api/v2/hwp/...`.
- Keep legacy code under `legacy/` until the user approves removal.

## Step Discipline

Each migration step must stop for approval before continuing to the next step.

## STEP 3: Node sidecar HTTP server

- services/hwp-node/src/ scaffolded with Fastify
- /health and /version endpoints verified
- TypeScript build produces dist/
- Python server integration deferred to STEP 7
