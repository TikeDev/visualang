import asyncio
import io
import os
import sys
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from job_store import JobStore  # noqa: E402
from job_runner import JobRunner  # noqa: E402
from routers import generate as generate_router  # noqa: E402
from routers import jobs as jobs_router  # noqa: E402
from main import app  # noqa: E402


YOUTUBE_SOURCE = {"kind": "youtube", "url": "https://example.test/video"}


def fake_transcript_fn(calls, transcript=None):
    async def run(source, *, cancel_event=None):
        calls.append("transcript")
        return transcript or [{"text": "hola", "start": 0, "duration": 1}]

    return run


def fake_concepts_fn(calls, concepts=None):
    async def run(transcript):
        calls.append("concepts")
        return concepts or [
            {"concept": "tea", "image_prompt": "cup", "timestamp_seconds": 0}
        ]

    return run


def fake_images_fn(calls, images=None):
    async def run(concepts, *, cancel_event=None, on_progress=None):
        calls.append("images")
        return images or [{"timestamp_seconds": 0, "image_url": "/images/x.jpg"}]

    return run


def fake_export_fn(calls, video_path="/tmp/visualang_data/jobs/job/video.mp4"):
    async def run(transcript, images, job_dir, *, job_id=None):
        calls.append("export")
        return {"video_path": video_path}

    return run


def make_runner(store, calls, **overrides):
    kwargs = dict(
        transcript_fn=fake_transcript_fn(calls),
        concepts_fn=fake_concepts_fn(calls),
        images_fn=fake_images_fn(calls),
        export_fn=fake_export_fn(calls),
    )
    kwargs.update(overrides)
    return JobRunner(store, **kwargs)


def test_runner_runs_all_stages_for_a_new_job(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    calls = []
    runner = make_runner(store, calls)

    asyncio.run(runner.run(access.job_id))

    assert calls == ["transcript", "concepts", "images", "export"]
    job = store.require_by_resume_token(access.resume_token)
    assert job["status"] == "done"
    assert job["stage"] == "export"


def test_runner_checkpoints_each_stage_and_resumes_from_images(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    store.update(
        access.job_id,
        stage="generating_images",
        status="error",
        transcript=[{"text": "hola", "start": 0, "duration": 1}],
        concepts=[{"concept": "tea", "image_prompt": "cup", "timestamp_seconds": 0}],
    )
    calls = []
    runner = make_runner(store, calls)

    asyncio.run(runner.retry(access.job_id))

    assert calls == ["images", "export"]
    job = store.require_by_resume_token(access.resume_token)
    assert job["status"] == "done"


def test_failed_stage_persists_error_and_status(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    calls = []

    async def failing_concepts(transcript):
        calls.append("concepts")
        raise RuntimeError("boom")

    runner = make_runner(store, calls, concepts_fn=failing_concepts)

    asyncio.run(runner.run(access.job_id))

    job = store.require_by_resume_token(access.resume_token)
    assert job["status"] == "error"
    assert job["stage"] == "concepts"
    assert "boom" in job["error"]


def test_cancel_preserves_completed_artifacts(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    store.update(
        access.job_id,
        transcript=[{"text": "hola", "start": 0, "duration": 1}],
        stage="generating_images",
        status="running",
    )
    calls = []
    runner = make_runner(store, calls)

    asyncio.run(runner.cancel(access.job_id))

    job = store.require_by_resume_token(access.resume_token)
    assert job["status"] == "cancelled"
    assert job["transcript"] == [{"text": "hola", "start": 0, "duration": 1}]


def test_runner_passes_cancel_event_to_transcript_fn(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    calls = []
    captured = {}

    async def transcript_fn(source, *, cancel_event=None):
        captured["cancel_event"] = cancel_event
        return [{"text": "hola", "start": 0, "duration": 1}]

    runner = make_runner(store, calls, transcript_fn=transcript_fn)

    asyncio.run(runner.run(access.job_id))

    assert isinstance(captured["cancel_event"], threading.Event)


def test_cancel_during_transcript_stage_marks_job_cancelled(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    calls = []

    async def main():
        started = asyncio.Event()

        async def transcript_fn(source, *, cancel_event=None):
            started.set()
            await asyncio.Event().wait()

        runner = make_runner(store, calls, transcript_fn=transcript_fn)
        asyncio.ensure_future(runner.run(access.job_id))
        await started.wait()
        await runner.cancel(access.job_id)

    asyncio.run(main())

    job = store.require_by_resume_token(access.resume_token)
    assert job["status"] == "cancelled"
    assert calls == []


def test_cancel_is_a_no_op_for_a_job_with_no_running_task(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job(YOUTUBE_SOURCE)
    calls = []
    runner = make_runner(store, calls)

    asyncio.run(runner.cancel(access.job_id))

    job = store.require_by_resume_token(access.resume_token)
    assert job["status"] == "queued"


def test_reconcile_marks_running_jobs_interrupted(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    running = store.create_job(YOUTUBE_SOURCE, now=100)
    expired = store.create_job(YOUTUBE_SOURCE, now=80)
    store.update(running.job_id, status="running", stage="generating_images")

    from job_runner import reconcile_jobs_after_restart

    reconcile_jobs_after_restart(store, now=101)

    assert (
        store.require_by_resume_token(running.resume_token, now=101)["status"]
        == "interrupted"
    )
    assert store.get_by_resume_token(expired.resume_token, now=101) is None


@pytest.fixture()
def job_test_client(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    calls = []
    runner = make_runner(store, calls)

    monkeypatch.setattr(jobs_router, "get_job_store", lambda: store)
    monkeypatch.setattr(jobs_router, "get_job_runner", lambda: runner)

    with TestClient(app) as client:
        yield client, store, calls


def test_create_get_cancel_retry_delete_job(job_test_client):
    client, store, calls = job_test_client

    created = client.post(
        "/jobs", json={"type": "youtube", "url": "https://youtu.be/example"}
    )
    assert created.status_code == 202
    token = created.json()["resume_token"]

    get_response = client.get(f"/jobs/{token}")
    assert get_response.status_code == 200
    body = get_response.json()
    assert "id" not in body or "path" not in str(body)
    assert get_response.headers["cache-control"] == "no-store"
    assert get_response.headers["referrer-policy"] == "no-referrer"

    cancelled = client.post(f"/jobs/{token}/cancel")
    assert cancelled.status_code == 200

    retried = client.post(f"/jobs/{token}/retry")
    assert retried.status_code == 202

    deleted = client.delete(f"/jobs/{token}")
    assert deleted.status_code == 204

    assert client.get(f"/jobs/{token}").status_code == 404


def test_wrong_resume_secret_is_not_found(job_test_client):
    client, store, calls = job_test_client

    created = client.post(
        "/jobs", json={"type": "youtube", "url": "https://youtu.be/example"}
    )
    job_id = created.json()["resume_token"].split(".", 1)[0]

    assert client.get(f"/jobs/{job_id}.wrong-secret").status_code == 404


def test_download_transcript_handles_pipeline_payload_shape(job_test_client):
    client, store, calls = job_test_client

    access = store.create_job(YOUTUBE_SOURCE)
    store.update(
        access.job_id,
        transcript={
            "transcript": [
                {"text": "hola", "start": 0, "duration": 1},
                {"text": "mundo", "start": 65, "duration": 1},
            ],
            "audio_path": "/tmp/audio.mp3",
            "title": "Lesson",
            "gate": {"verdict": "proceed"},
        },
    )

    response = client.get(f"/jobs/{access.resume_token}/transcript")

    assert response.status_code == 200
    assert response.text == "[00:00] hola\n[01:05] mundo"


def test_download_images_returns_zip_of_image_files(job_test_client, tmp_path, monkeypatch):
    client, store, calls = job_test_client

    image_dir = tmp_path / "artifacts"
    image_dir.mkdir()
    (image_dir / "abc.jpg").write_bytes(b"first-image")
    (image_dir / "def.jpg").write_bytes(b"second-image")
    monkeypatch.setattr(generate_router, "IMAGE_DIR", image_dir)

    access = store.create_job(YOUTUBE_SOURCE)
    store.update(
        access.job_id,
        images=[
            {"timestamp_seconds": 27, "image_url": "/images/abc.jpg"},
            {"timestamp_seconds": 59, "image_url": "/images/def.jpg"},
        ],
    )

    response = client.get(f"/jobs/{access.resume_token}/images")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="visualang_images.zip"'
    )
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["01_27s.jpg", "02_59s.jpg"]
    assert archive.read("01_27s.jpg") == b"first-image"
    assert archive.read("02_59s.jpg") == b"second-image"


def test_download_images_404s_when_no_files_exist_on_disk(
    job_test_client, tmp_path, monkeypatch
):
    client, store, calls = job_test_client

    image_dir = tmp_path / "artifacts"
    image_dir.mkdir()
    monkeypatch.setattr(generate_router, "IMAGE_DIR", image_dir)

    access = store.create_job(YOUTUBE_SOURCE)
    store.update(
        access.job_id,
        images=[{"timestamp_seconds": 27, "image_url": "/images/missing.jpg"}],
    )

    assert client.get(f"/jobs/{access.resume_token}/images").status_code == 404


def test_job_response_never_exposes_filesystem_paths(job_test_client):
    client, store, calls = job_test_client

    created = client.post(
        "/jobs", json={"type": "youtube", "url": "https://youtu.be/example"}
    )
    token = created.json()["resume_token"]
    job_id = token.split(".", 1)[0]
    store.update(
        job_id,
        status="error",
        stage="export",
        error="boom",
        video_path=f"/var/data/visualang/jobs/{job_id}/video.mp4",
    )

    body = client.get(f"/jobs/{token}").json()

    assert "/var/data" not in str(body)
    assert "video_path" not in body


def test_download_job_video_inline_and_attachment(job_test_client, tmp_path):
    client, store, calls = job_test_client

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4-bytes")

    access = store.create_job(YOUTUBE_SOURCE)

    assert (
        client.get(f"/jobs/{access.resume_token}/video?inline=true").status_code == 404
    )

    store.update(
        access.job_id, status="done", stage="export", video_path=str(video_file)
    )

    download = client.get(f"/jobs/{access.resume_token}/video")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["cache-control"] == "no-store"

    inline = client.get(f"/jobs/{access.resume_token}/video?inline=true")
    assert inline.status_code == 200
    assert inline.headers["content-disposition"] == "inline"
    assert "private" in inline.headers["cache-control"]
    assert inline.content == b"mp4-bytes"
