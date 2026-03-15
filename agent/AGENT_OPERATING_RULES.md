# CASForge Working Skills

## What This Project Needs From The Agent

CASForge is not a generic Gherkin generator. It is a repo-faithful CAS ATDD composer.
The agent working on this project should behave like:

- a retrieval-first planner
- a conservative assembler
- a quality gatekeeper
- not a freeform feature writer

## Operating Principles

1. Read real code before changing architecture.
2. Prefer deterministic planning/composition over prompt creativity.
3. Preserve repo authenticity wherever possible.
4. Reject low-confidence scenarios instead of forcing output.
5. Use tests as gates between each tuning cycle.
6. Use exact file examples sparingly and intentionally.
7. Prefer honest gaps over wrong repo borrowing.

## Project-Specific Skills

### 1. Story fact extraction

Goal:

- reduce a messy JIRA story into normalized, reusable facts

Where:

- [src/casforge/generation/story_facts.py](../src/casforge/generation/story_facts.py)
- [assets/prompts/extract_story_facts.txt](../assets/prompts/extract_story_facts.txt)

Good practice:

- keep facts literal
- drop ambiguous facts
- preserve polarity
- split compound rules
- detect scope/entity/matrix cues early

### 2. Deterministic planning

Goal:

- turn facts into short, precise, retrieval-friendly plan items

Where:

- [src/casforge/generation/scenario_planner.py](../src/casforge/generation/scenario_planner.py)

Good plan item properties:

- short title
- one behavior only
- clear entity
- clear expected state
- clear polarity
- must-anchor terms
- must-assert terms
- forbidden terms
- section metadata that mirrors repo authoring style

Bad plan item signs:

- generic wording
- repeated synonyms instead of distinct behavior
- target like `this field`
- no entity
- no polarity
- no section identity

### 3. Repo-anchored assembly

Goal:

- choose one coherent repo scenario chain, then compose conservatively

Where:

- [src/casforge/generation/feature_assembler.py](../src/casforge/generation/feature_assembler.py)

Good assembly behavior:

- choose scenario-level anchor, not isolated step fragments
- preserve setup chain from same scenario
- preserve action chain from same scenario
- replace assertion only when necessary
- stay in same domain/screen/stage family
- use section-aware and matrix-aware scoring
- omit weak relaxed-scope anchors rather than forcing them

Bad assembly behavior:

- mixing Recommendation and Credit Approval without explicit state movement intent
- pulling unrelated assertion from another domain
- flattening rich repo chain into generic Given/When/Then
- keeping a bad scenario just because it is syntactically valid

### 4. Confidence gating

Goal:

- convert uncertainty into visible metadata instead of wrong feature output

What to keep:

- `coverage_gaps`
- `omitted_plan_items`
- `scenario_debug`
- `NEW_STEP_NOT_IN_REPO`

Rule:

- fewer correct scenarios is better than more wrong scenarios

## Recommended Debug Workflow

### Fast cycle

```powershell
python -m unittest discover -s test -v
python tools/cli/smoke_small_chunks.py
```

### Retrieval regression

```powershell
python tools/cli/evaluate_retrieval.py --threshold 85
```

### Real sample generation

```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/committee.csv --story CAS-264757 --flow-type unordered --output workspace/generated/phase4_eval_patterns_v5
python tools/cli/validate_generated_features.py --dir workspace/generated/phase4_eval_patterns_v5
```

## How To Judge Output Quality

Do not stop at ?file generated successfully.? Judge against these axes:

1. Scope correctness
2. LOB/stage correctness
3. Polarity correctness
4. Scenario family correctness
5. Repo-authentic chain quality
6. Assertion relevance
7. Cross-domain leakage
8. Scenario count adequacy
9. Whether omitted gaps are honest and useful

## What Not To Do

1. Do not tune prompts for prettier full feature writing.
2. Do not replace retrieval because output quality is bad.
3. Do not overfit to one gold file by hardcoding story-specific paths.
4. Do not invent business steps if a repo-authentic step exists.
5. Do not hide uncertainty.
6. Do not infer ordered/unordered.
7. Do not raise scenario count by relaxing quality gates.

## Current Known Weak Spots

1. default-state checkbox resolution
2. exact recommended-limit matching
3. recommendation-stage MTNS composition
4. some remaining entity granularity issues in omni decision stories
5. weak fallback assertions when repo has no exact match

## Best Next Improvement Areas

1. strengthen default-state scenario matching in `feature_assembler.py`
2. improve exact target separation in `story_facts.py` and `feature_assembler.py`
3. add a safer recommendation-stage state-movement composer
4. keep section-aware planning and conservative gating intact
5. surface omitted-plan reasons more clearly in UI later

## Essential Files To Remember

- [src/casforge/generation/story_facts.py](../src/casforge/generation/story_facts.py)
- [src/casforge/generation/scenario_planner.py](../src/casforge/generation/scenario_planner.py)
- [src/casforge/generation/intent_extractor.py](../src/casforge/generation/intent_extractor.py)
- [src/casforge/generation/feature_assembler.py](../src/casforge/generation/feature_assembler.py)
- [test/test_generation_planning.py](../test/test_generation_planning.py)
- [tools/cli/smoke_small_chunks.py](../tools/cli/smoke_small_chunks.py)
- [workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature](../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature)

## Final Reminder

The real problem is still semantic planning quality, not syntax generation.
The right path remains:

- better facts
- better plan items
- stricter anchor eligibility
- honest confidence gating
- targeted reruns on real samples
