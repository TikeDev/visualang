import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from pathlib import Path

import requests
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agents import image_rewriter
from agents.tools import analyze_image_handler
from config import (
    NUNCHAKU_API_KEY,
    NUNCHAKU_BACKOFF_BASE_SECONDS,
    NUNCHAKU_BASE_URL,
    NUNCHAKU_ENABLE_REWRITE_RECOVERY,
    NUNCHAKU_MAX_429_RETRIES,
    NUNCHAKU_MIN_INTERVAL_SECONDS,
    NUNCHAKU_MODEL,
    NUNCHAKU_NEGATIVE_PROMPT,
    NUNCHAKU_TIER,
    VISUALANG_DATA_DIR,
)
from routers import metrics

logger = logging.getLogger(__name__)
router = APIRouter()

IMAGE_DIR = VISUALANG_DATA_DIR / "artifacts"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

_THROTTLE_LOCK = threading.Lock()
_NEXT_NUNCHAKU_ATTEMPT_AT = 0.0
MAX_NUNCHAKU_BACKOFF_SECONDS = 12.0


class GenerationCancelled(Exception):
    """Raised when cooperative image generation cancellation is requested."""


def _raise_if_cancelled(cancel_event, filepath: str | None = None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        if filepath is not None:
            Path(filepath).unlink(missing_ok=True)
        raise GenerationCancelled("Image generation cancelled")


def _reserve_nunchaku_slot(now_fn=time.monotonic) -> float:
    """Reserve the next outbound attempt slot across all Nunchaku calls."""
    global _NEXT_NUNCHAKU_ATTEMPT_AT

    with _THROTTLE_LOCK:
        now = now_fn()
        reserved_at = max(now, _NEXT_NUNCHAKU_ATTEMPT_AT)
        _NEXT_NUNCHAKU_ATTEMPT_AT = reserved_at + NUNCHAKU_MIN_INTERVAL_SECONDS
    return max(0.0, reserved_at - now)


def _get_retry_delay_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            logger.warning("Invalid Retry-After header from Nunchaku: %r", retry_after)

    return min(NUNCHAKU_BACKOFF_BASE_SECONDS * (2 ** attempt), MAX_NUNCHAKU_BACKOFF_SECONDS)


def _call_nunchaku(
    prompt: str,
    model: str,
    tier: str,
    *,
    post_fn=requests.post,
    sleep_fn=time.sleep,
    now_fn=time.monotonic,
) -> str:
    """Call Nunchaku and return the raw base64 JPEG (pre-decode)."""
    for attempt in range(NUNCHAKU_MAX_429_RETRIES + 1):
        spacing_delay = _reserve_nunchaku_slot(now_fn=now_fn)
        if spacing_delay > 0:
            logger.info("Waiting %.1fs before next Nunchaku request", spacing_delay)
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
        if response.status_code != 429:
            response.raise_for_status()
            return response.json()["data"][0]["b64_json"]

        if attempt >= NUNCHAKU_MAX_429_RETRIES:
            response.raise_for_status()

        retry_delay = _get_retry_delay_seconds(response, attempt)
        logger.warning(
            "Nunchaku returned 429; retrying in %.1fs (%s/%s)",
            retry_delay,
            attempt + 1,
            NUNCHAKU_MAX_429_RETRIES,
        )
        sleep_fn(retry_delay)

    raise RuntimeError("Nunchaku retry loop exited unexpectedly")


def _save_b64(b64_data: str) -> str:
    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGE_DIR / filename
    filepath.write_bytes(base64.b64decode(b64_data))
    return str(filepath)


def generate_image(prompt: str, model: str = NUNCHAKU_MODEL, tier: str = NUNCHAKU_TIER) -> dict:
    """Generate an image. Returns {filepath, b64} so callers can vision-check
    without re-reading the file."""
    start = time.time()
    b64_data = _call_nunchaku(prompt, model, tier)
    filepath = _save_b64(b64_data)
    elapsed_ms = int((time.time() - start) * 1000)
    metrics.record("nunchaku_generate_ms", elapsed_ms)
    logger.info(f"Generated image in {elapsed_ms}ms | model={model} tier={tier} | {prompt[:80]}")
    return {"filepath": filepath, "b64": b64_data}


def _generate_image_cancellable(prompt: str, cancel_event=None) -> dict:
    result = generate_image(prompt)
    _raise_if_cancelled(cancel_event, result["filepath"])
    return result


async def _generate_with_recovery(concept: dict, cancel_event=None) -> dict:
    """Generate one image serially. If vision post-check flags text, rewrite
    the prompt and retry once."""
    original_prompt = concept["image_prompt"]
    concept_name = concept["concept"]

    _raise_if_cancelled(cancel_event)
    result = await run_in_threadpool(
        _generate_image_cancellable, original_prompt, cancel_event
    )
    if not NUNCHAKU_ENABLE_REWRITE_RECOVERY:
        return {**result, "prompt_used": original_prompt}

    _raise_if_cancelled(cancel_event, result["filepath"])
    try:
        check = await analyze_image_handler(image_b64=result["b64"])
    except Exception as e:
        logger.warning("vision check raised, skipping recovery: %s", e)
        return {**result, "prompt_used": original_prompt}

    if not check.get("has_text"):
        return {**result, "prompt_used": original_prompt}

    failure_signal = f"vision check detected text in output: {check.get('details', '')}"
    logger.info("Image failed post-check for '%s' — rewriting prompt", concept_name)
    metrics.record("rewriter_triggered", 1)

    _raise_if_cancelled(cancel_event, result["filepath"])
    try:
        rewrite = await image_rewriter.run(
            original_prompt=original_prompt,
            failure_signal=failure_signal,
            concept=concept_name,
        )
    except Exception as e:
        logger.warning("rewriter failed, returning original image: %s", e)
        return {**result, "prompt_used": original_prompt}

    _raise_if_cancelled(cancel_event, result["filepath"])
    retry = await run_in_threadpool(
        _generate_image_cancellable, rewrite.revised_prompt, cancel_event
    )
    logger.info("Retry used revised prompt: %s", rewrite.reasoning[:80])
    return {**retry, "prompt_used": rewrite.revised_prompt}


async def generate_images(concepts: list, cancel_event=None, on_progress=None) -> list[dict]:
    total = len(concepts)
    images = []
    for index, concept in enumerate(concepts, start=1):
        _raise_if_cancelled(cancel_event)
        final = await _generate_with_recovery(concept, cancel_event=cancel_event)
        image = {
            "timestamp_seconds": concept["timestamp_seconds"],
            "image_url": f"/images/{Path(final['filepath']).name}",
        }
        _raise_if_cancelled(cancel_event, final["filepath"])
        images.append(image)
        if on_progress is not None:
            try:
                _raise_if_cancelled(cancel_event, final["filepath"])
            except GenerationCancelled:
                images.pop()
                raise
            await on_progress(index, total, concept, image)
    return images


async def generate_images_stream(concepts: list):
    total = len(concepts)
    t0 = time.time()
    progress_events = asyncio.Queue()
    cancel_event = asyncio.Event()
    generation_task = None

    async def on_progress(index, progress_total, concept, image):
        event = json.dumps({
            "index": index,
            "total": progress_total,
            "image_url": image["image_url"],
            "concept": concept["concept"],
        })
        progress_events.put_nowait(f"data: {event}\n\n")

    try:
        generation_task = asyncio.create_task(
            generate_images(
                concepts,
                cancel_event=cancel_event,
                on_progress=on_progress,
            )
        )
        while not generation_task.done() or not progress_events.empty():
            try:
                yield await asyncio.wait_for(progress_events.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue
        ordered = await generation_task
        metrics.record("generate_batch_ms", int((time.time() - t0) * 1000))
        metrics.record("generate_batch_size", total)
        yield f"data: {json.dumps({'done': True, 'images': ordered})}\n\n"
    except Exception as e:
        logger.exception("Image generation stream failed")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    finally:
        cancel_event.set()
        if generation_task is not None:
            if not generation_task.done():
                generation_task.cancel()
            await asyncio.gather(generation_task, return_exceptions=True)


class GenerateRequest(BaseModel):
    concepts: list


@router.post("/generate")
async def generate(body: GenerateRequest):
    return StreamingResponse(
        generate_images_stream(body.concepts),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
