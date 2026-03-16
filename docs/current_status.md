# CASForge — Current Status

Last updated: 2026-03-16

---

## What Works End-to-End

| Step | Status |
|------|--------|
| Parse JIRA CSV export | Working |
| Extract test intents via LLM | Working — Jinja2 templating fixed the silent failure |
| Hybrid retrieval (FAISS + FTS + Trigram) | Working |
| LLM scenario selection + step pruning | Working |
| Assemble ordered `.feature` file | Working |
| Assemble unordered `.feature` file | Working |
| Grounding check (`# [NEW_STEP_NOT_IN_REPO]`) | Working |
| Examples table from real repo data | Working |
| Web UI — load stories, edit intents, generate | Working |
| Web UI — LOB/Stage chip clouds | Working (populated from `domain_knowledge.json`) |
| Web UI — SSE streaming progress | Working |
| Manual story entry (no CSV) | Working |
| DB connection pool | Working (ThreadedConnectionPool, max 10) |
| CLI generation | Working |

---

## Known Limitations

### 1. New Feature Retrieval Quality

**Issue:** When a story describes a brand-new feature (one that does not yet exist in the ATDD corpus), retrieval pulls scenarios from the nearest related feature. This can result in steps from the wrong application stage (e.g. Credit Approval steps appearing in a Recommendation scenario).

**Symptom:** `# [NEW_STEP_NOT_IN_REPO]` appears on many steps. The synthesised Then assertion appears (`# [SYNTHESIZED_ASSERTION - verify manually]`).

**Impact:** The generated file is still useful as a structural draft but requires more manual review for new features.

**Root cause:** The FAISS corpus only has what has been ingested. It cannot invent steps that do not exist yet.

**Workaround:** The tester replaces the flagged steps with correct ones from the repository. For entirely new UI components, some manual step authoring is unavoidable.

---

### 2. Scope Values in `#${}` Header Lines

**Issue:** For stories that do not explicitly mention LOB codes or stage names in their text, the `#${ProductType:[...]}` and `#${ApplicationStage:[...]}` lines will be empty.

**Current behaviour:** The assembler only trusts scope values that appear in the story's own `summary` and `system_process` text. It does not guess from retrieved scenarios (which caused wrong LOBs to appear previously).

**Workaround:** The tester fills in the `#${}` lines manually after download, or the JIRA author adds explicit LOB/stage references to the story description.

---

### 3. Synthesised Then Assertions

**Issue:** If the LLM produces steps with no `Then` assertion, a fallback assertion is synthesised from the intent text and marked `# [SYNTHESIZED_ASSERTION - verify manually]`.

**When it happens:** When retrieval returns scenarios from the wrong context and the LLM prunes away the Then steps.

**Impact:** Scenario is included rather than silently dropped. The tester knows exactly which assertion needs replacing.

---

## Architecture Changes Made (This Sprint)

These are the significant changes from the last round of work:

| Change | Why |
|--------|-----|
| Jinja2 templating for all LLM prompts | Python `str.format()` broke on JSON `{}` in prompt bodies — caused silent empty intent extraction |
| Scenario-based LLM selection (`forge.py` rewrite) | Old approach showed disconnected step snippets; LLM had no context to pick from |
| DB connection pool (`ThreadedConnectionPool`) | Prevent connection exhaustion under concurrent users |
| `/api/config` endpoint | Wire UI chip clouds to `domain_knowledge.json` instead of hardcoding |
| `/api/story/manual` endpoint | Allow direct story entry without a CSV file |
| `_pipeline_stream()` shared generator | Removed code duplication between blocking and streaming endpoints |
| `#${}` scope filter | Only emit LOBs/stages mentioned in the story text — stopped wrong values from polluting headers |
| Leading `And` → `Given` promotion | Fixed first step appearing as `And` after login steps were stripped |
| Then synthesis fallback | Stopped scenarios being silently dropped when LLM missed the assertion |

---

## File Health

| File | State |
|------|-------|
| `src/casforge/generation/forge.py` | Clean — complete rewrite, scenario-based pipeline |
| `src/casforge/generation/intent_extractor.py` | Clean — Jinja2, normalised families |
| `src/casforge/parsing/jira_parser.py` | Clean |
| `src/casforge/retrieval/retrieval.py` | Clean — no changes needed |
| `src/casforge/storage/connection.py` | Clean — connection pool added |
| `src/casforge/web/app.py` | Clean — new endpoints, shared pipeline stream |
| `assets/prompts/extract_intents.txt` | Clean — Jinja2, expanded rules |
| `assets/prompts/pick_scenario.txt` | Clean — Jinja2, combined pick + prune |
| `config/domain_knowledge.json` | Clean — single source of truth |

---

## Test Coverage

Three test files exist:

| File | Covers |
|------|--------|
| `test_jira_parser_edges.py` | Markup stripping, field extraction |
| `test_llm_output_parsers.py` | Step line parsing, intent JSON parsing |
| `test_retrieval_regression.py` | Retrieval correctness for known queries |

Old test files for the previous assembler/planner architecture have been deleted. There is no test for `forge.py` end-to-end (would require a running LLM and DB).

---

## What Was Deleted

The following files were removed as part of the cleanup:

- `agent/` folder and all contents (old AI agent handoff notes, diagnostics, reports)
- `docs/casforge_problem_statement.md` — replaced by `docs/problem_statement.md`
- `docs/HeyCodex.md` — outdated
- `docs/FrontEnd_Expectations/approach.md` — outdated
- `assets/prompts/forge_scenario.txt` — replaced by `pick_scenario.txt`
- `src/casforge/generation/feature_assembler.py` — replaced by `forge.py`
- `src/casforge/generation/scenario_planner.py` — replaced by `forge.py`
- `src/casforge/generation/heuristic_config.py` — no longer needed
- `src/casforge/generation/story_facts.py` — no longer needed
- `test/test_generation_planning.py` — covered the deleted planner
