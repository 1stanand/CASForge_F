# CASForge — Pipeline Overview

How all the files connect, end to end.

---

## The Two Pipelines

CASForge has two separate flows that run at different times.

---

## Pipeline 1 — Ingestion (run once, or after repo updates)

This reads your existing test repository and stores everything in a database + vector index.

```
ATDD Repository (.feature files)
        │
        ▼
feature_parser.py          Parses each file into features / scenarios / steps / example blocks
        │
        ▼
PostgreSQL Database         Stores: features, scenarios, steps, example_blocks tables
        │                          + unique_steps materialized view (deduped step texts)
        ▼
embedder.py                Embeds each unique step text into a vector (all-MiniLM-L6-v2)
        │
        ▼
FAISS Index                Vector similarity index stored in workspace/index/
```

**Run this with:**
```
tools\windows\ingest_full_rebuild.bat   (first time or full refresh)
tools\windows\ingest_incremental.bat    (after adding new .feature files)
```

---

## Pipeline 2 — Generation (runs every time you use the tool)

This takes a JIRA story and produces a `.feature` file draft.

```
JIRA CSV Export
        │
        ▼
jira_parser.py             Cleans JIRA wiki markup, extracts:
  (JiraStory dataclass)      summary, system_process, description,
                             acceptance_criteria, business_scenarios,
                             impacted_areas, key_ui_steps
        │
        ▼
intent_extractor.py        Calls LLM (Llama 3 8B) with extract_intents.txt prompt
  Phase A                    → Returns list of test intents
  (LLM via Jinja2)           Example: "Display decision checkbox for each sub loan at Recommendation"
                             Each intent has: id, text, family (positive/negative/validation/etc.)
        │
        │  ← User reviews & edits intents in UI here →
        │
        ▼
forge.py — Phase A          For EACH intent:
  (Retrieval + LLM)
        │
        ├─ search()          Hybrid retrieval: vector (50%) + FTS (30%) + trigram (20%)
        │    retrieval.py    Returns top 20 steps with full parent scenario context
        │
        ├─ _group_by_scenario()   Groups step results into top 5 unique parent scenarios
        │
        └─ _llm_pick_and_prune()  Calls LLM with pick_scenario.txt prompt
                                  LLM picks the best matching scenario,
                                  prunes steps to fit the specific intent,
                                  outputs only Given/When/Then lines

        │
        ▼
Intermediate JSON            workspace/generated/output/{key}_scenarios.json
  (_save_scenarios_json)      Saved after LLM phase, before assembly
                              Contains: pruned steps, source scenario, example_blocks

        │
        ▼
forge.py — Phase B           Assembly (deterministic, no LLM)
  (Assembly)
        │
        ├─ _build_file_header()   Tags (@Epic-CAS, @AuthoredBy, @CAS-XXXXX)
        │    reads: assets/templates/ordered.feature or unordered.feature
        │    + Background block (unordered) or business context (ordered)
        │    + #${ProductType:[...]} #${ApplicationStage:[...]} dict lines
        │
        ├─ _build_scenario()      For each intent:
        │    - Scenario Outline title
        │    - Steps with # [NEW_STEP_NOT_IN_REPO] markers for ungrounded steps
        │    - Examples table
        │
        └─ _build_examples_table() Scans step text for <Variable> placeholders
                                   Builds | Header | rows | table

        │
        ▼
.feature file                workspace/generated/output/{key}.feature
```

---

## Key Files — Where Each Responsibility Lives

| What you want to change | File to edit |
|------------------------|-------------|
| How JIRA stories are parsed | `src/casforge/parsing/jira_parser.py` |
| What intents the LLM extracts | `assets/prompts/extract_intents.txt` |
| How retrieval search works | `src/casforge/retrieval/retrieval.py` |
| Which scenario the LLM picks | `assets/prompts/pick_scenario.txt` |
| The full forge pipeline | `src/casforge/generation/forge.py` |
| Feature file structure/tags | `assets/templates/ordered.feature` / `unordered.feature` |
| LOB chips, stage chips, families | `config/domain_knowledge.json` |
| Web API endpoints | `src/casforge/web/app.py` |
| DB schema | `src/casforge/storage/schema.sql` |
| Settings / environment | `.env` |

---

## Ordered vs Unordered Flow

The user selects this before generating.

| | Ordered | Unordered |
|-|---------|-----------|
| Tag | `@Order` | — |
| Background | None | `Given user is on CAS Login Page` |
| First step per scenario | `Given all prerequisite are performed...` | Normal Given |
| Scenario titles | `Step 1 — Verify ...` | `Verify ...` |
| Use case | E2E journeys (LogicalID flows) | Independent feature validations |

---

## Retrieval — How It Finds Steps

Three channels run in parallel and scores are merged:

1. **Vector (FAISS)** — Semantic similarity. "decision checkbox" finds steps about checkboxes even if exact words differ.
2. **Full-text search (PostgreSQL)** — Keyword precision. Finds steps that contain the exact terms.
3. **Trigram (pg_trgm)** — Fuzzy matching. Handles typos, partial words, abbreviations.

Each retrieved result includes:
- The matching step text + keyword
- The **full parent scenario** (all steps, not just the matching one)
- The **Examples block** from that scenario (real test data values)
- Scope metadata (which LOBs and stages that scenario covers)

This is why the LLM can pick a whole scenario — it sees the complete picture, not isolated steps.

---

## Grounding Check

After assembly, every step is checked against the 15,000+ steps in the database.

- If the step exists verbatim → no marker
- If the step does not exist → `  # [NEW_STEP_NOT_IN_REPO]`

Steps marked this way are also listed in `quality.unresolved_steps` in the API response and shown in the UI. The tester knows exactly what needs manual attention.
