import logging
import re
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

from agents import transcript_gate
from config import (
    OPENAI_API_KEY,
    YT_DLP_DENO_PATH,
    YOUTUBE_PROXY_ENABLED,
    YOUTUBE_PROXY_HTTP_URL,
    YOUTUBE_PROXY_HTTPS_URL,
)

logger = logging.getLogger(__name__)
router = APIRouter()

IMAGE_DIR = Path("/tmp/visualang_images")
IMAGE_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
AUDIO_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


class YtDlpLogBridge:
    def debug(self, msg: str):
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str):
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg: str):
        logger.error("yt-dlp: %s", msg)


# --- Normalizers ---

def _segment_value(segment: dict, key: str):
    if isinstance(segment, dict):
        return segment[key]
    return getattr(segment, key)


def normalize_segment(segment: dict, source: str) -> dict:
    if source == "youtube":
        return {
            "text": _segment_value(segment, "text"),
            "start": _segment_value(segment, "start"),
            "duration": _segment_value(segment, "duration"),
        }
    elif source == "whisper":
        return {
            "text": _segment_value(segment, "text"),
            "start": _segment_value(segment, "start"),
            "duration": _segment_value(segment, "end") - _segment_value(segment, "start"),
        }


def normalize_transcript(segments: list, source: str) -> list:
    return [normalize_segment(s, source) for s in segments]


# --- Helpers ---

def youtube_proxy_enabled() -> bool:
    return YOUTUBE_PROXY_ENABLED and bool(YOUTUBE_PROXY_HTTP_URL or YOUTUBE_PROXY_HTTPS_URL)


def get_yt_dlp_proxy_url() -> str | None:
    if not youtube_proxy_enabled():
        return None
    return YOUTUBE_PROXY_HTTPS_URL or YOUTUBE_PROXY_HTTP_URL


def get_proxy_connection_label() -> str:
    if not youtube_proxy_enabled():
        return "direct connection"
    proxy_url = get_yt_dlp_proxy_url()
    parsed = urlparse(proxy_url or "")
    host = parsed.hostname or "configured proxy"
    port = f":{parsed.port}" if parsed.port else ""
    scheme = parsed.scheme or "http"
    return f"proxy connection ({scheme}://{host}{port})"


def build_youtube_transcript_api():
    if not youtube_proxy_enabled():
        return YouTubeTranscriptApi()
    return YouTubeTranscriptApi(
        proxy_config=GenericProxyConfig(
            http_url=YOUTUBE_PROXY_HTTP_URL,
            https_url=YOUTUBE_PROXY_HTTPS_URL,
        )
    )


def build_yt_dlp_options(*, skip_download: bool = False, output_base: str | None = None) -> dict:
    ydl_opts = {
        "quiet": True,
        "noprogress": True,
        "logger": YtDlpLogBridge(),
        "js_runtimes": {"deno": {"path": YT_DLP_DENO_PATH}},
    }
    if skip_download:
        ydl_opts["skip_download"] = True
    if output_base is not None:
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "outtmpl": output_base,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            }
        )
    proxy_url = get_yt_dlp_proxy_url()
    if proxy_url:
        ydl_opts["proxy"] = proxy_url
    return ydl_opts


def get_video_info(video_url: str) -> dict:
    ydl_opts = build_yt_dlp_options(skip_download=True)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        return {"title": info.get("title", "Untitled"), "duration": info.get("duration", 0)}


def extract_audio(video_url: str, output_base: str):
    ydl_opts = build_yt_dlp_options(output_base=output_base)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])


def transcribe_audio(audio_path: str) -> list:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return normalize_transcript(response.segments or [], source="whisper")


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if host == "youtu.be":
        candidate = path.lstrip("/").split("/", 1)[0]
        if candidate:
            return candidate

    if host == "youtube.com" or host.endswith(".youtube.com"):
        if path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
            if candidate:
                return candidate

        short_match = re.match(r"^/shorts/([^/?]+)", path)
        if short_match:
            return short_match.group(1)

    raise ValueError(f"Could not extract video ID from URL: {url}")


def build_audio_url(audio_path: str) -> str:
    return f"/media/audio/{Path(audio_path).name}"


def build_youtube_audio_path(video_id: str) -> str:
    return str(IMAGE_DIR / f"{video_id}.mp3")


def resolve_audio_file(filename: str) -> Path:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = IMAGE_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return path


def audio_media_type(path: Path) -> str:
    return AUDIO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def select_youtube_transcript(video_id: str):
    ytt_api = build_youtube_transcript_api()
    transcript_list = ytt_api.list(video_id)
    transcripts = list(transcript_list)
    if not transcripts:
        raise ValueError(f"No transcripts available for video {video_id}")

    # Prefer manually created subtitles when present, otherwise fall back to the
    # first available auto-generated track. This preserves the video's spoken
    # language instead of defaulting to English-only captions.
    manual = [item for item in transcripts if not item.is_generated]
    selected = manual[0] if manual else transcripts[0]
    logger.info(
        "Selected %s transcript for %s: %s (%s)",
        "generated" if selected.is_generated else "manual",
        video_id,
        selected.language_code,
        selected.language,
    )
    return selected


# --- Routes ---

class YoutubeRequest(BaseModel):
    video_url: str


async def _handle_youtube(video_url: str):
    logger.info(f"Transcript request for YouTube URL: {video_url}")
    try:
        video_id = extract_video_id(video_url)
        logger.info(f"Extracted video ID: {video_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("YouTube ingestion using %s", get_proxy_connection_label())

    info: dict | None = None
    title = "Untitled"
    try:
        info = get_video_info(video_url)
        title = info["title"]
        logger.info(f"Video title: {title}")
    except Exception as e:
        logger.warning("Could not fetch video info over %s: %s", get_proxy_connection_label(), e)

    audio_base = str(IMAGE_DIR / video_id)
    audio_path = build_youtube_audio_path(video_id)
    audio_ready = False

    try:
        selected_transcript = select_youtube_transcript(video_id)
        raw_transcript = selected_transcript.fetch().to_raw_data()
        normalized = normalize_transcript(raw_transcript, "youtube")
        logger.info(
            "Fetched transcript: %s segments from %s (%s)",
            len(normalized),
            selected_transcript.language_code,
            selected_transcript.language,
        )
    except Exception as e:
        logger.warning(
            "Transcript fetch failed for %s over %s; falling back to Whisper transcription: %s",
            video_id,
            get_proxy_connection_label(),
            e,
        )
        try:
            extract_audio(video_url, audio_base)
            audio_ready = True
            logger.info(f"Audio extracted to: {audio_path}")
        except Exception as audio_error:
            logger.error(
                "Audio extraction failed during transcript fallback over %s: %s",
                get_proxy_connection_label(),
                audio_error,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to fetch transcript. Audio extraction fallback failed.",
            )

        try:
            normalized = transcribe_audio(audio_path)
            logger.info("Transcribed fallback audio: %s segments", len(normalized))
        except Exception as transcription_error:
            logger.error("Whisper fallback failed for %s: %s", video_id, transcription_error)
            raise HTTPException(
                status_code=500,
                detail="Failed to fetch transcript. Transcription fallback failed.",
            )

    # Prefer yt-dlp duration; fall back to last segment end time.
    if info and info.get("duration"):
        duration = info["duration"]
    elif normalized:
        last = normalized[-1]
        duration = last["start"] + last["duration"]
    else:
        duration = 0
    verdict = await transcript_gate.run(normalized, title=title, duration=duration)
    if verdict.verdict == "reject":
        raise HTTPException(status_code=422, detail=f"Transcript rejected: {verdict.reason}")

    if not audio_ready:
        try:
            extract_audio(video_url, audio_base)
            audio_ready = True
            logger.info(f"Audio extracted to: {audio_path}")
        except Exception as e:
            logger.error("Audio extraction failed over %s: %s", get_proxy_connection_label(), e)
            raise HTTPException(status_code=500, detail="Audio extraction failed.")

    return {
        "transcript": normalized,
        "audio_path": audio_path,
        "audio_url": build_audio_url(audio_path),
        "title": title,
        "gate": {
            "verdict": verdict.verdict,
            "reason": verdict.reason,
            "detected_language": verdict.detected_language,
        },
    }


async def _handle_upload(file: UploadFile):
    logger.info(f"Transcript upload: {file.filename}, size={file.size}")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    audio_bytes = await file.read()
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 25 MB limit.")

    filename = f"{uuid.uuid4()}_{file.filename}"
    audio_path = IMAGE_DIR / filename
    try:
        audio_path.write_bytes(audio_bytes)
        logger.info(f"Saved upload to: {audio_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    try:
        normalized = transcribe_audio(str(audio_path))
        logger.info(f"Transcribed: {len(normalized)} segments")
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    title = Path(file.filename).stem
    duration = (normalized[-1]["start"] + normalized[-1]["duration"]) if normalized else 0
    verdict = await transcript_gate.run(normalized, title=title, duration=duration)
    if verdict.verdict == "reject":
        raise HTTPException(status_code=422, detail=f"Transcript rejected: {verdict.reason}")

    return {
        "transcript": normalized,
        "audio_path": str(audio_path),
        "audio_url": build_audio_url(str(audio_path)),
        "title": title,
        "gate": {
            "verdict": verdict.verdict,
            "reason": verdict.reason,
            "detected_language": verdict.detected_language,
        },
    }


@router.post("/transcript")
async def transcript(request: Request):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            body = YoutubeRequest.model_validate(await request.json())
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")
        return await _handle_youtube(body.video_url)

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if file is None or not hasattr(file, "filename"):
            raise HTTPException(status_code=400, detail="Missing file upload")
        return await _handle_upload(file)

    raise HTTPException(
        status_code=400,
        detail="Unsupported content type. Use application/json or multipart/form-data.",
    )


@router.post("/transcript/youtube")
async def transcript_youtube(body: YoutubeRequest):
    return await _handle_youtube(body.video_url)


@router.post("/transcript/upload")
async def transcript_upload(file: UploadFile = File(...)):
    return await _handle_upload(file)


@router.get("/media/audio/{filename}")
async def get_audio_file(filename: str):
    path = resolve_audio_file(filename)
    return FileResponse(
        path,
        media_type=audio_media_type(path),
        filename=path.name,
        content_disposition_type="inline",
    )
