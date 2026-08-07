import asyncio
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import app
from routers import export


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_export_state():
    export.jobs.clear()
    export.active_processes.clear()
    yield
    export.jobs.clear()
    export.active_processes.clear()


def _write_image(name: str) -> Path:
    path = export.IMAGE_DIR / name
    path.write_bytes(b"fake-image")
    return path


def _cleanup_paths(*paths: Path):
    for path in paths:
        path.unlink(missing_ok=True)


def _cleanup_job_metadata(job_id: str):
    export.get_job_metadata_path(job_id).unlink(missing_ok=True)


def test_get_ken_burns_variant_wraps_deterministically():
    first = export.get_ken_burns_variant(0)
    wrapped = export.get_ken_burns_variant(len(export.KEN_BURNS_VARIANTS))

    assert first["name"] == "ken-burns-zoom-in-left"
    assert wrapped == first


def test_build_transition_plan_uses_expected_xfade_offsets():
    transitions = export.build_transition_plan([3.0, 4.0, 5.0], fade_duration=0.8)

    assert transitions == [
        {"index": 1, "type": "xfade", "duration": 0.8, "offset": 2.2},
        {"index": 2, "type": "xfade", "duration": 0.8, "offset": 5.4},
    ]


def test_build_transition_plan_falls_back_to_concat_for_short_scenes():
    transitions = export.build_transition_plan([0.6, 4.0, 0.7], fade_duration=0.8)

    assert transitions == [
        {"index": 1, "type": "concat", "duration": 0.0, "offset": 0.6},
        {"index": 2, "type": "concat", "duration": 0.0, "offset": 4.6},
    ]


def test_build_ffmpeg_args_contains_non_empty_filter_graph(tmp_path):
    image_one = _write_image("ffmpeg-one.jpg")
    image_two = _write_image("ffmpeg-two.jpg")
    try:
        images = [
            {"image_url": "/images/ffmpeg-one.jpg", "duration_seconds": 3.0},
            {"image_url": "/images/ffmpeg-two.jpg", "duration_seconds": 4.0},
        ]

        args = export.build_ffmpeg_args(
            "/tmp/fake-audio.mp3",
            images,
            str(tmp_path / "out.mp4"),
        )

        filter_graph = args[args.index("-filter_complex") + 1]
        assert filter_graph
        assert "zoompan" in filter_graph
        assert "xfade=transition=fade" in filter_graph
        assert filter_graph.count("settb=AVTB") == 2
        assert filter_graph.count(f"setpts=N/({export.EXPORT_FPS}*TB)") == 2
        assert args[args.index("-map") + 1] == "[video]"
        assert "-nostdin" in args
        assert args[args.index("-loglevel") + 1] == "error"
        assert args[args.index("-preset") + 1] == "veryfast"
        assert args[args.index("-threads") + 1] == "1"
    finally:
        _cleanup_paths(image_one, image_two)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_build_ffmpeg_args_produces_non_empty_video(tmp_path):
    image_one = export.IMAGE_DIR / "smoke-red.jpg"
    image_two = export.IMAGE_DIR / "smoke-blue.jpg"
    audio_path = export.IMAGE_DIR / "smoke-tone.mp3"
    output_path = tmp_path / "smoke-export.mp4"

    fixture_commands = [
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=1024x1024:d=1",
            "-frames:v",
            "1",
            str(image_one),
        ],
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1024x1024:d=1",
            "-frames:v",
            "1",
            str(image_two),
        ],
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.2",
            "-c:a",
            "mp3",
            str(audio_path),
        ],
    ]

    try:
        for command in fixture_commands:
            subprocess.run(command, check=True, capture_output=True, text=True)

        args = export.build_ffmpeg_args(
            str(audio_path),
            [
                {"image_url": f"/images/{image_one.name}", "duration_seconds": 1.2},
                {"image_url": f"/images/{image_two.name}", "duration_seconds": 1.2},
            ],
            str(output_path),
        )

        result = subprocess.run(args, check=False, capture_output=True, text=True)

        assert result.returncode == 0, result.stderr
        assert output_path.exists()
        assert output_path.stat().st_size > 0
    finally:
        _cleanup_paths(image_one, image_two, audio_path, output_path)


def test_derive_image_durations_from_timestamps_matches_audio_length():
    images = [
        {"timestamp_seconds": 10, "image_url": "/images/a.jpg"},
        {"timestamp_seconds": 40, "image_url": "/images/b.jpg"},
        {"timestamp_seconds": 70, "image_url": "/images/c.jpg"},
    ]

    derived = export.derive_image_durations(images, audio_duration=100.0)

    durations = [img["duration_seconds"] for img in derived]
    assert durations == [40.0, pytest.approx(30.8), pytest.approx(30.8)]
    # Each xfade shortens the timeline by fade_duration, so with compensation
    # every fade completes exactly at its concept timestamp and the video
    # track spans the full audio.
    transitions = export.build_transition_plan(durations)
    assert [t["offset"] for t in transitions] == [
        pytest.approx(39.2),
        pytest.approx(69.2),
    ]
    assert sum(durations) - sum(t["duration"] for t in transitions) == pytest.approx(
        100.0
    )


def test_derive_image_durations_passthrough_when_durations_explicit():
    images = [
        {"timestamp_seconds": 0, "image_url": "/images/a.jpg", "duration_seconds": 3.0},
        {"timestamp_seconds": 3, "image_url": "/images/b.jpg", "duration_seconds": 4.0},
    ]

    assert export.derive_image_durations(images, audio_duration=50.0) is images


def test_derive_image_durations_sorts_out_of_order_timestamps():
    images = [
        {"timestamp_seconds": 40, "image_url": "/images/b.jpg"},
        {"timestamp_seconds": 10, "image_url": "/images/a.jpg"},
    ]

    derived = export.derive_image_durations(images, audio_duration=60.0)

    assert [img["image_url"] for img in derived] == ["/images/a.jpg", "/images/b.jpg"]


def test_derive_image_durations_single_image_fills_audio():
    derived = export.derive_image_durations(
        [{"timestamp_seconds": 12, "image_url": "/images/a.jpg"}], audio_duration=45.0
    )

    assert derived[0]["duration_seconds"] == 45.0


def test_derive_image_durations_clamps_timestamp_past_audio_end():
    images = [
        {"timestamp_seconds": 0, "image_url": "/images/a.jpg"},
        {"timestamp_seconds": 90, "image_url": "/images/b.jpg"},
    ]

    derived = export.derive_image_durations(images, audio_duration=80.0)

    assert derived[1]["duration_seconds"] == export.MIN_SCENE_DURATION_SECONDS


def test_derive_image_durations_falls_back_to_default_without_audio_duration():
    images = [
        {"timestamp_seconds": 0, "image_url": "/images/a.jpg"},
        {"timestamp_seconds": 20, "image_url": "/images/b.jpg"},
    ]

    derived = export.derive_image_durations(images, audio_duration=None)

    assert derived[0]["duration_seconds"] == 20.0
    assert derived[1]["duration_seconds"] == pytest.approx(
        export.DEFAULT_IMAGE_DURATION_SECONDS + export.CROSSFADE_DURATION_SECONDS
    )


def test_run_ffmpeg_export_derives_durations_for_job_pipeline_images(
    monkeypatch, tmp_path
):
    job_id = "derived-durations-job"
    export.jobs[job_id] = {"status": "pending", "video_path": None}
    captured = {}

    monkeypatch.setattr(export, "probe_audio_duration", lambda audio_path: 100.0)

    def fake_build_ffmpeg_args(audio_path, images, output_path):
        captured["images"] = images
        return ["visualang-missing-ffmpeg-binary"]

    monkeypatch.setattr(export, "build_ffmpeg_args", fake_build_ffmpeg_args)

    images = [
        {"timestamp_seconds": 10, "image_url": "/images/a.jpg"},
        {"timestamp_seconds": 40, "image_url": "/images/b.jpg"},
        {"timestamp_seconds": 70, "image_url": "/images/c.jpg"},
    ]

    try:
        asyncio.run(
            export.run_ffmpeg_export(
                job_id, "/tmp/audio.mp3", images, str(tmp_path / "out.mp4")
            )
        )

        durations = [img["duration_seconds"] for img in captured["images"]]
        assert durations == [40.0, pytest.approx(30.8), pytest.approx(30.8)]
        assert export.jobs[job_id]["expected_duration_seconds"] == pytest.approx(101.6)
    finally:
        _cleanup_job_metadata(job_id)
        _cleanup_paths(export.IMAGE_DIR / f"{job_id}_ffmpeg.stderr.log")


def test_start_export_route_accepts_multiple_images_and_writes_zip(monkeypatch):
    image_one = _write_image("route-one.jpg")
    image_two = _write_image("route-two.jpg")
    captured = {}
    job_id = None
    output_path = None

    async def fake_run_ffmpeg_export(job_id, audio_path, images, output_path):
        captured["job_id"] = job_id
        captured["audio_path"] = audio_path
        captured["images"] = images
        captured["output_path"] = output_path
        Path(output_path).write_bytes(b"fake-video")
        export.update_job(job_id, status="done", video_path=output_path)

    monkeypatch.setattr(export, "run_ffmpeg_export", fake_run_ffmpeg_export)

    response = client.post(
        "/export",
        json={
            "audio_path": "/tmp/test-audio.mp3",
            "images": [
                {
                    "timestamp_seconds": 0,
                    "image_url": "/images/route-one.jpg",
                    "duration_seconds": 3.0,
                    "concept": "scene one",
                },
                {
                    "timestamp_seconds": 3,
                    "image_url": "/images/route-two.jpg",
                    "duration_seconds": 4.0,
                    "concept": "scene two",
                },
            ],
            "transcript": [{"start": 0, "text": "hola"}],
        },
    )

    try:
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        output_path = Path(captured["output_path"])
        assert captured["job_id"] == job_id
        assert len(captured["images"]) == 2

        metadata_path = export.get_job_metadata_path(job_id)
        assert metadata_path.exists()

        zip_path = Path(export.jobs[job_id]["zip_path"])
        transcript_path = Path(export.jobs[job_id]["transcript_path"])
        assert zip_path.exists()
        assert transcript_path.exists()

        with zipfile.ZipFile(zip_path, "r") as zf:
            assert sorted(zf.namelist()) == [
                "00_0s_scene_one.jpg",
                "01_3s_scene_two.jpg",
            ]
        assert transcript_path.read_text() == "[00:00] hola"

        export.jobs.clear()

        status_response = client.get(f"/export/{job_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "done"

        video_response = client.get(f"/export/{job_id}/video")
        assert video_response.status_code == 200
        assert video_response.content == b"fake-video"

        transcript_response = client.get(f"/export/{job_id}/transcript")
        assert transcript_response.status_code == 200
        assert transcript_response.text == "[00:00] hola"

        images_response = client.get(f"/export/{job_id}/images")
        assert images_response.status_code == 200
        assert images_response.headers["content-type"].startswith("application/zip")
    finally:
        cleanup_targets = [image_one, image_two]
        if job_id:
            job = export.load_persisted_job(job_id) or {}
            cleanup_targets.append(export.get_job_metadata_path(job_id))
            cleanup_targets.extend(
                Path(value)
                for value in [
                    output_path,
                    job.get("zip_path"),
                    job.get("transcript_path"),
                    job.get("video_path"),
                ]
                if value
            )
        _cleanup_paths(*cleanup_targets)


def test_run_ffmpeg_export_persists_error_status(monkeypatch):
    job_id = "failed-export-test"
    export.jobs[job_id] = {"status": "pending", "video_path": None}
    export.persist_job(job_id)

    monkeypatch.setattr(
        export,
        "build_ffmpeg_args",
        lambda audio_path, images, output_path: ["visualang-missing-ffmpeg-binary"],
    )

    try:
        asyncio.run(export.run_ffmpeg_export(job_id, "/tmp/missing.mp3", [], "/tmp/missing.mp4"))
        export.jobs.clear()

        status_response = client.get(f"/export/{job_id}")
        assert status_response.status_code == 200
        body = status_response.json()
        assert body["status"] == "error"
        assert "visualang-missing-ffmpeg-binary" in body["error"]
    finally:
        _cleanup_job_metadata(job_id)


def test_get_export_status_marks_interrupted_running_job_as_error():
    job_id = "interrupted-export-test"
    output_path = export.IMAGE_DIR / f"{job_id}.mp4"
    export.jobs[job_id] = {
        "status": "running",
        "video_path": None,
        "output_path": str(output_path),
        "created_at": export.PROCESS_STARTED_AT - 10,
        "started_at": export.PROCESS_STARTED_AT - 5,
        "updated_at": export.PROCESS_STARTED_AT - 5,
    }
    export.persist_job(job_id)
    export.jobs.clear()

    try:
        response = client.get(f"/export/{job_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "server restart" in body["error"]
    finally:
        _cleanup_job_metadata(job_id)
        _cleanup_paths(output_path)


def test_cancel_export_terminates_active_process_and_cleans_registry():
    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        async def wait(self):
            return -15

    process = FakeProcess()
    export.jobs["cancel-job"] = {"status": "running", "video_path": None}
    export.active_processes["cancel-job"] = process

    try:
        cancelled = asyncio.run(export.cancel_export("cancel-job"))

        assert cancelled is True
        assert process.terminated is True
        assert process.killed is False
        assert export.jobs["cancel-job"]["status"] == "cancelled"
        assert "cancel-job" not in export.active_processes
    finally:
        _cleanup_job_metadata("cancel-job")


def test_cancel_export_kills_process_that_does_not_terminate(monkeypatch):
    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.killed = False
            self.release = asyncio.Event()

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True
            self.release.set()

        async def wait(self):
            await self.release.wait()
            return -9

    process = FakeProcess()
    export.jobs["kill-job"] = {"status": "running", "video_path": None}
    export.active_processes["kill-job"] = process
    monkeypatch.setattr(export, "EXPORT_CANCEL_TIMEOUT_SECONDS", 0.001)

    try:
        cancelled = asyncio.run(export.cancel_export("kill-job"))

        assert cancelled is True
        assert process.terminated is True
        assert process.killed is True
        assert "kill-job" not in export.active_processes
    finally:
        _cleanup_job_metadata("kill-job")


def test_run_ffmpeg_export_preserves_cancelled_status_and_cleans_registry(
    monkeypatch, tmp_path
):
    job_id = "cancelled-run-job"

    class FakeProcess:
        pid = 4321
        returncode = -15

        async def wait(self):
            assert export.active_processes[job_id] is self
            export.update_job(job_id, status="cancelled", error=None)
            return self.returncode

        def kill(self):
            raise AssertionError("completed wait should not be killed")

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    export.jobs[job_id] = {"status": "pending", "video_path": None}
    monkeypatch.setattr(export, "build_ffmpeg_args", lambda *args: ["ffmpeg"])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    try:
        asyncio.run(
            export.run_ffmpeg_export(
                job_id, "/tmp/audio.mp3", [], str(tmp_path / "cancelled.mp4")
            )
        )

        assert export.jobs[job_id]["status"] == "cancelled"
        assert "error" not in export.jobs[job_id] or export.jobs[job_id]["error"] is None
        assert job_id not in export.active_processes
    finally:
        _cleanup_job_metadata(job_id)
        _cleanup_paths(export.IMAGE_DIR / f"{job_id}_ffmpeg.stderr.log")


def test_cancelling_ffmpeg_runner_shuts_down_child_and_removes_partials(
    monkeypatch, tmp_path
):
    job_id = "runner-task-cancelled"
    output_path = tmp_path / "partial.mp4"
    wait_started = asyncio.Event()

    class FakeProcess:
        pid = 9876
        returncode = None

        def __init__(self):
            self.terminated = False
            self.killed = False
            self.wait_calls = 0
            self.release = asyncio.Event()

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            self.release.set()

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.release.set()

        async def wait(self):
            self.wait_calls += 1
            wait_started.set()
            await self.release.wait()
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        output_path.write_bytes(b"partial-video")
        return process

    async def run_and_cancel():
        task = asyncio.create_task(
            export.run_ffmpeg_export(job_id, "/tmp/audio.mp3", [], str(output_path))
        )
        await wait_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    export.jobs[job_id] = {"status": "pending", "video_path": None}
    monkeypatch.setattr(export, "build_ffmpeg_args", lambda *args: ["ffmpeg"])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    stderr_path = export.IMAGE_DIR / f"{job_id}_ffmpeg.stderr.log"
    try:
        asyncio.run(run_and_cancel())

        assert process.terminated is True
        assert process.wait_calls >= 2
        assert job_id not in export.active_processes
        assert export.jobs[job_id]["status"] == "cancelled"
        assert not output_path.exists()
        assert not stderr_path.exists()
    finally:
        _cleanup_job_metadata(job_id)
        _cleanup_paths(output_path, stderr_path)
