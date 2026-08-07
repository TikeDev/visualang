import asyncio
import json
import logging
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import VISUALANG_DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

IMAGE_DIR = VISUALANG_DATA_DIR / "artifacts"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_WIDTH = 1280
EXPORT_HEIGHT = 720
EXPORT_FPS = 24
EXPORT_SCALE_WIDTH = 1436
EXPORT_SCALE_HEIGHT = 808
CROSSFADE_DURATION_SECONDS = 0.8
DEFAULT_IMAGE_DURATION_SECONDS = 30.0
MIN_SCENE_DURATION_SECONDS = 1 / EXPORT_FPS
EXPORT_PROCESS_TIMEOUT_SECONDS = 14 * 60
EXPORT_CANCEL_TIMEOUT_SECONDS = 2.0
PROCESS_STARTED_AT = time.time()
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
jobs: dict[str, dict] = {}
active_processes: dict[str, asyncio.subprocess.Process] = {}


async def shutdown_process(process) -> None:
    """Stop a child process cooperatively, escalating to kill after a grace period."""
    if getattr(process, "returncode", None) is not None:
        await process.wait()
        return

    try:
        process.terminate()
    except ProcessLookupError:
        await process.wait()
        return

    try:
        await asyncio.wait_for(
            process.wait(), timeout=EXPORT_CANCEL_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


def remove_export_partials(
    job_id: str,
    *,
    output_path: str | Path | None = None,
    stderr_path: str | Path | None = None,
) -> None:
    job = jobs.get(job_id, {})
    paths = (
        output_path or job.get("output_path"),
        stderr_path or job.get("stderr_path"),
    )
    for path in paths:
        if path:
            Path(path).unlink(missing_ok=True)


async def cancel_export(job_id: str) -> bool:
    process = active_processes.get(job_id)
    if process is None:
        return False

    update_job(job_id, status="cancelled", error=None)
    try:
        await shutdown_process(process)
        remove_export_partials(job_id)
    finally:
        if active_processes.get(job_id) is process:
            active_processes.pop(job_id, None)
    return True


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
    job["updated_at"] = time.time()
    persist_job(job_id)
    return job


def coerce_job_timestamp(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_text_tail(path: Path, max_bytes: int = 8000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(size - max_bytes, 0))
        return handle.read().decode("utf-8", errors="replace")


def total_export_duration(images: list[dict]) -> float:
    return sum(
        normalize_scene_duration(img.get("duration_seconds", DEFAULT_IMAGE_DURATION_SECONDS))
        for img in images
    )


def reconcile_export_job(job_id: str, job: dict) -> dict:
    status = job.get("status")
    if status not in {"pending", "running"}:
        return job

    output_path = job.get("video_path") or job.get("output_path")
    if output_path and Path(output_path).is_file() and Path(output_path).stat().st_size > 0:
        return update_job(job_id, status="done", video_path=output_path, error=None)

    reference_time = coerce_job_timestamp(
        job.get("started_at") or job.get("created_at") or job.get("updated_at")
    )
    if reference_time is None or reference_time < PROCESS_STARTED_AT:
        return update_job(
            job_id,
            status="error",
            error="Export was interrupted by a server restart. Retry export from the preview.",
        )

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
    return reconcile_export_job(job_id, job)


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


def probe_audio_duration(audio_path: str) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def derive_image_durations(
    images: list[dict],
    audio_duration: float | None,
    fade_duration: float = CROSSFADE_DURATION_SECONDS,
) -> list[dict]:
    """Fill in duration_seconds from consecutive timestamp_seconds boundaries.

    Mirrors the frontend Player: image i shows from its timestamp until the
    next image's timestamp (the first image is pulled back to t=0), and the
    last image runs to the end of the audio.
    """
    if all("duration_seconds" in img for img in images):
        return images
    if not all("timestamp_seconds" in img for img in images):
        return images

    ordered = sorted(images, key=lambda img: img["timestamp_seconds"])
    boundaries = [0.0] + [float(img["timestamp_seconds"]) for img in ordered[1:]]
    if audio_duration is not None:
        boundaries.append(float(audio_duration))
    else:
        boundaries.append(
            float(ordered[-1]["timestamp_seconds"]) + DEFAULT_IMAGE_DURATION_SECONDS
        )

    durations = [
        normalize_scene_duration(boundaries[i + 1] - boundaries[i])
        for i in range(len(ordered))
    ]
    # Each xfade shortens the timeline by fade_duration; extend the incoming
    # scene so every fade completes exactly at that scene's timestamp and the
    # video track spans the full audio.
    for i in range(1, len(durations)):
        if can_crossfade(durations[i - 1], durations[i], fade_duration):
            durations[i] += fade_duration

    return [
        {**img, "duration_seconds": duration}
        for img, duration in zip(ordered, durations)
    ]


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

    ffmpeg_args = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
    ]
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
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            output_path,
        ]
    )
    return ffmpeg_args


async def run_ffmpeg_export(job_id: str, audio_path: str, images: list, output_path: str):
    export_started_at = time.time()
    proc = None
    if not all("duration_seconds" in img for img in images):
        audio_duration = await asyncio.to_thread(probe_audio_duration, audio_path)
        images = derive_image_durations(images, audio_duration)
    expected_duration = total_export_duration(images)
    update_job(
        job_id,
        status="running",
        started_at=export_started_at,
        output_path=output_path,
        image_count=len(images),
        expected_duration_seconds=expected_duration,
    )
    stderr_path = IMAGE_DIR / f"{job_id}_ffmpeg.stderr.log"
    try:
        ffmpeg_args = build_ffmpeg_args(audio_path, images, output_path)
        logger.info(
            "Running FFmpeg export for job %s: images=%s expected_duration=%.3fs output=%s",
            job_id,
            len(images),
            expected_duration,
            output_path,
        )
        with stderr_path.open("wb") as stderr_file:
            proc = await asyncio.create_subprocess_exec(
                *ffmpeg_args,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )
            active_processes[job_id] = proc
            update_job(job_id, ffmpeg_pid=proc.pid, stderr_path=str(stderr_path))
            logger.info(
                "FFmpeg process started for job %s: pid=%s",
                job_id,
                proc.pid,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=EXPORT_PROCESS_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = time.time() - export_started_at
                if jobs.get(job_id, {}).get("status") == "cancelled":
                    return
                logger.error(
                    "FFmpeg export timed out for job %s: pid=%s elapsed=%.3fs",
                    job_id,
                    proc.pid,
                    elapsed,
                )
                update_job(
                    job_id,
                    status="error",
                    error=(
                        "FFmpeg export timed out. Retry export with fewer concepts "
                        "or a shorter clip."
                    ),
                    stderr_path=str(stderr_path),
                    returncode=proc.returncode,
                    elapsed_seconds=elapsed,
                )
                return

        elapsed = time.time() - export_started_at
        if jobs.get(job_id, {}).get("status") == "cancelled":
            return
        if proc.returncode != 0:
            stderr_tail = read_text_tail(stderr_path)
            logger.error(
                "FFmpeg failed for job %s: pid=%s returncode=%s elapsed=%.3fs stderr=%s",
                job_id,
                proc.pid,
                proc.returncode,
                elapsed,
                stderr_tail,
            )
            update_job(
                job_id,
                status="error",
                error=stderr_tail or f"FFmpeg exited with code {proc.returncode}",
                stderr_path=str(stderr_path),
                returncode=proc.returncode,
                elapsed_seconds=elapsed,
            )
            return

        output_size = Path(output_path).stat().st_size
        if jobs.get(job_id, {}).get("status") == "cancelled":
            return
        logger.info(
            "FFmpeg export complete for job %s: pid=%s returncode=%s elapsed=%.3fs "
            "output_size=%s bytes",
            job_id,
            proc.pid,
            proc.returncode,
            elapsed,
            output_size,
        )
        update_job(
            job_id,
            status="done",
            video_path=output_path,
            stderr_path=str(stderr_path),
            returncode=proc.returncode,
            elapsed_seconds=elapsed,
            output_size_bytes=output_size,
        )

    except asyncio.CancelledError:
        elapsed = time.time() - export_started_at
        update_job(
            job_id,
            status="cancelled",
            error="Export interrupted",
            elapsed_seconds=elapsed,
        )
        if proc is not None:
            await asyncio.shield(shutdown_process(proc))
        remove_export_partials(
            job_id, output_path=output_path, stderr_path=stderr_path
        )
        raise
    except Exception as e:
        elapsed = time.time() - export_started_at
        logger.error(
            "Export failed for job %s: elapsed=%.3fs error=%s",
            job_id,
            elapsed,
            e,
        )
        if jobs.get(job_id, {}).get("status") != "cancelled":
            update_job(job_id, status="error", error=str(e), elapsed_seconds=elapsed)
    finally:
        if active_processes.get(job_id) is proc:
            active_processes.pop(job_id, None)


@router.post("/export")
async def start_export(body: ExportRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    output_path = str(IMAGE_DIR / f"{job_id}.mp4")

    images_dicts = [img.model_dump() for img in body.images]
    now = time.time()
    jobs[job_id] = {
        "status": "pending",
        "video_path": None,
        "output_path": output_path,
        "created_at": now,
        "updated_at": now,
    }
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
