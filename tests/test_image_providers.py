import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import image_providers  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


def test_image_provider_defaults_to_cloudflare():
    env = os.environ.copy()
    env.pop("IMAGE_PROVIDER", None)

    result = subprocess.run(
        [sys.executable, "-c", "import config; print(config.IMAGE_PROVIDER)"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "cloudflare"


def test_call_cloudflare_decodes_image_and_sends_expected_request(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account-id")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "test-token")
    calls = []
    encoded = base64.b64encode(b"jpeg-data").decode("ascii")

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(
            200, {"success": True, "result": {"image": encoded}}
        )

    result = image_providers.call_cloudflare(
        "storybook fox", post_fn=fake_post
    )

    assert result.image_bytes == b"jpeg-data"
    assert result.provider == "cloudflare"
    assert result.model == "@cf/black-forest-labs/flux-1-schnell"
    assert calls == [
        (
            (
                "https://api.cloudflare.com/client/v4/accounts/"
                "account-id/ai/run/"
                "@cf/black-forest-labs/flux-1-schnell",
            ),
            {
                "headers": {
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
                "json": {"prompt": "storybook fox", "steps": 4},
                "timeout": 60,
            },
        )
    ]


@pytest.mark.parametrize(
    ("account_id", "token", "missing_name"),
    [
        (None, "token", "CLOUDFLARE_ACCOUNT_ID"),
        ("account", None, "CLOUDFLARE_API_TOKEN"),
    ],
)
def test_call_cloudflare_requires_credentials(
    monkeypatch, account_id, token, missing_name
):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", account_id)
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", token)

    with pytest.raises(image_providers.ImageProviderError, match=missing_name):
        image_providers.call_cloudflare("prompt")


def test_call_cloudflare_rejects_malformed_response(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "token")

    with pytest.raises(
        image_providers.ImageProviderError, match="invalid response"
    ):
        image_providers.call_cloudflare(
            "prompt",
            post_fn=lambda *args, **kwargs: FakeResponse(
                200, {"success": True, "result": {}}
            ),
        )


def test_call_cloudflare_retries_429_using_retry_after(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "token")
    encoded = base64.b64encode(b"ok").decode("ascii")
    responses = [
        FakeResponse(429, headers={"Retry-After": "2"}),
        FakeResponse(
            200, {"success": True, "result": {"image": encoded}}
        ),
    ]
    sleeps = []

    result = image_providers.call_cloudflare(
        "prompt",
        post_fn=lambda *args, **kwargs: responses.pop(0),
        sleep_fn=sleeps.append,
    )

    assert result.image_bytes == b"ok"
    assert sleeps == [2.0]


def test_call_cloudflare_retries_500_with_exponential_backoff(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setattr(
        image_providers, "CLOUDFLARE_BACKOFF_BASE_SECONDS", 1.0
    )
    encoded = base64.b64encode(b"ok").decode("ascii")
    responses = [
        FakeResponse(500),
        FakeResponse(503),
        FakeResponse(200, {"success": True, "result": {"image": encoded}}),
    ]
    sleeps = []

    result = image_providers.call_cloudflare(
        "prompt",
        post_fn=lambda *args, **kwargs: responses.pop(0),
        sleep_fn=sleeps.append,
    )

    assert result.image_bytes == b"ok"
    assert sleeps == [1.0, 2.0]


def test_call_cloudflare_does_not_retry_permanent_error(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "token")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return FakeResponse(401)

    with pytest.raises(image_providers.ImageProviderError, match="status 401"):
        image_providers.call_cloudflare("prompt", post_fn=fake_post)

    assert len(calls) == 1


def test_call_cloudflare_400_raises_content_policy_error_with_reason(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "token")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return FakeResponse(
            400,
            {
                "success": False,
                "errors": [{"code": 5004, "message": "content flagged by safety filter"}],
            },
        )

    with pytest.raises(
        image_providers.ImageContentPolicyError,
        match="content flagged by safety filter",
    ):
        image_providers.call_cloudflare("prompt", post_fn=fake_post)

    assert len(calls) == 1


def test_call_cloudflare_400_raises_content_policy_error_without_body(monkeypatch):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(image_providers, "CLOUDFLARE_API_TOKEN", "token")

    def fake_post(*args, **kwargs):
        return FakeResponse(400, {})

    with pytest.raises(image_providers.ImageContentPolicyError):
        image_providers.call_cloudflare("prompt", post_fn=fake_post)


def test_call_cloudflare_retries_connection_errors_and_sanitizes_failure(
    monkeypatch,
):
    monkeypatch.setattr(image_providers, "CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(
        image_providers, "CLOUDFLARE_API_TOKEN", "secret-token"
    )
    monkeypatch.setattr(image_providers, "CLOUDFLARE_MAX_RETRIES", 2)
    sleeps = []

    with pytest.raises(
        image_providers.ImageProviderError, match="request failed"
    ) as exc:
        image_providers.call_cloudflare(
            "prompt",
            post_fn=lambda *args, **kwargs: (_ for _ in ()).throw(
                requests.ConnectionError("socket failed with secret-token")
            ),
            sleep_fn=sleeps.append,
        )

    assert "secret-token" not in str(exc.value)
    assert sleeps == [1.0, 2.0]
