# Langfuse Guide for Visualang

A plain-language guide to navigating Langfuse and understanding what data gets captured, when, and why.

## Table of Contents

- [Navigating the Langfuse UI](#navigating-the-langfuse-ui)
  - [Traces table](#traces-table)
  - [Opening a trace](#opening-a-trace)
  - [Finding one job's trace](#finding-one-jobs-trace)
- [How data is picked up at every stage](#how-data-is-picked-up-at-every-stage)
  - [The big picture](#the-big-picture)
  - [Stage 0: the job starts](#stage-0-the-job-starts)
  - [Stage 1: transcript](#stage-1-transcript)
  - [Stage 2: concepts](#stage-2-concepts)
  - [Stage 3: generating_images](#stage-3-generating_images)
  - [Stage 4: export](#stage-4-export)
  - [The job finishes](#the-job-finishes)
- [Key terms cheat sheet](#key-terms-cheat-sheet)

---

## Navigating the Langfuse UI

### Traces table

When you log in to Langfuse and open your project, the main view you want is **Tracing → Traces** in the left sidebar. This is a table, one row per Visualang job. Each row shows:

- **Name** — always `visualang-job` for this project (every job creates one trace with this name)
- **Input** — a preview of the video/audio source (URL or filename)
- **Output** — a preview of the result (`concept_count`, `image_count`, `status`)
- **Timestamp**, **Latency** (how long the job took), and **Cost** (LLM token cost — image generation isn't priced per-token so it won't add to this)

Click any row to open the full trace.

### Opening a trace

A trace page has two main parts:

- **Left panel: the tree.** This is a nested list showing the shape of the job — one root (`visualang-job`) containing four stage boxes (`transcript`, `concepts`, `generating_images`, `export`), and each stage containing the individual LLM/image-generation calls that happened inside it. Indentation = nesting. Click any row in the tree to inspect it on the right.
- **Right panel: the details.** Whatever you clicked in the tree, its Input, Output, Metadata, timing, and (for LLM calls) token usage and model name show up here.

Rows in the tree are colored/tagged by **type**:
- `SPAN` — a container/grouping step (the job itself, and each of the four stages). No model, no tokens — it just marks "this is where stage X happened."
- `GENERATION` — an actual LLM or image-generation call. This is where you'll see the prompt that went in and the text/image that came out, plus token counts for LLM calls.

If a `GENERATION` row shows an image thumbnail in its Output, click it to view the generated image full-size directly in the browser — you don't need to go dig it out of the app.

### Finding one job's trace

Two ways to jump to a specific run:

1. **By source** — in the Traces table, the Input column preview usually shows enough of the YouTube URL or filename to spot it directly.
2. **By job ID** — every trace has the job's ID attached as metadata. Use the filter bar above the Traces table, add a filter on `Metadata`, key `job_id`, and paste in the job ID. You can get the job ID from the app's URL after starting a job — the URL hash looks like `#/jobs/<job_id>.<secret>`; the part before the dot is the job ID.

---

## How data is picked up at every stage

### The big picture

Visualang runs a job through four stages in order: **transcript → concepts → generating_images → export**. This lives in [`backend/job_runner.py`](../backend/job_runner.py) as `JobRunner._execute()`. That one method is also where Langfuse tracing starts and ends — it wraps the whole job in one trace, then wraps each stage in its own nested span. Everything below happens inside that single method call.

```
visualang-job (SPAN, the whole job)
├── transcript (SPAN)
│   └── run_claude (GENERATION) × a few — TranscriptGate checks
├── concepts (SPAN)
│   └── run_claude (GENERATION) × a few — ConceptExtractor's draft/critique/fix
├── generating_images (SPAN)
│   └── cloudflare_image_generation (GENERATION) × one per concept
└── export (SPAN)
    (no LLM/image calls — just ffmpeg, nothing sent to Langfuse here)
```

### Stage 0: the job starts

**Code:** [`job_runner.py:86-91`](../backend/job_runner.py#L86)

The moment `_execute()` begins, it opens the root trace:

```python
with observability.observe(
    as_type="span",
    name="visualang-job",
    input={"source": job.get("source")},
    metadata={"job_id": job_id},
) as trace:
```

- **Input** is the job's source — either `{"type": "youtube", "url": ...}` or `{"type": "upload", "filename": ...}`. Only the reference is stored, never the raw video/audio bytes.
- **Metadata** carries the `job_id` so you can filter by it later.
- **Output** is left empty for now — it gets filled in at the very end, once the job finishes (see [The job finishes](#the-job-finishes) below).

Everything that happens for the rest of the job nests inside this trace automatically — you don't have to pass anything explicitly; Langfuse tracks "what's currently open" behind the scenes.

### Stage 1: transcript

**Code:** [`job_runner.py:98-105`](../backend/job_runner.py#L98) calling into `TranscriptGate` ([`backend/agents/transcript_gate.py`](../backend/agents/transcript_gate.py))

```python
with observability.observe(as_type="span", name="transcript"):
    transcript = await self.transcript_fn(job["source"], cancel_event=cancel_event)
```

This opens a `transcript` span. Inside it, the transcript gets fetched from YouTube (or the uploaded audio gets transcribed), then `TranscriptGate` runs — a small agent that checks the transcript is usable (enough speech, clear language, etc.) before spending money on the rest of the pipeline. Every Claude call it makes goes through `run_claude()` / `run_claude_with_tools()` in [`backend/agents/base.py`](../backend/agents/base.py), which is the **one choke point** for every LLM call in the whole app — see [How every LLM call gets logged](#how-every-llm-call-gets-logged) below for what gets captured there.

### Stage 2: concepts

**Code:** [`job_runner.py:107-113`](../backend/job_runner.py#L107) calling into `ConceptExtractor` ([`backend/agents/concept_extractor.py`](../backend/agents/concept_extractor.py))

```python
with observability.observe(as_type="span", name="concepts"):
    concepts = await self.concepts_fn(job["transcript"])
```

Inside this span, `ConceptExtractor` runs its draft → critique → fix loop to turn the transcript into a list of visual concepts (each with a timestamp and an image prompt). Each of those three steps is its own `run_claude()` call, so you'll typically see 2-3 `GENERATION` rows nested here. Once this finishes, the trace records how many concepts came out (`concept_count`).

### Stage 3: generating_images

**Code:** [`job_runner.py:115-121`](../backend/job_runner.py#L115) calling into `image_providers.py`

```python
with observability.observe(as_type="span", name="generating_images"):
    images = await self.images_fn(job["concepts"], cancel_event=cancel_event)
```

For each concept, Visualang calls the image provider (Cloudflare or Nunchaku). Both `call_cloudflare()` and `call_nunchaku()` in [`backend/image_providers.py`](../backend/image_providers.py) open their own `GENERATION` span:

```python
with observability.observe(
    as_type="generation",
    name="cloudflare_image_generation",
    model=CLOUDFLARE_MODEL,
    input={"prompt": prompt},
) as generation:
    ...
    observability.update(generation, output={"image": LangfuseMedia(...)})
```

- **Input** is the actual image prompt text that was sent.
- **Output** is the generated image itself, uploaded into Langfuse as media (not just a link) — that's why you can click the thumbnail and see the picture right there in the trace, even after the app's own copy gets cleaned up (job artifacts are deleted after 24 hours; the Langfuse copy is not).

This step generates images concurrently, so you'll see multiple `cloudflare_image_generation` rows with overlapping timestamps — that's expected, not a bug.

### Stage 4: export

**Code:** [`job_runner.py:123-131`](../backend/job_runner.py#L123)

```python
with observability.observe(as_type="span", name="export"):
    result = await self.export_fn(...)
```

This stage stitches the images and audio into the final `.mp4` using ffmpeg. There's no LLM or image-generation call here, so this span will show up in the trace tree as an empty container — just there to mark how long export took.

### The job finishes

**Code:** [`job_runner.py:133-147`](../backend/job_runner.py#L133)

Whether the job succeeds, fails, or gets cancelled, the same `finally` block runs:

```python
finally:
    observability.update(trace, output=trace_output)
    observability.flush()
```

- `trace_output` was being built up throughout the job (`concept_count`, `image_count`, and finally `status`: `"done"`, `"error"`, or `"cancelled"`). This becomes the trace's final Output — what you see summarized in the Traces table.
- `flush()` forces any buffered data to actually get sent to Langfuse before the function returns. This matters because jobs run as background tasks, not as part of a normal web request/response — without an explicit flush, data could sit in memory and never make it out if the process exits at the wrong moment.

### How every LLM call gets logged

Regardless of which stage it happens in, every single Claude API call — TranscriptGate, ConceptExtractor's draft/critique/fix, the OpenAI fallback on errors — passes through `run_claude()` or `run_claude_with_tools()` in [`backend/agents/base.py`](../backend/agents/base.py). That's the one place this is implemented, so every LLM call automatically gets:

- **Input**: the system prompt and the user message actually sent
- **Output**: the model's text response
- **Model name**: e.g. `claude-sonnet-4-6`, `claude-haiku-4-5-...`
- **Token usage**: input tokens / output tokens, which is what lets Langfuse estimate cost

This is why you don't see separate instrumentation code scattered through `transcript_gate.py` or `concept_extractor.py` — they just call `run_claude()`, and get tracing for free.

---

## Key terms cheat sheet

| Term | What it means here |
|---|---|
| **Trace** | One entire Visualang job, from source to finished video. Always named `visualang-job`. |
| **Span** | A container marking a phase of work (a stage, or the whole job). No prompt/output of its own beyond a summary — just groups what happened inside it. |
| **Generation** | One actual LLM or image-generation API call. Has a model name, an input (prompt), an output (response/image), and usually token counts. |
| **Observation** | Langfuse's umbrella term for "anything in the tree" — spans and generations are both observations. |
| **Metadata** | Extra tags attached to a trace/observation that aren't the input or output themselves — right now, mainly `job_id`, used for filtering. |
| **Flush** | Forcing buffered tracing data to actually send. Needed here because jobs run as background tasks, not web requests. |
