# CASForge — Ranking Logic

## Overview

Ranking in CASForge is a multi-stage process:

1. **Per-channel retrieval** — each channel returns up to 50 candidates with raw scores
2. **Score normalisation** — raw scores scaled to [0, 1] within each channel
3. **Weighted merge** — normalised scores combined by channel weights
4. **Post-merge boosts** — CAS-domain knowledge applied to lift contextually relevant results
5. **Final sort** — descending by accumulated score, top_k returned

---

## Step 1 — Per-Channel Retrieval

Each channel queries independently:

```
Vector channel:   top 50 by cosine similarity    (FAISS)
FTS channel:      top 50 by ts_rank_cd           (PostgreSQL)
Trigram channel:  top 50 by word_similarity       (PostgreSQL pg_trgm, min 0.1)
```

Candidates from all three channels are pooled — a step can appear in multiple channels.

---

## Step 2 — Score Normalisation (min-max per channel)

Raw scores vary by channel type and query length. Normalisation makes them comparable:

```python
def normalise(score, all_scores_in_channel):
    lo = min(all_scores_in_channel)
    hi = max(all_scores_in_channel)
    if hi == lo:
        return 1.0
    return (score - lo) / (hi - lo)
```

The top result in each channel always normalises to 1.0; the worst to 0.0.

---

## Step 3 — Weighted Score Merge

```python
WEIGHTS = {
    'vector':  0.50,
    'fts':     0.30,
    'trigram': 0.20,
}

merged_score[step_id] += weight * normalised_score
```

A step appearing in all three channels with high normalised scores accumulates up to 1.0.

**Why these weights?**
- Vector (50%) is highest because semantic similarity is the most reliable signal across
  diverse CAS step phrasings.
- FTS (30%) rewards exact keyword matches with stemming — important when the query and
  step share the same root word.
- Trigram (20%) acts as a tiebreaker for partial text overlap — useful for short queries
  and abbreviations but noisy for longer queries.

---

## Step 4 — Post-Merge Boosts

Boosts are multiplicative and applied after merging. They encode CAS domain knowledge:
the same step tested under `@Recommendation` is more relevant to a Recommendation query
than the identical step tested under `@DDE`.

### Stage Boost (×1.30)

**Trigger**: query contains a detectable CAS stage name.

**Detection** (`config/workflow.py`, `detect_stage(query)`):
- `STAGE_PATTERNS` are compiled from all stage annotations in `order.json`
  (e.g. `@CreditApproval`, `@Recommendation`, `@Disbursal`, `@DDE`, etc.)
- CamelCase is split into phrase variants:
  - `@CreditApproval` → `["credit approval", "creditapproval"]`
  - `@DDE` → `["dde"]`
- Patterns are sorted **longest-first** to prevent `"credit"` matching
  `@CreditBureauReferral` before `@CreditApproval`.
- Only one stage is detected per query (the first longest match).

**Application**: Step IDs are fetched whose scenarios carry that stage annotation in
`example_blocks.block_annotations`, `scenarios.scenario_annotations`,
`features.file_annotations`, or `scenarios.title`. Matched step IDs get score × 1.30.

```
Example:
  Query: "Guarantor edit at Recommendation stage"
  Detected: @Recommendation
  Steps under @Recommendation: boosted × 1.30
  Steps under @DDE (same step text): not boosted
  → @Recommendation result rises to #1
```

### Sub-Tag Boost (×1.15)

**Trigger**: query contains a CAS sub-tag / modifier word.

**Detection** (`config/workflow.py`, `detect_sub_tags(query)`):
- `SUB_TAGS` extracted from `order.json` entries (all non-primary tags):
  `@Guarantor`, `@Primary`, `@CoApplicant`, `@Reject`, `@MoveToNext`,
  `@AppInfo`, `@Document`, `@Collateral`, `@Charge`, etc.
- Multiple sub-tags can be detected in one query.
- Same phrase-matching and longest-first pattern approach as stage detection.

**Application**: Step IDs in scenarios with that sub-tag annotation get score × 1.15.
Multiple sub-tags stack (each applies independently).

```
Example:
  Query: "Guarantor edit at Recommendation stage"
  Detected sub-tags: [@Guarantor]
  Steps in @Guarantor scenarios: boosted × 1.15
  Combined with stage boost: × 1.30 × 1.15 = × 1.495
```

---

## Query Expansion Effect on Ranking

For short queries (≤3 words), synonym expansion shifts the merged score before boosts.

**Before expansion**: `"Delete Guarantor"` — vector embedding doesn't strongly associate
with `user removes "Guarantor" customer` (rank 3, score 0.51)

**After expansion**: `"Delete Guarantor remove removes deleted"` — embedding moves toward
the deletion-action cluster; `removes` now a direct token match (rank 1, score 0.70)

Expansion is deliberately limited to ≤3 words because longer queries already carry enough
context. Expanding `"user clicks on committee approval button"` would dilute rather than
sharpen the result.

---

## Ranking Failure Cases

These are known, accepted limitations:

| Case | Why it fails | Impact |
|---|---|---|
| Bare 1-word query (`"reject"`) | Ambiguous — dozens of equally-valid steps match | Low: Llama produces full sentences |
| Domain-specific literal match beats intent | `"Minimum Approvals"` as literal text ranks initiation step above reject step | Rare: specific committee logic |
| Synonym not in expansion list | Action verb not covered by 12 synonym groups | Can be fixed by extending `query_expander.py` |

All failures occur on 2–3 word fragments. Full-sentence queries (the output Llama will
produce) score 100% on the validation set.

---

## Tuning Reference

| Parameter | Location | Default | Effect |
|---|---|---|---|
| Vector weight | `catalogue/retrieval.py` | `0.50` | Raise to favour semantic match |
| FTS weight | `catalogue/retrieval.py` | `0.30` | Raise to favour exact keyword |
| Trigram weight | `catalogue/retrieval.py` | `0.20` | Raise to favour fuzzy partial |
| Stage boost | `catalogue/retrieval.py` | `1.30` | Raise to enforce stage isolation more aggressively |
| Sub-tag boost | `catalogue/retrieval.py` | `1.15` | |
| Max words to expand | `catalogue/query_expander.py` | `3` | Raise to expand longer queries |
| Max synonyms per group | `catalogue/query_expander.py` | `3` | Raise for more coverage, lower for precision |
| Trigram min similarity | `catalogue/retrieval.py` | `0.1` | Raise to reduce noise; lower to catch more fragments |
| Top-k per channel | `catalogue/retrieval.py` | `50` | Raise if top_k requested is large |

---

## Full Ranking Example

Query: `"Guarantor visible at DDE stage"`

```
1. Query expansion:  ≤3 words? No (5 words) → no expansion
2. Stage detection:  "DDE" → @DDE (boost × 1.30)
3. Sub-tag detection: "Guarantor" → @Guarantor (boost × 1.15)

Channel results (simplified):
  Vector:  [step_A=0.82, step_B=0.71, step_C=0.61, ...]
  FTS:     [step_A=0.90, step_D=0.75, step_B=0.60, ...]
  Trigram: [step_B=0.55, step_A=0.50, step_E=0.40, ...]

After normalise + weight merge:
  step_A: 0.50×1.0 + 0.30×1.0 + 0.20×0.67 = 0.93
  step_B: 0.50×0.82 + 0.30×0.60 + 0.20×1.0 = 0.79
  ...

After stage boost (step_A is in @DDE scenario):
  step_A: 0.93 × 1.30 = 1.21

After sub-tag boost (step_A is in @Guarantor example block):
  step_A: 1.21 × 1.15 = 1.39

Final sort: step_A=1.39, step_B=0.79, ...
```

The boosts can push a score above 1.0 — this is intentional. Scores are relative
within a query, not absolute. The top result is what matters.
