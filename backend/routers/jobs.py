from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agents import concept_extractor
from config import JOB_RETENTION_SECONDS, VISUALANG_DATA_DIR
from job_runner import JobRunner
from job_store import JobStore
from routers import export as export_router
from routers import generate as generate_router
from routers.transcript import _handle_upload_bytes, _handle_youtube

logger = logging.getLogger(__name__)
router = APIRouter()

PRIVATE_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}

# Fields that may end up in job payloads but must never reach the client:
# filesystem paths, subprocess identifiers, and raw provider error detail.
_PRIVATE_FIELDS = frozenset(
    {
        "video_path",
        "output_path",
        "stderr_path",
        "zip_path",
        "transcript_path",
        "ffmpeg_pid",
        "audio_path",
    }
)

_store: JobStore | None = None
_runner: JobRunner | None = None


async def _transcript_fn(source: dict, *, cancel_event=None) -> dict:
    result = await _handle_youtube(source["url"], cancel_event=cancel_event)
    return {
        "transcript": result["transcript"],
        "audio_path": result["audio_path"],
        "title": result["title"],
        "gate": result["gate"],
    }


async def _concepts_fn(transcript_payload: dict) -> list:
    return await concept_extractor.run(transcript_payload["transcript"])


async def _images_fn(concepts: list, *, cancel_event=None, on_progress=None) -> list:
    return await generate_router.generate_images(
        concepts, cancel_event=cancel_event, on_progress=on_progress
    )


async def _export_fn(
    transcript_payload: dict, images: list, job_dir: Path, *, job_id: str
) -> dict:
    output_path = job_dir / "video.mp4"
    await export_router.run_ffmpeg_export(
        job_id, transcript_payload["audio_path"], images, str(output_path)
    )
    export_job = export_router.jobs.get(job_id, {})
    if export_job.get("status") != "done":
        raise RuntimeError(export_job.get("error") or "Export failed")
    return {"video_path": str(output_path)}


def get_job_store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore(VISUALANG_DATA_DIR, retention_seconds=JOB_RETENTION_SECONDS)
    return _store


def get_job_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner(
            get_job_store(),
            transcript_fn=_transcript_fn,
            concepts_fn=_concepts_fn,
            images_fn=_images_fn,
            export_fn=_export_fn,
        )
    return _runner


def sanitize_job(job: dict) -> dict:
    public = {key: value for key, value in job.items() if key not in _PRIVATE_FIELDS}
    public.pop("source", None)
    if public.get("error"):
        public["error"] = "The job failed. You can retry from the failed stage."
    return public


def require_job_by_token(token: str) -> dict:
    job = get_job_store().get_by_resume_token(token)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def private_response(payload: dict | None = None, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=payload or {}, status_code=status_code, headers=PRIVATE_RESPONSE_HEADERS
    )


class CreateJobRequest(BaseModel):
    type: str
    url: str


@router.post("/jobs", status_code=202)
async def create_job(body: CreateJobRequest):
    store = get_job_store()
    runner = get_job_runner()
    access = store.create_job({"type": body.type, "url": body.url})
    asyncio.ensure_future(runner.run(access.job_id))
    return private_response({"resume_token": access.resume_token}, status_code=202)


@router.post("/jobs/upload", status_code=202)
async def create_upload_job(file: UploadFile = File(...)):
    store = get_job_store()
    runner = get_job_runner()
    filename = file.filename
    audio_bytes = await file.read()
    access = store.create_job({"type": "upload", "filename": filename})

    async def transcript_fn(_source: dict, *, cancel_event=None) -> dict:
        result = await _handle_upload_bytes(audio_bytes, filename, cancel_event=cancel_event)
        return {
            "transcript": result["transcript"],
            "audio_path": result["audio_path"],
            "title": result["title"],
            "gate": result["gate"],
        }

    runner.transcript_fn = transcript_fn
    asyncio.ensure_future(runner.run(access.job_id))
    return private_response({"resume_token": access.resume_token}, status_code=202)


@router.get("/jobs/{resume_token}")
async def get_job(resume_token: str):
    job = require_job_by_token(resume_token)
    return private_response(sanitize_job(job))


@router.post("/jobs/{resume_token}/cancel")
async def cancel_job(resume_token: str):
    job = require_job_by_token(resume_token)
    await get_job_runner().cancel(job["id"])
    refreshed = require_job_by_token(resume_token)
    return private_response(sanitize_job(refreshed))


@router.post("/jobs/{resume_token}/retry", status_code=202)
async def retry_job(resume_token: str):
    job = require_job_by_token(resume_token)
    asyncio.ensure_future(get_job_runner().retry(job["id"]))
    return private_response(status_code=202)


@router.delete("/jobs/{resume_token}", status_code=204)
async def delete_job(resume_token: str):
    job = require_job_by_token(resume_token)
    get_job_store().delete_job(job["id"])
    return Response(status_code=204, headers=PRIVATE_RESPONSE_HEADERS)


@router.get("/jobs/{resume_token}/video")
async def download_job_video(resume_token: str, inline: bool = False):
    job = require_job_by_token(resume_token)
    video_path = job.get("video_path")
    if job.get("status") != "done" or not video_path or not Path(video_path).is_file():
        raise HTTPException(status_code=404, detail="Video not ready")
    if inline:
        return FileResponse(
            video_path,
            media_type="video/mp4",
            headers={
                "Content-Disposition": "inline",
                "Cache-Control": "private, max-age=3600",
                "Referrer-Policy": "no-referrer",
            },
        )
    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename="visualang.mp4",
        headers=PRIVATE_RESPONSE_HEADERS,
    )


@router.get("/jobs/{resume_token}/transcript")
async def download_job_transcript(resume_token: str):
    job = require_job_by_token(resume_token)
    transcript_payload = job.get("transcript")
    segments = (
        transcript_payload.get("transcript")
        if isinstance(transcript_payload, dict)
        else transcript_payload
    )
    if not segments:
        raise HTTPException(status_code=404, detail="Transcript not available")
    lines = []
    for seg in segments:
        start = int(seg.get("start", 0))
        mm, ss = divmod(start, 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {seg.get('text', '')}")
    return Response(
        content="\n".join(lines),
        media_type="text/plain",
        headers={
            **PRIVATE_RESPONSE_HEADERS,
            "Content-Disposition": 'attachment; filename="transcript.txt"',
        },
    )


def _build_images_zip(entries: list[tuple[object, Path]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for index, (timestamp, path) in enumerate(entries, start=1):
            label = f"{int(timestamp)}s" if timestamp is not None else path.stem
            archive.write(path, arcname=f"{index:02d}_{label}{path.suffix}")
    return buffer.getvalue()


@router.get("/jobs/{resume_token}/images")
async def download_job_images(resume_token: str):
    job = require_job_by_token(resume_token)
    images = job.get("images")
    if not images:
        raise HTTPException(status_code=404, detail="Images not available")
    entries = []
    for image in images:
        name = Path(image.get("image_url", "")).name
        path = generate_router.IMAGE_DIR / name
        if name and path.is_file():
            entries.append((image.get("timestamp_seconds"), path))
    if not entries:
        raise HTTPException(status_code=404, detail="Images not available")
    zip_bytes = await asyncio.to_thread(_build_images_zip, entries)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            **PRIVATE_RESPONSE_HEADERS,
            "Content-Disposition": 'attachment; filename="visualang_images.zip"',
        },
    )
