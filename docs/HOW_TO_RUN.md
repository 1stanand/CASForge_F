# CASForge - How To Run

Run every command from the repository root: `D:\CAS_FORGE_FINAL - Copy`

## 1. Canonical Structure

```text
src/casforge/               runtime code
  web/                      FastAPI app + UI serving
  generation/               intent planning + feature assembly
  retrieval/                retrieval + embeddings
  parsing/                  jira + gherkin parsing
  workflow/                 order/stage rules
  storage/                  DB helpers + schema
  shared/                   settings + path helpers

tools/cli/                  canonical Python CLI entrypoints
tools/windows/              canonical Windows bat entrypoints
assets/templates/           ordered/unordered feature templates
assets/prompts/             LLM prompt files
assets/workflow/            order.json and workflow assets
workspace/reference_repo/   local ATDD corpus mirror
workspace/samples/          sample JIRA inputs
workspace/generated/        generated .feature outputs
workspace/index/            FAISS index artifacts
```

## 2. Compatibility Wrappers

The new canonical entrypoints live in `tools/cli/` and `tools/windows/`.
The old entrypoints still work through thin wrappers:

- `bat\*.bat` delegates to `tools\windows\*.bat`
- `scripts\*.py` delegates to `tools\cli\*.py`
- `api\app.py` re-exports `casforge.web.app`

Use the canonical paths in new docs and automation. Keep the wrapper paths only for backward compatibility.

## 3. Important Paths

- Feature corpus default: `workspace\reference_repo\Features`
- Sample JIRA files: `workspace\samples\sampleJira\`
- Ordered/unordered templates: `assets\templates\`
- Prompt files: `assets\prompts\`
- Workflow order file: `assets\workflow\order.json`
- Default generated output: `workspace\generated\output`
- Preserved legacy-style output folders:
  - `workspace\generated\output_final`
  - `workspace\generated\output_ordered`
  - `workspace\generated\output_unordered`
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

Canonical:

```powershell
python setup.py
```

Wrapper:

```powershell
bat\setup.bat
```

This will:
1. Test PostgreSQL connectivity
2. Create `CASForge_F` if needed
3. Apply `src\casforge\storage\schema.sql`
4. Ingest feature files
5. Build the FAISS index

## 5. Day-to-Day Ingest And Index

### Incremental ingest

Canonical:

```powershell
python tools/cli/ingest.py
python tools/cli/build_index.py
```

Wrappers:

```powershell
bat\ingest_incremental.bat
```

### Full rebuild

Canonical:

```powershell
python tools/cli/ingest.py --full-rebuild
python tools/cli/build_index.py
```

Wrappers:

```powershell
bat\ingest_full_rebuild.bat
```

## 6. Start The Web UI / API

Wrapper:

```powershell
bat\start_server.bat
```

Canonical:

```powershell
python -m uvicorn casforge.web.app:app --host 0.0.0.0 --port 8000 --reload
```

Then open: `http://localhost:8000`

UI flow:
1. Enter a CSV path from `workspace\samples\sampleJira\...` or your own export
2. Load stories
3. Extract intents
4. Review/edit intents and scope
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

Wrapper-compatible legacy commands still work too:

```powershell
python scripts/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv --story CAS-256008 --flow-type unordered
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

Wrapper:

```powershell
bat\test_retrieval.bat
```

Canonical:

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

**`ModuleNotFoundError` on old wrapper commands**
Run commands from the repository root. The wrappers assume the repo root is the working directory.
