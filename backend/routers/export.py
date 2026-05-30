import asyncio
import json
import logging
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

IMAGE_DIR = Path("/tmp/visualang_images")
IMAGE_DIR.mkdir(exist_ok=True)
EXPORT_WIDTH = 1280
EXPORT_HEIGHT = 720
EXPORT_FPS = 30
EXPORT_SCALE_WIDTH = 1436
EXPORT_SCALE_HEIGHT = 808
CROSSFADE_DURATION_SECONDS = 0.8
DEFAULT_IMAGE_DURATION_SECONDS = 30.0
MIN_SCENE_DURATION_SECONDS = 1 / EXPORT_FPS
KEN_BURNS_VARIANTS = [
    {
        "name": "ken-burns-zoom-in-left",
        "zoom_start": 1.0,
        "zoom_end": 1.08,
        "pan_x": -0.02,
        "pan_y": -0.01,
    },
    {
        "name": "ken-burns-zoom-in-right",
        "zoom_start": 1.0,
        "zoom_end": 1.08,
        "pan_x": 0.02,
        "pan_y": 0.01,
    },
    {
        "name": "ken-burns-zoom-out-left",
        "zoom_start": 1.08,
        "zoom_end": 1.0,
        "pan_x": -0.01,
        "pan_y": 0.01,
    },
    {
        "name": "ken-burns-zoom-out-right",
        "zoom_start": 1.08,
        "zoom_end": 1.0,
        "pan_x": 0.02,
        "pan_y": -0.01,
    },
]

# In-memory job registry
jobs: dict = {}


class ExportImage(BaseModel):
    timestamp_seconds: float
    image_url: str
    duration_seconds: float
    concept: str = ""


class ExportRequest(BaseModel):
    audio_path: str
    images: list[ExportImage]
    transcript: list = []


def get_job_metadata_path(job_id: str) -> Path:
    return IMAGE_DIR / f"{job_id}.json"


def persist_job(job_id: str) -> None:
    job = jobs.get(job_id)
    if job is None:
        return

    path = get_job_metadata_path(job_id)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(job), encoding="utf-8")
    tmp_path.replace(path)


def update_job(job_id: str, **fields) -> dict:
    job = jobs.setdefault(job_id, {"status": "pending", "video_path": None})
    job.update(fields)
    persist_job(job_id)
    return job


def load_persisted_job(job_id: str) -> dict | None:
    if job_id in jobs:
        return jobs[job_id]

    path = get_job_metadata_path(job_id)
    if not path.is_file():
        return None

    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Could not parse export job metadata for %s", job_id)
        return None

    if not isinstance(job, dict):
        logger.warning("Export job metadata for %s was not an object", job_id)
        return None

    jobs[job_id] = job
    return job


def require_job(job_id: str) -> dict:
    job = load_persisted_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def format_seconds(value: float) -> str:
    return f"{value:.3f}"


def normalize_scene_duration(duration_seconds: float) -> float:
    return max(float(duration_seconds or 0), MIN_SCENE_DURATION_SECONDS)


def seconds_to_frames(duration_seconds: float, fps: int = EXPORT_FPS) -> int:
    return max(1, int(round(duration_seconds * fps)))


def get_ken_burns_variant(index: int) -> dict:
    return KEN_BURNS_VARIANTS[index % len(KEN_BURNS_VARIANTS)]


def resolve_export_image_path(image_url: str) -> Path:
    filename = Path(urlparse(image_url).path).name
    if not filename:
        raise ValueError(f"Invalid image URL for export: {image_url!r}")
    return IMAGE_DIR / filename


def can_crossfade(previous_duration: float, next_duration: float, fade_duration: float) -> bool:
    return previous_duration > fade_duration and next_duration > fade_duration


def build_transition_plan(
    durations: list[float],
    fade_duration: float = CROSSFADE_DURATION_SECONDS,
) -> list[dict]:
    if not durations:
        return []

    transitions: list[dict] = []
    current_timeline = durations[0]
    for index in range(1, len(durations)):
        previous_duration = durations[index - 1]
        next_duration = durations[index]
        if can_crossfade(previous_duration, next_duration, fade_duration):
            offset = max(current_timeline - fade_duration, 0.0)
            transitions.append(
                {
                    "index": index,
                    "type": "xfade",
                    "duration": fade_duration,
                    "offset": round(offset, 3),
                }
            )
            current_timeline = current_timeline + next_duration - fade_duration
        else:
            transitions.append(
                {
                    "index": index,
                    "type": "concat",
                    "duration": 0.0,
                    "offset": round(current_timeline, 3),
                }
            )
            current_timeline += next_duration
    return transitions


def build_scene_filter(
    input_index: int,
    scene_index: int,
    duration_seconds: float,
    fps: int = EXPORT_FPS,
) -> str:
    duration_seconds = normalize_scene_duration(duration_seconds)
    frames = seconds_to_frames(duration_seconds, fps=fps)
    frame_denominator = max(frames - 1, 1)
    variant = get_ken_burns_variant(scene_index)
    zoom_start = variant["zoom_start"]
    zoom_end = variant["zoom_end"]
    zoom_step = abs(zoom_end - zoom_start) / frame_denominator
    if zoom_end >= zoom_start:
        zoom_expr = (
            f"if(eq(on,0),{zoom_start:.5f},min(zoom+{zoom_step:.6f},{zoom_end:.5f}))"
        )
    else:
        zoom_expr = (
            f"if(eq(on,0),{zoom_start:.5f},max(zoom-{zoom_step:.6f},{zoom_end:.5f}))"
        )
    x_expr = f"(iw-iw/zoom)/2+({variant['pan_x']:.5f}*iw)*on/{frame_denominator}"
    y_expr = f"(ih-ih/zoom)/2+({variant['pan_y']:.5f}*ih)*on/{frame_denominator}"
    return (
        f"[{input_index}:v]"
        f"scale={EXPORT_SCALE_WIDTH}:{EXPORT_SCALE_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={EXPORT_SCALE_WIDTH}:{EXPORT_SCALE_HEIGHT},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={EXPORT_WIDTH}x{EXPORT_HEIGHT}:fps={fps},"
        f"trim=duration={format_seconds(duration_seconds)},"
        f"fps={fps},"
        f"settb=AVTB,"
        f"setpts=N/({fps}*TB),"
        f"setsar=1,format=yuv420p"
        f"[v{scene_index}]"
    )


def build_filter_complex(
    images: list[dict],
    fps: int = EXPORT_FPS,
    fade_duration: float = CROSSFADE_DURATION_SECONDS,
) -> tuple[str, str]:
    if not images:
        raise ValueError("At least one image is required for export")

    durations = [
        normalize_scene_duration(img.get("duration_seconds", DEFAULT_IMAGE_DURATION_SECONDS))
        for img in images
    ]
    filter_parts = [
        build_scene_filter(input_index=i, scene_index=i, duration_seconds=duration, fps=fps)
        for i, duration in enumerate(durations)
    ]

    current_label = "[v0]"
    for transition in build_transition_plan(durations, fade_duration=fade_duration):
        next_label = f"[v{transition['index']}]"
        output_label = f"[vx{transition['index']}]"
        if transition["type"] == "xfade":
            filter_parts.append(
                f"{current_label}{next_label}"
                f"xfade=transition=fade:duration={format_seconds(transition['duration'])}:"
                f"offset={format_seconds(transition['offset'])}"
                f"{output_label}"
            )
        else:
            filter_parts.append(
                f"{current_label}{next_label}concat=n=2:v=1:a=0{output_label}"
            )
        current_label = output_label

    final_label = "[video]"
    filter_parts.append(f"{current_label}format=yuv420p{final_label}")
    return ";".join(filter_parts), final_label


def build_ffmpeg_args(
    audio_path: str,
    images: list[dict],
    output_path: str,
    fps: int = EXPORT_FPS,
) -> list[str]:
    if not images:
        raise ValueError("At least one image is required for export")

    ffmpeg_args = ["ffmpeg", "-y"]
    for img in images:
        duration = normalize_scene_duration(
            img.get("duration_seconds", DEFAULT_IMAGE_DURATION_SECONDS)
        )
        ffmpeg_args.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-t",
                format_seconds(duration),
                "-i",
                str(resolve_export_image_path(img["image_url"])),
            ]
        )

    filter_complex, final_video_label = build_filter_complex(images, fps=fps)
    ffmpeg_args.extend(
        [
            "-i",
            audio_path,
            "-filter_complex",
            filter_complex,
            "-map",
            final_video_label,
            "-map",
            f"{len(images)}:a",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            output_path,
        ]
    )
    return ffmpeg_args


async def run_ffmpeg_export(job_id: str, audio_path: str, images: list, output_path: str):
    update_job(job_id, status="running")
    try:
        ffmpeg_args = build_ffmpeg_args(audio_path, images, output_path)
        logger.info(f"Running FFmpeg export for job {job_id}")
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"FFmpeg failed for job {job_id}: {stderr.decode()}")
            update_job(job_id, status="error", error=stderr.decode())
            return

        output_size = Path(output_path).stat().st_size
        logger.info(f"FFmpeg export complete for job {job_id}: {output_size} bytes")
        update_job(job_id, status="done", video_path=output_path)

    except Exception as e:
        logger.error(f"Export failed for job {job_id}: {e}")
        update_job(job_id, status="error", error=str(e))


@router.post("/export")
async def start_export(body: ExportRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    output_path = str(IMAGE_DIR / f"{job_id}.mp4")

    images_dicts = [img.model_dump() for img in body.images]
    jobs[job_id] = {"status": "pending", "video_path": None}
    persist_job(job_id)

    background_tasks.add_task(
        run_ffmpeg_export, job_id, body.audio_path, images_dicts, output_path
    )

    # Also write transcript txt and images zip immediately
    if body.transcript:
        txt_path = IMAGE_DIR / f"{job_id}_transcript.txt"
        lines = []
        for seg in body.transcript:
            start = int(seg.get("start", 0))
            mm, ss = divmod(start, 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {seg.get('text', '')}")
        txt_path.write_text("\n".join(lines))
        update_job(job_id, transcript_path=str(txt_path))

    zip_path = IMAGE_DIR / f"{job_id}_images.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i, img in enumerate(body.images):
            filename = Path(urlparse(img.image_url).path).name
            img_path = IMAGE_DIR / filename
            if img_path.exists():
                ts = int(img.timestamp_seconds)
                concept = img.concept.replace(" ", "_")[:40]
                zf.write(img_path, f"{i:02d}_{ts}s_{concept}.jpg")
    update_job(job_id, zip_path=str(zip_path))

    return {"job_id": job_id}


@router.get("/export/{job_id}")
async def get_export_status(job_id: str):
    return require_job(job_id)


@router.get("/export/{job_id}/video")
async def download_video(job_id: str):
    job = require_job(job_id)
    video_path = job.get("video_path")
    if job.get("status") != "done" or not video_path or not Path(video_path).is_file():
        raise HTTPException(status_code=404, detail="Video not ready")
    return FileResponse(video_path, media_type="video/mp4",
                        filename="visualang.mp4")


@router.get("/export/{job_id}/transcript")
async def download_transcript(job_id: str):
    job = require_job(job_id)
    transcript_path = job.get("transcript_path")
    if not transcript_path or not Path(transcript_path).is_file():
        raise HTTPException(status_code=404, detail="Transcript not available")
    return FileResponse(transcript_path, media_type="text/plain",
                        filename="transcript.txt")


@router.get("/export/{job_id}/images")
async def download_images(job_id: str):
    job = require_job(job_id)
    zip_path = job.get("zip_path")
    if not zip_path or not Path(zip_path).is_file():
        raise HTTPException(status_code=404, detail="Images zip not available")
    return FileResponse(zip_path, media_type="application/zip",
                        filename="visualang_images.zip")
