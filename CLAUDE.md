# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo is the `Visualang` app: a comprehensible-input visual companion for language learning. It takes a YouTube URL or local audio file, extracts a transcript, uses backend runtime agents to identify visual moments, generates storybook illustrations, and renders a downloadable `.mp4` with synced audio. The frontend lives in `frontend/` (React + Vite) and the backend lives in `backend/` (FastAPI).

The backend pipeline is guarded by three runtime agents: `TranscriptGate`, `ConceptExtractor`, and `ImagePromptRewriter`. See [`backend/AGENTS.md`](backend/AGENTS.md) before changing prompts, model wiring, or router integration.

## Commands

```bash
# Install everything from repo root (frontend + workspace)
pnpm install

# Backend setup
cd backend && pip install -r requirements.txt
cp .env.example .env

# Run both apps from repo root (needs an active Python env with backend deps)
pnpm dev

# Backend only
cd backend && uvicorn main:app --reload

# Frontend only
cd frontend && pnpm dev

# Frontend build / lint
cd frontend && pnpm build
cd frontend && pnpm lint

# Frontend tests (Vitest)
cd frontend && pnpm test
cd frontend && pnpm test -- jobState.test.js   # single file

# Backend/python tests
pytest tests/test_generate.py -v
pytest tests/test_image_providers.py -v
pytest tests/test_visualang_phase2.py -v
pytest tests/test_export.py -v
pytest tests/test_generate.py -v -k test_name   # single test
```

## Render CLI and Skills

- Use the `render-cli` skill for Render CLI installation, authentication, deploys, logs, SSH, `psql`, Blueprint validation, and CI/CD scripting.
- Reach for related Render skills by task: `render-deploy`, `render-blueprints`, `render-web-services`, `render-env-vars`, `render-postgres`, `render-debug`, and `render-static-sites`.
- Common commands: `render login`, `render workspace set`, `render services -o json`, `render deploys create <service-id> --wait --confirm -o json`, `render logs -r <service-id> --tail`, `render psql <db-id>`, `render ssh <service-id> --ephemeral`, and `render blueprints validate`.
- In non-interactive workflows, use `RENDER_API_KEY`, `--confirm`, and `-o json`. Never print or commit Render API keys.
- Render skills can be managed with `render skills install`, `render skills update`, and `render skills list`.

## Architecture

### Job-based pipeline (current model)

The backend runs the whole pipeline (transcript → concepts → images → export) as a single resumable **job**, tracked in SQLite, rather than driven step-by-step by the frontend.

- `backend/job_store.py` — `JobStore` persists jobs in `jobs.sqlite3` under `VISUALANG_DATA_DIR`. Each job has a UUID4 `id` plus a separate `secret`; clients only ever see the combined `resume_token` (`"{id}.{secret}"`), required to read or mutate a job. Job state (`status`, `stage`, `transcript`, `concepts`, `images`, etc.) is stored as a JSON blob per row. Jobs expire after `JOB_RETENTION_SECONDS` (default 24h); expired rows and their artifact directories are swept via tombstone-rename-then-delete so deletes are crash-safe.
- `backend/job_runner.py` — `JobRunner` drives a job through `STAGE_ORDER = (transcript, concepts, generating_images, export)`, calling injected `transcript_fn`/`concepts_fn`/`images_fn`/`export_fn`. `retry()` resumes from the job's last recorded `stage` instead of restarting. `reconcile_jobs_after_restart()` runs at boot to mark any job left `running` as `interrupted` so it becomes retryable after a crash or redeploy.
- `backend/routers/jobs.py` — public API: `POST /jobs` (YouTube), `POST /jobs/upload` (audio file), `GET /jobs/{resume_token}`, `POST /jobs/{resume_token}/cancel`, `POST /jobs/{resume_token}/retry`, `DELETE /jobs/{resume_token}`, plus `/video`, `/transcript`, `/images` download endpoints. `sanitize_job()` strips internal fields (`_PRIVATE_FIELDS`: filesystem paths, ffmpeg pid, etc.) and the raw `source` before any job dict reaches the client. Responses set `Cache-Control: no-store` since resume tokens are bearer credentials.
- Frontend: `frontend/src/jobApi.js` wraps the job HTTP API and encodes the resume token into the URL hash (`#/jobs/<token>`) so a job can be resumed by reloading or sharing the link. `frontend/src/jobState.js` (`getJobView`) is a pure function mapping a job payload to UI state (label, primary/secondary action, whether to keep showing the in-progress preview) — keep it pure and exhaustively tested in `jobState.test.js` when adding new statuses. `frontend/src/components/JobProgress.jsx` renders that view.

When changing job semantics, update `STAGE_ORDER`/`_STAGE_INDEX` in `job_runner.py`, the status union handled by `getJobView`, and `_PRIVATE_FIELDS` together — they encode the same state machine from three angles.

### Image generation providers

`backend/image_providers.py` abstracts image generation behind `call_cloudflare`, returning a `GeneratedImage(image_bytes, provider, model)` or raising `ImageProviderError` / `ImageContentPolicyError` (sanitized, API-safe messages). `IMAGE_PROVIDER` env var selects the active provider (`cloudflare` default). Cloudflare Workers AI is called directly over REST using `CLOUDFLARE_ACCOUNT_ID`/`CLOUDFLARE_API_TOKEN`; retries respect `Retry-After` headers with exponential backoff capped at `MAX_BACKOFF_SECONDS`.

`backend/routers/generate.py` fans concept-to-image generation out concurrently (ceiling: `IMAGE_GENERATION_CONCURRENCY`), streams progress in completion order over SSE while preserving transcript order in the final list, and retries provider 429s/5xx with backoff. When `IMAGE_ENABLE_REWRITE_RECOVERY` is on, a Haiku vision check can trigger `ImagePromptRewriter` and a single regeneration attempt — see `backend/AGENTS.md` for the agent side of this.

### Runtime agents

Three async agents in `backend/agents/` (Anthropic SDK, hand-rolled state machine, no LangChain) guard the pipeline: `TranscriptGate` (reject unusable transcripts before spending money), `ConceptExtractor` (draft → critique → fix graph for visual concepts), `ImagePromptRewriter` (rewrite prompts after a vision-check failure). Model IDs live in `backend/agents/prompts.py`. Full details, the agent/router wiring table, and the "adding a new agent" checklist are in [`backend/AGENTS.md`](backend/AGENTS.md) — read it before touching `agents/*` or any router that calls into them.

### Other backend pieces

- `backend/main.py` wires the FastAPI app, lifespan logging (including Render shutdown-signal diagnostics), CORS, static file serving for generated images (`/images` → `VISUALANG_DATA_DIR/artifacts`), and router registration.
- `backend/config.py` is the single source of truth for env-driven settings (image provider selection, retries/backoff, job retention, CORS origins, YouTube proxy settings) — add new env vars here, not as scattered `os.getenv` calls.
- `backend/routers/` also contains the older non-job transcript/concepts/generate/export endpoints (still used directly by tests and possibly by older frontend code paths) plus `metrics.py` (rolling latency percentiles, in-memory, resettable via `POST /metrics/reset`) and `demo.py` (serves seeded fixtures from `backend/scripts/seed_demo.py`, bypassing live APIs).
- `frontend/src/App.jsx` orchestrates the job lifecycle (create → poll → resume from URL hash → preview → download) and `frontend/src/components/Player.jsx` handles synced playback/scene presentation.

## Notes

- Keep `.env`, `.env.local`, `backend/.env`, and `frontend/.env` out of git.
- `tests/test_generate.py` and `tests/test_image_providers.py` exercise the Cloudflare code path; check which env vars/mocks a given test expects before assuming a real API key is required.
- Generated backend assets are served from `VISUALANG_DATA_DIR` (defaults to `/tmp/visualang_data`), with jobs under `jobs/<job_id>/` and images under `artifacts/`.

## Related Documentation

| File | Description | When to consult |
|------|-------------|-----------------|
| [visualang-prompt-for-claude-code.md](visualang-prompt-for-claude-code.md) | Full Visualang build spec, UX goals, and phase notes | Checking original product intent or phase-specific expectations |
| [backend/AGENTS.md](backend/AGENTS.md) | Runtime agent flow, model usage, and router integration | Editing `backend/agents/*` or agent-backed routers |
