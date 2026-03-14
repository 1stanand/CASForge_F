# Code Manual

## Purpose
This document maps the current codebase by responsibility. It reflects the current implementation, not the older pre-reorg layout.

## End-to-End Runtime Flow
1. A CSV path is selected in the UI or CLI.
2. `src/casforge/parsing/jira_parser.py` loads one story and cleans JIRA markup.
3. `src/casforge/generation/story_facts.py` derives structured facts from the story.
4. `src/casforge/generation/scenario_planner.py` turns those facts into structured plan items.
5. `src/casforge/generation/intent_extractor.py` exposes those plan items as UI/API-friendly intents.
6. `src/casforge/generation/feature_assembler.py` consumes the structured intents, finds repo anchors through retrieval, builds scenario plans, renders a feature file, and runs a grounding pass.
7. `src/casforge/web/app.py` or `tools/cli/generate_feature.py` returns / writes the feature.

## Repository Layout

### Runtime package: `src/casforge/`
This is the canonical implementation layer.

#### `src/casforge/shared/`
- `paths.py`
  - Central filesystem anchors.
  - Defines project root, assets, workspace, templates, samples, outputs, index, and storage SQL paths.
- `settings.py`
  - Single environment/config source.
  - Loads `.env` and exposes DB, model, output, repo-path, and index settings.
- `normalisation.py`
  - Large lookup tables for canonical screen names, LOB aliases, stage aliases, and keyword normalization.
  - Used by parser and screen-context inference.

#### `src/casforge/storage/`
- `connection.py`
  - Psycopg2 connection and cursor helpers.
  - SQL runner used by setup and schema flows.
- `schema.sql`
  - Core DB schema for features, scenarios, steps, and example blocks.
- `CreateViews.sql`
  - SQL views / materialized-view support for retrieval.

#### `src/casforge/parsing/`
- `jira_parser.py`
  - Loads JIRA CSV rows into `JiraStory` objects.
  - Cleans JIRA wiki markup and splits current/new process blocks.
- `feature_parser.py`
  - Parses repository `.feature` files into structured feature/scenario/step/example-block dicts.
  - Handles repo-specific extensions like dictionaries and file/scenario/example annotations.
- `screen_context.py`
  - Infers `screen_context` for parsed steps by detecting navigation anchors.

#### `src/casforge/workflow/`
- `ordering.py`
  - Loads `assets/workflow/order.json`.
  - Detects stage tags and sub-tags from free text.
  - Used by retrieval boosting and feature tag rendering.

#### `src/casforge/retrieval/`
- `query_expander.py`
  - Normalizes noisy user queries and expands short queries with synonym terms.
- `embedder.py`
  - Builds and loads the FAISS vector index over unique step texts.
- `retrieval.py`
  - Main hybrid retrieval engine.
  - Runs vector, FTS, and trigram channels.
  - Applies stage / sub-tag boosts.
  - Returns step hits with scenario context and extracted scope metadata.

#### `src/casforge/generation/`
- `llm_client.py`
  - Thin lazy singleton wrapper over `llama_cpp`.
  - Used only where the current pipeline still relies on model output.
- `story_facts.py`
  - Converts a `JiraStory` into structured facts:
    - scope defaults
    - entities
    - rules
    - coverage signals
    - matrix signals
  - Uses heuristic-first extraction, with LLM overlay only when heuristics are not strong enough.
- `scenario_planner.py`
  - Converts story facts into structured plan items.
  - Adds section metadata, expected outcome, polarity, must-anchor terms, must-assert terms, and matrix signatures.
- `intent_extractor.py`
  - Public structured-intent layer used by API and CLI.
  - Handles backward compatibility with legacy list-of-strings intent payloads.
- `feature_assembler.py`
  - Current generation core.
  - Responsibilities currently include:
    - effective-scope handling
    - anchor selection and ranking
    - scenario-level grouping
    - assertion retrieval
    - fallback/scaffold handling
    - template rendering
    - grounding and unresolved-step marking

#### `src/casforge/web/`
- `models.py`
  - Pydantic request/response models for stories, intents, generation, search, upload, and output files.
- `app.py`
  - FastAPI app.
  - Serves the frontend and all current API endpoints.
- `frontend/index.html`
  - Main static HTML shell for the current UI.
- `frontend/app.js`
  - Full client-side orchestration.
  - Handles CSV upload, story loading, intent editing, per-intent scope remap, generation streaming, artifact rendering.
- `frontend/app.css`
  - Styling for the current UI.
- `frontend_legacy.html`
  - Legacy frontend artifact. Not part of the mounted runtime path.

## CLI and Wrapper Layer

### Canonical CLI: `tools/cli/`
- `generate_feature.py`
  - Primary CLI for one-story or all-story feature generation.
- `ingest.py`
  - Parses repo `.feature` files into PostgreSQL.
  - Refreshes `unique_steps` materialized view.
- `build_index.py`
  - Builds the FAISS index from DB rows.
- `test_retrieval.py`
  - Interactive retrieval REPL.
- `evaluate_retrieval.py`
  - Regression benchmark for retrieval quality.
- `smoke_small_chunks.py`
  - Fast component-level generation sanity checks.
- `validate_generated_features.py`
  - Structural and grounding validation for generated feature files.
- `sitecustomize.py`
  - Ensures project root and `src/` are importable in CLI runs.

### Compatibility wrappers
- `scripts/*.py`
  - Thin wrappers forwarding to `tools/cli/*`.
- `api/app.py`, `api/models.py`
  - Thin compatibility imports for the old API paths.
- `bat/*.bat` and `tools/windows/*.bat`
  - Windows wrappers for setup, ingest, server start, retrieval test, and generation.
- `setup.py`
  - One-command bootstrap for DB creation, schema apply, ingest, and index build.
- `sitecustomize.py`
  - Root import-path helper.

## Frontend/API Contract

### Main API endpoints in `src/casforge/web/app.py`
- `GET /`
  - serves `frontend/index.html`
- `POST /api/upload-csv`
  - stores uploaded CSV text into workspace samples
- `GET /api/stories`
  - lists stories from a CSV
- `GET /api/story/{key}`
  - returns parsed story details
- `POST /api/intents`
  - returns structured intents and inferred story scope defaults
- `POST /api/generate`
  - synchronous feature generation
- `POST /api/generate/stream`
  - streaming feature generation over SSE
- `POST /api/search`
  - retrieval search endpoint
- `GET /api/output`
  - lists generated feature files
- `GET /api/output/{filename}`
  - returns one generated feature file

### UI state in `app.js`
Main state buckets:
- CSV / story selection
- story scope defaults
- current intents
- flow type
- artifact text and quality
- unresolved steps
- modal state

### Important UI behaviors
- Flow type is explicit and user-selected.
- Story scope can be auto/inferred or manually overridden.
- Intent scope can inherit story scope or override it per intent.
- Generation uses the streaming endpoint and updates the artifact view on the `feature` event.

## Ingestion / Retrieval Data Flow
1. `tools/cli/ingest.py` finds all `.feature` files in the configured repo path.
2. `feature_parser.py` parses each file.
3. Parsed data is inserted into `features`, `scenarios`, `steps`, and `example_blocks` tables.
4. `unique_steps` materialized view is refreshed.
5. `tools/cli/build_index.py` loads `unique_steps` and calls `embedder.build_index()`.
6. `retrieval.py` uses the DB plus FAISS index at runtime.

## Test Map
- `test/test_jira_parser_edges.py`
  - JIRA cleanup and tiny CSV sanity
- `test/test_llm_output_parsers.py`
  - output parser and output-format cleanup helpers
- `test/test_retrieval_regression.py`
  - retrieval regression suite
- `test/test_generation_planning.py`
  - planner, story facts, and retrieval-first assembler unit cases
- `tools/cli/smoke_small_chunks.py`
  - fast end-to-end-lite sanity checks
- `tools/cli/evaluate_retrieval.py`
  - retrieval benchmark gate
- `tools/cli/validate_generated_features.py`
  - generated feature structural validation gate

## Assets and Data
- `assets/prompts/`
  - current LLM prompts for story facts and legacy intent assembly support
- `assets/templates/`
  - ordered/unordered feature templates
- `assets/workflow/order.json`
  - stage and sub-tag ordering ground truth
- `workspace/samples/`
  - sample CSV inputs and uploads
- `workspace/generated/`
  - generated feature outputs
- `workspace/index/`
  - FAISS artifacts
- `workspace/scratch/`
  - ad hoc query and prompt scratch files

## Current Reality of the Generation Stack
- Retrieval is hybrid and repository-driven.
- Story understanding is partially model-assisted, but planning is deterministic.
- Final feature assembly is mostly deterministic, but still includes fallback generation and a post-render grounding pass.
- The main accuracy-sensitive code is concentrated in `feature_assembler.py`.

## Files to Read First in a New Session
1. `src/casforge/web/app.py`
2. `src/casforge/generation/story_facts.py`
3. `src/casforge/generation/scenario_planner.py`
4. `src/casforge/generation/intent_extractor.py`
5. `src/casforge/generation/feature_assembler.py`
6. `src/casforge/retrieval/retrieval.py`
7. `test/test_generation_planning.py`
8. `tools/cli/smoke_small_chunks.py`
9. `agent/CodeReviewRepor.md`
10. `agent/NextSteps.md`
