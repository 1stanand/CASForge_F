# CASForge — Next Fixes Needed

Ordered by impact. High priority items affect the quality of every generated file.
Low priority items are polish or nice-to-haves.

---

## High Priority

### 1. Retrieval Quality for New Features

**Problem:** When a brand-new UI feature has no matching scenarios in the corpus,
retrieval returns the nearest related thing — often from the wrong application stage.
This means the LLM picks steps from the wrong context and the output has many
`# [NEW_STEP_NOT_IN_REPO]` markers.

**Why it matters:** This is the core job of CASForge. Frequent wrong-stage hits mean
the tester still has significant manual work.

**Possible approaches:**
- Fine-tune retrieval scoring to weight stage-matching more heavily
  (e.g. penalise results whose `scope_application_stages` does not overlap the story's intent)
- Add stage as a filter parameter to `search()` and let the intent carry a stage hint
- Expand the corpus (ingest more feature files so the index has better coverage)

**Affected files:** `src/casforge/retrieval/retrieval.py`, `src/casforge/generation/forge.py`

---

### 2. Scope Values (`#${}` Lines) for Stories Without Explicit LOB/Stage Text

**Problem:** Stories that reference LOBs implicitly (e.g. the summary says
"Recommendation screen changes" without listing `HL`, `PL`) produce empty
`#${ProductType:[]}` and `#${ApplicationStage:[]}` lines.

**Current workaround:** Tester fills these in manually.

**Proper fix:** Try to infer from:
1. `impacted_areas` field in the JIRA story (e.g. "HL, PL, LAP — Recommendation")
2. Intent family + stage hints from the intent list
3. The LOB/stage filters the user selected in the UI before generation

**Affected files:** `src/casforge/generation/forge.py` (`_build_file_header`)

---

## Medium Priority

### 3. Stage Hint Propagation from UI to Retrieval ✅ DONE

**Problem:** The user selects LOBs and stages in the UI before generating, but
those selections are not passed into the retrieval query. The search ignores this
context entirely.

**Fix applied:** `search()` now accepts `stage_hint` param. `forge_feature()` extracts
stage hint from `story.system_process` via `detect_stage()` and passes it to every
`search()` call. Stage-tagged steps matching the hint get a 1.6× boost (vs 1.3× for
auto-detected stage). Query expander `_MAX_WORDS_TO_EXPAND` raised from 3 → 10; added
checkbox/default/readonly synonym groups.

**Affected files:** `src/casforge/retrieval/retrieval.py`, `src/casforge/generation/forge.py`

---

### 4. Structured Logging

**Problem:** All log output goes to stdout as unformatted text. Under concurrent
users it is hard to tell which log line belongs to which request.

**Fix:** Add `request_id` context to each log line using Python's `logging.extra`
or a structured logging library like `structlog`.

**Affected files:** `src/casforge/web/app.py`, any module that uses `_log`

---

### 5. Global State in `app.py`

**Problem:** `_manual_stories` is a plain module-level dict. Under Uvicorn with
multiple workers this state will not be shared.

**Fix (short term):** This is fine for single-worker mode. Add a comment.

**Fix (long term):** Move manual stories to a DB table or Redis if multi-worker
deployment is needed.

**Affected files:** `src/casforge/web/app.py`

---

## Low Priority

### 6. HTML-in-Python Strings in `app.py`

**Problem:** Some error responses are assembled by concatenating HTML strings
in Python. This is fragile and hard to maintain.

**Fix:** Move to Jinja2-rendered error pages or plain JSON error responses
that the frontend renders.

---

### 7. Examples Table Column Matching

**Problem:** The assembler currently uses `example_blocks[0]` from the top
retrieved scenario for Examples data. But those columns might not match the
`<Variable>` placeholders in the pruned steps.

**Current mitigation:** The assembler only uses EB columns that appear in actual
step variables, falling back to `<ColumnName>` placeholders.

**Better fix:** Align the Examples header to the pruned steps first, then fill
values from `example_blocks` where column names match.

**Affected files:** `src/casforge/generation/forge.py` (`_build_examples_table`)

---

### 8. Remove `legacy_intents` Field ✅ DONE

Removed `legacy_intents` from `IntentsResponse`, `GenerateResponse`, `intent_extractor.py`,
and all `app.py` call sites.

---

### 9. Test Coverage for `forge.py` ✅ DONE

Added `test/test_forge_assembly.py` — 22 unit tests for `_parse_gwt_lines`,
`_group_by_scenario`, `_build_examples_table`, and `_build_scenario`. All pass without LLM or DB.

---

## Already Done (for reference)

- DB connection pool fix — `conn.close()` does NOT return to pool in psycopg2; replaced all
  call sites with `release_conn(conn)` which calls `pool.putconn(conn)` correctly. All 35 tests pass.
- Jinja2 templating — fixed silent intent extraction failure
- Scenario-based LLM selection — replaced disconnected step snippet approach
- Then synthesis fallback — stopped silent scenario omission
- Leading `And` → `Given` promotion
- DB connection pool
- `/api/config` endpoint for UI chip clouds
- `/api/story/manual` endpoint
- `#${}` scope filter (story-text-only)
- SSE stream + blocking endpoint code deduplication
- Documentation cleanup (removed ~15 outdated files)
