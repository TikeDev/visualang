# Render Deployment

This repo deploys to Render as two separate services from the same monorepo:

- `frontend/` as a free Static Site
- `backend/` as a Starter Web Service

This setup is for demo readiness, not production hardening. It keeps the current `/tmp` file usage, in-memory export job state, and single-instance backend behavior.

## Prerequisites

- Rotate the OpenAI key currently stored in your local `backend/.env` before deploying anywhere. Do not reuse that value.
- Keep `.env` files local-only. Enter secrets in Render manually.
- Push the repo with `render.yaml`, docs, and frontend lockfile changes before creating services.

## Blueprint Option

The repo root includes `render.yaml`, which defines both services.

- Frontend service: `visualang-frontend`
- Backend service: `visualang-backend`

Important Blueprint caveat:

- Render prompts for `sync: false` env vars only during the initial Blueprint creation flow.
- After the services already exist, update those env vars from the Render Dashboard, not by editing `render.yaml`.

## Backend Web Service

Create a Render Web Service with these settings if you are not using the Blueprint:

- Service type: `Web Service`
- Runtime: `Python`
- Plan: `Starter`
- Root Directory: `backend`
- Build Command: `curl -fsSL https://deno.land/install.sh | sh && pip install -r requirements.txt`
- Start Command: `export PATH="$HOME/.deno/bin:$PATH" && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

### Backend Environment Variables

Set these in Render:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `NUNCHAKU_API_KEY`
- `CORS_ALLOWED_ORIGINS`
- `YOUTUBE_PROXY_ENABLED`
- `YOUTUBE_PROXY_HTTP_URL`
- `YOUTUBE_PROXY_HTTPS_URL`
- `YT_DLP_DENO_PATH` only if Deno is not available on `PATH`

Set `CORS_ALLOWED_ORIGINS` to the exact deployed frontend origin, for example:

```text
https://visualang-frontend.onrender.com
```

For local development, if `CORS_ALLOWED_ORIGINS` is unset, the backend defaults to:

- `http://localhost:5173`
- `http://127.0.0.1:5173`
- `http://localhost:4173`
- `http://127.0.0.1:4173`

## Frontend Static Site

Create a Render Static Site with these settings if you are not using the Blueprint:

- Service type: `Static Site`
- Plan: `Free`
- Root Directory: `frontend`
- Build Command: `npm ci && npm run build`
- Publish Directory: `dist`

### Frontend Environment Variables

Set this in Render before the frontend build:

- `VITE_API_URL`

Set it to the full backend origin, for example:

```text
https://visualang-backend.onrender.com
```

## Recommended Deploy Order

1. Deploy the backend first.
2. Copy the backend external URL from Render.
3. Set frontend `VITE_API_URL` to that backend URL.
4. Deploy the frontend static site.
5. Copy the frontend external URL from Render.
6. Set backend `CORS_ALLOWED_ORIGINS` to that exact frontend origin.
7. Redeploy the backend.

This two-step flow is required because:

- the frontend needs the backend URL at build time
- the backend should only allow the final frontend origin in CORS

## Smoke Test Checklist

After both services are live:

1. Open the frontend and submit a known-good YouTube URL.
2. Confirm transcript fetch succeeds.
3. Confirm concept extraction succeeds.
4. Confirm image generation streams images into the preview.
5. Start an export and confirm job polling finishes.
6. Download the exported video.
7. Download the transcript text file.
8. Download the images zip.
9. Check backend logs in Render if any step stalls or fails.

## Known Demo Limits

- Files written to `/tmp` are ephemeral and disappear after restarts or deploys.
- Export jobs are stored only in memory and are lost on restart or redeploy.
- The backend should stay at one instance for the demo because there is no shared job state or shared file storage.
- Concurrent demo users can increase latency or cause export contention.
