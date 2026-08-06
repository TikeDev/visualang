from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
from dataclasses import dataclass

import requests

from config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_BACKOFF_BASE_SECONDS,
    CLOUDFLARE_MAX_RETRIES,
    CLOUDFLARE_MODEL,
    IMAGE_PROVIDER,
    NUNCHAKU_API_KEY,
    NUNCHAKU_BACKOFF_BASE_SECONDS,
    NUNCHAKU_BASE_URL,
    NUNCHAKU_MAX_429_RETRIES,
    NUNCHAKU_MIN_INTERVAL_SECONDS,
    NUNCHAKU_MODEL,
    NUNCHAKU_NEGATIVE_PROMPT,
    NUNCHAKU_TIER,
)

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 12.0
_NUNCHAKU_THROTTLE_LOCK = threading.Lock()
_NEXT_NUNCHAKU_ATTEMPT_AT = 0.0


@dataclass(frozen=True)
class GeneratedImage:
    image_bytes: bytes
    provider: str
    model: str


class ImageProviderError(RuntimeError):
    """A sanitized image-provider failure safe to return through the API."""


class ImageContentPolicyError(ImageProviderError):
    """The provider rejected the prompt itself (content/safety policy)."""


def _extract_cloudflare_error_reason(response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if not errors:
        return None
    first = errors[0] if isinstance(errors, list) else None
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    return str(message) if message else None


def _retry_delay(response, attempt: int, base_seconds: float) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return min(base_seconds * (2**attempt), MAX_BACKOFF_SECONDS)


def call_cloudflare(
    prompt: str,
    *,
    post_fn=requests.post,
    sleep_fn=time.sleep,
) -> GeneratedImage:
    if not CLOUDFLARE_ACCOUNT_ID:
        raise ImageProviderError(
            "CLOUDFLARE_ACCOUNT_ID is required when IMAGE_PROVIDER=cloudflare"
        )
    if not CLOUDFLARE_API_TOKEN:
        raise ImageProviderError(
            "CLOUDFLARE_API_TOKEN is required when IMAGE_PROVIDER=cloudflare"
        )

    endpoint = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}"
    )

    for attempt in range(CLOUDFLARE_MAX_RETRIES + 1):
        try:
            response = post_fn(
                endpoint,
                headers={
                    "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt, "steps": 4},
                timeout=60,
            )
        except requests.RequestException as exc:
            if attempt < CLOUDFLARE_MAX_RETRIES:
                sleep_fn(
                    min(
                        CLOUDFLARE_BACKOFF_BASE_SECONDS * (2**attempt),
                        MAX_BACKOFF_SECONDS,
                    )
                )
                continue
            raise ImageProviderError(
                "Cloudflare image request failed"
            ) from exc

        retryable = response.status_code == 429 or response.status_code >= 500
        if retryable and attempt < CLOUDFLARE_MAX_RETRIES:
            sleep_fn(
                _retry_delay(
                    response,
                    attempt,
                    CLOUDFLARE_BACKOFF_BASE_SECONDS,
                )
            )
            continue
        if response.status_code >= 400:
            reason = _extract_cloudflare_error_reason(response)
            logger.warning(
                "Cloudflare image generation failed with status %s: %s",
                response.status_code,
                reason or "<no error body>",
            )
            if response.status_code == 400:
                raise ImageContentPolicyError(
                    "Cloudflare rejected the prompt"
                    + (f": {reason}" if reason else "")
                )
            raise ImageProviderError(
                "Cloudflare image generation failed with status "
                f"{response.status_code}"
            )

        try:
            payload = response.json()
            if payload.get("success") is not True:
                raise KeyError("success")
            image_bytes = base64.b64decode(
                payload["result"]["image"], validate=True
            )
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise ImageProviderError(
                "Cloudflare returned an invalid response"
            ) from exc

        return GeneratedImage(
            image_bytes=image_bytes,
            provider="cloudflare",
            model=CLOUDFLARE_MODEL,
        )

    raise ImageProviderError("Cloudflare retry loop exited unexpectedly")


def _reserve_nunchaku_slot(now_fn=time.monotonic) -> float:
    global _NEXT_NUNCHAKU_ATTEMPT_AT

    with _NUNCHAKU_THROTTLE_LOCK:
        now = now_fn()
        reserved_at = max(now, _NEXT_NUNCHAKU_ATTEMPT_AT)
        _NEXT_NUNCHAKU_ATTEMPT_AT = reserved_at + NUNCHAKU_MIN_INTERVAL_SECONDS
    return max(0.0, reserved_at - now)


def call_nunchaku(
    prompt: str,
    model: str = NUNCHAKU_MODEL,
    tier: str = NUNCHAKU_TIER,
    *,
    post_fn=requests.post,
    sleep_fn=time.sleep,
    now_fn=time.monotonic,
) -> GeneratedImage:
    if not NUNCHAKU_API_KEY:
        raise ImageProviderError(
            "NUNCHAKU_API_KEY is required when IMAGE_PROVIDER=nunchaku"
        )

    for attempt in range(NUNCHAKU_MAX_429_RETRIES + 1):
        spacing_delay = _reserve_nunchaku_slot(now_fn=now_fn)
        if spacing_delay > 0:
            sleep_fn(spacing_delay)

        response = post_fn(
            f"{NUNCHAKU_BASE_URL}/v1/images/generations",
            headers={
                "Authorization": f"Bearer {NUNCHAKU_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
                "tier": tier,
                "response_format": "b64_json",
                "negative_prompt": NUNCHAKU_NEGATIVE_PROMPT,
            },
            timeout=60,
        )
        if (
            response.status_code == 429
            and attempt < NUNCHAKU_MAX_429_RETRIES
        ):
            sleep_fn(
                _retry_delay(
                    response,
                    attempt,
                    NUNCHAKU_BACKOFF_BASE_SECONDS,
                )
            )
            continue
        if response.status_code >= 400:
            raise ImageProviderError(
                "Nunchaku image generation failed with status "
                f"{response.status_code}"
            )

        try:
            encoded = response.json()["data"][0]["b64_json"]
            image_bytes = base64.b64decode(encoded, validate=True)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            binascii.Error,
        ) as exc:
            raise ImageProviderError(
                "Nunchaku returned an invalid response"
            ) from exc

        return GeneratedImage(
            image_bytes=image_bytes,
            provider="nunchaku",
            model=model,
        )

    raise ImageProviderError("Nunchaku retry loop exited unexpectedly")


def generate(prompt: str, provider: str | None = None) -> GeneratedImage:
    selected = (provider or IMAGE_PROVIDER).lower()
    if selected == "cloudflare":
        return call_cloudflare(prompt)
    if selected == "nunchaku":
        return call_nunchaku(prompt)
    raise ImageProviderError(f"Unsupported image provider: {selected}")
