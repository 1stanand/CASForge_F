-- =============================================================
-- CASForge — Analytical & Operational Views
-- Run with: psql -U postgres -d CASForge_F -f db/CreateViews.sql
-- =============================================================

-- ─────────────────────────────────────────────────────────────
-- v_steps_full
-- Every step joined with its scenario, feature, and all
-- annotation arrays. The primary query/debug view.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_steps_full AS
SELECT
    st.id                           AS step_id,
    st.keyword,
    st.step_text,
    st.step_position,
    st.screen_context,
    sc.id                           AS scenario_id,
    sc.title                        AS scenario_title,
    sc.is_outline,
    sc.scenario_index,
    sc.scenario_annotations,
    f.id                            AS feature_id,
    f.file_name,
    f.file_path,
    f.feature_title,
    f.file_annotations,
    f.is_order_file,
    f.is_e2e_order,
    f.parse_error,
    f.parsed_at
FROM steps st
JOIN scenarios sc ON sc.id = st.scenario_id
JOIN features  f  ON f.id  = sc.feature_id;


-- ─────────────────────────────────────────────────────────────
-- v_scenario_summary
-- One row per scenario with step count, annotation arrays,
-- example block count, and parent file info.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_scenario_summary AS
SELECT
    sc.id                                   AS scenario_id,
    sc.title                                AS scenario_title,
    sc.is_outline,
    sc.scenario_index,
    sc.scenario_annotations,
    COUNT(DISTINCT st.id)                   AS step_count,
    COUNT(DISTINCT eb.id)                   AS example_block_count,
    f.id                                    AS feature_id,
    f.file_name,
    f.feature_title,
    f.file_annotations,
    f.parse_error
FROM scenarios sc
JOIN features f          ON f.id  = sc.feature_id
LEFT JOIN steps st       ON st.scenario_id = sc.id
LEFT JOIN example_blocks eb ON eb.scenario_id = sc.id
GROUP BY sc.id, sc.title, sc.is_outline, sc.scenario_index,
         sc.scenario_annotations, f.id, f.file_name,
         f.feature_title, f.file_annotations, f.parse_error;


-- ─────────────────────────────────────────────────────────────
-- v_feature_summary
-- One row per feature file with scenario count, step count,
-- and parse status — good for a quick health dashboard.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_feature_summary AS
SELECT
    f.id                        AS feature_id,
    f.file_name,
    f.feature_title,
    f.file_annotations,
    f.is_order_file,
    f.is_e2e_order,
    f.has_conflict,
    f.parse_error,
    f.parsed_at,
    COUNT(DISTINCT sc.id)       AS scenario_count,
    COUNT(DISTINCT st.id)       AS step_count
FROM features f
LEFT JOIN scenarios sc ON sc.feature_id = f.id
LEFT JOIN steps     st ON st.scenario_id = sc.id
GROUP BY f.id, f.file_name, f.feature_title, f.file_annotations,
         f.is_order_file, f.is_e2e_order, f.has_conflict,
         f.parse_error, f.parsed_at;


-- ─────────────────────────────────────────────────────────────
-- v_parse_errors
-- All files that did not parse cleanly.
-- Also catches files with annotation/dict conflicts.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_parse_errors AS
SELECT
    f.id,
    f.file_name,
    f.file_path,
    f.parse_error,
    f.has_conflict,
    f.parsed_at
FROM features f
WHERE f.parse_error IS NOT NULL
   OR f.has_conflict = TRUE
ORDER BY f.parsed_at DESC;


-- ─────────────────────────────────────────────────────────────
-- v_stage_coverage
-- How many scenarios (and steps) exist per CAS stage tag.
-- Unnests block_annotations from example_blocks which is
-- where stage tags (@Recommendation, @DDE etc.) live in CAS.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_stage_coverage AS
SELECT
    ann.tag                                     AS stage_tag,
    COUNT(DISTINCT sc.id)                       AS scenario_count,
    COUNT(DISTINCT st.id)                       AS step_count,
    COUNT(DISTINCT f.id)                        AS feature_count
FROM example_blocks eb
CROSS JOIN LATERAL unnest(eb.block_annotations) AS ann(tag)
JOIN scenarios sc ON sc.id = eb.scenario_id
JOIN features  f  ON f.id  = sc.feature_id
LEFT JOIN steps st ON st.scenario_id = sc.id
WHERE ann.tag LIKE '@%'
GROUP BY ann.tag
ORDER BY scenario_count DESC;


-- ─────────────────────────────────────────────────────────────
-- v_annotation_frequency
-- All unique annotations (file + scenario + block) ranked
-- by how often they appear across the whole corpus.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_annotation_frequency AS
SELECT tag, COUNT(*) AS occurrences, source
FROM (
    -- File-level annotations
    SELECT unnest(file_annotations) AS tag, 'file' AS source
    FROM features

    UNION ALL

    -- Scenario-level annotations
    SELECT unnest(scenario_annotations) AS tag, 'scenario' AS source
    FROM scenarios

    UNION ALL

    -- Block-level annotations (where stage tags live)
    SELECT unnest(block_annotations) AS tag, 'block' AS source
    FROM example_blocks
) combined
WHERE tag LIKE '@%'
GROUP BY tag, source
ORDER BY occurrences DESC;


-- ─────────────────────────────────────────────────────────────
-- v_screen_coverage
-- How many unique steps and scenarios reference each
-- canonical screen name. Shows which screens have the most
-- test coverage.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_screen_coverage AS
SELECT
    COALESCE(st.screen_context, '(no screen context)')  AS screen,
    COUNT(DISTINCT st.id)                               AS step_count,
    COUNT(DISTINCT sc.id)                               AS scenario_count,
    COUNT(DISTINCT f.id)                                AS feature_count
FROM steps st
JOIN scenarios sc ON sc.id = st.scenario_id
JOIN features  f  ON f.id  = sc.feature_id
GROUP BY st.screen_context
ORDER BY step_count DESC;


-- ─────────────────────────────────────────────────────────────
-- v_keyword_distribution
-- Count of steps by keyword (Given/When/Then/And/But).
-- Useful sanity check — healthy feature files have more
-- Then/And than Given.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_keyword_distribution AS
SELECT
    COALESCE(keyword, '(null)') AS keyword,
    COUNT(*)                    AS step_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM steps
GROUP BY keyword
ORDER BY step_count DESC;


-- ─────────────────────────────────────────────────────────────
-- v_duplicate_steps
-- Step texts that appear more than once (case-insensitive).
-- High duplicates are normal in CAS — the same background
-- step is copied into every scenario. Useful to verify
-- unique_steps materialised view coverage.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_duplicate_steps AS
SELECT
    lower(trim(step_text))  AS normalised_text,
    COUNT(*)                AS occurrences,
    MIN(id)                 AS first_step_id
FROM steps
GROUP BY lower(trim(step_text))
HAVING COUNT(*) > 1
ORDER BY occurrences DESC;


-- ─────────────────────────────────────────────────────────────
-- Quick sanity query (not a view — run manually if needed):
--
--   SELECT * FROM v_feature_summary   ORDER BY step_count DESC LIMIT 20;
--   SELECT * FROM v_stage_coverage    ORDER BY scenario_count DESC;
--   SELECT * FROM v_screen_coverage   ORDER BY step_count DESC LIMIT 30;
--   SELECT * FROM v_parse_errors;
--   SELECT * FROM v_keyword_distribution;
--   SELECT * FROM v_annotation_frequency LIMIT 40;
-- ─────────────────────────────────────────────────────────────
