"""Agent base — wraps Anthropic SDK with a tool-use loop, fallback, and logging.

Every agent node that needs to talk to an LLM does so through `run_claude()`
or `run_claude_with_tools()`. Both support prompt caching and will fall back
to OpenAI's gpt-4.1 if Anthropic returns 5xx.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable

import anthropic
from anthropic import APIStatusError

logger = logging.getLogger(__name__)


def _record(name: str, value: int | float) -> None:
    """Record a metric if the metrics module is importable. Fail-silent to keep
    agents testable in isolation."""
    try:
        from routers import metrics as _metrics

        _metrics.record(name, value)
    except Exception:
        pass


# Lazy singletons — created on first use so importing this module doesn't
# require the env vars to be set at import time (useful for tests).
_anthropic_client: anthropic.AsyncAnthropic | None = None
_openai_client: Any = None


def _get_anthropic() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
    return _anthropic_client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI

        _openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


async def run_claude(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1500,
    temperature: float = 0.0,
) -> str:
    """Single-turn Claude call with OpenAI fallback on 5xx. Returns text only."""
    t0 = time.monotonic()
    try:
        client = _get_anthropic()
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _record(f"claude_{model}_ms", elapsed_ms)
        _record("claude_calls", 1)
        logger.info(
            "claude %s: %d in, %d out, %dms",
            model,
            resp.usage.input_tokens,
            resp.usage.output_tokens,
            elapsed_ms,
        )
        return text
    except APIStatusError as e:
        if 500 <= e.status_code < 600:
            _record("anthropic_5xx_fallback", 1)
            logger.warning("Anthropic %d — falling back to OpenAI", e.status_code)
            return await _openai_fallback(system=system, user=user, max_tokens=max_tokens)
        raise


async def _openai_fallback(*, system: str, user: str, max_tokens: int) -> str:
    from .prompts import OPENAI_FALLBACK

    t0 = time.monotonic()
    client = _get_openai()
    resp = await client.chat.completions.create(
        model=OPENAI_FALLBACK,
        max_tokens=max_tokens,
        temperature=0.0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    logger.info(
        "openai %s fallback: %dms",
        OPENAI_FALLBACK,
        int((time.monotonic() - t0) * 1000),
    )
    return resp.choices[0].message.content or ""


async def run_claude_with_tools(
    *,
    model: str,
    system: str,
    user: str,
    tools: list[dict],
    tool_handlers: dict[str, Callable[..., Any]],
    max_tokens: int = 2000,
    max_iterations: int = 6,
) -> str:
    """Multi-turn Claude tool-use loop. Returns final text response.

    `tools` is the JSONSchema list passed to the API.
    `tool_handlers` maps tool names to sync or async callables that receive
    the tool's input dict and return a JSON-serializable result.
    """
    import inspect

    client = _get_anthropic()
    messages: list[dict] = [{"role": "user", "content": user}]

    for iteration in range(max_iterations):
        t0 = time.monotonic()
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
        )
        logger.info(
            "claude %s iter %d: stop=%s, %d in, %d out, %dms",
            model,
            iteration,
            resp.stop_reason,
            resp.usage.input_tokens,
            resp.usage.output_tokens,
            int((time.monotonic() - t0) * 1000),
        )

        if resp.stop_reason == "end_turn":
            return "".join(b.text for b in resp.content if b.type == "text")

        if resp.stop_reason != "tool_use":
            logger.warning("unexpected stop_reason=%s — returning text", resp.stop_reason)
            return "".join(b.text for b in resp.content if b.type == "text")

        # Record the assistant turn as-is, then run every tool call and append results.
        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            handler = tool_handlers.get(block.name)
            if handler is None:
                result = {"error": f"unknown tool: {block.name}"}
            else:
                try:
                    out = handler(**block.input)
                    if inspect.isawaitable(out):
                        out = await out
                    result = out
                except Exception as e:
                    logger.exception("tool %s raised", block.name)
                    result = {"error": str(e)}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"tool loop exceeded {max_iterations} iterations")


def _parse_json_candidate(candidate: str) -> Any:
    decoder = json.JSONDecoder()
    cleaned = candidate.strip()

    try:
        value, end = decoder.raw_decode(cleaned)
    except json.JSONDecodeError:
        pass
    else:
        if cleaned[end:].strip() == "":
            return value

    for match in re.finditer(r"[\[{]", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start():])
        except json.JSONDecodeError:
            continue
        return value

    raise json.JSONDecodeError("No JSON object or array found", cleaned, 0)


def parse_json_strict(text: str) -> Any:
    """Parse a JSON response, stripping accidental markdown fences if present.

    Raises ValueError with the raw text logged at WARNING so you can see what
    the model actually produced when parsing fails.
    """
    cleaned = text.strip()
    try:
        return _parse_json_candidate(cleaned)
    except json.JSONDecodeError as e:
        fence_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
        for fenced in fence_matches:
            try:
                return _parse_json_candidate(fenced)
            except json.JSONDecodeError:
                continue

        logger.warning("JSON parse failed. Raw response:\n%s", text)
        raise ValueError(f"model returned malformed JSON: {e}") from e
