# CASForge — Code Manual

This is a file-by-file reference. Read it when you need to know where something lives,
what a file is responsible for, and what you should and should not change in it.

---

## Directory Layout

```
src/casforge/
  parsing/        Reading input (JIRA CSV, .feature files)
  generation/     LLM calls, intent extraction, feature assembly
  retrieval/      FAISS + PostgreSQL hybrid search
  storage/        Database connection, schema
  workflow/       Stage ordering rules
  shared/         Settings, paths, utility functions
  web/            FastAPI REST API + UI serving

config/           JSON configuration (edit freely, no code changes)
assets/
  prompts/        LLM prompt templates (.txt, Jinja2 syntax)
  templates/      Feature file structural templates (.feature)
  workflow/       Stage order ground truth (order.json)
tools/
  cli/            Python entrypoints for CLI use
  windows/        .bat shortcuts for Windows
test/             Unit + regression tests
workspace/
  reference_repo/ Local mirror of the ATDD feature corpus
  samples/        Sample JIRA CSV files
  generated/      Output .feature files + intermediate JSON
  index/          FAISS index files
```

---

## `src/casforge/parsing/`

### `jira_parser.py`

**Responsibility:** Reads a JIRA CSV export and returns a list of `JiraStory` objects.

**What it does:**
- Strips JIRA wiki markup (`{code}`, `{noformat}`, `[text|url]`, `h1.`, etc.)
- Maps CSV column headers to structured fields
- Populates the `JiraStory` dataclass:

```python
@dataclass
class JiraStory:
    issue_key: str
    summary: str
    description: str
    system_process: str          # the "System Process" field from JIRA
    acceptance_criteria: str
    business_scenarios: str
    impacted_areas: str
    key_ui_steps: str
    story_description: str       # fallback description field
```

**When to edit:** When JIRA column names change, or a new field needs to be extracted.

---

### `feature_parser.py`

**Responsibility:** Parses `.feature` files from the ATDD corpus into structured Python objects.

**What it does:**
- Handles standard Gherkin (Feature, Scenario Outline, Given/When/Then/And)
- Also handles CAS-specific extensions: `#${...}` dictionary lines, `@Tag` annotations
- Stores results into PostgreSQL tables: `features`, `scenarios`, `steps`, `example_blocks`

**When to edit:** When the ATDD corpus uses a new non-standard Gherkin extension that the parser does not recognise.

---

## `src/casforge/generation/`

### `intent_extractor.py`

**Responsibility:** Calls the LLM with a JIRA story and returns a list of test intents.

**Key function:** `extract_intents(story) -> list[dict]`

Each intent dict has:
```python
{ "id": "intent_001", "text": "Verify decision checkbox unchecked by default", "family": "default_state" }
```

**How it works:**
1. Loads `assets/prompts/extract_intents.txt` (Jinja2 template)
2. Renders the template with story fields
3. Calls `llm_client.chat()`
4. Parses the JSON array from the LLM response
5. Normalises family names, deduplicates near-identical intents

**Important:** The prompt template uses `{{ variable }}` syntax (Jinja2), not `{variable}` (Python format strings). This is intentional — Jinja2 is safe against JSON braces in the prompt body.

**When to edit:** If intent quality is poor, edit `assets/prompts/extract_intents.txt` instead of this file.

---

### `forge.py`

**Responsibility:** The main generation pipeline. Takes a story + list of intents → returns a `.feature` file as a string.

**Key function:** `forge_feature(story, intents, flow_type, on_progress=None) -> ForgeResult`

**Two phases:**

**Phase A — Retrieval + LLM (per intent):**
1. `search(intent_text, top_k=20)` — hybrid FAISS+FTS+trigram retrieval
2. Gate: skip only if no results or all scores < 0.25
3. `_group_by_scenario()` — group step results into top 5 unique parent scenarios
4. `_llm_pick_and_prune()` — single LLM call: pick best scenario + output pruned steps
5. Fallback: if LLM returns no `Then` step, synthesise one from intent text (marked for manual review)

**Phase B — Assembly (no LLM):**
1. `_build_file_header()` — tags, `#${}` scope lines, Background (unordered) or business context block (ordered)
2. `_build_scenario()` — scenario outline title, steps, grounding check
3. `_build_examples_table()` — Examples block from retrieved data + `<Variable>` scan

**Return value — `ForgeResult`:**
```python
@dataclass
class ForgeResult:
    feature_text: str            # the complete .feature file content
    quality: dict                # scenario_count, grounded_steps, unresolved_steps
    unresolved_steps: list       # steps marked [NEW_STEP_NOT_IN_REPO]
    omitted_plan_items: list     # intents that produced no scenario
    scenarios_json_path: str     # path to intermediate JSON file
```

**When to edit:**
- Change assembly logic → edit this file
- Change LLM pick/prune behaviour → edit `assets/prompts/pick_scenario.txt`

---

### `llm_client.py`

**Responsibility:** Thin wrapper around `llama-cpp-python`. Loads the model once and exposes `chat()`.

**Key function:** `chat(system_prompt, user_prompt, temperature, max_tokens) -> str`

**When to edit:** If switching to a different LLM backend (e.g. Ollama, OpenAI). The rest of the codebase only calls `llm_client.chat()`.

---

## `src/casforge/retrieval/`

### `retrieval.py`

**Responsibility:** Hybrid search over the step corpus.

**Key function:** `search(query, top_k=20) -> list[dict]`

Each result dict:
```python
{
    "step_text": str,
    "keyword": str,                  # Given/When/Then
    "scenario_title": str,
    "file_name": str,
    "scenario_steps": list[dict],    # ALL steps of the parent scenario
    "example_blocks": list[dict],    # real Examples table with data
    "scope_product_types": list,
    "scope_application_stages": list,
    "score": float,                  # merged 0–1 score
}
```

**Three channels (run in parallel, scores merged):**
- **Vector (FAISS)** — weight 50%. Semantic similarity via `all-MiniLM-L6-v2` embeddings.
- **Full-text search (PostgreSQL)** — weight 30%. Exact keyword matching via `tsvector`.
- **Trigram (pg_trgm)** — weight 20%. Fuzzy matching for typos and abbreviations.

**When to edit:** Change retrieval weights, add a new search channel, or tune result count.

---

### `embedder.py`

**Responsibility:** Embeds step texts into vectors using `sentence-transformers`.

**Key function:** `build_index()` — reads all unique steps from DB, embeds them, saves FAISS index.

Called once during ingest. Not called during generation (FAISS index is loaded from disk).

---

### `query_expander.py`

**Responsibility:** Expands a search query by looking up entity aliases and domain terms from `domain_knowledge.json` before sending to retrieval.

**When to edit:** If query expansion is missing important aliases.

---

## `src/casforge/storage/`

### `connection.py`

**Responsibility:** PostgreSQL connection pool.

**Key functions:**
- `get_conn()` — gets a connection from the pool (ThreadedConnectionPool, max 10)
- `get_cursor(conn)` — context manager that returns a DictCursor and handles commit/rollback
- `conn.close()` — returns connection to pool (does not actually close the TCP connection)

**When to edit:** If you need to change pool size or add connection retry logic.

---

## `src/casforge/web/`

### `app.py`

**Responsibility:** FastAPI application. All REST endpoints live here.

**Key endpoints:**

| Method | Path | What it does |
|--------|------|-------------|
| `GET` | `/` | Serves `index.html` |
| `GET` | `/api/config` | Returns LOBs, stages, families from `domain_knowledge.json` |
| `POST` | `/api/stories` | Parses a JIRA CSV and returns story list |
| `GET` | `/api/story/{key}` | Returns one parsed story |
| `POST` | `/api/story/manual` | Accepts a manually typed story (no CSV) |
| `POST` | `/api/intents` | Calls `extract_intents()`, returns intent list |
| `POST` | `/api/generate` | Full generation, returns complete result (blocking) |
| `GET` | `/api/generate/stream` | Same generation, streams progress events via SSE |
| `GET` | `/api/download/{key}` | Downloads the generated `.feature` file |

**Important internals:**
- `_pipeline_stream(req, csv_path)` — shared generator used by both `/api/generate` and `/api/generate/stream`
- `_manual_stories: dict` — in-memory store for stories entered via `/api/story/manual`

**When to edit:** To add endpoints, change request/response shapes, or adjust SSE streaming.

---

### `models.py`

**Responsibility:** Pydantic request/response models for the API.

**When to edit:** When adding or changing API fields.

---

## `src/casforge/shared/`

### `settings.py`

Reads `.env` and exposes typed settings:
- `LLM_MODEL_PATH`, `LLM_CONTEXT_LENGTH`, `LLM_GPU_LAYERS`, `LLM_NUM_THREADS`
- `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`
- `DB_*` connection parameters
- `FEATURES_REPO_PATH`, `OUTPUT_DIR`

### `paths.py`

Single source of truth for all directory paths used across modules:
- `PROMPTS_DIR`, `TEMPLATES_DIR`, `CONFIG_DIR`, `OUTPUT_DIR`, `INDEX_DIR`

### `normalisation.py`

Text normalisation helpers (lowercase, strip punctuation) shared across parsing and retrieval.

---

## `assets/prompts/`

LLM prompt files. **All use Jinja2 syntax** (`{{ variable }}`).

| File | Used by | What it controls |
|------|---------|-----------------|
| `extract_intents.txt` | `intent_extractor.py` | How the LLM reads a JIRA story and outputs test intents |
| `pick_scenario.txt` | `forge.py` | How the LLM picks the best scenario and prunes its steps |

**Format of each file:**
```
SYSTEM:
... system instructions ...

USER:
... Jinja2 template with {{ variables }} ...
```

**To improve LLM output quality, edit these files, not the Python code.**

---

## `assets/templates/`

Structural templates for the generated `.feature` file.

| File | When used |
|------|-----------|
| `ordered.feature` | `flow_type == "ordered"` — E2E journeys |
| `unordered.feature` | `flow_type == "unordered"` — independent feature tests |

The assembler reads the `@Tag` lines from these templates and fills in the real story key and author values. The `#${...}` dictionary lines are also taken from here.

---

## `config/`

| File | What it controls |
|------|-----------------|
| `domain_knowledge.json` | LOBs, stages, entities, families — see `docs/domain_knowledge_guide.md` |
| `planner_hints.json` | Aliases for planning terms (internal use) |
| `assembler_hints.json` | Term buckets for assembly (internal use) |

---

## `test/`

| File | What it tests |
|------|--------------|
| `test_jira_parser_edges.py` | JIRA wiki markup stripping, field extraction |
| `test_llm_output_parsers.py` | `_parse_gwt_lines()`, intent JSON parsing |
| `test_retrieval_regression.py` | Retrieval returns expected steps for known queries |

Run all tests: `python -m unittest discover -s test -v`
