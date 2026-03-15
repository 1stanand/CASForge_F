# CASForge Pipeline Overview

## End-to-End Runtime Flow

1. CSV path is selected in UI or CLI
2. `src/casforge/parsing/jira_parser.py` loads one story and cleans JIRA markup
3. `src/casforge/generation/story_facts.py` derives structured facts from the story
4. `src/casforge/generation/scenario_planner.py` turns those facts into structured plan items
5. `src/casforge/generation/intent_extractor.py` exposes those plan items as UI/API-friendly intents
6. `src/casforge/generation/feature_assembler.py` consumes structured intents, finds repo anchors through retrieval, builds scenario plans, renders a feature file, and runs a grounding pass
7. `src/casforge/web/app.py` or `tools/cli/generate_feature.py` returns / writes the feature

## Ingestion / Retrieval Flow

1. `tools/cli/ingest.py` finds all `.feature` files in the configured repo path
2. `feature_parser.py` parses each file
3. Parsed data is inserted into `features`, `scenarios`, `steps`, and `example_blocks` tables
4. `unique_steps` materialized view is refreshed
5. `tools/cli/build_index.py` loads `unique_steps` and calls `embedder.build_index()`
6. `retrieval.py` uses the DB plus FAISS index at runtime

## Current Reality

- retrieval is hybrid and repository-driven
- story understanding is partially model-assisted
- planning is deterministic
- final assembly is mostly deterministic, but still includes fallback generation and a post-render grounding pass
- the main accuracy-sensitive code is concentrated in `feature_assembler.py`
