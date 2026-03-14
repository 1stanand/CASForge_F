# CASForge â€” Retrieval Architecture

## Overview

CASForge uses **hybrid 3-channel retrieval** to find the best-matching Gherkin steps from the
~161k-step PostgreSQL catalogue. No single retrieval method is sufficient:

| Method alone | Failure mode |
|---|---|
| Vector only | Misses exact keyword matches; "guarantor" â‰  "applicant" semantically, but "guarantor" is in the text |
| FTS only | Misses paraphrased steps ("remove" vs "delete", "see" vs "visible") |
| Trigram only | Correct fragment matches but poor ranking for full-sentence queries |

Combining all three with weighted scoring gives the best of each.

---

## Three Retrieval Channels

### Channel 1 â€” Vector (Semantic, weight 50%)

- **Model**: `all-MiniLM-L6-v2` (384-dim, CPU, ~80 MB)
- **Index**: FAISS `IndexFlatIP` on L2-normalised vectors â†’ cosine similarity
- **Stored in**: `workspace/index/faiss_index.bin` + `workspace/index/step_id_map.npy`
- **Retrieves**: Top 50 step IDs + cosine scores (0â€“1)
- **Strength**: Catches semantically equivalent steps phrased differently
  - "committee should display" â†” "committee screen is shown"
  - "user fills in address" â†” "user enters address information"
- **Query input**: `expand_for_vector(query)` â€” synonym words appended for short queries

### Channel 2 â€” Full-Text Search (FTS, weight 30%)

- **Engine**: PostgreSQL `websearch_to_tsquery('english', query)`
- **Index**: GIN index on generated `step_tsv TSVECTOR` column
- **Scoring**: `ts_rank_cd(step_tsv, query_tsv)`
- **Retrieves**: Top 50 step IDs + ts_rank scores
- **Strength**: Exact keyword matches with English stemming (`saving` = `save` = `saved`)
- **Query input**: OR-expanded query for short queries
  - `"Delete Guarantor"` â†’ `(delete OR remove OR removes OR deleted) Guarantor`

### Channel 3 â€” Trigram Fuzzy (weight 20%)

- **Engine**: PostgreSQL `pg_trgm` extension, `word_similarity(query, step_text)`
- **Index**: GIN index on `step_text` with `gin_trgm_ops`
- **Threshold**: `word_similarity > 0.1` (catches partial matches)
- **Retrieves**: Top 50 step IDs + similarity scores (0â€“1)
- **Strength**: Partial matches, abbreviations, minor typos
  - `"guarant"` â†’ `"guarantor"`
  - `"DDE appli"` â†’ `"DDE application"`
- **Query input**: `expand_for_trigram(query)` â€” same as vector expansion

---

## Score Merging

Each channel returns up to 50 hits. Steps can appear in multiple channels.

```
weights = { vector: 0.50, fts: 0.30, trigram: 0.20 }

for each channel:
    min-max normalise scores within that channel's results â†’ [0, 1]
    multiply by channel weight
    accumulate into per-step score dict

sort by accumulated score descending
return top_k
```

Min-max normalisation ensures no channel dominates due to raw score scale differences
(ts_rank can be 0.001â€“2.0; cosine is 0â€“1; trigram is 0â€“1).

---

## Query Expansion (short queries only)

Applied when query word count â‰¤ 3.

**Vector / Trigram expansion** â€” synonym words appended:
```
"Delete Guarantor"  â†’  "Delete Guarantor remove removes deleted"
```

**FTS expansion** â€” OR groups for `websearch_to_tsquery`:
```
"Delete Guarantor"  â†’  "(delete OR remove OR removes OR deleted) Guarantor"
```

Synonym groups cover 12 action categories:
delete/remove, visible/present, reject/decline, add/create, submit/save,
approve/sanction, edit/update, open/navigate, verify/validate,
pick/select, initiate/start, pending/wait.

Only â‰¤3-word queries are expanded because longer queries already have enough context â€”
expansion on a 6-word query dilutes precision.

---

## Post-Merge Boosts

After score merging, two optional score multipliers are applied based on CAS workflow semantics.

### Stage Boost (Ã—1.30)

When the query contains a known CAS stage name (from `order.json`), steps whose scenarios
carry that stage annotation are boosted.

Detection: `src/casforge/workflow/ordering.py` â†’ `detect_stage(query)` â€” longest-match regex over
all stage tags (e.g. `@CreditApproval`, `@Recommendation`, `@Disbursal`).

Annotation lookup: checks `example_blocks.block_annotations` (primary),
`scenarios.scenario_annotations`, `features.file_annotations`, and
`scenarios.title LIKE '%<stage>%'`.

**Critical detail**: In CAS feature files, stage annotations appear in
`Examples:` blocks (`block_annotations`), not on the Scenario itself. This is
why all three annotation arrays are checked.

### Sub-Tag Boost (Ã—1.15)

When the query mentions a CAS role/modifier (`@Guarantor`, `@Primary`, `@CoApplicant`,
`@Reject`, `@MoveToNext`, etc.), steps in scenarios with those sub-tags are boosted.

Detection: `src/casforge/workflow/ordering.py` â†’ `detect_sub_tags(query)` â€” multi-match; a single
query can trigger several sub-tags.

---

## Optional Pre-Retrieval Filters

Filters applied before or during channel queries (not post-merge):

| Filter | Parameter | Applied where |
|---|---|---|
| Screen context | `screen_filter` | `WHERE screen_context = ?` in FTS + trigram; FAISS post-filter |
| Keyword | `keyword_filter` | `WHERE keyword = ?` (Given / When / Then / And / But) |

No stage/sub-tag filter â€” boosts are preferred over hard filters to avoid missing
cross-stage steps.

---

## Result Format

Each result includes the matched step, its score, and the full surrounding scenario context:

```json
{
  "step_id": 1234,
  "keyword": "When",
  "step_text": "user navigates to committee approval screen",
  "score": 0.87,
  "screen_context": "Committee",
  "scenario_title": "Committee approval with general majority",
  "file_name": "Committee.feature",
  "file_path": "...",
  "scenario_steps": [
    {"keyword": "Given", "step_text": "all prerequisite are performed..."},
    {"keyword": "When",  "step_text": "user navigates to committee approval screen"},
    {"keyword": "Then",  "step_text": "committee approval screen should be displayed"}
  ],
  "detected_stage": "@CreditApproval",
  "detected_sub_tags": []
}
```

The full scenario context is what makes LLM assembly reliable â€” the LLM sees not
just one step but the complete pattern of how that intent is tested.

---

## Rebuild Commands

```bat
# After any ingest â€” rebuild FAISS index (~2 min for 17k unique steps)
python tools/cli/build_index.py

# Full rebuild (drops DB, re-parses all, rebuilds index)
bat\ingest_full_rebuild.bat

# Interactive retrieval test
bat\test_retrieval.bat
```

---

## Accuracy (Phase 1 validation)

| Query type | Score |
|---|---|
| Full-sentence (Llama-style output) | 15/15 = **100%** |
| All including 2â€“3 word fragments | 17/20 = **85%** |

The 3 failures are bare 2â€“3 word fragments (e.g. `"reject"` alone) that even a human
would need more context to disambiguate. Llama produces full-sentence intents, so the
effective accuracy for Phase 2 is 100%.






