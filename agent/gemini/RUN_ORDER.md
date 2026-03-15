# Gemini Run Order

Ignore paths listed in .agent/EXCLUDE_PATHS.md

## Phase 1 — Read only

1. .agent/PROJECT_STATUS.md
2. .agent/PIPELINE_OVERVIEW.md
3. .agent/gemini/REVIEW_SCOPE.md
4. .agent/gemini/INPUTS.md
5. .agent/gemini/REVIEW_PROMPT.md
6. .agent/gemini/OUTPUT_FORMAT.md
7. CodeManual.md
8. Continuation_Guide.md
9. NextSteps.md
10. skills.md

## Phase 2 — Inspect code only after docs

Inspect these first:

1. src/casforge/generation/story_facts.py
2. src/casforge/generation/scenario_planner.py
3. src/casforge/generation/feature_assembler.py

Inspect other files only if needed.

## Phase 3 — Produce outputs

1. agent/reports/gemini_root_cause_review.md
2. agent/reports/gemini_root_cause_review.json
