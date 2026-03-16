"""
api/app.py
----------
CASForge FastAPI backend — Phase 3.

Serves both the REST API and the HTML frontend.

Start with:
    uvicorn casforge.web.app:app --reload --host 0.0.0.0 --port 8000
Or via bat:
    bat/start_server.bat

Endpoints
---------
GET  /                          → HTML frontend (index.html)
GET  /api/stories?csv=<path>    → list all stories in a CSV
GET  /api/story/<key>?csv=<path>→ full story detail
POST /api/intents               → extract intents (LLM call — slow)
POST /api/generate              → full pipeline: intents + feature file (LLM call — slow)
POST /api/generate/stream       → same as /generate but streams progress as SSE events
POST /api/search                → step retrieval search
GET  /api/output                → list generated .feature files
GET  /api/output/<filename>     → content of a specific generated file
"""

from __future__ import annotations

import logging
import os
import re

import json
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import List

from casforge.web.models import (
    StoryRef, StoryInfo, StorySummary,
    IntentsResponse, GenerateRequest, GenerateResponse,
    DirectForgeRequest,
    UploadCsvRequest, UploadCsvResponse,
    SearchRequest, StepResult, OutputFile,
)
from casforge.shared.paths import WEB_FRONTEND_DIR, SAMPLES_DIR, CONFIG_DIR, ensure_dir, resolve_user_path
from casforge.shared.settings import OUTPUT_DIR

# In-memory store for stories submitted via the manual entry form.
# Key: upper-cased issue_key.  Cleared on server restart (intentional — ephemeral session data).
_manual_stories: dict = {}

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
_log = logging.getLogger("casforge.api")

app = FastAPI(
    title="CASForge",
    description="JIRA → Gherkin .feature file generator for CAS ATDD",
    version="2.0",
)

# Serve static files from the packaged frontend directory.
_FRONTEND_DIR = str(WEB_FRONTEND_DIR)
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# Frontend
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index():
    html_path = os.path.join(_FRONTEND_DIR, "index.html")
    if not os.path.isfile(html_path):
        return HTMLResponse("<h1>web frontend index.html not found</h1>", status_code=404)
    return FileResponse(html_path)


# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/upload-csv", response_model=UploadCsvResponse)
def upload_csv(req: UploadCsvRequest):
    """Store a browser-uploaded CSV into the workspace samples area and return its path."""
    raw_name = os.path.basename((req.filename or "upload.csv").strip())
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name) or "upload.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name += ".csv"

    uploads_dir = ensure_dir(SAMPLES_DIR / "uploads")
    stored_path = uploads_dir / safe_name
    stored_path.write_text(req.content or "", encoding="utf-8")
    return UploadCsvResponse(filename=safe_name, stored_path=str(stored_path))


# ─────────────────────────────────────────────────────────────────────────────
# Config — LOBs, stages, families for UI chip clouds
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    """
    Return domain configuration for the UI: LOB chips, stage chips, family list.
    Driven by config/domain_knowledge.json — edit that file to add new chips,
    no HTML changes needed.
    """
    try:
        with open(CONFIG_DIR / "domain_knowledge.json", encoding="utf-8-sig") as f:
            dk = json.load(f)
    except Exception as e:
        _log.warning("Could not load domain_knowledge.json: %s", e)
        dk = {}

    lobs    = [entry["canonical"] for entry in (dk.get("lob_aliases") or []) if entry.get("canonical")]
    stages  = [entry["canonical"] if isinstance(entry, dict) else entry
               for entry in (dk.get("stages") or [])]
    families = [entry["key"] if isinstance(entry, dict) else entry
                for entry in (dk.get("families") or [])]

    return {"lobs": lobs, "stages": stages, "families": families}


# ─────────────────────────────────────────────────────────────────────────────
# Manual story entry — add a story without a CSV file
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/story/manual")
def add_manual_story(payload: dict):
    """
    Accept a story typed in manually via the UI form.
    Stored in memory for the session; accessible via csv=manual.
    """
    from casforge.parsing.jira_parser import JiraStory

    key = str(payload.get("issue_key") or "").strip().upper()
    summary = str(payload.get("summary") or "").strip()
    if not key:
        raise HTTPException(status_code=422, detail="issue_key is required")
    if not summary:
        raise HTTPException(status_code=422, detail="summary is required")

    story = JiraStory(
        issue_key           = key,
        summary             = summary,
        issue_type          = "Story",
        description         = str(payload.get("description") or ""),
        legacy_process      = "",
        system_process      = str(payload.get("new_process") or ""),
        business_scenarios  = "",
        impacted_areas      = str(payload.get("impacted_areas") or ""),
        key_ui_steps        = "",
        acceptance_criteria = str(payload.get("acceptance_criteria") or ""),
        story_description   = "",
    )
    _manual_stories[key] = story
    _log.info("Manual story added: %s — %s", key, summary)
    return {"status": "ok", "issue_key": key}


# Story management
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/stories", response_model=List[StorySummary])
def list_stories(csv: str = Query(..., description="Absolute or relative path to JIRA CSV, or 'manual'")):
    """List all stories in a JIRA CSV export, or all manually added stories."""
    if csv.strip().lower() == "manual":
        return [StorySummary(key=s.issue_key, summary=s.summary, type=s.issue_type)
                for s in _manual_stories.values()]
    from casforge.parsing.jira_parser import load_all_stories
    csv_path = _resolve_path(csv)
    stories = load_all_stories(csv_path)
    return [StorySummary(key=s.issue_key, summary=s.summary, type=s.issue_type)
            for s in stories]


@app.get("/api/story/{key}", response_model=StoryInfo)
def get_story(key: str, csv: str = Query(...)):
    """Return full parsed details for a single story."""
    if csv.strip().lower() == "manual":
        story = _manual_stories.get(key.upper())
        if not story:
            raise HTTPException(status_code=404, detail=f"Manual story not found: {key}")
    else:
        from casforge.parsing.jira_parser import load_story
        csv_path = _resolve_path(csv)
        try:
            story = load_story(csv_path, key)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return StoryInfo(
        issue_key           = story.issue_key,
        summary             = story.summary,
        issue_type          = story.issue_type,
        description         = story.description,
        new_process         = story.system_process,   # maps renamed field
        current_process     = story.legacy_process,   # maps renamed field
        business_scenarios  = story.business_scenarios,
        impacted_areas      = story.impacted_areas,
        key_ui_steps        = story.key_ui_steps,
        acceptance_criteria = story.acceptance_criteria,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM — intent extraction
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/intents", response_model=IntentsResponse)
def extract_intents_endpoint(req: StoryRef):
    """
    Extract testable intents from a JIRA story using Llama.
    This is a slow operation (~1-3 minutes on CPU).
    """
    from casforge.parsing.jira_parser import load_story
    from casforge.generation.intent_extractor import (
        extract_intents,
        infer_story_scope_defaults,
        normalise_story_scope_defaults,
    )

    csv_path = _resolve_path(req.csv_path)
    try:
        story = load_story(csv_path, req.story_key)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    _log.info("Extracting intents for %s ...", req.story_key)
    defaults = (
        normalise_story_scope_defaults(req.story_scope_defaults.model_dump())
        if req.story_scope_defaults else infer_story_scope_defaults(story)
    )
    intents = extract_intents(story, story_scope_defaults=defaults)
    return IntentsResponse(
        story_key=story.issue_key,
        summary=story.summary,
        story_scope_defaults=defaults,
        intents=intents,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Shared pipeline — used by both streaming and non-streaming endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _pipeline_stream(req: GenerateRequest, csv_path: str):
    """
    Generator that runs the full JIRA → intents → forge pipeline and yields
    SSE-style event dicts.  Both /api/generate and /api/generate/stream use this.
    """
    from casforge.parsing.jira_parser import load_story
    from casforge.generation.intent_extractor import (
        extract_intents, coerce_intents,
        infer_story_scope_defaults,
        normalise_story_scope_defaults,
    )
    from casforge.generation.forge import forge_feature
    from casforge.workflow.ordering import detect_stage, detect_sub_tags

    def _event(event: str, data) -> str:
        return f"data: {json.dumps({'event': event, 'data': data})}\n\n"

    if csv_path.strip().lower() == "manual":
        story = _manual_stories.get(req.story_key.upper())
        if not story:
            yield _event("error", f"Manual story not found: {req.story_key}")
            return
    else:
        try:
            story = load_story(csv_path, req.story_key)
        except ValueError as e:
            yield _event("error", str(e))
            return

    defaults = (
        normalise_story_scope_defaults(req.story_scope_defaults.model_dump())
        if req.story_scope_defaults else infer_story_scope_defaults(story)
    )

    if req.intents:
        intents = coerce_intents(req.intents, story_scope_defaults=defaults)
        yield _event("status", f"Using {len(intents)} provided intents...")
    else:
        yield _event("status", "Extracting test intents (LLM)...")
        intents = extract_intents(story, story_scope_defaults=defaults)
        if not intents:
            yield _event("error", "LLM returned no intents — check model output.")
            return

    yield _event("intents", intents)

    yield _event("status", f"Forging {len(intents)} scenarios from repository steps (LLM)...")
    try:
        assembly = forge_feature(story=story, intents=intents, flow_type=req.flow_type)
        feature_text = assembly.feature_text
    except Exception as e:
        yield _event("error", f"Forge failed: {e}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_key = req.story_key.replace("-", "_")
    out_path = os.path.join(OUTPUT_DIR, f"{safe_key}.feature")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(feature_text + "\n")

    stage_q  = story.summary + " " + (story.impacted_areas or "")
    stage    = detect_stage(stage_q)
    sub_tags = detect_sub_tags(stage_q)

    yield _event("feature", {
        "text":                 feature_text,
        "stage":                stage,
        "sub_tags":             sub_tags,
        "flow_type":            req.flow_type,
        "file_path":            out_path,
        "story_scope_defaults": defaults,
        "quality":              assembly.quality,
        "unresolved_steps":     assembly.unresolved_steps,
        "scenario_debug":       assembly.scenario_debug,
        "coverage_gaps":        assembly.coverage_gaps,
        "omitted_plan_items":   assembly.omitted_plan_items,
        # also include full intents and story meta for non-streaming caller
        "_intents":             intents,
        "_story_key":           story.issue_key,
        "_summary":             story.summary,
    })
    yield _event("done", None)


# ─────────────────────────────────────────────────────────────────────────────
# LLM — full feature generation (non-streaming)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/generate", response_model=GenerateResponse)
def generate_feature_endpoint(req: GenerateRequest):
    """
    Full pipeline: JIRA story → intents → step retrieval → .feature file.
    Collects streaming events internally and returns the final result as JSON.
    """
    csv_path = _resolve_path(req.csv_path)

    feature_payload = None
    error_msg = None

    for raw in _pipeline_stream(req, csv_path):
        # Each yielded value is "data: {...}\n\n"
        line = raw.strip()
        if line.startswith("data: "):
            evt = json.loads(line[6:])
            if evt["event"] == "error":
                error_msg = evt["data"]
                break
            if evt["event"] == "feature":
                feature_payload = evt["data"]

    if error_msg:
        raise HTTPException(status_code=422, detail=error_msg)
    if not feature_payload:
        raise HTTPException(status_code=500, detail="Pipeline produced no feature output.")

    intents = feature_payload.pop("_intents", [])
    story_key = feature_payload.pop("_story_key", req.story_key)
    summary   = feature_payload.pop("_summary", "")

    return GenerateResponse(
        story_key           = story_key,
        summary             = summary,
        flow_type           = req.flow_type,
        story_scope_defaults= feature_payload.get("story_scope_defaults"),
        intents             = intents,
        feature_text        = feature_payload["text"],
        file_path           = feature_payload["file_path"],
        stage               = feature_payload.get("stage", ""),
        sub_tags            = feature_payload.get("sub_tags", []),
        quality             = feature_payload.get("quality", {}),
        unresolved_steps    = feature_payload.get("unresolved_steps", []),
        scenario_debug      = feature_payload.get("scenario_debug", []),
        coverage_gaps       = feature_payload.get("coverage_gaps", []),
        omitted_plan_items  = feature_payload.get("omitted_plan_items", []),
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM — streaming generation (Server-Sent Events)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/generate/stream")
def generate_feature_stream(req: GenerateRequest):
    """
    Same as /api/generate but streams progress events as Server-Sent Events.

    Events emitted (each as a JSON string):
        { "event": "status",   "data": "Extracting intents..." }
        { "event": "intents",  "data": ["intent1", "intent2", ...] }
        { "event": "status",   "data": "Forging scenarios..." }
        { "event": "feature",  "data": { "text": "...", "stage": "...", ... } }
        { "event": "done",     "data": null }
        { "event": "error",    "data": "error message" }
    """
    csv_path = _resolve_path(req.csv_path)
    return StreamingResponse(_pipeline_stream(req, csv_path), media_type="text/event-stream")


# Direct Forge — skip JIRA intake, assemble directly from user-written intents

@app.post("/api/forge/direct")
def forge_direct(req: DirectForgeRequest):
    """
    Accepts raw intent lines and forges a .feature file directly.
    Skips JIRA parsing and LLM extraction. Streams the same SSE events.
    """
    from casforge.parsing.jira_parser import JiraStory
    from casforge.generation.forge import forge_feature

    def _event(event: str, data) -> str:
        return f"data: {json.dumps({'event': event, 'data': data})}\n\n"

    def _stream():
        raw_lines = [
            l.strip() for l in req.intents_text.splitlines()
            if l.strip() and not l.strip().startswith('#')
        ]
        if not raw_lines:
            yield _event("error", "No intents provided - add at least one line.")
            return

        intents = [
            {"id": f"direct_{i:03d}", "text": line, "family": "positive", "inherit_story_scope": True}
            for i, line in enumerate(raw_lines, 1)
        ]

        yield _event("status", f"Assembling {len(intents)} intents via retrieval...")

        story = JiraStory(
            issue_key="DIRECT",
            summary=req.title or "Direct Forge",
            issue_type="Story",
            description="",
            legacy_process="",
            system_process="",
            business_scenarios="",
            impacted_areas="",
            key_ui_steps="",
            acceptance_criteria="",
            story_description="",
        )

        try:
            assembly = forge_feature(
                story=story,
                intents=intents,
                flow_type=req.flow_type,
            )
        except Exception as e:
            yield _event("error", f"Forge failed: {e}")
            return

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        out_path = os.path.join(OUTPUT_DIR, "direct_forge.feature")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(assembly.feature_text + "\n")

        yield _event("feature", {
            "text": assembly.feature_text,
            "quality": assembly.quality,
            "unresolved_steps": assembly.unresolved_steps,
            "coverage_gaps": assembly.coverage_gaps,
            "omitted_plan_items": assembly.omitted_plan_items,
        })
        yield _event("done", None)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval search
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/search", response_model=List[StepResult])
def search_steps(req: SearchRequest):
    """Search the step catalogue using hybrid retrieval."""
    from casforge.retrieval.retrieval import search

    results = search(
        query          = req.query,
        top_k          = req.top_k,
        screen_filter  = req.screen_filter,
        keyword_filter = req.keyword_filter,
    )

    return [
        StepResult(
            step_id        = r.get("step_id", 0),
            keyword        = r.get("keyword", ""),
            step_text      = r.get("step_text", ""),
            score          = r.get("score", 0.0),
            screen_context = r.get("screen_context"),
            scenario_title = r.get("scenario_title"),
            file_name      = r.get("file_name"),
            scenario_steps = r.get("scenario_steps", []),
        )
        for r in results
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Output file management
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/output")
def list_output_files():
    """List all generated .feature files."""
    if not os.path.isdir(OUTPUT_DIR):
        return []
    files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith(".feature"))
    return [
        {
            "filename":  f,
            "story_key": f.replace("_", "-").replace(".feature", ""),
            "size":      os.path.getsize(os.path.join(OUTPUT_DIR, f)),
        }
        for f in files
    ]


@app.get("/api/output/{filename}")
def get_output_file(filename: str):
    """Return the content of a generated .feature file."""
    if not filename.endswith(".feature"):
        raise HTTPException(status_code=400, detail="Only .feature files allowed")
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return {"filename": filename, "content": open(path, encoding="utf-8").read()}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_path(path: str) -> str:
    """Resolve a path relative to the project root if not absolute.
    The special value 'manual' is returned as-is (handled by callers directly)."""
    if path.strip().lower() == "manual":
        return "manual"
    if os.path.isabs(path):
        return path
    resolved = str(resolve_user_path(path))
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail=f"CSV file not found: {path}")
    return resolved
