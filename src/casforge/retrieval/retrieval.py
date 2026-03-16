"""
catalogue/retrieval.py
----------------------
Hybrid step retrieval: three independent channels merged by weighted score.

Channel 1 â€" Vector (semantic, FAISS)
    Model: all-MiniLM-L6-v2 (cosine similarity)
    Weight: 0.50
    Strength: catches semantically identical steps phrased differently

Channel 2 â€" Full-Text Search (PostgreSQL ts_rank_cd)
    Weight: 0.30
    Strength: precise keyword matches with stemming

Channel 3 â€" Trigram fuzzy (PostgreSQL pg_trgm similarity)
    Weight: 0.20
    Strength: partial input, typos, abbreviated keywords

All channels return up to ``top_k`` candidates each.
Scores are min-max normalised per-channel then merged.
The final list is deduplicated by step_id and re-sorted.

Each result includes the matched step AND all steps of its scenario
(i.e. full context, the way IntelliJ shows the whole surrounding scenario).

Public API
----------
search(query, top_k, screen_filter, keyword_filter) -> list[dict]

Each dict in the result list:
    step_id         int
    step_text       str
    keyword         str       Given/When/Then/And/But
    score           float     merged 0â€"1
    screen_context  str|None
    scenario_title  str|None
    file_path       str
    file_name       str
    scenario_steps  list[{keyword, step_text, screen_context}]
"""

import logging
import re
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

from casforge.storage.connection import get_conn, release_conn, get_cursor
from casforge.retrieval.embedder import load_index, search_index
from casforge.workflow.ordering import detect_stage, detect_sub_tags, STAGE_TAGS, SUB_TAGS
from casforge.retrieval.query_expander import (
    expand_for_vector,
    expand_for_fts,
    expand_for_trigram,
    normalise_query_text,
)

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Channel weights
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

_WEIGHTS = {
    "vector":  0.50,
    "fts":     0.30,
    "trigram": 0.20,
}

# Minimum trigram similarity to include (filters noise)
_TRIGRAM_MIN = 0.10

# Score multiplier for auto-detected stage (from query text).
# 1.30 = 30% boost enough to re-rank without completely overriding relevance.
_STAGE_BOOST = 1.30

# Stronger boost when the stage is explicitly supplied by the caller (forge knows
# the story stage from system_process even when the intent text omits it).
_STAGE_HINT_BOOST = 1.60

# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Lazy-loaded FAISS index
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

_faiss_index  = None
_faiss_id_map = None
_vector_disabled_reason: Optional[str] = None


def _get_faiss():
    global _faiss_index, _faiss_id_map
    if _faiss_index is None:
        _faiss_index, _faiss_id_map = load_index()
    return _faiss_index, _faiss_id_map


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Score helpers
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _minmax(scores: list[float]) -> list[float]:
    """Min-max normalise a list of scores to [0, 1]."""
    if not scores:
        return scores
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Channel 1: Vector search
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _channel_vector(query: str, top_k: int, screen_filter: Optional[str]) -> list[tuple[int, float]]:
    """
    Returns [(step_id, raw_cosine_score), ...] sorted descending.
    If screen_filter is given, fetches more candidates and filters post-hoc.
    """
    global _vector_disabled_reason

    if _vector_disabled_reason:
        return []

    try:
        idx, id_map = _get_faiss()
    except Exception as e:
        _vector_disabled_reason = str(e)
        logger.warning("Vector channel unavailable (disabled for this process): %s", e)
        return []

    fetch_k = top_k * 4 if screen_filter else top_k
    try:
        raw = search_index(idx, id_map, query, top_k=fetch_k)
    except Exception as e:
        _vector_disabled_reason = str(e)
        logger.warning("Vector query failed (disabled for this process): %s", e)
        return []

    if not screen_filter:
        return raw[:top_k]

    # Post-filter by screen_context using DB lookup
    ids = [r[0] for r in raw]
    if not ids:
        return []

    conn = get_conn()
    try:
        with get_cursor(conn) as cur:
            cur.execute(
                "SELECT id FROM steps WHERE id = ANY(%s) AND screen_context = %s",
                (ids, screen_filter)
            )
            allowed = {row["id"] for row in cur.fetchall()}
    finally:
        release_conn(conn)

    filtered = [(sid, sc) for sid, sc in raw if sid in allowed]
    return filtered[:top_k]


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Channel 2: Full-text search
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _channel_fts(
    conn,
    query: str,
    top_k: int,
    screen_filter: Optional[str],
    keyword_filter: Optional[str],
) -> list[tuple[int, float]]:
    """
    PostgreSQL full-text search using websearch_to_tsquery.
    Accepts OR-expanded queries like '(delete OR remove) guarantor' so synonym
    variants are treated as alternatives, not required terms.
    Returns [(step_id, rank_score), ...] sorted descending.
    """
    fts_query = expand_for_fts(query)

    extra_where = ""
    fts_params: list = [fts_query]
    if screen_filter:
        extra_where += " AND screen_context = %s"
        fts_params.append(screen_filter)
    if keyword_filter:
        extra_where += " AND keyword = %s"
        fts_params.append(keyword_filter)
    fts_params.append(top_k)

    sql = f"""
        SELECT id,
               ts_rank_cd(step_tsv, websearch_to_tsquery('english', %s)) AS rank
        FROM steps
        WHERE step_tsv @@ websearch_to_tsquery('english', %s)
        {extra_where}
        ORDER BY rank DESC
        LIMIT %s
    """
    # fts_query appears twice: once for rank, once for WHERE
    all_params = [fts_query, fts_query] + fts_params[1:]

    try:
        with get_cursor(conn) as cur:
            cur.execute(sql, all_params)
            rows = cur.fetchall()
        return [(row["id"], float(row["rank"])) for row in rows]
    except Exception as exc:
        conn.rollback()
        logger.warning("FTS channel error: %s", exc)
        return []


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Channel 3: Trigram fuzzy search
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _channel_trigram(
    conn,
    query: str,
    top_k: int,
    screen_filter: Optional[str],
    keyword_filter: Optional[str],
) -> list[tuple[int, float]]:
    """
    PostgreSQL pg_trgm word_similarity search.
    word_similarity(query, step_text) works well for partial input (e.g. "guarant").
    Returns [(step_id, similarity_score), ...] sorted descending.
    """
    # Param order must match SQL placeholders:
    # SELECT word_similarity(%s, step_text)  â†’ query
    # WHERE  word_similarity(%s, step_text)  â†’ query
    #        > %s                            â†’ _TRIGRAM_MIN
    trgm_params: list = [query, query, _TRIGRAM_MIN]
    extra_where = ""
    if screen_filter:
        extra_where += " AND screen_context = %s"
        trgm_params.append(screen_filter)
    if keyword_filter:
        extra_where += " AND keyword = %s"
        trgm_params.append(keyword_filter)
    trgm_params.append(top_k)

    sql = f"""
        SELECT id,
               word_similarity(%s, step_text) AS sim
        FROM steps
        WHERE word_similarity(%s, step_text) > %s
              {extra_where}
        ORDER BY sim DESC
        LIMIT %s
    """

    try:
        with get_cursor(conn) as cur:
            cur.execute(sql, trgm_params)
            rows = cur.fetchall()
        return [(row["id"], float(row["sim"])) for row in rows]
    except Exception as exc:
        conn.rollback()
        logger.warning("Trigram channel error: %s", exc)
        return []


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Score merger
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _merge(
    vector_hits:  list[tuple[int, float]],
    fts_hits:     list[tuple[int, float]],
    trigram_hits: list[tuple[int, float]],
) -> list[tuple[int, float]]:
    """
    Merge three ranked lists into one.
    Each channel is min-max normalised then multiplied by its weight.
    Returns [(step_id, merged_score), ...] sorted descending.
    """
    # Normalise each channel
    def normalise_channel(hits: list[tuple[int, float]], weight: float) -> dict[int, float]:
        if not hits:
            return {}
        raw_scores = [s for _, s in hits]
        normed = _minmax(raw_scores)
        return {sid: normed[i] * weight for i, (sid, _) in enumerate(hits)}

    v_scores = normalise_channel(vector_hits,  _WEIGHTS["vector"])
    f_scores = normalise_channel(fts_hits,     _WEIGHTS["fts"])
    t_scores = normalise_channel(trigram_hits, _WEIGHTS["trigram"])

    all_ids = set(v_scores) | set(f_scores) | set(t_scores)
    merged: dict[int, float] = {}
    for sid in all_ids:
        merged[sid] = (
            v_scores.get(sid, 0.0) +
            f_scores.get(sid, 0.0) +
            t_scores.get(sid, 0.0)
        )

    return sorted(merged.items(), key=lambda x: -x[1])


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Stage + sub-stage detection and boost
# (stage names and annotation tags come from workflow/ordering.py â†’ order.json)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _fetch_tagged_step_ids(conn, tags: list[str], candidate_ids: list[int]) -> set[int]:
    """
    Return the subset of candidate_ids whose scenario/file/example-block
    has at least one annotation matching any of the given @Tags.

    Matching is case-insensitive and uses LIKE so compound annotation strings
    like '@CreditApproval @CommitteeInitiation' still match '@CreditApproval'.
    """
    if not tags or not candidate_ids:
        return set()

    ann_lower = [t.lower() for t in tags]

    with get_cursor(conn) as cur:
        cur.execute(
            """
            SELECT DISTINCT s.id
            FROM steps s
            JOIN scenarios sc ON sc.id = s.scenario_id
            JOIN features   f  ON f.id  = sc.feature_id
            WHERE s.id = ANY(%s)
              AND (
                   EXISTS (
                       SELECT 1 FROM unnest(sc.scenario_annotations) ann
                       WHERE lower(ann) LIKE ANY(
                           SELECT '%%' || a || '%%' FROM unnest(%s::text[]) a
                       )
                   )
                OR EXISTS (
                       SELECT 1 FROM unnest(f.file_annotations) ann
                       WHERE lower(ann) LIKE ANY(
                           SELECT '%%' || a || '%%' FROM unnest(%s::text[]) a
                       )
                   )
                OR EXISTS (
                       SELECT 1 FROM example_blocks eb
                       JOIN unnest(eb.block_annotations) ann ON TRUE
                       WHERE eb.scenario_id = sc.id
                         AND lower(ann) LIKE ANY(
                             SELECT '%%' || a || '%%' FROM unnest(%s::text[]) a
                         )
                   )
              )
            """,
            (candidate_ids, ann_lower, ann_lower, ann_lower)
        )
        return {row["id"] for row in cur.fetchall()}


def _apply_boost(
    merged: list[tuple[int, float]],
    boosted_ids: set[int],
    boost: float,
) -> list[tuple[int, float]]:
    """
    Multiply scores for steps in boosted_ids by boost factor, then re-sort.
    """
    if not boosted_ids:
        return merged
    result = [
        (sid, score * boost if sid in boosted_ids else score)
        for sid, score in merged
    ]
    return sorted(result, key=lambda x: -x[1])


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Context fetch
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def _fetch_context(conn, step_ids: list[int]) -> dict[int, dict]:
    """
    For each step_id, fetch:
      - the step itself (keyword, step_text, screen_context)
      - all steps of the same scenario (in order)
      - scenario title
      - file_path, file_name

    Returns {step_id: context_dict}.
    """
    if not step_ids:
        return {}

    # Step + scenario + feature in one query
    with get_cursor(conn) as cur:
        cur.execute(
            """
            SELECT
                s.id                      AS step_id,
                s.keyword,
                s.step_text,
                s.screen_context,
                sc.id                     AS scenario_id,
                sc.title                  AS scenario_title,
                sc.scenario_annotations,
                sc.scenario_dicts,
                f.file_path,
                f.file_name,
                f.file_annotations,
                f.file_dicts
            FROM steps s
            JOIN scenarios sc ON sc.id = s.scenario_id
            JOIN features   f  ON f.id  = sc.feature_id
            WHERE s.id = ANY(%s)
            """,
            (step_ids,)
        )
        target_rows = {row["step_id"]: dict(row) for row in cur.fetchall()}

    if not target_rows:
        return {}

    # Fetch all steps for the relevant scenarios
    scenario_ids = list({r["scenario_id"] for r in target_rows.values()})
    with get_cursor(conn) as cur:
        cur.execute(
            """
            SELECT scenario_id, keyword, step_text, screen_context, step_position
            FROM steps
            WHERE scenario_id = ANY(%s)
            ORDER BY scenario_id, step_position
            """,
            (scenario_ids,)
        )
        all_steps_rows = cur.fetchall()

    with get_cursor(conn) as cur:
        cur.execute(
            """
            SELECT
                scenario_id,
                block_annotations,
                block_dicts,
                headers,
                rows,
                block_index
            FROM example_blocks
            WHERE scenario_id = ANY(%s)
            ORDER BY scenario_id, block_index
            """,
            (scenario_ids,),
        )
        example_rows = cur.fetchall()

    # Group scenario steps
    scenario_steps: dict[int, list[dict]] = defaultdict(list)
    for row in all_steps_rows:
        scenario_steps[row["scenario_id"]].append({
            "keyword":        row["keyword"],
            "step_text":      row["step_text"],
            "screen_context": row["screen_context"],
        })

    scenario_examples: dict[int, list[dict]] = defaultdict(list)
    for row in example_rows:
        scenario_examples[row["scenario_id"]].append(
            {
                "block_annotations": row.get("block_annotations") or [],
                "block_dicts": row.get("block_dicts") or {},
                "headers": row.get("headers") or [],
                "rows": row.get("rows") or [],
            }
        )

    # Build result
    result = {}
    for step_id, info in target_rows.items():
        scen_id = info["scenario_id"]
        scope_meta = _extract_scope_values(
            file_annotations=info.get("file_annotations") or [],
            scenario_annotations=info.get("scenario_annotations") or [],
            file_dicts=info.get("file_dicts") or {},
            scenario_dicts=info.get("scenario_dicts") or {},
            example_blocks=scenario_examples.get(scen_id, []),
        )
        result[step_id] = {
            "step_id":         step_id,
            "step_text":       info["step_text"],
            "keyword":         info["keyword"],
            "screen_context":  info["screen_context"],
            "scenario_title":  info["scenario_title"],
            "file_path":       info["file_path"],
            "file_name":       info["file_name"],
            "scenario_steps":  scenario_steps.get(scen_id, []),
            "file_annotations": info.get("file_annotations") or [],
            "scenario_annotations": info.get("scenario_annotations") or [],
            "file_dicts": info.get("file_dicts") or {},
            "scenario_dicts": info.get("scenario_dicts") or {},
            "example_blocks": scenario_examples.get(scen_id, []),
            **scope_meta,
        }

    return result


def _extract_scope_values(
    file_annotations: list[str],
    scenario_annotations: list[str],
    file_dicts: dict,
    scenario_dicts: dict,
    example_blocks: list[dict],
) -> dict:
    stage_tag_set = {x.lower() for x in STAGE_TAGS}
    sub_tag_set = {x.lower() for x in SUB_TAGS}
    product_keys = {"producttype", "lob", "lineofbusiness", "loanproduct", "product"}
    stage_keys = {"applicationstage", "stage", "workflowstage", "stagename"}

    all_annotations: list[str] = []
    seen_ann: set[str] = set()

    def _push_ann(values):
        for raw in values or []:
            text = str(raw).strip()
            if not text:
                continue
            k = text.lower()
            if k in seen_ann:
                continue
            seen_ann.add(k)
            all_annotations.append(text)

    _push_ann(file_annotations)
    _push_ann(scenario_annotations)
    for eb in example_blocks:
        _push_ann(eb.get("block_annotations") or [])

    stage_tags = [a for a in all_annotations if a.lower() in stage_tag_set]
    sub_tags = [a for a in all_annotations if a.lower() in sub_tag_set]

    product_values: list[str] = []
    stage_values: list[str] = []
    seen_product: set[str] = set()
    seen_stage: set[str] = set()

    def _push_value(raw_val, target_list: list[str], seen_set: set[str]):
        value = str(raw_val).strip()
        if not value:
            return
        if value.startswith("<") and value.endswith(">"):
            return
        key = value.lower()
        if key in seen_set:
            return
        seen_set.add(key)
        target_list.append(value)

    def _read_dicts(d: dict):
        if not isinstance(d, dict):
            return
        for raw_k, raw_v in d.items():
            k = str(raw_k).strip().lower()
            values = raw_v if isinstance(raw_v, list) else [raw_v]
            if k in product_keys:
                for v in values:
                    _push_value(v, product_values, seen_product)
            elif k in stage_keys:
                for v in values:
                    _push_value(v, stage_values, seen_stage)

    _read_dicts(file_dicts)
    _read_dicts(scenario_dicts)
    for eb in example_blocks:
        _read_dicts(eb.get("block_dicts") or {})
        for row in (eb.get("rows") or []):
            if not isinstance(row, dict):
                continue
            for raw_k, raw_v in row.items():
                k = str(raw_k).strip().lower()
                if k in product_keys:
                    _push_value(raw_v, product_values, seen_product)
                elif k in stage_keys:
                    _push_value(raw_v, stage_values, seen_stage)

    return {
        "scope_annotations": all_annotations,
        "scope_stage_tags": stage_tags,
        "scope_sub_tags": sub_tags,
        "scope_product_types": product_values,
        "scope_application_stages": stage_values,
    }


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Public search function
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

def search(
    query: str,
    top_k: int = 20,
    screen_filter: Optional[str] = None,
    keyword_filter: Optional[str] = None,
    stage_hint: Optional[str] = None,
) -> list[dict]:
    """
    Hybrid step search.

    Args:
        query:          Natural language query or partial step text.
        top_k:          Number of results to return (default 20).
        screen_filter:  Canonical screen name to restrict results to.
                        Use values from SCREEN_NAME_MAP canonical column.
        keyword_filter: Restrict to Given/When/Then/And/But steps only.
        stage_hint:     Plain-text stage name supplied by the caller (e.g. "Recommendation").
                        Used for a stronger boost (1.6x) even when the intent text itself
                        does not contain the stage name.  Detected stage from query text
                        still applies (1.3x), upgraded to 1.6x when they match.

    Returns:
        List of result dicts, each containing:
            step_id, step_text, keyword, score, screen_context,
            scenario_title, file_path, file_name, scenario_steps
        Sorted by descending merged score.

    Notes:
        - If the FAISS index is not built yet, the vector channel is silently
          skipped and only FTS + trigram results are returned.
        - If the DB has no matching steps, an empty list is returned.
        - Never raises -- all channel errors are logged and skipped.
    """
    if not query or not query.strip():
        return []

    query = normalise_query_text(query.strip())

    # Detect stage and sub-stage tags from query using order.json ground truth
    detected_stage    = detect_stage(query)       # e.g. "@Recommendation"
    detected_sub_tags = detect_sub_tags(query)    # e.g. ["@Guarantor"]
    if detected_stage:
        logger.debug("Stage detected: %s  sub-tags: %s", detected_stage, detected_sub_tags)

    # Each channel fetches more than top_k so the merge has more to work with
    fetch_k = top_k * 3

    conn = get_conn()
    try:
        # â"€â"€ Run all three channels â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        # Each channel gets a query variant optimised for its matching strategy.
        vector_hits  = _channel_vector(expand_for_vector(query), fetch_k, screen_filter)
        fts_hits     = _channel_fts(conn, query, fetch_k, screen_filter, keyword_filter)
        trigram_hits = _channel_trigram(conn, expand_for_trigram(query), fetch_k, screen_filter, keyword_filter)

        logger.debug(
            "Channels - vector: %d  fts: %d  trigram: %d",
            len(vector_hits), len(fts_hits), len(trigram_hits)
        )

        # â"€â"€ Merge scores â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        merged = _merge(vector_hits, fts_hits, trigram_hits)

        if not merged:
            return []

        all_candidate_ids = [sid for sid, _ in merged]

        # -- Stage boost -------------------------------------------------------
        # Auto-detected stage (from query text): 1.3x boost.
        # Explicit stage_hint from caller: 1.6x boost (upgraded from 1.3x when
        # hint matches auto-detected; additive when they differ).
        hint_tag: Optional[str] = None
        if stage_hint:
            hint_tag = detect_stage(stage_hint)
            if not hint_tag:
                # stage_hint may already be a @Tag string
                hint_tag = stage_hint if stage_hint.startswith("@") else None

        if detected_stage:
            boost = _STAGE_HINT_BOOST if hint_tag == detected_stage else _STAGE_BOOST
            stage_ids = _fetch_tagged_step_ids(conn, [detected_stage], all_candidate_ids)
            if stage_ids:
                logger.debug("Stage boost (%s) -> %d/%d candidates", detected_stage, len(stage_ids), len(merged))
                merged = _apply_boost(merged, stage_ids, boost)
                all_candidate_ids = [sid for sid, _ in merged]

        if hint_tag and hint_tag != detected_stage:
            # Caller specified a stage not present in the intent text — boost separately
            hint_ids = _fetch_tagged_step_ids(conn, [hint_tag], all_candidate_ids)
            if hint_ids:
                logger.debug("Stage hint boost (%s) -> %d candidates", hint_tag, len(hint_ids))
                merged = _apply_boost(merged, hint_ids, _STAGE_HINT_BOOST)
                all_candidate_ids = [sid for sid, _ in merged]

        # â"€â"€ Sub-stage boost (Guarantor, Primary, etc.) â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        # Additional 15% boost for sub-stage matches (e.g. @Guarantor when
        # query says "guarantor"). Applied on top of stage boost.
        if detected_sub_tags:
            sub_ids = _fetch_tagged_step_ids(conn, detected_sub_tags, all_candidate_ids)
            if sub_ids:
                logger.debug("Sub-tag boost %s â†’ %d candidates", detected_sub_tags, len(sub_ids))
                merged = _apply_boost(merged, sub_ids, 1.15)

        # â"€â"€ Keyword post-filter â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        # The vector channel doesn't support keyword filtering natively.
        # Apply it here as a post-filter on merged results so all three
        # channels honour the keyword_filter parameter consistently.
        if keyword_filter:
            kw_lower = keyword_filter.lower()
            with get_cursor(conn) as cur:
                cur.execute(
                    "SELECT id FROM steps WHERE id = ANY(%s) AND lower(keyword) = %s",
                    ([sid for sid, _ in merged], kw_lower)
                )
                allowed_ids = {row["id"] for row in cur.fetchall()}
            merged = [(sid, sc) for sid, sc in merged if sid in allowed_ids]

        # Take top_k step IDs
        top_ids_with_scores = merged[:top_k]
        top_ids = [sid for sid, _ in top_ids_with_scores]
        score_map = {sid: score for sid, score in top_ids_with_scores}

        # â"€â"€ Fetch context for all top steps â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        context_map = _fetch_context(conn, top_ids)

    finally:
        release_conn(conn)

    # â"€â"€ Assemble and order final results â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
    # Deduplicate by step_text â€" the same step may appear in multiple
    # scenarios (same step_text, different step_id). Keep highest score.
    results = []
    seen_texts: set[str] = set()
    for step_id, merged_score in top_ids_with_scores:
        ctx = context_map.get(step_id)
        if ctx is None:
            continue   # step was deleted between query and context fetch
        txt_lower = ctx["step_text"].lower().strip()
        if txt_lower in seen_texts:
            continue
        seen_texts.add(txt_lower)
        results.append({
            **ctx,
            "score":             round(merged_score, 4),
            "detected_stage":    detected_stage,
            "detected_sub_tags": detected_sub_tags,
        })

    return results


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Quick CLI test
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "committee approval"
    print(f"\nQuery: {query!r}\n")
    results = search(query, top_k=5)
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r['score']:.3f}  {r['keyword']}: {r['step_text'][:80]}")
        print(f"     scenario : {r['scenario_title']}")
        print(f"     screen   : {r['screen_context']}")
        print(f"     file     : {r['file_name']}")
        print(f"     context  : {len(r['scenario_steps'])} steps in scenario")
        print()



