# AGENTS.md

This file provides guidance to coding agents working in this repository.

## Session Phrase Mapping

When the user says `see the running browser`, interpret it as:
`check the Chrome DevTools MCP server`.

## Safety Rules

- Never publish passwords, API keys, or tokens to git, npm, Docker, logs, or screenshots.
- Never commit `.env` files. Keep `backend/.env`, `frontend/.env`, `.env`, and `.env.local` out of git.
- Before any commit, verify no secrets are staged.
- `.gitignore` already excludes the main env-file patterns; preserve that coverage if you edit it.

## Browser Rules

- Use the already-running Chrome Beta instance for browser debugging. Do not launch a new browser when the user refers to the running or open browser.
- Chrome Beta binary on macOS: `/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta`
- Expected remote debugging port: `9222`
- DevTools MCP should target `http://127.0.0.1:9222`
- If Chrome DevTools shows regular Chrome tabs instead of Chrome Beta, stop and ask the user to relaunch the correct browser.
- If nothing is available on port `9222`, ask the user to launch Chrome Beta. Do not launch it yourself.

## Project Overview

This repo is the `Visualang` app: a language-learning video companion that turns a YouTube URL or uploaded audio file into transcript-driven storybook visuals and an exported video. Frontend lives in `frontend/`; backend lives in `backend/`.

## Common Commands

```bash
# Install frontend deps
pnpm install

# Run both apps from repo root
pnpm dev

# Run backend only
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload

# Run frontend only
cd frontend
pnpm dev

# Build frontend
cd frontend
pnpm build

# Run tests
pytest tests/test_visualang_phase2.py -v
pytest tests/test_generate.py -v
pytest tests/test_image_providers.py -v
pytest tests/test_export.py -v

# Frontend tests (Vitest)
cd frontend
pnpm test
```

## Render CLI and Skills

- Use the `render-cli` skill when a task involves Render CLI setup, auth, deploys, logs, SSH, `psql`, Blueprint validation, or CI/CD automation.
- Useful related skills: `render-deploy`, `render-blueprints`, `render-web-services`, `render-env-vars`, `render-postgres`, `render-debug`, and `render-static-sites`.
- The Render CLI supports `render login`, `render workspace set`, `render services -o json`, `render deploys create <service-id> --wait --confirm -o json`, `render logs -r <service-id> --tail`, `render psql <db-id>`, `render ssh <service-id> --ephemeral`, and `render blueprints validate`.
- For scripts or CI, prefer `RENDER_API_KEY`, `--confirm`, and `-o json`; never print or commit API keys.
- `render skills install`, `render skills update`, and `render skills list` manage Render agent skills for supported AI coding tools.

## Environment

- Backend expects `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_API_TOKEN` in `backend/.env`.
- Frontend uses `VITE_API_URL` and defaults to `http://localhost:8000`.
- Generated backend assets (jobs, images) are served from `VISUALANG_DATA_DIR` (defaults to `/tmp/visualang_data`); images are exposed at `/images/*`.

## Architecture Summary

### Frontend

- Stack: React 19 + Vite, Vitest for tests.
- Entry files: `frontend/src/main.jsx`, `frontend/src/App.jsx`.
- `frontend/src/App.jsx` orchestrates the job lifecycle: create job, poll/resume via `frontend/src/jobApi.js`, render progress via `frontend/src/components/JobProgress.jsx` (driven by the pure state mapper in `frontend/src/jobState.js`), preview, and download.
- The resume token for an in-flight or completed job lives in the URL hash (`#/jobs/<token>`) so a job survives reload or sharing the link.
- `frontend/src/config.js` holds the backend base URL.

### Backend

- Stack: FastAPI.
- Entry file: `backend/main.py`.
- Routers:
  - `backend/routers/jobs.py` — job-based pipeline API (current model): create/get/cancel/retry/delete + video/transcript/images downloads, all gated by a resume token.
  - `backend/routers/transcript.py`, `concepts.py`, `generate.py`, `export.py` — underlying per-stage logic, also reachable directly (used by tests and the job runner's injected stage functions).
  - `backend/routers/metrics.py` — rolling latency percentiles, in-memory.
  - `backend/routers/demo.py` — serves seeded fixtures from `backend/scripts/seed_demo.py`.
- `backend/job_store.py` (`JobStore`, SQLite-backed) and `backend/job_runner.py` (`JobRunner`, stage state machine) implement the resumable job model. See [`CLAUDE.md`](CLAUDE.md) for the full job lifecycle and the resume-token security model.
- `backend/image_providers.py` wraps Cloudflare Workers AI behind `call_cloudflare`; `generate.py` calls it directly.
- `backend/config.py` is the single source of truth for env-driven settings — add new env vars there.
- Health check: `GET /health`.

### Runtime Agents

- Visualang backend includes three Anthropic-powered runtime agents in `backend/agents/`:
  - `TranscriptGate`
  - `ConceptExtractor`
  - `ImagePromptRewriter`
- They are wired through the backend routers and documented in detail in `backend/AGENTS.md`.

### Tests

- `tests/test_visualang_phase2.py` covers orchestration flow.
- `tests/test_generate.py` covers generation router behavior.
- `tests/test_image_providers.py` covers the Cloudflare provider abstraction.
- `tests/test_export.py` covers export packaging behavior.
- `frontend/src/jobState.test.js`, `frontend/src/jobApi.test.js`, `frontend/src/components/JobProgress.test.jsx` cover the frontend job lifecycle.

## Working Conventions

- Prefer focused edits over broad rewrites; preserve the current frontend/backend split.
- Treat `backend/.env` as local-only. Never print or copy real secrets into docs, fixtures, or commit messages.
- Shared behavior should usually be coordinated through API contracts, not duplicated logic.
- When changing job semantics, update `STAGE_ORDER` in `job_runner.py`, the status handling in `frontend/src/jobState.js`, and `_PRIVATE_FIELDS` in `routers/jobs.py` together — they encode the same state machine from three angles.
- When changing the generation pipeline, check both `frontend/src/App.jsx` and the corresponding backend router payloads.
- When changing backend agents, also consult `backend/AGENTS.md` before editing prompts, tool wiring, or model selection.

## Related Documentation

| File | Description | When to consult |
|------|-------------|-----------------|
| [backend/AGENTS.md](backend/AGENTS.md) | Runtime agent flow, files, model usage, router integration | Editing `backend/agents/*` or agent-backed routers |
| [visualang-prompt-for-claude-code.md](visualang-prompt-for-claude-code.md) | Full Visualang build spec, UX goals, implementation phases | Checking product requirements or phase-specific behavior |
| [README.md](README.md) | Visualang overview, local setup, testing, deployment entrypoints | Checking current app behavior or local run instructions |
