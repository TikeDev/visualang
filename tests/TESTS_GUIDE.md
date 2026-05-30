# Tests Guide

This directory contains the backend-focused pytest suite for VisuaLang. The
tests are designed to validate the local FastAPI pipeline behavior without
calling live model, transcription, YouTube, or image generation providers.

## Setup

Install the Python test dependencies from the repo root:

```bash
pip install -r requirements.txt
```

The tests import backend modules directly by adding `backend/` to `sys.path`.
You do not need to start the FastAPI server before running them.

## Common Commands

Run the full test directory:

```bash
pytest tests -v
```

Run a single module:

```bash
pytest tests/test_visualang_phase2.py -v
pytest tests/test_generate.py -v
pytest tests/test_export.py -v
pytest tests/test_config.py -v
```

Run tests whose names match a keyword:

```bash
pytest tests -k transcript -v
```

Stop after the first failure:

```bash
pytest tests -x -v
```

## Module Map

| File | Covers |
|------|--------|
| `test_config.py` | Environment variable parsing, especially YouTube proxy settings. |
| `test_visualang_phase2.py` | Transcript routes, YouTube and upload ingestion, transcript gate handling, proxy behavior, concept extraction errors, and audio media serving. |
| `test_generate.py` | Nunchaku request retry behavior, `429` backoff, request spacing, and prompt rewrite recovery. |
| `test_export.py` | Ken Burns variant selection, transition planning, FFmpeg argument generation, export route job setup, transcript output, and image zip artifacts. |

## Test Conventions

- Mock provider and network boundaries with `monkeypatch`; normal tests should
  not make live OpenAI, Anthropic, Nunchaku, YouTube, or proxy requests.
- Prefer focused route and helper tests over broad end-to-end tests. Most tests
  validate one backend behavior and stub expensive dependencies.
- Use FastAPI `TestClient` for route behavior when HTTP status codes and
  response payloads matter.
- Keep generated test files cleaned up. Export and media-route tests may create
  files under `/tmp/visualang_images`.
- Keep tests deterministic. Retry, throttle, and timing behavior should use
  fake sleep/time functions instead of real waiting.
- Do not require real secrets for routine test runs. If a test needs an API
  key path, patch the client or configuration instead of reading local `.env`
  secrets.

## External Tooling Notes

- `test_export.py` includes an FFmpeg smoke test that is skipped automatically
  when `ffmpeg` is not available on the shell path.
- The rest of the suite should run without external services as long as Python
  dependencies are installed.
- `tests/test_generate.py` validates Nunchaku request construction and retry
  behavior with fake responses, not live image generation.
