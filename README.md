# VisuaLang

VisuaLang is a language-learning video companion built with React and FastAPI. It takes a YouTube video or Shorts URL, or an uploaded audio file, extracts a transcript, turns key moments into storybook-style images, previews the sequence in the browser, and exports a downloadable video package.

> ⚠️ At the moment, YouTube video and Shorts links only work reliably in local development.
On the deployed app, YouTube ingestion may fail because hosted environments like Render are often blocked by YouTube.

## What VisuaLang Does Today

- Accepts a YouTube video link, YouTube Shorts link, or local audio upload.
- Fetches YouTube captions when available and falls back to transcribing extracted audio when they are not.
- Runs a transcript gate before the expensive parts of the pipeline.
- Extracts visual concepts with backend runtime agents.
- Streams image generation progress from the backend to the frontend.
- Previews synced audio + illustrated scenes in the browser player.
- Starts an FFmpeg export job in the background and exposes video, transcript, and image downloads.
- Supports seeded demo fixtures and lightweight in-memory metrics for demos.

## Visitor Flow

<p align="center">
  <img
    src="frontend/public/visitor-flow.png"
    alt="Visitor flow showing YouTube URL or Audio Upload to Transcript and Audio Extraction to Quality Gate to Concept Selection, followed by generation, preview, export, and downloads."
    width="1000"
  />
</p>

## Repo Structure

```text
frontend/   React 19 + Vite app
backend/    FastAPI app, runtime agents, routers, export pipeline
tests/      VisuaLang-focused tests
```

## Local Development

### Prerequisites

- Node.js with `pnpm`
- Python 3
- Deno available on your shell path for YouTube extraction through `yt-dlp`
- `ffmpeg` available on your shell path for video export

### Quick start

1. Install frontend and root workspace dependencies:

```bash
pnpm install
```

2. Create local env files:

```bash
cp backend/.env.example backend/.env
printf "VITE_API_URL=http://localhost:8000\n" > frontend/.env
```

3. Install backend dependencies in your active Python environment:

```bash
pip install -r backend/requirements.txt
```

4. Run both apps from the repo root:

```bash
pnpm dev
```

The root `pnpm dev` script starts:

- the backend with `cd backend && uvicorn main:app --reload`
- the frontend with `cd frontend && pnpm dev`

Because of that, make sure the Python environment with `uvicorn` and backend dependencies is active in the same shell before you run `pnpm dev`.

### Run services separately

Backend:

```bash
cd backend
uvicorn main:app --reload
```

Frontend:

```bash
cd frontend
pnpm dev
```

Frontend build:

```bash
cd frontend
pnpm build
```

## Environment Setup

Keep all env files local only. `.env`, `.env.local`, `frontend/.env`, and `backend/.env` are gitignored and should stay that way.

### Backend: `backend/.env`

The backend requires these variables:

```bash
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
NUNCHAKU_API_KEY=sk-nunchaku-...
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

These variables are optional overrides. You can omit them locally and in Render unless you need the specific behavior described below.

```bash
YOUTUBE_PROXY_ENABLED=false
YOUTUBE_PROXY_HTTP_URL=
YOUTUBE_PROXY_HTTPS_URL=
YT_DLP_DENO_PATH=
NUNCHAKU_MIN_INTERVAL_SECONDS=2.0
NUNCHAKU_MAX_429_RETRIES=4
NUNCHAKU_BACKOFF_BASE_SECONDS=3.0
NUNCHAKU_ENABLE_REWRITE_RECOVERY=false
```

Notes:

- `CORS_ALLOWED_ORIGINS` is a comma-separated list.
- Hosted YouTube ingestion on Render is likely to fail without a rotating proxy because YouTube blocks many cloud-provider IPs.
- Set `YOUTUBE_PROXY_ENABLED=true` and configure `YOUTUBE_PROXY_HTTP_URL` and/or `YOUTUBE_PROXY_HTTPS_URL` when you want hosted YouTube transcript fetches and `yt-dlp` requests to run through a proxy.
- If only one proxy URL is provided, the backend reuses it for both transcript fetches and `yt-dlp` requests.
- `YT_DLP_DENO_PATH` is optional. Leave it empty when `deno` is already on `PATH`; set it to the Deno executable path if the backend process cannot find Deno.
- The Nunchaku retry and throttle settings have built-in defaults: 2 seconds between attempts, 4 rate-limit retries, 3 seconds base backoff, and rewrite recovery disabled.
- Generated images and uploaded audio are stored under `/tmp/visualang_images`.

### Frontend: `frontend/.env`

```bash
VITE_API_URL=http://localhost:8000
```

If omitted, the frontend falls back to `http://localhost:8000`.

## How The Pipeline Works

1. `POST /transcript`
   Accepts either JSON with a YouTube video or Shorts URL, or multipart upload with an audio file. YouTube first tries `youtube-transcript-api`, then falls back to `yt-dlp` + OpenAI transcription when captions are unavailable or fail to load; local uploads use OpenAI transcription directly.
2. Transcript gate
   `TranscriptGate` evaluates whether the transcript is usable before the rest of the pipeline runs.
3. `POST /concepts`
   `ConceptExtractor` turns transcript segments into visual moments with image prompts.
4. `POST /generate`
   The backend generates images serially through Nunchaku and streams progress back over server-sent events.
5. Browser preview
   The React player preloads generated images, syncs them to audio, and applies Ken Burns style motion and fades.
6. `POST /export`
   The backend starts an FFmpeg export job, then the frontend polls for completion and exposes download links for the final video, transcript, and image zip.
7. Demo + observability helpers
   Seeded demos are served from `/demo/*`, and rolling in-memory stats are exposed from `/metrics`.

## Contributor Notes

- The backend runtime agents are documented in [backend/AGENTS.md](backend/AGENTS.md).
- The main frontend orchestration lives in `frontend/src/App.jsx`.
- The browser preview player lives in `frontend/src/components/Player.jsx`.
- Generated assets are served from `/tmp/visualang_images` through `/images/*` and `/media/audio/*`.
- Seeded demo fixtures are generated by `backend/scripts/seed_demo.py` and served from the backend `/demo/*` routes. The frontend demo loader is only partially wired today.
- `GET /health` is the basic backend health check.
- `GET /metrics` and `POST /metrics/reset` are in-memory demo-oriented endpoints, not production monitoring.

## Testing

For test coverage, conventions, and troubleshooting notes, see [tests/TESTS_GUIDE.md](tests/TESTS_GUIDE.md).

Run the local VisuaLang test suite:

```bash
pytest tests/test_visualang_phase2.py -v
pytest tests/test_generate.py -v
pytest tests/test_export.py -v
```

Notes:

- These tests cover the current VisuaLang app rather than the old fork extras.
- `tests/test_generate.py` may require a valid `NUNCHAKU_API_KEY` depending on the path being exercised.

## Related Documentation

- [backend/AGENTS.md](backend/AGENTS.md) for runtime agent behavior, model usage, and router integration
- [render.yaml](render.yaml) for the Render service definitions
- [visualang-prompt-for-claude-code.md](visualang-prompt-for-claude-code.md) for the original build spec and product framing
