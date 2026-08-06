import os
from pathlib import Path
import shutil
from dotenv import load_dotenv

load_dotenv()

DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_optional_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _get_csv(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return default

    values = [item.strip() for item in raw.split(",")]
    filtered = [item for item in values if item]
    return filtered or default


# API keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CLOUDFLARE_ACCOUNT_ID = _get_optional_str("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = _get_optional_str("CLOUDFLARE_API_TOKEN")
NUNCHAKU_API_KEY = os.getenv("NUNCHAKU_API_KEY")
CORS_ALLOWED_ORIGINS = _get_csv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS)
YOUTUBE_PROXY_HTTP_URL = _get_optional_str("YOUTUBE_PROXY_HTTP_URL")
YOUTUBE_PROXY_HTTPS_URL = _get_optional_str("YOUTUBE_PROXY_HTTPS_URL")
YOUTUBE_PROXY_ENABLED = _get_bool(
    "YOUTUBE_PROXY_ENABLED",
    bool(YOUTUBE_PROXY_HTTP_URL or YOUTUBE_PROXY_HTTPS_URL),
)
YT_DLP_DENO_PATH = _get_optional_str("YT_DLP_DENO_PATH") or shutil.which("deno")
VISUALANG_DATA_DIR = Path(os.getenv("VISUALANG_DATA_DIR", "/tmp/visualang_data"))
JOB_RETENTION_SECONDS = _get_int("JOB_RETENTION_SECONDS", 86400)

# Image generation settings
IMAGE_PROVIDER = (_get_optional_str("IMAGE_PROVIDER") or "cloudflare").lower()
IMAGE_GENERATION_CONCURRENCY = max(
    1, _get_int("IMAGE_GENERATION_CONCURRENCY", 4)
)
IMAGE_ENABLE_REWRITE_RECOVERY = _get_bool(
    "IMAGE_ENABLE_REWRITE_RECOVERY",
    _get_bool("NUNCHAKU_ENABLE_REWRITE_RECOVERY", False),
)

# Cloudflare Workers AI settings
CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
CLOUDFLARE_MAX_RETRIES = max(
    0, _get_int("CLOUDFLARE_MAX_RETRIES", 4)
)
CLOUDFLARE_BACKOFF_BASE_SECONDS = max(
    0.0, _get_float("CLOUDFLARE_BACKOFF_BASE_SECONDS", 1.0)
)

# Nunchaku settings
NUNCHAKU_MODEL = "nunchaku-flux.2-klein-9b"
NUNCHAKU_TIER = "fast"
NUNCHAKU_BASE_URL = "https://api.nunchaku.dev"
NUNCHAKU_NEGATIVE_PROMPT = (
    "text, words, letters, signs, labels, watermark, logo, UI elements, captions"
)
NUNCHAKU_MIN_INTERVAL_SECONDS = _get_float("NUNCHAKU_MIN_INTERVAL_SECONDS", 2.0)
NUNCHAKU_MAX_429_RETRIES = _get_int("NUNCHAKU_MAX_429_RETRIES", 4)
NUNCHAKU_BACKOFF_BASE_SECONDS = _get_float("NUNCHAKU_BACKOFF_BASE_SECONDS", 3.0)
NUNCHAKU_ENABLE_REWRITE_RECOVERY = IMAGE_ENABLE_REWRITE_RECOVERY

# Claude settings
CLAUDE_MODEL = "claude-sonnet-4-6"

# System prompt
SYSTEM_PROMPT = """
You are a visual companion generator for language learning videos. Given a transcript with
timestamps, identify 1 visual concept every 20-30 seconds that is concrete and visualizable.

For each concept return:
- timestamp_seconds (integer)
- concept (the word or phrase in the original language)
- image_prompt (English image generation prompt)

Rules for image_prompts:
- Describe only visual elements — no text, signs, labels, letters, or words anywhere in the scene
- Simple composition with one clear primary subject
- Translate concepts to English even if the transcript is in another language
- Skip abstract or non-visual moments — pick the next concrete one instead
- End every prompt with: "children's storybook illustration, simple composition, one main \
subject, soft colors, painterly, no text, no letters"

Output a JSON array only. No preamble, no explanation, no markdown.
"""
