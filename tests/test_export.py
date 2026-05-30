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
    yield
    export.jobs.clear()


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
