import asyncio
import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import mock_open

from fastapi.testclient import TestClient

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import app
from agents import base, transcript_gate as gate_module
from routers import concepts, transcript


client = TestClient(app)


def _gate_result(verdict="proceed", reason="looks good", detected_language="es"):
    return SimpleNamespace(
        verdict=verdict,
        reason=reason,
        detected_language=detected_language,
    )


class FakeFetchedTranscript:
    def __init__(self, segments):
        self._segments = segments

    def to_raw_data(self):
        return self._segments


class FakeCaptionTrack:
    def __init__(self, *, language_code, language, is_generated, segments):
        self.language_code = language_code
        self.language = language
        self.is_generated = is_generated
        self._segments = segments

    def fetch(self):
        return FakeFetchedTranscript(self._segments)


class FakeYouTubeTranscriptApi:
    def __init__(self, transcripts, *, proxy_config=None):
        self._transcripts = transcripts
        self.proxy_config = proxy_config

    def list(self, video_id):
        assert video_id == "abc123"
        return self._transcripts


class FailingYouTubeTranscriptApi:
    def __init__(self, *, proxy_config=None):
        self.proxy_config = proxy_config

    def list(self, video_id):
        assert video_id == "abc123"
        raise RuntimeError("captions unavailable")


class FakeYoutubeDL:
    last_opts = None

    def __init__(self, opts):
        FakeYoutubeDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, video_url, download):
        assert download is False
        return {"title": "Breakfast Spanish", "duration": 42}

    def download(self, urls):
        assert urls == ["https://www.youtube.com/watch?v=abc123"]


def test_extract_video_id_supports_watch_short_and_share_urls():
    assert transcript.extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert transcript.extract_video_id("https://youtu.be/abc123?si=share-code") == "abc123"
    assert transcript.extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"
    assert (
        transcript.extract_video_id("https://m.youtube.com/shorts/abc123?feature=share")
        == "abc123"
    )


def test_transcript_youtube_unified_success(monkeypatch):
    monkeypatch.setattr(
        transcript,
        "YouTubeTranscriptApi",
        lambda **kwargs: FakeYouTubeTranscriptApi(
            [
                FakeCaptionTrack(
                    language_code="es",
                    language="Spanish",
                    is_generated=False,
                    segments=[
                        {"text": "hola", "start": 0.0, "duration": 1.2},
                        {"text": "mundo", "start": 1.2, "duration": 1.0},
                    ],
                )
            ]
        ),
    )
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Breakfast Spanish", "duration": 42})
    monkeypatch.setattr(transcript, "extract_audio", lambda video_url, output_base: None)

    async def fake_gate_run(normalized, *, title, duration):
        assert len(normalized) == 2
        assert title == "Breakfast Spanish"
        assert duration == 42
        return _gate_result()

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 200
    assert response.json() == {
        "transcript": [
            {"text": "hola", "start": 0.0, "duration": 1.2},
            {"text": "mundo", "start": 1.2, "duration": 1.0},
        ],
        "audio_path": "/tmp/visualang_images/abc123.mp3",
        "audio_url": "/media/audio/abc123.mp3",
        "title": "Breakfast Spanish",
        "gate": {
            "verdict": "proceed",
            "reason": "looks good",
            "detected_language": "es",
        },
    }


def test_transcript_youtube_shorts_success(monkeypatch):
    monkeypatch.setattr(
        transcript,
        "YouTubeTranscriptApi",
        lambda **kwargs: FakeYouTubeTranscriptApi(
            [
                FakeCaptionTrack(
                    language_code="es",
                    language="Spanish",
                    is_generated=False,
                    segments=[
                        {"text": "buenas", "start": 0.0, "duration": 0.8},
                        {"text": "tardes", "start": 0.8, "duration": 0.9},
                    ],
                )
            ]
        ),
    )
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Short Lesson", "duration": 18})
    monkeypatch.setattr(transcript, "extract_audio", lambda video_url, output_base: None)

    async def fake_gate_run(normalized, *, title, duration):
        assert title == "Short Lesson"
        assert duration == 18
        return _gate_result()

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/shorts/abc123"})

    assert response.status_code == 200
    assert response.json()["transcript"] == [
        {"text": "buenas", "start": 0.0, "duration": 0.8},
        {"text": "tardes", "start": 0.8, "duration": 0.9},
    ]
    assert response.json()["audio_path"] == "/tmp/visualang_images/abc123.mp3"
    assert response.json()["audio_url"] == "/media/audio/abc123.mp3"


def test_transcript_upload_unified_success(monkeypatch):
    monkeypatch.setattr(
        transcript,
        "transcribe_audio",
        lambda audio_path: [
            {"text": "bonjour", "start": 0.0, "duration": 1.5},
            {"text": "tout le monde", "start": 1.5, "duration": 2.0},
        ],
    )

    async def fake_gate_run(normalized, *, title, duration):
        assert title == "lesson"
        assert duration == 3.5
        return _gate_result(verdict="warn", reason="low confidence opening segment", detected_language="fr")

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post(
        "/transcript",
        files={"file": ("lesson.mp3", io.BytesIO(b"fake-audio"), "audio/mpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "lesson"
    assert body["transcript"] == [
        {"text": "bonjour", "start": 0.0, "duration": 1.5},
        {"text": "tout le monde", "start": 1.5, "duration": 2.0},
    ]
    assert body["gate"] == {
        "verdict": "warn",
        "reason": "low confidence opening segment",
        "detected_language": "fr",
    }
    assert body["audio_path"].endswith("_lesson.mp3")
    assert body["audio_url"].startswith("/media/audio/")
    assert body["audio_url"].endswith("_lesson.mp3")


def test_build_youtube_transcript_api_uses_generic_proxy_config(monkeypatch):
    captured = {}

    class FakeGenericProxyConfig:
        def __init__(self, http_url=None, https_url=None):
            captured["http_url"] = http_url
            captured["https_url"] = https_url

    def fake_youtube_transcript_api(**kwargs):
        captured["proxy_config"] = kwargs.get("proxy_config")
        return "fake-client"

    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_ENABLED", True)
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTP_URL", "http://proxy.example:8080")
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTPS_URL", "https://proxy.example:8443")
    monkeypatch.setattr(transcript, "GenericProxyConfig", FakeGenericProxyConfig)
    monkeypatch.setattr(transcript, "YouTubeTranscriptApi", fake_youtube_transcript_api)

    client = transcript.build_youtube_transcript_api()

    assert client == "fake-client"
    assert captured["http_url"] == "http://proxy.example:8080"
    assert captured["https_url"] == "https://proxy.example:8443"
    assert captured["proxy_config"] is not None


def test_get_video_info_uses_proxy_for_yt_dlp(monkeypatch):
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_ENABLED", True)
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTP_URL", "http://proxy.example:8080")
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTPS_URL", "https://proxy.example:8443")
    monkeypatch.setattr(transcript, "YT_DLP_DENO_PATH", "/opt/deno/bin/deno")
    monkeypatch.setattr(transcript.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    info = transcript.get_video_info("https://www.youtube.com/watch?v=abc123")

    assert info == {"title": "Breakfast Spanish", "duration": 42}
    assert FakeYoutubeDL.last_opts["proxy"] == "https://proxy.example:8443"
    assert FakeYoutubeDL.last_opts["skip_download"] is True
    assert FakeYoutubeDL.last_opts["noprogress"] is True
    assert FakeYoutubeDL.last_opts["js_runtimes"] == {
        "deno": {"path": "/opt/deno/bin/deno"}
    }
    assert hasattr(FakeYoutubeDL.last_opts["logger"], "warning")


def test_extract_audio_uses_proxy_for_yt_dlp(monkeypatch):
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_ENABLED", True)
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTP_URL", "http://proxy.example:8080")
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTPS_URL", None)
    monkeypatch.setattr(transcript.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    transcript.extract_audio("https://www.youtube.com/watch?v=abc123", "/tmp/visualang_images/abc123")

    assert FakeYoutubeDL.last_opts["proxy"] == "http://proxy.example:8080"
    assert FakeYoutubeDL.last_opts["outtmpl"] == "/tmp/visualang_images/abc123"
    assert FakeYoutubeDL.last_opts["format"] == "bestaudio/best"
    assert FakeYoutubeDL.last_opts["noprogress"] is True


def test_yt_dlp_options_allow_missing_deno_path(monkeypatch):
    monkeypatch.setattr(transcript, "YT_DLP_DENO_PATH", None)

    opts = transcript.build_yt_dlp_options()

    assert opts["js_runtimes"] == {"deno": {"path": None}}
    assert opts["noprogress"] is True
    assert hasattr(opts["logger"], "error")


def test_transcript_youtube_falls_back_to_whisper_with_proxy_enabled(monkeypatch):
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_ENABLED", True)
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTP_URL", "http://proxy.example:8080")
    monkeypatch.setattr(transcript, "YOUTUBE_PROXY_HTTPS_URL", None)
    monkeypatch.setattr(transcript, "YouTubeTranscriptApi", lambda **kwargs: FailingYouTubeTranscriptApi(**kwargs))
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Fallback Lesson", "duration": 64})
    monkeypatch.setattr(transcript, "extract_audio", lambda video_url, output_base: None)
    monkeypatch.setattr(
        transcript,
        "transcribe_audio",
        lambda audio_path: [
            {"text": "hola", "start": 0.0, "duration": 1.0},
            {"text": "otra vez", "start": 1.0, "duration": 1.5},
        ],
    )

    async def fake_gate_run(normalized, *, title, duration):
        assert normalized[0]["text"] == "hola"
        assert title == "Fallback Lesson"
        assert duration == 64
        return _gate_result()

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 200
    assert response.json()["title"] == "Fallback Lesson"
    assert response.json()["audio_path"] == "/tmp/visualang_images/abc123.mp3"
    assert response.json()["transcript"] == [
        {"text": "hola", "start": 0.0, "duration": 1.0},
        {"text": "otra vez", "start": 1.0, "duration": 1.5},
    ]


def test_transcript_youtube_returns_500_when_audio_fallback_fails(monkeypatch):
    monkeypatch.setattr(transcript, "YouTubeTranscriptApi", lambda **kwargs: FailingYouTubeTranscriptApi(**kwargs))
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Fallback Lesson", "duration": 64})

    def fail_extract_audio(video_url, output_base):
        raise RuntimeError("yt-dlp blocked")

    monkeypatch.setattr(transcript, "extract_audio", fail_extract_audio)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to fetch transcript. Audio extraction fallback failed."


def test_transcribe_audio_uses_whisper_verbose_json(monkeypatch):
    captured = {}

    class FakeTranscriptions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                segments=[
                    SimpleNamespace(text="hola", start=0.0, end=1.0),
                    SimpleNamespace(text="mundo", start=1.0, end=2.5),
                ]
            )

    class FakeAudio:
        def __init__(self):
            self.transcriptions = FakeTranscriptions()

    class FakeOpenAI:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.audio = FakeAudio()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr("builtins.open", mock_open(read_data=b"audio-bytes"))

    normalized = transcript.transcribe_audio("/tmp/fake.mp3")

    assert captured["api_key"] == transcript.OPENAI_API_KEY
    assert captured["model"] == "whisper-1"
    assert captured["response_format"] == "verbose_json"
    assert captured["timestamp_granularities"] == ["segment"]
    assert normalized == [
        {"text": "hola", "start": 0.0, "duration": 1.0},
        {"text": "mundo", "start": 1.0, "duration": 1.5},
    ]


def test_transcript_invalid_youtube_url_returns_400():
    response = client.post("/transcript", json={"video_url": "https://example.com/not-youtube"})
    assert response.status_code == 400
    assert "Could not extract video ID" in response.json()["detail"]


def test_transcript_unsupported_file_type_returns_400():
    response = client.post(
        "/transcript",
        files={"file": ("notes.txt", io.BytesIO(b"not-audio"), "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file type: .txt"


def test_transcript_upload_rejects_removed_legacy_file_types():
    response = client.post(
        "/transcript",
        files={"file": ("lesson.ogg", io.BytesIO(b"fake-audio"), "audio/ogg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported file type: .ogg"


def test_transcript_upload_rejects_files_over_25_mb():
    response = client.post(
        "/transcript",
        files={"file": ("lesson.mp3", io.BytesIO(b"x" * (25 * 1024 * 1024 + 1)), "audio/mpeg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "File exceeds 25 MB limit."


def test_parse_json_strict_accepts_embedded_fenced_json():
    parsed = base.parse_json_strict(
        """Based on the inspection results:
```json
{"verdict": "proceed", "reason": "usable", "detected_language": "es"}
```
"""
    )

    assert parsed == {"verdict": "proceed", "reason": "usable", "detected_language": "es"}


def test_transcript_gate_parses_embedded_json(monkeypatch):
    async def fake_run_claude_with_tools(**kwargs):
        return (
            "Summary first.\n"
            '```json\n{"verdict": "warn", "reason": "language ambiguous", '
            '"detected_language": "unknown"}\n```'
        )

    monkeypatch.setattr(gate_module.base, "run_claude_with_tools", fake_run_claude_with_tools)

    result = asyncio.run(
        gate_module.run(
            [{"text": "hola mundo " * 30, "start": 0.0, "duration": 30.0}],
            title="Spanish lesson",
            duration=30.0,
        )
    )

    assert result.verdict == "warn"
    assert result.reason == "language ambiguous"
    assert result.detected_language == "unknown"


def test_transcript_gate_parse_failure_uses_deterministic_fallback(monkeypatch):
    async def fake_run_claude_with_tools(**kwargs):
        return "I inspected the transcript, but forgot to return JSON."

    monkeypatch.setattr(gate_module.base, "run_claude_with_tools", fake_run_claude_with_tools)

    result = asyncio.run(
        gate_module.run(
            [{"text": "hola mundo " * 80, "start": 0.0, "duration": 60.0}],
            title="Spanish lesson",
            duration=60.0,
        )
    )

    assert result.verdict == "proceed"
    assert "deterministic quality check passed" in result.reason


def test_transcript_gate_reject_returns_422(monkeypatch):
    monkeypatch.setattr(
        transcript,
        "YouTubeTranscriptApi",
        lambda **kwargs: FakeYouTubeTranscriptApi(
            [
                FakeCaptionTrack(
                    language_code="es",
                    language="Spanish",
                    is_generated=False,
                    segments=[{"text": "hola", "start": 0.0, "duration": 1.0}],
                )
            ]
        ),
    )
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Rejected clip", "duration": 10})
    monkeypatch.setattr(transcript, "extract_audio", lambda video_url, output_base: None)

    async def fake_gate_run(normalized, *, title, duration):
        return _gate_result(verdict="reject", reason="too sparse", detected_language="unknown")

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://youtu.be/abc123"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Transcript rejected: too sparse"


def test_transcript_youtube_falls_back_to_whisper_when_captions_fail(monkeypatch):
    captured = {"extract_audio_calls": 0, "transcribe_audio_path": None}

    monkeypatch.setattr(transcript, "YouTubeTranscriptApi", lambda: FailingYouTubeTranscriptApi())
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "No Captions Short", "duration": 14})

    def fake_extract_audio(video_url, output_base):
        captured["extract_audio_calls"] += 1
        assert video_url == "https://www.youtube.com/shorts/abc123"
        assert output_base.endswith("/abc123")

    monkeypatch.setattr(transcript, "extract_audio", fake_extract_audio)

    def fake_transcribe_audio(audio_path):
        captured["transcribe_audio_path"] = audio_path
        return [
            {"text": "hola desde whisper", "start": 0.0, "duration": 1.0},
            {"text": "seguimos", "start": 1.0, "duration": 1.2},
        ]

    monkeypatch.setattr(transcript, "transcribe_audio", fake_transcribe_audio)

    async def fake_gate_run(normalized, *, title, duration):
        assert normalized == [
            {"text": "hola desde whisper", "start": 0.0, "duration": 1.0},
            {"text": "seguimos", "start": 1.0, "duration": 1.2},
        ]
        assert title == "No Captions Short"
        assert duration == 14
        return _gate_result(verdict="warn", reason="captions missing, whisper used", detected_language="es")

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/shorts/abc123"})

    assert response.status_code == 200
    assert captured["extract_audio_calls"] == 1
    assert captured["transcribe_audio_path"] == "/tmp/visualang_images/abc123.mp3"
    assert response.json()["transcript"] == [
        {"text": "hola desde whisper", "start": 0.0, "duration": 1.0},
        {"text": "seguimos", "start": 1.0, "duration": 1.2},
    ]
    assert response.json()["gate"] == {
        "verdict": "warn",
        "reason": "captions missing, whisper used",
        "detected_language": "es",
    }
    assert response.json()["audio_path"] == "/tmp/visualang_images/abc123.mp3"
    assert response.json()["audio_url"] == "/media/audio/abc123.mp3"


def test_transcript_gate_reject_after_whisper_fallback_returns_422(monkeypatch):
    monkeypatch.setattr(transcript, "YouTubeTranscriptApi", lambda: FailingYouTubeTranscriptApi())
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Sparse Short", "duration": 9})
    monkeypatch.setattr(transcript, "extract_audio", lambda video_url, output_base: None)
    monkeypatch.setattr(
        transcript,
        "transcribe_audio",
        lambda audio_path: [{"text": "...", "start": 0.0, "duration": 0.5}],
    )

    async def fake_gate_run(normalized, *, title, duration):
        assert normalized == [{"text": "...", "start": 0.0, "duration": 0.5}]
        assert title == "Sparse Short"
        assert duration == 9
        return _gate_result(verdict="reject", reason="too sparse", detected_language="unknown")

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/shorts/abc123"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Transcript rejected: too sparse"


def test_transcript_youtube_falls_back_to_generated_non_english_track(monkeypatch):
    monkeypatch.setattr(
        transcript,
        "YouTubeTranscriptApi",
        lambda **kwargs: FakeYouTubeTranscriptApi(
            [
                FakeCaptionTrack(
                    language_code="es",
                    language="Spanish",
                    is_generated=True,
                    segments=[
                        {"text": "buenos dias", "start": 0.0, "duration": 1.5},
                        {"text": "amigos", "start": 1.5, "duration": 1.0},
                    ],
                )
            ]
        ),
    )
    monkeypatch.setattr(transcript, "get_video_info", lambda url: {"title": "Morning Spanish", "duration": 15})
    monkeypatch.setattr(transcript, "extract_audio", lambda video_url, output_base: None)

    async def fake_gate_run(normalized, *, title, duration):
        assert normalized[0]["text"] == "buenos dias"
        assert title == "Morning Spanish"
        assert duration == 15
        return _gate_result(verdict="proceed", reason="generated captions are usable", detected_language="es")

    monkeypatch.setattr(transcript.transcript_gate, "run", fake_gate_run)

    response = client.post("/transcript", json={"video_url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 200
    assert response.json()["gate"] == {
        "verdict": "proceed",
        "reason": "generated captions are usable",
        "detected_language": "es",
    }
    assert response.json()["transcript"] == [
        {"text": "buenos dias", "start": 0.0, "duration": 1.5},
        {"text": "amigos", "start": 1.5, "duration": 1.0},
    ]


def test_concepts_parse_failure_returns_500(monkeypatch):
    async def fake_run(transcript_input):
        raise ValueError("malformed JSON from model")

    monkeypatch.setattr(concepts.concept_extractor, "run", fake_run)

    response = client.post(
        "/concepts",
        json={"transcript": [{"text": "hola", "start": 0.0, "duration": 1.0}]},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Concept extraction failed: malformed JSON from model"


def test_media_audio_route_serves_existing_file():
    audio_path = transcript.IMAGE_DIR / "route-test.mp3"
    audio_path.write_bytes(b"fake-audio")
    try:
        response = client.get(f"/media/audio/{audio_path.name}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")
        assert "inline" in response.headers["content-disposition"]
        assert response.content == b"fake-audio"
    finally:
        audio_path.unlink(missing_ok=True)


def test_media_audio_route_rejects_invalid_filename():
    response = client.get("/media/audio/..secret.mp3")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid filename"


def test_media_audio_route_returns_404_for_missing_file():
    response = client.get("/media/audio/missing-file.mp3")
    assert response.status_code == 404
    assert response.json()["detail"] == "Audio not found"
