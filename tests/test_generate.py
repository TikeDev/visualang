import asyncio
import base64
import os
import sys
import threading
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from routers import generate
from routers import export, transcript
from config import VISUALANG_DATA_DIR
from main import app


client = TestClient(app)


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._payload


def test_artifact_roots_use_configured_data_directory():
    expected = VISUALANG_DATA_DIR / "artifacts"

    assert generate.IMAGE_DIR == expected
    assert export.IMAGE_DIR == expected
    assert transcript.IMAGE_DIR == expected
    assert expected.is_dir()


def test_images_route_serves_configured_artifact():
    image_path = generate.IMAGE_DIR / "configured-image-route.jpg"
    image_path.write_bytes(b"configured-image")
    try:
        response = client.get(f"/images/{image_path.name}")

        assert response.status_code == 200
        assert response.content == b"configured-image"
    finally:
        image_path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def reset_generate_state(monkeypatch):
    monkeypatch.setattr(generate, "_NEXT_NUNCHAKU_ATTEMPT_AT", 0.0)
    monkeypatch.setattr(generate, "NUNCHAKU_MIN_INTERVAL_SECONDS", 2.0)
    monkeypatch.setattr(generate, "NUNCHAKU_MAX_429_RETRIES", 4)
    monkeypatch.setattr(generate, "NUNCHAKU_BACKOFF_BASE_SECONDS", 3.0)
    monkeypatch.setattr(generate, "NUNCHAKU_ENABLE_REWRITE_RECOVERY", False)


def test_call_nunchaku_success_first_attempt():
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(200, {"data": [{"b64_json": "abc123"}]})

    result = generate._call_nunchaku("prompt", "model", "tier", post_fn=fake_post)

    assert result == "abc123"
    assert len(calls) == 1


def test_call_nunchaku_retries_429_using_retry_after(monkeypatch):
    responses = [
        FakeResponse(429, headers={"Retry-After": "5"}),
        FakeResponse(200, {"data": [{"b64_json": "ok"}]}),
    ]
    sleeps = []
    current_time = [0.0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds

    def fake_now():
        return current_time[0]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    result = generate._call_nunchaku(
        "prompt",
        "model",
        "tier",
        post_fn=fake_post,
        sleep_fn=fake_sleep,
        now_fn=fake_now,
    )

    assert result == "ok"
    assert sleeps == [5.0]


def test_call_nunchaku_retries_429_using_backoff_when_retry_after_missing():
    responses = [
        FakeResponse(429),
        FakeResponse(200, {"data": [{"b64_json": "ok"}]}),
    ]
    sleeps = []
    current_time = [0.0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds

    def fake_now():
        return current_time[0]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    result = generate._call_nunchaku(
        "prompt",
        "model",
        "tier",
        post_fn=fake_post,
        sleep_fn=fake_sleep,
        now_fn=fake_now,
    )

    assert result == "ok"
    assert sleeps == [3.0]


def test_call_nunchaku_exhausts_429_retry_budget():
    responses = [
        FakeResponse(429),
        FakeResponse(429),
        FakeResponse(429),
    ]
    sleeps = []
    current_time = [0.0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds

    def fake_now():
        return current_time[0]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    generate.NUNCHAKU_MAX_429_RETRIES = 2
    with pytest.raises(requests.HTTPError):
        generate._call_nunchaku(
            "prompt",
            "model",
            "tier",
            post_fn=fake_post,
            sleep_fn=fake_sleep,
            now_fn=fake_now,
        )

    assert sleeps == [3.0, 6.0]


def test_call_nunchaku_enforces_spacing_between_calls():
    responses = [
        FakeResponse(200, {"data": [{"b64_json": "one"}]}),
        FakeResponse(200, {"data": [{"b64_json": "two"}]}),
    ]
    sleeps = []
    current_time = [0.0]

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current_time[0] += seconds

    def fake_now():
        return current_time[0]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    assert generate._call_nunchaku(
        "prompt-1",
        "model",
        "tier",
        post_fn=fake_post,
        sleep_fn=fake_sleep,
        now_fn=fake_now,
    ) == "one"
    assert generate._call_nunchaku(
        "prompt-2",
        "model",
        "tier",
        post_fn=fake_post,
        sleep_fn=fake_sleep,
        now_fn=fake_now,
    ) == "two"

    assert sleeps == [2.0]


def test_generate_with_recovery_skips_rewrite_when_disabled(monkeypatch):
    prompts = []
    encoded = base64.b64encode(b"image").decode("ascii")

    def fake_call_nunchaku(prompt, model, tier, **kwargs):
        prompts.append(prompt)
        return encoded

    def fake_save_b64(b64_data):
        assert b64_data == encoded
        return "/tmp/fake-image.jpg"

    async def fail_analyze(**kwargs):
        raise AssertionError("vision analysis should be skipped when rewrite recovery is disabled")

    monkeypatch.setattr(generate, "_call_nunchaku", fake_call_nunchaku)
    monkeypatch.setattr(generate, "_save_b64", fake_save_b64)
    monkeypatch.setattr(generate, "analyze_image_handler", fail_analyze)

    result = asyncio.run(
        generate._generate_with_recovery({"concept": "tea", "image_prompt": "original prompt"})
    )

    assert prompts == ["original prompt"]
    assert result == {"filepath": "/tmp/fake-image.jpg", "b64": encoded, "prompt_used": "original prompt"}


def test_generate_with_recovery_uses_rewritten_prompt_when_enabled(monkeypatch):
    prompts = []

    def fake_call_nunchaku(prompt, model, tier, **kwargs):
        prompts.append(prompt)
        encoded = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
        return encoded

    def fake_save_b64(_b64_data):
        return "/tmp/fake-image.jpg"

    async def fake_analyze(**kwargs):
        return {"has_text": True, "details": "letters on mug"}

    async def fake_rewrite_run(**kwargs):
        assert kwargs["original_prompt"] == "original prompt"
        return SimpleNamespace(revised_prompt="rewritten prompt", reasoning="remove text")

    monkeypatch.setattr(generate, "NUNCHAKU_ENABLE_REWRITE_RECOVERY", True)
    monkeypatch.setattr(generate, "_call_nunchaku", fake_call_nunchaku)
    monkeypatch.setattr(generate, "_save_b64", fake_save_b64)
    monkeypatch.setattr(generate, "analyze_image_handler", fake_analyze)
    monkeypatch.setattr(generate.image_rewriter, "run", fake_rewrite_run)

    result = asyncio.run(
        generate._generate_with_recovery({"concept": "tea", "image_prompt": "original prompt"})
    )

    assert prompts == ["original prompt", "rewritten prompt"]
    assert result["filepath"] == "/tmp/fake-image.jpg"
    assert result["prompt_used"] == "rewritten prompt"


def test_generate_images_stops_before_next_provider_call_when_cancelled(monkeypatch):
    cancel_event = asyncio.Event()
    calls = []

    async def fake_generate_with_recovery(concept, cancel_event=None):
        calls.append(concept["concept"])
        cancel_event.set()
        return {"filepath": f"/tmp/{concept['concept']}.jpg", "b64": "image"}

    monkeypatch.setattr(generate, "_generate_with_recovery", fake_generate_with_recovery)

    with pytest.raises(generate.GenerationCancelled):
        asyncio.run(
            generate.generate_images(
                [
                    {"concept": "first", "image_prompt": "one", "timestamp_seconds": 0},
                    {"concept": "second", "image_prompt": "two", "timestamp_seconds": 1},
                ],
                cancel_event=cancel_event,
            )
        )

    assert calls == ["first"]


def test_generate_images_reports_progress_in_result_order(monkeypatch):
    progress = []
    concepts = [
        {"concept": "first", "image_prompt": "one", "timestamp_seconds": 0},
        {"concept": "second", "image_prompt": "two", "timestamp_seconds": 7},
    ]

    async def fake_generate_with_recovery(concept, cancel_event=None):
        return {"filepath": f"/tmp/{concept['concept']}.jpg", "b64": "image"}

    async def on_progress(index, total, concept, image):
        progress.append((index, total, concept["concept"], image.copy()))

    monkeypatch.setattr(generate, "_generate_with_recovery", fake_generate_with_recovery)

    images = asyncio.run(generate.generate_images(concepts, on_progress=on_progress))

    assert images == [
        {"timestamp_seconds": 0, "image_url": "/images/first.jpg"},
        {"timestamp_seconds": 7, "image_url": "/images/second.jpg"},
    ]
    assert progress == [
        (1, 2, "first", images[0]),
        (2, 2, "second", images[1]),
    ]


def test_generate_images_stream_delegates_to_generation_primitive(monkeypatch):
    calls = []
    concepts = [{"concept": "tea", "image_prompt": "cup", "timestamp_seconds": 4}]

    async def fake_generate_images(received, cancel_event=None, on_progress=None):
        calls.append(received)
        image = {"timestamp_seconds": 4, "image_url": "/images/tea.jpg"}
        await on_progress(1, 1, received[0], image)
        return [image]

    async def collect_stream():
        return [event async for event in generate.generate_images_stream(concepts)]

    monkeypatch.setattr(generate, "generate_images", fake_generate_images)

    events = asyncio.run(collect_stream())

    assert calls == [concepts]
    assert events == [
        'data: {"index": 1, "total": 1, "image_url": "/images/tea.jpg", "concept": "tea"}\n\n',
        'data: {"done": true, "images": [{"timestamp_seconds": 4, "image_url": "/images/tea.jpg"}]}\n\n',
    ]


def test_generate_with_recovery_cancels_after_provider_before_analysis(monkeypatch):
    cancel_event = asyncio.Event()
    calls = []

    async def fake_run_in_threadpool(function, *args):
        cancel_event.set()
        return {"filepath": "/tmp/generated.jpg", "b64": "image"}

    async def fake_analyze(**kwargs):
        calls.append("analyze")
        return {"has_text": True, "details": "text"}

    async def fake_rewrite(**kwargs):
        calls.append("rewrite")
        return SimpleNamespace(revised_prompt="retry", reasoning="reason")

    monkeypatch.setattr(generate, "NUNCHAKU_ENABLE_REWRITE_RECOVERY", True)
    monkeypatch.setattr(generate, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(generate, "analyze_image_handler", fake_analyze)
    monkeypatch.setattr(generate.image_rewriter, "run", fake_rewrite)

    with pytest.raises(generate.GenerationCancelled):
        asyncio.run(
            generate._generate_with_recovery(
                {"concept": "tea", "image_prompt": "cup"},
                cancel_event=cancel_event,
            )
        )

    assert calls == []


def test_generate_with_recovery_cancels_after_analysis_before_rewriter(monkeypatch):
    cancel_event = asyncio.Event()
    calls = []

    async def fake_run_in_threadpool(function, *args):
        return {"filepath": "/tmp/generated.jpg", "b64": "image"}

    async def fake_analyze(**kwargs):
        calls.append("analyze")
        cancel_event.set()
        return {"has_text": True, "details": "text"}

    async def fake_rewrite(**kwargs):
        calls.append("rewrite")
        return SimpleNamespace(revised_prompt="retry", reasoning="reason")

    monkeypatch.setattr(generate, "NUNCHAKU_ENABLE_REWRITE_RECOVERY", True)
    monkeypatch.setattr(generate, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(generate, "analyze_image_handler", fake_analyze)
    monkeypatch.setattr(generate.image_rewriter, "run", fake_rewrite)

    with pytest.raises(generate.GenerationCancelled):
        asyncio.run(
            generate._generate_with_recovery(
                {"concept": "tea", "image_prompt": "cup"},
                cancel_event=cancel_event,
            )
        )

    assert calls == ["analyze"]


def test_generate_images_cancels_completed_inflight_result_before_progress(monkeypatch):
    cancel_event = asyncio.Event()
    progress = []

    async def fake_generate_with_recovery(concept, cancel_event=None):
        cancel_event.set()
        return {"filepath": "/tmp/generated.jpg", "b64": "image"}

    async def on_progress(index, total, concept, image):
        progress.append(image)

    monkeypatch.setattr(generate, "_generate_with_recovery", fake_generate_with_recovery)

    with pytest.raises(generate.GenerationCancelled):
        asyncio.run(
            generate.generate_images(
                [{"concept": "tea", "image_prompt": "cup", "timestamp_seconds": 0}],
                cancel_event=cancel_event,
                on_progress=on_progress,
            )
        )

    assert progress == []


def test_generate_images_stream_aclose_cancels_child_generation(monkeypatch):
    captured = {}

    async def fake_generate_images(concepts, cancel_event=None, on_progress=None):
        captured["cancel_event"] = cancel_event
        captured["task"] = asyncio.current_task()
        image = {"timestamp_seconds": 0, "image_url": "/images/first.jpg"}
        await on_progress(1, 1, concepts[0], image)
        try:
            await asyncio.Event().wait()
        finally:
            captured["child_finished"] = True

    async def close_after_first_event():
        stream = generate.generate_images_stream(
            [{"concept": "first", "image_prompt": "one", "timestamp_seconds": 0}]
        )
        first_event = await anext(stream)
        await stream.aclose()
        return first_event

    monkeypatch.setattr(generate, "generate_images", fake_generate_images)

    first_event = asyncio.run(close_after_first_event())

    assert '"index": 1' in first_event
    assert captured["cancel_event"].is_set()
    assert captured["task"].done()
    assert captured["child_finished"] is True


def test_generate_images_stream_emits_error_event_and_cleans_child(monkeypatch):
    captured = {}

    async def fake_generate_images(concepts, cancel_event=None, on_progress=None):
        captured["cancel_event"] = cancel_event
        captured["task"] = asyncio.current_task()
        raise RuntimeError("provider unavailable")

    async def collect_stream():
        return [event async for event in generate.generate_images_stream([])]

    monkeypatch.setattr(generate, "generate_images", fake_generate_images)

    events = asyncio.run(collect_stream())

    assert events == ['data: {"error": "provider unavailable"}\n\n']
    assert captured["cancel_event"].is_set()
    assert captured["task"].done()


def test_generate_images_deletes_inflight_file_cancelled_before_publication(
    monkeypatch, tmp_path
):
    cancel_event = asyncio.Event()
    generated_path = tmp_path / "discarded.jpg"

    async def fake_generate_with_recovery(concept, cancel_event=None):
        generated_path.write_bytes(b"discard me")
        cancel_event.set()
        return {"filepath": str(generated_path), "b64": "image"}

    monkeypatch.setattr(generate, "_generate_with_recovery", fake_generate_with_recovery)

    with pytest.raises(generate.GenerationCancelled):
        asyncio.run(
            generate.generate_images(
                [{"concept": "tea", "image_prompt": "cup", "timestamp_seconds": 0}],
                cancel_event=cancel_event,
            )
        )

    assert not generated_path.exists()


def test_cancelled_generation_task_cleans_file_saved_later_by_provider_thread(
    monkeypatch, tmp_path
):
    cancel_event = asyncio.Event()
    provider_started = threading.Event()
    provider_returned = threading.Event()
    release_provider = threading.Event()
    generated_path = tmp_path / "late-provider-result.jpg"

    def fake_generate_image(prompt):
        provider_started.set()
        release_provider.wait(timeout=2)
        generated_path.write_bytes(b"late image")
        provider_returned.set()
        return {"filepath": str(generated_path), "b64": "image"}

    async def cancel_during_provider():
        task = asyncio.create_task(
            generate.generate_images(
                [{"concept": "tea", "image_prompt": "cup", "timestamp_seconds": 0}],
                cancel_event=cancel_event,
            )
        )
        while not provider_started.is_set():
            await asyncio.sleep(0)
        cancel_event.set()
        task.cancel()
        release_provider.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        while not provider_returned.is_set():
            await asyncio.sleep(0)

        async def wait_until_removed():
            while generated_path.exists():
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_until_removed(), timeout=0.5)

    monkeypatch.setattr(generate, "NUNCHAKU_ENABLE_REWRITE_RECOVERY", False)
    monkeypatch.setattr(generate, "generate_image", fake_generate_image)

    asyncio.run(cancel_during_provider())

    assert not generated_path.exists()
