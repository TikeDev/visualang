"""Langfuse tracing helper — thin wrapper so callers never need try/except.

Mirrors the fail-silent pattern in agents/base.py's `_record()`: a Langfuse
outage or missing credentials must never break a real job.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

from config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

logger = logging.getLogger(__name__)

_client = None
_enabled = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)


def _get_client():
    global _client
    if _client is None and _enabled:
        from langfuse import get_client

        _client = get_client()
    return _client


@contextmanager
def observe(*, as_type: str, name: str, **kwargs):
    """Start a Langfuse observation. No-ops (yields None) if Langfuse isn't
    configured or fails to start, so instrumentation never breaks a job.

    Exceptions raised by the wrapped code always propagate — only failures
    in starting the Langfuse observation itself are swallowed.
    """
    client = _get_client()
    cm = None
    observation = None
    if client is not None:
        try:
            cm = client.start_as_current_observation(as_type=as_type, name=name, **kwargs)
            observation = cm.__enter__()
        except Exception:
            logger.warning("Langfuse observation %r failed to start", name, exc_info=True)
            cm = None

    try:
        yield observation
    finally:
        if cm is not None:
            cm.__exit__(None, None, None)


def update(observation, **kwargs) -> None:
    if observation is None:
        return
    try:
        observation.update(**kwargs)
    except Exception:
        logger.warning("Langfuse observation update failed", exc_info=True)


def flush() -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.warning("Langfuse flush failed", exc_info=True)
