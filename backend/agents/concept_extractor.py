"""ConceptExtractor — three-node graph: extract -> critique -> fix.

- extract: Claude Sonnet produces a draft concept list from the transcript
- critique: tools check the draft for forbidden text, bad spacing, and rate
  visualizability. If nothing is flagged, skip to END.
- fix: Claude Sonnet revises flagged concepts and returns the final list.

Returns list[dict] matching the shape consumed by `/generate`:
  [{timestamp_seconds, concept, image_prompt}, ...]
"""

from __future__ import annotations

import json
import logging

from . import base, prompts, tools
from .graph import END, Graph

logger = logging.getLogger(__name__)


def _format_transcript(transcript: list[dict]) -> str:
    lines = []
    for seg in transcript:
        end = seg["start"] + seg.get("duration", 0)
        lines.append(f"[{int(seg['start']):04d}s-{int(end):04d}s] {seg['text']}")
    return "\n".join(lines)


async def _extract_node(state: dict) -> str:
    user = (
        "Transcript:\n"
        + _format_transcript(state["transcript"])
        + "\n\nReturn the JSON array of concepts."
    )
    text = await base.run_claude(
        model=prompts.CONCEPT_EXTRACTOR_MODEL,
        system=prompts.CONCEPT_EXTRACTOR_SYSTEM,
        user=user,
        max_tokens=8000,
    )
    draft = base.parse_json_strict(text)
    if not isinstance(draft, list):
        raise ValueError(f"extractor returned non-list: {type(draft).__name__}")
    state["draft"] = draft
    logger.info("ConceptExtractor extract: %d concepts", len(draft))
    return "critique"


async def _critique_node(state: dict) -> str:
    draft = state["draft"]
    indexed = [{"index": i, **c} for i, c in enumerate(draft)]

    forbidden = tools.check_forbidden_handler(
        concepts=[{"index": i["index"], "image_prompt": i["image_prompt"]} for i in indexed]
    )
    spacing = tools.check_spacing_handler(
        timestamps=[c["timestamp_seconds"] for c in draft]
    )
    ratings = await tools.rate_visualizability_handler(
        concepts=[
            {"index": i["index"], "concept": i["concept"], "image_prompt": i["image_prompt"]}
            for i in indexed
        ]
    )

    flagged_indices: set[int] = set()
    for issue in forbidden["issues"]:
        flagged_indices.add(issue["index"])
    for rating in ratings.get("ratings", []):
        if rating.get("rating", 5) <= 2 or rating.get("issues"):
            flagged_indices.add(rating["index"])

    state["critique"] = {
        "forbidden": forbidden,
        "spacing": spacing,
        "ratings": ratings,
        "flagged_indices": sorted(flagged_indices),
    }
    logger.info(
        "ConceptExtractor critique: %d flagged, %d clusters, %d gaps",
        len(flagged_indices),
        len(spacing["clusters"]),
        len(spacing["gaps"]),
    )

    if not flagged_indices and not spacing["clusters"] and not spacing["gaps"]:
        state["final"] = draft
        return END
    return "fix"


async def _fix_node(state: dict) -> str:
    draft = state["draft"]
    critique = state["critique"]

    user = (
        "Original draft:\n"
        + json.dumps(draft, ensure_ascii=False)
        + "\n\nCritique:\n"
        + json.dumps(critique, ensure_ascii=False)
        + "\n\nTranscript context (for replacements):\n"
        + _format_transcript(state["transcript"])
        + "\n\nReturn the full revised JSON array."
    )
    text = await base.run_claude(
        model=prompts.CONCEPT_EXTRACTOR_MODEL,
        system=prompts.CONCEPT_FIX_SYSTEM,
        user=user,
        max_tokens=8000,
    )
    revised = base.parse_json_strict(text)
    if not isinstance(revised, list):
        raise ValueError(f"fix returned non-list: {type(revised).__name__}")
    state["final"] = revised
    logger.info("ConceptExtractor fix: %d concepts", len(revised))
    return END


_graph = Graph(
    {"extract": _extract_node, "critique": _critique_node, "fix": _fix_node},
    name="ConceptExtractor",
)


async def run(transcript: list[dict]) -> list[dict]:
    """Entry point: transcript -> final list of {timestamp_seconds, concept, image_prompt}."""
    if not transcript:
        return []
    final = await _graph.run(
        initial_state={"transcript": transcript},
        start="extract",
    )
    return final["final"]
