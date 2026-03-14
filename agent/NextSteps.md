# Next Steps

## Goal
Raise business-faithful generation quality without changing the model, embeddings, or ingestion architecture.

## Current Position
Based on the current review:
- the plumbing is mostly in place
- retrieval is not the main blocker
- parser and scope wiring are usable
- the main risk area is still the assembler path, especially late fallback and grounding behavior

## Priority Order

### Phase 1: stabilize the critical path
1. Remove late semantic drift from post-render grounding.
   - Restrict replacements to exact / near-exact matches only.
   - If a step is unresolved, keep it unresolved instead of repairing it with a weak repo step.
   - Prefer inline unresolved markers over only header notices.
2. Split `feature_assembler.py` into focused modules.
   - `anchor_selection.py`
   - `assertion_resolution.py`
   - `scenario_composer.py`
   - `feature_renderer.py`
   - `grounding.py`
3. Centralize scope utilities.
   - Move story-scope normalization, merge rules, and inference into one shared generation utility.
   - Replace duplicated local helpers in extractor, story facts, planner, and assembler.

### Phase 2: tighten business accuracy
4. Make confidence gating stricter for fallback cases.
   - Generated fallback scenarios should become coverage gaps unless the anchor is clearly strong.
   - Generated fallback assertions should be allowed only when transparency is explicit.
5. Strengthen default-state and state-movement handling.
   - These remain weak in the current sample runs.
   - Add dedicated tests for:
     - checked-by-default behavior
     - recommendation-to-credit-approval movement
     - recommended limit disablement tied to sub-product recommendation state
6. Push more logic into plan-time instead of compose-time.
   - Use the plan item as the authority for section, expected outcome, polarity, matrix signature, and target field.
   - Reduce downstream heuristic reinterpretation where possible.

### Phase 3: improve product contracts
7. Fix the UI/backend metadata mismatch.
   - Either wire `authorName` through generation and template tags or remove the editable field.
8. Clean dead paths and legacy artifacts.
   - remove or clearly mark unused helper paths
   - archive `frontend_legacy.html`
   - trim stale prompt/helper code that no longer participates in runtime
9. Tighten API path handling.
   - validate absolute CSV paths in `_resolve_path()`
   - clean small model / response hygiene issues

## Testing Changes Required

### Strengthen automated acceptance gates
1. Keep existing retrieval regression as-is.
2. Keep parser and planner unit tests as-is.
3. Add benchmark generation checks for 3-5 known stories.
   - Not exact-string goldens.
   - Use rubric-based assertions:
     - correct stage / LOB scope
     - correct family coverage
     - correct polarity
     - no domain leakage
     - adequate scenario count
     - no assertion spam
4. Tighten smoke thresholds.
   - A run with one scenario and multiple gaps should not count as a strong generation pass.
   - Keep the smoke suite fast, but make it meaningful.

### Useful benchmark categories
- omni recommendation / credit approval decisioning
- committee decision logic
- applicant information or lead-details validation
- collateral viewer / editability case
- one ordered flow with LogicalID propagation

## Refactor Sequence
This order minimizes churn:
1. isolate grounding logic first
2. centralize scope helpers
3. split anchor selection and assertion resolution out of `feature_assembler.py`
4. split rendering last
5. then add stricter benchmark tests

That sequence avoids editing everything at once while still attacking the highest-risk part first.

## What Does Not Need Redesign Right Now
- FAISS / embedding layer
- PostgreSQL schema
- ingestion flow
- order.json handling model
- FastAPI surface area

## Suggested Deliverables for the Next Engineering Pass
1. New shared scope utility module.
2. New grounding module with exact-match-first policy.
3. New anchor-selection module with scenario-level ranking only.
4. New assertion-resolution module.
5. Updated feature assembler reduced to orchestration + render call.
6. Benchmark test harness with a small fixed story set.
7. UI/backend author metadata fix.

## Success Criteria for the Next Pass
- no new domain leakage introduced by grounding
- fewer generated fallback assertions in final output
- benchmark stories show higher scenario relevance
- code review complexity decreases because assembler logic is no longer one monolith
- smoke and unit tests still pass
- retrieval benchmark remains at or above the current threshold

## Practical First Step
If work continues immediately, the best first code change is:
- extract the post-render grounding and replacement policy into its own module
- tighten replacement thresholds
- stop weak replacements from rewriting semantically correct but unresolved steps

That step is the most likely to improve real output quality without destabilizing the rest of the system.
