import logging
import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import CORS_ALLOWED_ORIGINS, YT_DLP_DENO_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


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

app = FastAPI(title="Visualang API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

IMAGE_DIR = Path("/tmp/visualang_images")
IMAGE_DIR.mkdir(exist_ok=True)
app.mount("/images", StaticFiles(directory=str(IMAGE_DIR)), name="images")

from routers import transcript, concepts, generate, export, metrics, demo  # noqa: E402

app.include_router(transcript.router)
app.include_router(concepts.router)
app.include_router(generate.router)
app.include_router(export.router)
app.include_router(metrics.router)
app.include_router(demo.router)


@app.get("/health")
def health():
    return {"status": "ok"}
