# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repo is the `Visualang` app: a comprehensible-input visual companion for language learning. It takes a YouTube URL or local audio file, extracts transcript, uses backend runtime agents to identify visual moments, generates storybook illustrations via Nunchaku, and renders a downloadable `.mp4` with synced audio. The frontend lives in `frontend/` (React + Vite) and the backend lives in `backend/` (FastAPI).

The backend pipeline is guarded by three runtime agents: `TranscriptGate`, `ConceptExtractor`, and `ImagePromptRewriter`. See [`backend/AGENTS.md`](backend/AGENTS.md) before changing prompts, model wiring, or router integration.

## Commands

```bash
# Backend
cd backend && pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload

# Frontend
pnpm install
cd frontend && pnpm dev

# Frontend build
cd frontend && pnpm build

# Tests
pytest tests/test_visualang_phase2.py -v
pytest tests/test_generate.py -v
pytest tests/test_export.py -v
```

## Render CLI and Skills

- Use the `render-cli` skill for Render CLI installation, authentication, deploys, logs, SSH, `psql`, Blueprint validation, and CI/CD scripting.
- Reach for related Render skills by task: `render-deploy`, `render-blueprints`, `render-web-services`, `render-env-vars`, `render-postgres`, `render-debug`, and `render-static-sites`.
- Common commands: `render login`, `render workspace set`, `render services -o json`, `render deploys create <service-id> --wait --confirm -o json`, `render logs -r <service-id> --tail`, `render psql <db-id>`, `render ssh <service-id> --ephemeral`, and `render blueprints validate`.
- In non-interactive workflows, use `RENDER_API_KEY`, `--confirm`, and `-o json`. Never print or commit Render API keys.
- Render skills can be managed with `render skills install`, `render skills update`, and `render skills list`.

## Architecture

- `frontend/src/App.jsx` orchestrates transcript fetch, concept extraction, image generation, preview, and export polling.
- `frontend/src/components/Player.jsx` handles synced playback and scene presentation.
- `backend/main.py` wires the FastAPI app, CORS, static image serving, and routers.
- `backend/routers/` contains transcript, concepts, generate, export, metrics, and demo endpoints.
- `backend/scripts/seed_demo.py` generates local seeded demo fixtures consumed by `/demo/*`.

## Notes

- Keep `.env`, `.env.local`, `backend/.env`, and `frontend/.env` out of git.
- `tests/test_generate.py` may require a valid `NUNCHAKU_API_KEY` depending on the path being exercised.
- Generated backend assets are served from `/tmp/visualang_images`.

## Related Documentation

| File | Description | When to consult |
|------|-------------|-----------------|
| [visualang-prompt-for-claude-code.md](visualang-prompt-for-claude-code.md) | Full Visualang build spec, UX goals, and phase notes | Checking original product intent or phase-specific expectations |
| [backend/AGENTS.md](backend/AGENTS.md) | Runtime agent flow, model usage, and router integration | Editing `backend/agents/*` or agent-backed routers |
