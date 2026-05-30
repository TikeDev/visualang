"""TranscriptGate — quality check before the pipeline commits.

Single-node agent: Claude (Haiku) decides proceed/warn/reject after inspecting
the transcript via count_words_per_minute, check_silence_ratio, and
detect_language_sample tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from . import base, prompts, tools
from .graph import END, Graph

logger = logging.getLogger(__name__)

Verdict = Literal["proceed", "warn", "reject"]


@dataclass
class GateResult:
    verdict: Verdict
    reason: str
    detected_language: str


def _coerce_verdict(value: str) -> Verdict:
    if value not in {"proceed", "warn", "reject"}:
        raise ValueError(f"invalid gate verdict: {value}")
    return value


def fallback_gate_result(transcript: list[dict]) -> GateResult:
    wpm_result = tools.count_wpm_handler(transcript=transcript)
    silence_result = tools.silence_handler(transcript=transcript)
    speech_seconds = sum(float(seg.get("duration", 0)) for seg in transcript)
    wpm = float(wpm_result["wpm"])
    silence_ratio = float(silence_result["silence_ratio"])

    if speech_seconds < 20 or wpm < 10:
        return GateResult(
            "reject",
            (
                "deterministic quality check rejected transcript "
                f"({wpm:.1f} WPM, {speech_seconds:.1f}s speech)"
            ),
            "unknown",
        )

    if wpm < 35 or silence_ratio > 0.7:
        return GateResult(
            "warn",
            (
                "deterministic quality check found unusual speech density "
                f"({wpm:.1f} WPM, silence ratio {silence_ratio:.2f})"
            ),
            "unknown",
        )

    return GateResult(
        "proceed",
        (
            "deterministic quality check passed after parser failure "
            f"({wpm:.1f} WPM, silence ratio {silence_ratio:.2f})"
        ),
        "unknown",
    )


async def _gate_node(state: dict) -> str:
    transcript = state["transcript"]
    title = state["title"]
    duration = state["duration"]

    handlers = tools.transcript_gate_handlers(transcript)

    user = (
        f"Title: {title}\n"
        f"Duration (s): {duration}\n"
        f"Segment count: {len(transcript)}\n\n"
        "Inspect the transcript using the available tools, then return your verdict JSON."
    )

    text = await base.run_claude_with_tools(
        model=prompts.TRANSCRIPT_GATE_MODEL,
        system=prompts.TRANSCRIPT_GATE_SYSTEM,
        user=user,
        tools=tools.TRANSCRIPT_GATE_TOOLS,
        tool_handlers=handlers,
        max_iterations=5,
    )

    try:
        parsed = base.parse_json_strict(text)
        state["result"] = GateResult(
            verdict=_coerce_verdict(parsed["verdict"]),
            reason=parsed["reason"],
            detected_language=parsed.get("detected_language", "unknown"),
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("gate parse failed (%s), using deterministic fallback", e)
        state["result"] = fallback_gate_result(transcript)
    return END


_graph = Graph({"gate": _gate_node}, name="TranscriptGate")


async def run(transcript: list[dict], *, title: str, duration: float) -> GateResult:
    """Entry point: inspect transcript quality and return a verdict.

    Args:
        transcript: normalized segments [{text, start, duration}, ...]
        title: video title for context
        duration: total duration in seconds
    """
    if not transcript:
        return GateResult("reject", "empty transcript", "unknown")

    final = await _graph.run(
        initial_state={"transcript": transcript, "title": title, "duration": duration},
        start="gate",
    )
    result: GateResult = final["result"]
    logger.info("TranscriptGate: %s — %s", result.verdict, result.reason)
    try:
        from routers import metrics as _metrics

        _metrics.record(f"gate_{result.verdict}", 1)
    except Exception:
        pass
    return result
