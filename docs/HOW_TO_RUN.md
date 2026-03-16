# CASForge - How To Run

Run every command from the repository root: `D:\CASForge_F`

## 1. Project Structure

```text
src/casforge/           runtime Python source
  web/                  FastAPI app + UI serving
  generation/           intent planning + feature assembly
  retrieval/            retrieval + embeddings
  parsing/              jira + gherkin parsing
  workflow/             order/stage rules
  storage/              DB helpers + schema
  shared/               settings + path helpers

config/                 JSON configuration files (edit to extend)
  domain_knowledge.json LOBs, stages, entities, families — single source of truth
  planner_hints.json    planner target aliases + synthetic templates
  assembler_hints.json  assembler term buckets + specificity hints

assets/
  prompts/              LLM prompt files (.txt)
  templates/            ordered/unordered feature templates (.feature)
  workflow/             order.json (read-only ATDD toolchain input)

tools/
  cli/                  Python CLI entrypoints
  windows/              Windows .bat entrypoints

test/                   Unit tests
docs/                   Documentation
workspace/
  reference_repo/       local ATDD corpus mirror
  samples/              sample JIRA inputs
  generated/            generated .feature outputs
  index/                FAISS index artifacts

casforge/               import stub (redirects to src/casforge/)
```

## 2. Adding New LOBs or Stages

Edit `config/domain_knowledge.json` — no code changes needed:

```json
// Add a new LOB:
{ "canonical": "MY_LOB", "phrases": ["my lob name", "my lob"] }

// Add a new stage:
{ "canonical": "My Stage", "aliases": ["my stage"] }
```

The UI dropdowns and intent extraction pick up changes automatically on next server start.

## 3. Important Paths

- Feature corpus default: `workspace\reference_repo\Features`
- Sample JIRA files: `workspace\samples\sampleJira\`
- Ordered/unordered templates: `assets\templates\`
- Prompt files: `assets\prompts\`
- Workflow order file: `assets\workflow\order.json`
- Generation config: `config\` (domain_knowledge.json, planner_hints.json, assembler_hints.json)
- Default generated output: `workspace\generated\output`
- Default FAISS index location: `workspace\index`

## 4. First-Time Setup

### Install dependencies

```powershell
pip install -r requirements.txt
```

Notes:
- Internet is required for the first install.
- The embedding model (`all-MiniLM-L6-v2`) is downloaded once and then cached locally.

### Configure `.env`

Set the DB values for your machine.
Set `LLM_MODEL_PATH` before running intent extraction or feature generation.

`FEATURES_REPO_PATH` is now optional if you want to use the local workspace mirror at `workspace\reference_repo\Features`.
If you want to ingest from another repository checkout, point `FEATURES_REPO_PATH` to that external Features root.

### Setup database + ingest + index

```powershell
python setup.py
```

Or via bat:

```powershell
tools\windows\setup.bat
```

This will:
1. Test PostgreSQL connectivity
2. Create `CASForge_F` if needed
3. Apply `src\casforge\storage\schema.sql`
4. Ingest feature files
5. Build the FAISS index

## 5. Day-to-Day Ingest And Index

### Incremental ingest

```powershell
python tools/cli/ingest.py
python tools/cli/build_index.py
```

Or via bat:

```powershell
tools\windows\ingest_incremental.bat
```

### Full rebuild

```powershell
python tools/cli/ingest.py --full-rebuild
python tools/cli/build_index.py
```

Or via bat:

```powershell
tools\windows\ingest_full_rebuild.bat
```

## 6. Start The Web UI / API

```powershell
tools\windows\start_server.bat
```

Or directly:

```powershell
python -m uvicorn casforge.web.app:app --host 0.0.0.0 --port 8000 --reload
```

Then open: `http://localhost:8000`

UI flow:
1. Enter a CSV path from `workspace\samples\sampleJira\...` or upload your own
2. Load stories
3. Extract intents
4. Review/edit intents and scope (LOB / Stage dropdowns populated from `config\domain_knowledge.json`)
5. Generate the feature file
6. Review/download the output

## 7. CLI Feature Generation

### Intents only

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --intents-only
```

### Single story

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --flow-type unordered
```

### All stories in one CSV

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --all --flow-type ordered
```

### Custom output directory

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --flow-type ordered --output workspace/generated/custom
```

Generated files are written to `workspace\generated\output` by default unless `OUTPUT_DIR` or `--output` overrides it.

## 8. Validation And Regression Checks

### Unit tests

```powershell
python -m unittest discover -s test -v
```

### Fast smoke gates

```powershell
python tools/cli/smoke_small_chunks.py
python tools/cli/smoke_small_chunks.py --with-llm
```

### Retrieval accuracy benchmark

```powershell
python tools/cli/evaluate_retrieval.py --threshold 85
```

### Generated feature validation

```powershell
python tools/cli/validate_generated_features.py --dir workspace/generated/output
```

## 9. Interactive Retrieval Tester

```powershell
tools\windows\test_retrieval.bat
```

Or directly:

```powershell
python tools/cli/test_retrieval.py
```

Useful commands inside the REPL:
- `<any text>` search for matching steps
- `:top 10` show more results
- `:screen Committee` filter by screen
- `:keyword Then` filter by step keyword
- `:clear` clear filters
- `:context off` hide surrounding steps
- `:q` exit

## 10. Quick DB Check

```powershell
python -c "from casforge.storage.connection import get_conn, get_cursor; conn = get_conn();
with get_cursor(conn) as cur:
    cur.execute('SELECT COUNT(*) AS n FROM features'); print('Files:       ', cur.fetchone()['n'])
    cur.execute('SELECT COUNT(*) AS n FROM scenarios'); print('Scenarios:   ', cur.fetchone()['n'])
    cur.execute('SELECT COUNT(*) AS n FROM steps'); print('Steps:       ', cur.fetchone()['n'])
    cur.execute('SELECT COUNT(*) AS n FROM unique_steps'); print('Unique steps:', cur.fetchone()['n'])
conn.close()"
```

## 11. Troubleshooting

**`FileNotFoundError: FAISS index not found`**
Run `python tools/cli/build_index.py` after ingest.

**`No steps found in DB`**
Run incremental ingest first. Check `FEATURES_REPO_PATH` in `.env` if you are using an external repo instead of the workspace mirror.

**`Cannot connect to PostgreSQL`**
Check `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` in `.env`.

**LLM not loading**
Check `LLM_MODEL_PATH` in `.env` and make sure it points to an absolute `.gguf` file.

**Generation is very slow on 8 GB RAM**
Close other heavy apps, reduce `LLM_CONTEXT_LENGTH`, lower `LLM_NUM_THREADS`, or offload layers with `LLM_GPU_LAYERS` if you have a GPU.

**`ModuleNotFoundError: No module named 'casforge'`**
Run commands from the repository root (`D:\CASForge_F`). The `casforge/` stub at root redirects imports to `src/casforge/`.
