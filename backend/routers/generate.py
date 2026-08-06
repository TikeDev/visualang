import asyncio
import base64
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agents import image_rewriter
from agents.tools import analyze_image_handler
import image_providers
from config import (
    IMAGE_ENABLE_REWRITE_RECOVERY,
    IMAGE_GENERATION_CONCURRENCY,
    VISUALANG_DATA_DIR,
)
from routers import metrics

logger = logging.getLogger(__name__)
router = APIRouter()

IMAGE_DIR = VISUALANG_DATA_DIR / "artifacts"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


class GenerationCancelled(Exception):
    """Raised when cooperative image generation cancellation is requested."""


def _raise_if_cancelled(cancel_event, filepath: str | None = None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        if filepath is not None:
            Path(filepath).unlink(missing_ok=True)
        raise GenerationCancelled("Image generation cancelled")


def _save_bytes(image_bytes: bytes) -> str:
    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGE_DIR / filename
    filepath.write_bytes(image_bytes)
    return str(filepath)


def generate_image(prompt: str) -> dict:
    """Generate an image. Returns {filepath, b64} so callers can vision-check
    without re-reading the file."""
    start = time.time()
    generated = image_providers.generate(prompt)
    filepath = _save_bytes(generated.image_bytes)
    b64_data = base64.b64encode(generated.image_bytes).decode("ascii")
    elapsed_ms = int((time.time() - start) * 1000)
    metrics.record("image_generate_ms", elapsed_ms)
    metrics.record(f"{generated.provider}_generate_ms", elapsed_ms)
    logger.info(
        "Generated image in %sms | provider=%s model=%s | %s",
        elapsed_ms,
        generated.provider,
        generated.model,
        prompt[:80],
    )
    return {
        "filepath": filepath,
        "b64": b64_data,
        "provider": generated.provider,
        "model": generated.model,
    }


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
    try:
        result = await run_in_threadpool(
            _generate_image_cancellable, original_prompt, cancel_event
        )
    except image_providers.ImageContentPolicyError as exc:
        _raise_if_cancelled(cancel_event)
        logger.info(
            "Image provider rejected prompt for '%s' — rewriting prompt",
            concept_name,
        )
        metrics.record("rewriter_triggered", 1)
        rewrite = await image_rewriter.run(
            original_prompt=original_prompt,
            failure_signal=f"image provider rejected prompt: {exc}",
            concept=concept_name,
        )
        _raise_if_cancelled(cancel_event)
        result = await run_in_threadpool(
            _generate_image_cancellable, rewrite.revised_prompt, cancel_event
        )
        logger.info("Retry used revised prompt: %s", rewrite.reasoning[:80])
        return {**result, "prompt_used": rewrite.revised_prompt}

    if not IMAGE_ENABLE_REWRITE_RECOVERY:
        return {**result, "prompt_used": original_prompt}

    _raise_if_cancelled(cancel_event, result["filepath"])
    try:
        check = await analyze_image_handler(image_b64=result["b64"])
    except Exception as e:
        logger.warning("vision check raised, skipping recovery: %s", e)
        return {**result, "prompt_used": original_prompt}

    if not check.get("has_text"):
        return {**result, "prompt_used": original_prompt}

    failure_signal = (
        "vision check detected text in output: "
        f"{check.get('details', '')}"
    )
    logger.info(
        "Image failed post-check for '%s' — rewriting prompt",
        concept_name,
    )
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


async def generate_images(
    concepts: list,
    cancel_event=None,
    on_progress=None,
) -> list[dict]:
    total = len(concepts)
    if total == 0:
        return []

    batch_cancel = cancel_event or asyncio.Event()
    semaphore = asyncio.Semaphore(IMAGE_GENERATION_CONCURRENCY)
    ordered_images: list[dict | None] = [None] * total

    async def generate_one(original_index: int, concept: dict):
        _raise_if_cancelled(batch_cancel)
        async with semaphore:
            _raise_if_cancelled(batch_cancel)
            final = await _generate_with_recovery(
                concept, cancel_event=batch_cancel
            )
        image = {
            "timestamp_seconds": concept["timestamp_seconds"],
            "image_url": f"/images/{Path(final['filepath']).name}",
        }
        _raise_if_cancelled(batch_cancel, final["filepath"])
        return original_index, concept, image, final["filepath"]

    tasks = [
        asyncio.create_task(generate_one(index, concept))
        for index, concept in enumerate(concepts)
    ]
    completed_count = 0
    published_indices: set[int] = set()

    try:
        for completed in asyncio.as_completed(tasks):
            original_index, concept, image, filepath = await completed
            _raise_if_cancelled(batch_cancel, filepath)
            ordered_images[original_index] = image
            completed_count += 1
            if on_progress is not None:
                await on_progress(
                    completed_count,
                    total,
                    concept,
                    image,
                )
                published_indices.add(original_index)
    except BaseException:
        batch_cancel.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for task_result in task_results:
            if not isinstance(task_result, tuple) or len(task_result) != 4:
                continue
            original_index, _concept, _image, filepath = task_result
            if original_index not in published_indices:
                Path(filepath).unlink(missing_ok=True)
        raise

    return [image for image in ordered_images if image is not None]


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
                yield await asyncio.wait_for(
                    progress_events.get(), timeout=0.05
                )
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
