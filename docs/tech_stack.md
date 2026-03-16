# CASForge — Technologies, Languages & Tools

## Language

**Python 3.9+** — entire backend, pipeline, and CLI

---

## Backend / API

| Tool | Version | What it does |
|------|---------|--------------|
| **FastAPI** | 0.100+ | REST API and SSE streaming server |
| **Uvicorn** | — | ASGI web server that runs FastAPI |
| **Pydantic** | v2 | Request/response model validation |

---

## Frontend

| Tool | What it does |
|------|--------------|
| **Plain HTML + CSS + JavaScript** | No framework — single `index.html` + `app.js` + `app.css` |
| **Server-Sent Events (SSE)** | Streams generation progress live to the browser |

No React, Vue, or any JS build step. Open the server and it works.

---

## LLM (Local AI)

| Tool | What it does |
|------|--------------|
| **llama.cpp** | Runs GGUF model files on CPU (no GPU required) |
| **llama-cpp-python** | Python bindings for llama.cpp |
| **Meta Llama 3 8B Instruct Q4** | Default model (GGUF format, ~4.5GB) |
| **Jinja2** | Templates for LLM prompts — `{{ variable }}` syntax, JSON-safe |

The LLM is used for two things only:
1. Extracting testable intents from a JIRA story
2. Picking and pruning the best matching scenario from retrieval candidates

---

## Retrieval

| Tool | What it does |
|------|--------------|
| **FAISS** | Vector similarity search over embedded step texts |
| **sentence-transformers** | Embeds step text into vectors (`all-MiniLM-L6-v2` model) |
| **PostgreSQL full-text search** | Keyword-based step search (tsvector + GIN index) |
| **PostgreSQL pg_trgm** | Trigram fuzzy matching for typos and partial words |

The three channels are combined with weighted scoring:
- Vector (semantic): 50%
- Full-text search (keyword): 30%
- Trigram (fuzzy): 20%

---

## Database

| Tool | What it does |
|------|--------------|
| **PostgreSQL 14+** | Stores all parsed feature files, scenarios, steps, and example data |
| **psycopg2** | Python PostgreSQL adapter |
| **ThreadedConnectionPool** | Reuses DB connections across concurrent requests |

Schema highlights:
- `TSVECTOR` generated columns for FTS
- `GIN` indexes for FTS and trigram search
- `JSONB` for example block rows (flexible column structure)
- Materialized view `unique_steps` for embedding deduplication

---

## Parsing

| Tool | What it does |
|------|--------------|
| **csv (stdlib)** | Reads JIRA CSV exports |
| **re (stdlib)** | Cleans JIRA wiki markup, parses Gherkin |
| **Custom state machine** | Parses `.feature` files including CAS-specific extensions (dictionaries, annotations) |

---

## Configuration

| File | What it controls |
|------|-----------------|
| `.env` | DB credentials, model path, context length, GPU layers, thread count |
| `config/domain_knowledge.json` | LOBs, stages, entities, test families — edit to extend, no code changes |
| `config/planner_hints.json` | Planning term aliases |
| `config/assembler_hints.json` | Assembly term buckets |
| `assets/prompts/*.txt` | Jinja2 LLM prompt templates |
| `assets/templates/*.feature` | Ordered/unordered feature file templates |
| `assets/workflow/order.json` | CAS stage ordering ground truth |

---

## Developer Tools

| Tool | What it does |
|------|--------------|
| **unittest (stdlib)** | Unit and regression tests in `test/` |
| **Windows .bat scripts** | `tools/windows/` — shortcuts for setup, server, ingest, retrieval test |
| **Python CLI scripts** | `tools/cli/` — ingest, index build, generate, validate, benchmark |

---

## Key External Dependencies Summary

```
fastapi          Web API framework
uvicorn          ASGI server
pydantic         Request/response validation
psycopg2-binary  PostgreSQL adapter
llama-cpp-python Local LLM inference
sentence-transformers  Step embedding
faiss-cpu        Vector search
jinja2           Prompt templating
python-dotenv    .env loading
```

Full list: `requirements.txt`
