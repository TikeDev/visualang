"""Tool implementations for the runtime agents.

Tools come in two flavors:
- Pure Python (regex, math, counting) — cheap and deterministic
- Sub-LLM tools (language detection, visualizability rating) — call Claude

Every tool exports two things:
- A JSONSchema dict (`*_SCHEMA`) passed to the Anthropic API
- A callable handler (`*_handler`) mapped by name in the agent's tool_handlers dict
"""

from __future__ import annotations

import re
from typing import Any

from . import base, prompts

# Words that hint at text ending up in the generated image.
FORBIDDEN_PROMPT_WORDS = [
    "text",
    "sign",
    "signs",
    "label",
    "labels",
    "letter",
    "letters",
    "word",
    "words",
    "caption",
    "captions",
    "writing",
    "written",
    "book page",
    "newspaper",
    "menu",
    "screen",
    "billboard",
    "poster",
    "logo",
    "watermark",
]

REQUIRED_SUFFIX_FRAGMENT = "children's storybook illustration"

# ---------------------------------------------------------------------------
# count_words_per_minute
# ---------------------------------------------------------------------------

COUNT_WPM_SCHEMA = {
    "name": "count_words_per_minute",
    "description": (
        "Compute words-per-minute over the transcript. "
        "Low WPM suggests silence or music."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def count_wpm_handler(*, transcript: list[dict]) -> dict:
    if not transcript:
        return {"wpm": 0.0, "word_count": 0, "duration_seconds": 0.0}
    total_words = sum(len(seg["text"].split()) for seg in transcript)
    last = transcript[-1]
    duration = last["start"] + last["duration"]
    wpm = (total_words / duration) * 60.0 if duration > 0 else 0.0
    return {"wpm": round(wpm, 1), "word_count": total_words, "duration_seconds": round(duration, 1)}


# ---------------------------------------------------------------------------
# check_silence_ratio
# ---------------------------------------------------------------------------

SILENCE_SCHEMA = {
    "name": "check_silence_ratio",
    "description": (
        "Ratio of silent gaps between segments vs. total duration. "
        "High ratio = sparse speech."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


def silence_handler(*, transcript: list[dict]) -> dict:
    if not transcript:
        return {"silence_ratio": 1.0, "total_seconds": 0.0}
    total = transcript[-1]["start"] + transcript[-1]["duration"]
    speech = sum(seg["duration"] for seg in transcript)
    silence = max(0.0, total - speech)
    ratio = silence / total if total > 0 else 1.0
    return {"silence_ratio": round(ratio, 2), "total_seconds": round(total, 1)}


# ---------------------------------------------------------------------------
# detect_language_sample (sub-LLM)
# ---------------------------------------------------------------------------

DETECT_LANGUAGE_SCHEMA = {
    "name": "detect_language_sample",
    "description": "Detect the primary language of the transcript by sampling a few segments.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}


async def detect_language_handler(*, transcript: list[dict]) -> dict:
    if not transcript:
        return {"language": "unknown", "confidence": 0.0}
    idx = [0, len(transcript) // 2, -1]
    sample = " | ".join(transcript[i]["text"] for i in idx)
    text = await base.run_claude(
        model=prompts.HAIKU,
        system=(
            "You detect the primary language of a transcript sample. "
            'Respond with a JSON object: {"language": "<ISO 639-1 code>", "confidence": <0-1>}. '
            'Use "unknown" if undetermined. Output JSON only.'
        ),
        user=f"Sample:\n{sample}",
        max_tokens=80,
    )
    try:
        return base.parse_json_strict(text)
    except ValueError:
        return {"language": "unknown", "confidence": 0.0}


# ---------------------------------------------------------------------------
# check_prompt_for_forbidden_text
# ---------------------------------------------------------------------------

CHECK_FORBIDDEN_SCHEMA = {
    "name": "check_prompt_for_forbidden_text",
    "description": (
        "Check draft image_prompts for forbidden words that invite text in generated images, "
        "and verify the required storybook suffix is present."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "image_prompt": {"type": "string"},
                    },
                    "required": ["index", "image_prompt"],
                },
            }
        },
        "required": ["concepts"],
    },
}


def check_forbidden_handler(*, concepts: list[dict]) -> dict:
    issues: list[dict] = []
    for c in concepts:
        prompt_lower = c["image_prompt"].lower()
        hits = [
            w
            for w in FORBIDDEN_PROMPT_WORDS
            if re.search(rf"\b{re.escape(w)}\b", prompt_lower)
        ]
        missing_suffix = REQUIRED_SUFFIX_FRAGMENT not in prompt_lower
        if hits or missing_suffix:
            issues.append(
                {
                    "index": c["index"],
                    "forbidden_words": hits,
                    "missing_suffix": missing_suffix,
                }
            )
    return {"issues": issues}


# ---------------------------------------------------------------------------
# check_timestamp_spacing
# ---------------------------------------------------------------------------

CHECK_SPACING_SCHEMA = {
    "name": "check_timestamp_spacing",
    "description": "Flag timestamp clusters (<15s apart) or gaps (>45s) in the concept list.",
    "input_schema": {
        "type": "object",
        "properties": {
            "timestamps": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["timestamps"],
    },
}


def check_spacing_handler(*, timestamps: list[int]) -> dict:
    sorted_ts = sorted(timestamps)
    clusters = []
    gaps = []
    for i in range(1, len(sorted_ts)):
        delta = sorted_ts[i] - sorted_ts[i - 1]
        if delta < 15:
            clusters.append({"between": [sorted_ts[i - 1], sorted_ts[i]], "delta": delta})
        elif delta > 45:
            gaps.append({"between": [sorted_ts[i - 1], sorted_ts[i]], "delta": delta})
    return {"clusters": clusters, "gaps": gaps}


# ---------------------------------------------------------------------------
# rate_visualizability (sub-LLM)
# ---------------------------------------------------------------------------

RATE_VISUALIZABILITY_SCHEMA = {
    "name": "rate_visualizability",
    "description": (
        "Rate each concept's visualizability 1-5 using a cheaper model. "
        "Flag concepts <= 2 as needing revision."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "concept": {"type": "string"},
                        "image_prompt": {"type": "string"},
                    },
                    "required": ["index", "concept", "image_prompt"],
                },
            }
        },
        "required": ["concepts"],
    },
}


async def rate_visualizability_handler(*, concepts: list[dict]) -> dict:
    import json as _json

    text = await base.run_claude(
        model=prompts.CONCEPT_CRITIQUE_MODEL,
        system=prompts.CONCEPT_CRITIQUE_SYSTEM,
        user="Draft concepts:\n" + _json.dumps(concepts, ensure_ascii=False),
        max_tokens=800,
    )
    try:
        ratings = base.parse_json_strict(text)
        return {"ratings": ratings}
    except ValueError:
        return {"ratings": [], "error": "critique returned malformed JSON"}


# ---------------------------------------------------------------------------
# analyze_generated_image (vision, sub-LLM)
# ---------------------------------------------------------------------------

ANALYZE_IMAGE_SCHEMA = {
    "name": "analyze_generated_image",
    "description": (
        "Vision check: does the generated image contain visible text, letters, "
        "or signage that shouldn't be there?"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "image_b64": {"type": "string", "description": "base64-encoded JPEG"},
        },
        "required": ["image_b64"],
    },
}


async def analyze_image_handler(*, image_b64: str) -> dict:
    client = base._get_anthropic()
    resp = await client.messages.create(
        model=prompts.HAIKU,
        max_tokens=200,
        system=(
            "You inspect images for visible text, letters, or signage. "
            'Respond with JSON only: {"has_text": bool, "details": "<short description>"}.'
        ),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": "Any visible text or signage? JSON only."},
                ],
            }
        ],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        return base.parse_json_strict(text)
    except ValueError:
        return {"has_text": False, "details": "analysis failed"}


# ---------------------------------------------------------------------------
# Tool bundles exposed per-agent
# ---------------------------------------------------------------------------

TRANSCRIPT_GATE_TOOLS = [COUNT_WPM_SCHEMA, SILENCE_SCHEMA, DETECT_LANGUAGE_SCHEMA]


def transcript_gate_handlers(transcript: list[dict]) -> dict:
    """Bind the transcript into tool handlers so the model doesn't have to pass it."""
    return {
        "count_words_per_minute": lambda **_: count_wpm_handler(transcript=transcript),
        "check_silence_ratio": lambda **_: silence_handler(transcript=transcript),
        "detect_language_sample": lambda **_: detect_language_handler(transcript=transcript),
    }


CONCEPT_CRITIQUE_TOOLS = [
    CHECK_FORBIDDEN_SCHEMA,
    CHECK_SPACING_SCHEMA,
    RATE_VISUALIZABILITY_SCHEMA,
]

CONCEPT_CRITIQUE_HANDLERS: dict[str, Any] = {
    "check_prompt_for_forbidden_text": check_forbidden_handler,
    "check_timestamp_spacing": check_spacing_handler,
    "rate_visualizability": rate_visualizability_handler,
}


IMAGE_REWRITER_TOOLS = [ANALYZE_IMAGE_SCHEMA]

IMAGE_REWRITER_HANDLERS: dict[str, Any] = {
    "analyze_generated_image": analyze_image_handler,
}
