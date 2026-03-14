# CASForge â€” Database Schema

**Database**: `CASForge_F`
**Engine**: PostgreSQL with `pg_trgm` extension
**Schema file**: `src/casforge/storage/schema.sql`
**Views file**: `src/casforge/storage/CreateViews.sql`

---

## Tables

### `features` â€” one row per `.feature` file

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | Auto-increment |
| `file_path` | TEXT UNIQUE | Absolute path â€” deduplication key for incremental parsing |
| `file_name` | TEXT | Basename only (e.g. `DDE_Guarantor.feature`) |
| `feature_title` | TEXT | Text after `Feature:` keyword |
| `file_annotations` | TEXT[] | `@tags` found in file header (before first Scenario) |
| `file_dicts` | JSONB | `#${Key=[...]}` dicts found in file header |
| `is_order_file` | BOOLEAN | File carries `@Order` annotation |
| `is_e2e_order` | BOOLEAN | File carries `@E2EOrder` annotation |
| `has_conflict` | BOOLEAN | Both `@Order` and dict entries in same file (invalid) |
| `parse_error` | TEXT | NULL = clean parse; any text = parser error message |
| `file_mtime` | DOUBLE PRECISION | `os.path.getmtime()` at parse time â€” used for incremental |
| `parsed_at` | TIMESTAMP | When this row was inserted |

---

### `scenarios` â€” one row per Scenario or Scenario Outline

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | |
| `feature_id` | INT FK â†’ features | Cascade delete |
| `title` | TEXT | Scenario title (or `__background__` for Background blocks) |
| `is_outline` | BOOLEAN | True if `Scenario Outline:` |
| `scenario_annotations` | TEXT[] | `@tags` on the scenario block |
| `scenario_dicts` | JSONB | `#${Key=[...]}` dicts on the scenario |
| `scenario_index` | INT | 0-based order within file |

---

### `example_blocks` â€” one row per `Examples:` block

Only populated for Scenario Outlines.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | |
| `scenario_id` | INT FK â†’ scenarios | Cascade delete |
| `block_annotations` | TEXT[] | **Stage tags live here** (e.g. `@Recommendation`, `@DDE`) |
| `block_dicts` | JSONB | Dict entries on the Examples block |
| `headers` | TEXT[] | Column names from the first `|` row |
| `rows` | JSONB | Array of `{col: val}` objects, one per data row |
| `block_index` | INT | 0-based order within scenario |

> **Important**: In CAS feature files, stage annotations (`@Recommendation`, `@CreditApproval`, etc.)
> are placed on `Examples:` blocks, NOT on the Scenario itself. Always check `block_annotations`
> when querying for stage coverage.

---

### `steps` â€” the core retrieval unit

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | |
| `scenario_id` | INT FK â†’ scenarios | Cascade delete |
| `keyword` | VARCHAR(10) | `Given` / `When` / `Then` / `And` / `But` |
| `step_text` | TEXT | Full step text (without keyword) |
| `step_position` | INT | 0-based position within scenario |
| `screen_context` | TEXT | Canonical screen name inferred from navigation steps (NULL if unknown) |
| `step_tsv` | TSVECTOR GENERATED | Auto-maintained FTS vector â€” `to_tsvector('english', step_text)` |

---

## Materialised View

### `unique_steps` â€” deduplicated steps for embedding

```sql
SELECT DISTINCT ON (lower(trim(step_text)))
    id, step_text, screen_context
FROM steps
ORDER BY lower(trim(step_text)), id;
```

- One row per unique step text (case-insensitive, trimmed)
- Used by `tools/cli/build_index.py` to build the FAISS vector index
- Refresh after ingest: `REFRESH MATERIALIZED VIEW CONCURRENTLY unique_steps;`

---

## Indexes

| Index | Table | Type | Purpose |
|---|---|---|---|
| `idx_steps_tsv` | steps | GIN | Full-text search channel |
| `idx_steps_trgm` | steps | GIN (gin_trgm_ops) | Trigram fuzzy channel |
| `idx_steps_scenario` | steps | btree | FK join |
| `idx_steps_screen` | steps | btree | Screen context filter |
| `idx_steps_keyword` | steps | btree | Keyword filter (Given/When/Then) |
| `idx_scenarios_feature` | scenarios | btree | FK join |
| `idx_examples_scenario` | example_blocks | btree | FK join + annotation lookup |
| `idx_unique_steps_id` | unique_steps | UNIQUE btree | FAISS ID mapping |
| `idx_unique_steps_trgm` | unique_steps | GIN (gin_trgm_ops) | Fuzzy on unique texts |

---

## Analytical Views (from `src/casforge/storage/CreateViews.sql`)

| View | Description |
|---|---|
| `v_steps_full` | Every step with full scenario + feature context â€” main debug view |
| `v_scenario_summary` | Scenarios with step count, block count, annotation arrays |
| `v_feature_summary` | Files with scenario count, step count, parse status |
| `v_parse_errors` | Files that failed parsing or have annotation conflicts |
| `v_stage_coverage` | Step/scenario count per CAS stage tag (from block_annotations) |
| `v_annotation_frequency` | All annotations ranked by occurrence count and source |
| `v_screen_coverage` | Step/scenario count per canonical screen name |
| `v_keyword_distribution` | Count and % of Given/When/Then/And/But |
| `v_duplicate_steps` | Step texts that appear more than once |

---

## Cascade Delete Chain

Deleting a `features` row cascades down through the entire tree:

```
features â†’ scenarios â†’ example_blocks
                     â†’ steps
```

This is used by incremental parsing: when a file changes, its `features` row is deleted
(which removes all scenarios, examples, and steps), then the file is re-parsed and
re-inserted fresh.

---

## Connection Config

All connection details live in `.env` and are read through `config/settings.py`:

```
DB_NAME=CASForge_F
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432
```

Never hardcode connection strings â€” always import from `config.settings`.

---

## Useful Queries

```sql
-- Overall counts
SELECT
    (SELECT COUNT(*) FROM features)       AS files,
    (SELECT COUNT(*) FROM scenarios)      AS scenarios,
    (SELECT COUNT(*) FROM example_blocks) AS example_blocks,
    (SELECT COUNT(*) FROM steps)          AS steps,
    (SELECT COUNT(*) FROM unique_steps)   AS unique_steps;

-- Files with parse errors
SELECT * FROM v_parse_errors;

-- Top 20 stages by scenario count
SELECT * FROM v_stage_coverage LIMIT 20;

-- Screen coverage
SELECT * FROM v_screen_coverage LIMIT 30;

-- Step keyword breakdown
SELECT * FROM v_keyword_distribution;

-- Find all steps for a specific scenario
SELECT keyword, step_text FROM v_steps_full
WHERE scenario_title ILIKE '%guarantor%'
ORDER BY scenario_id, step_position;
```



