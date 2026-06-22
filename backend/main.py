import logging
import os
import signal
import shutil
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import CORS_ALLOWED_ORIGINS, VISUALANG_DATA_DIR, YT_DLP_DENO_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
PROCESS_STARTED_AT = time.time()
RENDER_METADATA_KEYS = (
    "RENDER",
    "RENDER_SERVICE_ID",
    "RENDER_SERVICE_NAME",
    "RENDER_INSTANCE_ID",
    "RENDER_SERVICE_TYPE",
    "RENDER_EXTERNAL_URL",
    "RENDER_GIT_COMMIT",
    "RENDER_GIT_BRANCH",
)
SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM)
shutdown_signal_name: str | None = None
previous_signal_handlers: dict[int, signal.Handlers] = {}


def collect_render_metadata() -> dict[str, str]:
    return {
        key.lower(): value
        for key in RENDER_METADATA_KEYS
        if (value := os.getenv(key))
    }


def format_metadata(metadata: dict[str, str]) -> str:
    if not metadata:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(metadata.items()))


def is_render_runtime() -> bool:
    return os.getenv("RENDER") == "true"


def handle_shutdown_signal(signum: int, frame) -> None:
    global shutdown_signal_name

    shutdown_signal_name = signal.Signals(signum).name
    logger.warning("Received shutdown signal: %s", shutdown_signal_name)

    previous_handler = previous_signal_handlers.get(signum)
    if callable(previous_handler):
        previous_handler(signum, frame)
    elif previous_handler == signal.SIG_DFL:
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)


def install_shutdown_signal_logging() -> None:
    if not is_render_runtime() or threading.current_thread() is not threading.main_thread():
        return

    for signum in SHUTDOWN_SIGNALS:
        current_handler = signal.getsignal(signum)
        if current_handler is handle_shutdown_signal:
            continue
        previous_signal_handlers[signum] = current_handler
        signal.signal(signum, handle_shutdown_signal)


def log_runtime_diagnostics():
    deno_path = YT_DLP_DENO_PATH or shutil.which("deno")
    ffmpeg_path = shutil.which("ffmpeg")

    if deno_path:
        logger.info("Deno runtime available for yt-dlp: %s", deno_path)
    else:
        logger.warning(
            "Deno runtime not found; YouTube extraction through yt-dlp may miss formats"
        )

    if ffmpeg_path:
        logger.info("FFmpeg available for export/audio extraction: %s", ffmpeg_path)
    else:
        logger.warning("FFmpeg not found; audio extraction and export may fail")

    logger.info("CORS allowed origins: %s", ", ".join(CORS_ALLOWED_ORIGINS))


log_runtime_diagnostics()


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_shutdown_signal_logging()
    logger.info(
        "App boot: pid=%s ppid=%s metadata=%s",
        os.getpid(),
        os.getppid(),
        format_metadata(collect_render_metadata()),
    )
    try:
        yield
    finally:
        logger.info(
            "App shutdown: pid=%s signal=%s uptime_seconds=%.1f",
            os.getpid(),
            shutdown_signal_name or "unknown",
            time.time() - PROCESS_STARTED_AT,
        )


app = FastAPI(title="Visualang API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

IMAGE_DIR = VISUALANG_DATA_DIR / "artifacts"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(IMAGE_DIR)), name="images")

from routers import transcript, concepts, generate, export, metrics, demo, jobs  # noqa: E402

app.include_router(transcript.router)
app.include_router(concepts.router)
app.include_router(generate.router)
app.include_router(export.router)
app.include_router(metrics.router)
app.include_router(demo.router)
app.include_router(jobs.router)


@app.get("/health")
def health():
    return {"status": "ok"}
