import asyncio
import os
import sys

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from job_store import JobStore  # noqa: E402
from job_runner import JobRunner  # noqa: E402


YOUTUBE_SOURCE = {"kind": "youtube", "url": "https://example.test/video"}


def fake_transcript_fn(calls, transcript=None):
    async def run(source):
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
