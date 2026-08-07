from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, Awaitable, Callable

from job_store import JobStore

logger = logging.getLogger(__name__)

STAGE_ORDER = ("transcript", "concepts", "generating_images", "export")
_STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_ORDER)}


def reconcile_jobs_after_restart(store: JobStore, now: float | None = None) -> None:
    """On process startup: expire old jobs and mark interrupted any job that
    was mid-run when the previous process stopped, so it becomes retryable."""
    store.expire_jobs(now=now)
    with store._connect() as connection:  # noqa: SLF001 - startup reconciliation needs a raw scan
        rows = connection.execute("SELECT id, payload_json FROM jobs").fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("status") != "running":
            continue
        store.update(row["id"], status="interrupted")
        logger.info("Reconciled interrupted job after restart: %s", row["id"])


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        *,
        transcript_fn: Callable[[Any], Awaitable[list]] | None = None,
        concepts_fn: Callable[[list], Awaitable[list]] | None = None,
        images_fn: Callable[..., Awaitable[list]] | None = None,
        export_fn: Callable[..., Awaitable[dict]] | None = None,
    ) -> None:
        self.store = store
        self.transcript_fn = transcript_fn
        self.concepts_fn = concepts_fn
        self.images_fn = images_fn
        self.export_fn = export_fn
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def _cancel_event_for(self, job_id: str) -> threading.Event:
        return self._cancel_events.setdefault(job_id, threading.Event())

    async def run(self, job_id: str) -> None:
        await self._execute(job_id, start_stage="transcript")

    async def retry(self, job_id: str) -> None:
        job = self._job_row(job_id)
        start_stage = job.get("stage") or "transcript"
        if start_stage not in _STAGE_INDEX:
            start_stage = "transcript"
        await self._execute(job_id, start_stage=start_stage)

    async def cancel(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            cancel_event = self._cancel_event_for(job_id)
            cancel_event.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return

        job = self._job_row(job_id)
        if job.get("status") != "running":
            return
        self.store.update(job_id, status="cancelled")

    async def _execute(self, job_id: str, *, start_stage: str) -> None:
        cancel_event = self._cancel_event_for(job_id)
        cancel_event.clear()
        current = asyncio.current_task()
        if current is not None:
            self._tasks[job_id] = current

        try:
            self.store.update(job_id, status="running", error=None)
            job = self._job_row(job_id)

            stage_index = _STAGE_INDEX[start_stage]

            if stage_index <= _STAGE_INDEX["transcript"]:
                transcript = await self.transcript_fn(
                    job["source"], cancel_event=cancel_event
                )
                job = self.store.update(
                    job_id, transcript=transcript, stage="concepts"
                )

            if stage_index <= _STAGE_INDEX["concepts"]:
                concepts = await self.concepts_fn(job["transcript"])
                job = self.store.update(
                    job_id, concepts=concepts, stage="generating_images"
                )

            if stage_index <= _STAGE_INDEX["generating_images"]:
                images = await self.images_fn(
                    job["concepts"], cancel_event=cancel_event
                )
                job = self.store.update(job_id, images=images, stage="export")

            if stage_index <= _STAGE_INDEX["export"]:
                result = await self.export_fn(
                    job["transcript"],
                    job["images"],
                    self.store.job_dir(job_id),
                    job_id=job_id,
                )
                job = self.store.update(job_id, **result)

            self.store.update(job_id, status="done")
        except asyncio.CancelledError:
            self.store.update(job_id, status="cancelled")
            raise
        except Exception as error:
            stage = self._job_row(job_id).get("stage", start_stage)
            logger.exception("Job %s failed at stage %s", job_id, stage)
            self.store.update(job_id, status="error", error=str(error))
        finally:
            self._tasks.pop(job_id, None)

    def _job_row(self, job_id: str) -> dict:
        with self.store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return self.store._public_job(row)  # noqa: SLF001
