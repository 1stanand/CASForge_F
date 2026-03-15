# CASForge

CASForge is a conservative, repo-faithful ATDD feature composer for CAS JIRA stories.

It is not a generic Gherkin writer. The goal is to generate `.feature` files that stay close to how the existing CAS repository is authored, while surfacing uncertainty honestly instead of inventing business behavior.

## What CASForge Does

CASForge takes a JIRA CSV export plus a local mirror of the CAS ATDD repository and produces generated feature files using a retrieval-first pipeline:

1. Parse a JIRA story into structured fields.
2. Extract normalized story facts.
3. Build deterministic scenario plan items.
4. Retrieve relevant repo scenarios and steps.
5. Assemble a feature conservatively.
6. Mark unresolved steps as `NEW_STEP_NOT_IN_REPO` instead of silently replacing them with weak guesses.

## What CASForge Is Not

CASForge is not designed to:

- maximize scenario count at any cost
- rewrite business logic creatively
- hide uncertainty behind polished-looking Gherkin
- replace retrieval with freeform LLM generation
- treat one sample story as the business model for all future stories

The intended quality bar is:

- fewer correct scenarios is better than more wrong scenarios
- visible gaps are better than fabricated coverage
- repo-authentic chains are better than pretty but invented steps

## Current Philosophy

The system is intentionally built around:

- deterministic planning
- retrieval-first grounding
- conservative confidence gates
- explicit coverage gaps

This is important because the main failure mode in this domain is not syntax. It is semantic drift:

- wrong stage
- wrong screen
- wrong polarity
- wrong assertion
- wrong scenario family

CASForge tries to reduce those errors, even if that means omitting some scenarios.

## High-Level Pipeline

### 1. JIRA parsing

Relevant code:
- [jira_parser.py](./src/casforge/parsing/jira_parser.py)

The parser reads JIRA CSV exports and extracts story fields such as:

- summary
- description
- system processes
- business scenarios
- acceptance criteria
- story description
- filtered supplemental comments / final-approach style comments

`System processes` is already a primary source of truth in this repo.

Filtered comment-style fields are also important in many real orgs because implementation notes or final approach details are often written there. CASForge now keeps those notes as supplemental context instead of ignoring them completely.

### 2. Story fact extraction

Relevant code:
- [story_facts.py](./src/casforge/generation/story_facts.py)

This module converts messy Jira prose into a normalized fact model:

- entities
- business rules
- coverage signals
- matrix signals
- default scope

This is one of the most important modules in the pipeline. If story facts are weak or overfit, planning and assembly degrade quickly.

### 3. Deterministic planning

Relevant code:
- [scenario_planner.py](./src/casforge/generation/scenario_planner.py)
- [intent_extractor.py](./src/casforge/generation/intent_extractor.py)

Planning turns story facts into short, retrieval-friendly scenario intents with:

- family
- target
- expected outcome
- anchor terms
- assert terms
- section metadata

The planner is designed to keep intents narrow and composable.

### 4. Retrieval and assembly

Relevant code:
- [feature_assembler.py](./src/casforge/generation/feature_assembler.py)
- [retrieval](./src/casforge/retrieval)

The assembler searches the repo, ranks scenario anchors, reuses coherent step chains, and renders the final feature.

Important behavior:

- weak fallback scenario generation is restricted
- post-render step replacement is restricted
- unresolved steps stay visible as `NEW_STEP_NOT_IN_REPO`
- low-confidence items become `coverage_gaps` / `omitted_plan_items`

## Repository Layout

```text
src/casforge/
  generation/        story facts, intent extraction, planning, assembly
  parsing/           JIRA + Gherkin parsing
  retrieval/         embeddings, index, search
  storage/           PostgreSQL schema and helpers
  workflow/          ordering and stage rules
  web/               FastAPI app + UI
  shared/            settings and path helpers

config/              JSON configuration — edit here to extend CASForge
  domain_knowledge.json    LOBs, stages, entities, families (single source of truth)
  planner_hints.json       planner target aliases + synthetic templates
  assembler_hints.json     assembler term buckets + specificity hints

tools/
  cli/               Python CLI entrypoints
  windows/           Windows .bat entrypoints

assets/
  prompts/           LLM prompt files (.txt)
  templates/         feature file templates
  workflow/          order.json (read-only ATDD toolchain input)

workspace/
  reference_repo/    local mirror of CAS ATDD feature corpus
  samples/           sample JIRA exports
  generated/         generated output folders such as run1 / run2
  index/             FAISS artifacts

agent/
  diagnostics/       ongoing change and accuracy tracking
  reports/           analysis reports and tracked quality runs
  claude/            Claude AI session patches
  gemini/            Gemini review inputs/outputs
```

## Config Ownership

Generation configuration is split by ownership:

- `assets/workflow/order.json`
  - read-only ATDD/workflow input, not owned by CASForge
- `config/*.json`
  - CASForge-owned configuration for domain knowledge and generation hints
  - add new LOBs, stages, entities, or hint terms here — no code changes required
  - **not** a place for sample-JIRA rescue logic or hardcoded scenario outputs

If a future change only makes one narrow sample story pass, it should not be added as hidden business logic.

## Important Files

Core generation files:

- [story_facts.py](./src/casforge/generation/story_facts.py)
- [scenario_planner.py](./src/casforge/generation/scenario_planner.py)
- [intent_extractor.py](./src/casforge/generation/intent_extractor.py)
- [feature_assembler.py](./src/casforge/generation/feature_assembler.py)

Operational and tracking files:

- [HOW_TO_RUN.md](./docs/HOW_TO_RUN.md)
- [AGENT_OPERATING_RULES.md](./agent/AGENT_OPERATING_RULES.md)
- [gemini_root_cause_review.md](./agent/reports/gemini_root_cause_review.md)
- [codex_change_log.md](./agent/diagnostics/codex_change_log.md)
- [codex_patch_summary.md](./agent/diagnostics/codex_patch_summary.md)
- [accuracy_tracker.md](./agent/diagnostics/accuracy_tracker.md)
- [accuracy_progress.md](./agent/reports/accuracychecks/accuracy_progress.md)

## Setup

### Requirements

- Python
- PostgreSQL
- local CAS feature repository mirror
- local LLM model path if using the LLM-assisted parts

Python packages:

- `psycopg2-binary`
- `python-dotenv`
- `sentence-transformers`
- `faiss-cpu`
- `numpy`
- `llama-cpp-python`
- `fastapi`
- `uvicorn[standard]`

Install:

```powershell
pip install -r requirements.txt
```

### Environment

Configure `.env` with DB settings and local paths.

Important values include:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `FEATURES_REPO_PATH`
- `LLM_MODEL_PATH`

### Initial setup

```powershell
python setup.py
```

This will:

1. verify PostgreSQL connectivity
2. create the DB if needed
3. apply schema
4. ingest features
5. build the FAISS index

## Running CASForge

### Start the web app

```powershell
python -m uvicorn casforge.web.app:app --host 0.0.0.0 --port 8000 --reload
```

Or use the wrapper:

```powershell
bat\start_server.bat
```

### Generate a feature from CLI

Single story:

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --flow-type unordered
```

Intents only:

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --intents-only
```

Custom output folder:

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --flow-type ordered --output workspace/generated/custom
```

## Validation and Regression Gates

Unit tests:

```powershell
python -m unittest discover -s test -v
```

Fast smoke:

```powershell
python tools/cli/smoke_small_chunks.py
```

Retrieval benchmark:

```powershell
python tools/cli/evaluate_retrieval.py --threshold 85
```

Validate generated features:

```powershell
python tools/cli/validate_generated_features.py --dir workspace/generated/run1
```

## Output Conventions

Generated outputs should be grouped incrementally:

- `workspace/generated/run1`
- `workspace/generated/run2`
- `workspace/generated/run3`

This keeps generated files from polluting the workspace and makes it easier to compare quality across tuning cycles.

Accuracy tracking lives in:

- [accuracy_tracker.md](./agent/diagnostics/accuracy_tracker.md)
- [accuracy_progress.md](./agent/reports/accuracychecks/accuracy_progress.md)

## How To Judge Quality

Do not judge success only by “feature generated”.

Quality should be reviewed across:

1. scope correctness
2. stage correctness
3. domain / screen correctness
4. polarity correctness
5. scenario family correctness
6. assertion relevance
7. repo-authentic step chain quality
8. amount of unresolved / invented behavior
9. usefulness of surfaced coverage gaps

## Current Known Limitations

This repo is still under active tuning. The most important current limitations are:

- `story_facts.py` still uses domain heuristics and can become brittle
- some stories are under-specified unless `System processes` or comments carry the real business detail
- `feature_assembler.py` still contains complex anchor-selection heuristics
- generation quality is mixed across hard stories
- some improvements increase precision by omitting weak scenarios rather than increasing scenario count

Read the current analysis here:

- [gemini_root_cause_review.md](./agent/reports/gemini_root_cause_review.md)
- [accuracy_tracker.md](./agent/diagnostics/accuracy_tracker.md)

## Rules For Future Contributors

If you tune CASForge, keep these rules in mind:

1. Do not redesign around more freeform LLM generation unless there is a strong reason.
2. Do not change retrieval, ingestion, embeddings, or schema casually.
3. Prefer dropping ambiguous facts over extracting weak ones.
4. Prefer omitting weak scenarios over inventing them.
5. Preserve `coverage_gaps`, `omitted_plan_items`, and `NEW_STEP_NOT_IN_REPO`.
6. Avoid overfitting to a sample Jira story just to satisfy tests.
7. Validate changes on real sample generation, not only unit tests.

## Practical Note On Story Inputs

In many orgs, the real implementation detail is not in the Jira description.

It is often spread across:

- `System processes`
- `Story Description`
- `Acceptance Criteria`
- review comments
- assignee comments
- comments from bank / nucleus
- final-approach notes in comments

CASForge should be tuned with that reality in mind.

If a story has only a weak user-story sentence but strong `System processes` or useful final-approach comments, those sources should carry more weight than the generic description.

## Next Reading

If you are new to the repo, read these next:

1. [docs/HOW_TO_RUN.md](./docs/HOW_TO_RUN.md)
2. [agent/AGENT_OPERATING_RULES.md](./agent/AGENT_OPERATING_RULES.md)
3. [agent/reports/gemini_root_cause_review.md](./agent/reports/gemini_root_cause_review.md)
4. [agent/diagnostics/accuracy_tracker.md](./agent/diagnostics/accuracy_tracker.md)
