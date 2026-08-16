from __future__ import annotations

import base64
import binascii
import logging
import time
from dataclasses import dataclass

import requests

import observability
from config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_BACKOFF_BASE_SECONDS,
    CLOUDFLARE_MAX_RETRIES,
    CLOUDFLARE_MODEL,
    IMAGE_PROVIDER,
)

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 12.0


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
    with observability.observe(
        as_type="generation",
        name="cloudflare_image_generation",
        model=CLOUDFLARE_MODEL,
        input={"prompt": prompt},
    ) as generation:
        try:
            result = _call_cloudflare(prompt, post_fn=post_fn, sleep_fn=sleep_fn)
        except Exception as exc:
            observability.update(generation, level="ERROR", status_message=str(exc))
            raise
        if generation is not None:
            from langfuse.media import LangfuseMedia

            observability.update(
                generation,
                output={
                    "image": LangfuseMedia(
                        content_bytes=result.image_bytes, content_type="image/jpeg"
                    )
                },
            )
        return result


def _call_cloudflare(
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


def generate(prompt: str, provider: str | None = None) -> GeneratedImage:
    selected = (provider or IMAGE_PROVIDER).lower()
    if selected == "cloudflare":
        return call_cloudflare(prompt)
    raise ImageProviderError(f"Unsupported image provider: {selected}")
