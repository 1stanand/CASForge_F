-- =============================================================
-- CASForge â€” Step Catalogue Schema
-- Run with: psql -U postgres -d CASForge_F -f src/casforge/storage/schema.sql
-- =============================================================

-- Enable trigram extension for fuzzy search (pg_trgm)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Drop in FK-safe order
DROP MATERIALIZED VIEW IF EXISTS unique_steps;
DROP TABLE IF EXISTS steps          CASCADE;
DROP TABLE IF EXISTS example_blocks CASCADE;
DROP TABLE IF EXISTS scenarios      CASCADE;
DROP TABLE IF EXISTS features       CASCADE;

-- =============================================================
-- FEATURES â€” one row per .feature file
-- =============================================================
CREATE TABLE features (
    id                  SERIAL          PRIMARY KEY,
    file_path           TEXT            NOT NULL UNIQUE,   -- absolute path (dedup key)
    file_name           TEXT            NOT NULL,           -- basename
    feature_title       TEXT,                               -- text after "Feature:"
    file_annotations    TEXT[]          NOT NULL DEFAULT '{}',
    file_dicts          JSONB           NOT NULL DEFAULT '{}',
    is_order_file       BOOLEAN         NOT NULL DEFAULT FALSE,   -- has @Order
    is_e2e_order        BOOLEAN         NOT NULL DEFAULT FALSE,   -- has @E2EOrder
    has_conflict        BOOLEAN         NOT NULL DEFAULT FALSE,   -- @Order + dicts (invalid combo)
    parse_error         TEXT,                               -- NULL = clean parse
    file_mtime          DOUBLE PRECISION,                   -- os.path.getmtime for incremental
    parsed_at           TIMESTAMP       NOT NULL DEFAULT NOW()
);

-- =============================================================
-- SCENARIOS â€” one row per Scenario / Scenario Outline
-- =============================================================
CREATE TABLE scenarios (
    id                   SERIAL   PRIMARY KEY,
    feature_id           INT      NOT NULL REFERENCES features(id) ON DELETE CASCADE,
    title                TEXT,
    is_outline           BOOLEAN  NOT NULL DEFAULT FALSE,
    scenario_annotations TEXT[]   NOT NULL DEFAULT '{}',
    scenario_dicts       JSONB    NOT NULL DEFAULT '{}',
    scenario_index       INT      NOT NULL DEFAULT 0    -- order within file (0-based)
);

CREATE INDEX idx_scenarios_feature ON scenarios(feature_id);

-- =============================================================
-- EXAMPLE BLOCKS â€” one row per Examples: block inside a Scenario Outline
-- =============================================================
CREATE TABLE example_blocks (
    id                  SERIAL   PRIMARY KEY,
    scenario_id         INT      NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    block_annotations   TEXT[]   NOT NULL DEFAULT '{}',
    block_dicts         JSONB    NOT NULL DEFAULT '{}',
    headers             TEXT[]   NOT NULL DEFAULT '{}',
    rows                JSONB    NOT NULL DEFAULT '[]',   -- [{col: val, ...}, ...]
    block_index         INT      NOT NULL DEFAULT 0       -- order within scenario (0-based)
);

CREATE INDEX idx_examples_scenario ON example_blocks(scenario_id);

-- =============================================================
-- STEPS â€” the core retrieval unit
-- =============================================================
CREATE TABLE steps (
    id              SERIAL      PRIMARY KEY,
    scenario_id     INT         NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    keyword         VARCHAR(10),                           -- Given/When/Then/And/But
    step_text       TEXT        NOT NULL,
    step_position   INT         NOT NULL DEFAULT 0,        -- 0-based within scenario
    screen_context  TEXT,                                  -- canonical screen name or NULL
    -- Full-text search vector (auto-maintained)
    step_tsv        TSVECTOR    GENERATED ALWAYS AS (
                        to_tsvector('english', step_text)
                    ) STORED
);

-- Indexes for all three retrieval channels
CREATE INDEX idx_steps_tsv      ON steps USING GIN(step_tsv);                     -- FTS
CREATE INDEX idx_steps_trgm     ON steps USING GIN(step_text gin_trgm_ops);       -- trigram
CREATE INDEX idx_steps_scenario ON steps(scenario_id);
CREATE INDEX idx_steps_screen   ON steps(screen_context);
CREATE INDEX idx_steps_keyword  ON steps(keyword);

-- =============================================================
-- UNIQUE_STEPS â€” deduplicated step texts for embedding
-- Refresh with: REFRESH MATERIALIZED VIEW CONCURRENTLY unique_steps;
-- =============================================================
CREATE MATERIALIZED VIEW unique_steps AS
    SELECT DISTINCT ON (lower(trim(step_text)))
        id,
        step_text,
        screen_context
    FROM steps
    ORDER BY lower(trim(step_text)), id;

CREATE UNIQUE INDEX idx_unique_steps_id   ON unique_steps(id);
CREATE INDEX        idx_unique_steps_trgm ON unique_steps
    USING GIN(step_text gin_trgm_ops);

