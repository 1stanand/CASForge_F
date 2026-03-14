# CASForge Continuation Guide

## Purpose
This is the detailed handoff memory for the next coding session.
It should let the next engineer continue without rediscovering the same context.

## Non-Negotiable Product Rules
1. Ordered vs unordered flow must never be inferred from JIRA.
2. Repo-authentic steps are the default.
3. Assertion rule:
   - maximum `Then`
   - optional one `And`
   - never long `Then + And + And + And` tails
4. One approved intent may produce more than one scenario.
5. If no repo step is found, keep uncertainty visible with `NEW_STEP_NOT_IN_REPO` or omit the scenario when confidence is too low.
6. Retrieval is already a strength. Do not replace it casually.
7. Do not bulk-read the whole `Features/` tree.

## Read These First In Any New Session
1. [docs/cas_context/ATDD_Repo_CONTEXT.md](../docs/cas_context/ATDD_Repo_CONTEXT.md)
2. [docs/cas_context/CAS_Overview.md](../docs/cas_context/CAS_Overview.md)
3. [docs/FrontEnd_Expectations/approach.md](../docs/FrontEnd_Expectations/approach.md)
4. [docs/FrontEnd_Expectations/UI_Expectation.md](../docs/FrontEnd_Expectations/UI_Expectation.md)
5. [docs/HOW_TO_RUN.md](../docs/HOW_TO_RUN.md)

## Current Challenge
### What has been done
1. Project reorg and path rewiring are complete.
2. Story-facts extraction is wired into intent planning.
3. Deterministic scenario planning is in place.
4. The assembler now has:
   - hard eligibility checks
   - scenario-level scoring
   - confidence gating
   - `coverage_gaps`
   - `omitted_plan_items`
   - `scenario_debug`
5. Planner now assigns repo-style section metadata, not just flat families.
6. Assembler now uses section-aware and matrix-aware scoring.
7. LOB-aware search context and stronger target-specific matching were added.
8. Weak relaxed-scope fallback scenarios are being omitted more aggressively.
9. Full tests, smoke checks, retrieval benchmark, and output validation are passing.

### What is fine
1. Retrieval remains a core strength.
2. Templates and ordered/unordered rendering are stable.
3. Repo-grounded output flow still works end to end.
4. Output is now more sectioned and CAS-like than before.
5. Weak scenarios can now be omitted instead of always being forced.
6. The system is more modular and more inspectable than earlier phases.

### What is not fine
1. Real output quality is still below target on hard stories.
2. `CAS-264757` is improved, but still not at 85-90 percent.
3. One kept scenario is still weak:
   - `Keep Decision checkboxes checked by default`
4. Two unique intents are currently omitted rather than solved:
   - `Disable Recommended Limit when any subloan is not recommended`
   - `Move application to Credit Approval from Recommendation`
5. Recommendation-stage state-movement composition is still poor.
6. Exact default-state and recommended-limit matching are still weak.

### What needs to be done next
1. Improve default-state anchor selection and assertion resolution.
2. Build a safer state-movement composer for recommendation-stage decision flows.
3. Distinguish `recommended limit` from other limit/amount patterns more precisely.
4. Keep conservative gating in place. Do not reintroduce wrong scenario borrowing just to increase count.

## Current Best Reference Run
Latest generated sample:
- [../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature](../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature)

Generation summary from the latest run:
- intents total: `9`
- intents planned: `7`
- scenario count: `7`
- coverage gaps: `3`
- omitted plan items: `3`
- unresolved assertions: `1`
- grounded steps: `52 / 52`

Unique coverage-gap intents in the latest run:
1. `Disable Recommended Limit when any subloan is not recommended`
2. `Move application to Credit Approval from Recommendation`

## What Was Improved In The Latest Pass
1. Planner section mapping:
   - `UI Structure Validation`
   - `Checkbox Availability & Default State`
   - `Field Enablement Behaviour`
   - `Decision Logic Behaviour`
   - `Move To Next Stage Validations`
2. Section-aware anchor scoring was added.
3. Matrix-aware anchor scoring was added.
4. LOB-specific query expansion was added.
5. Target specificity was tightened so mismatched fields are rejected more often.
6. Weak fallback anchors with near-zero signal are now omitted.
7. Relaxed-scope fallback for weak state-movement cases is now omitted instead of forced.

## Honest Quality Assessment Right Now
Current rough assessment for `CAS-264757`:
1. structurally better than earlier phase outputs
2. semantically safer than earlier phase outputs
3. still below target quality overall
4. currently better described as conservative and reviewable, not final-quality

### What improved
1. Sectioned output now looks closer to real CAS files.
2. Cross-domain and wrong-field borrowing is lower.
3. Bad scenarios are more often surfaced as gaps instead of silently emitted.
4. Decision-column and checkbox-availability cases are much cleaner than before.

### What is still wrong
1. Default-state checkbox scenario still falls back weakly.
2. Recommended-limit disable behavior still has no acceptable repo-authentic anchor.
3. Recommendation-to-credit-approval state movement is still not solved cleanly.
4. The sample is still below the business-quality threshold even though the system is safer.

## Highest-Value Next Work
### Priority 1: Fix default-state behavior
Files:
- [src/casforge/generation/feature_assembler.py](../src/casforge/generation/feature_assembler.py)
- [src/casforge/generation/scenario_planner.py](../src/casforge/generation/scenario_planner.py)

Focus:
1. prefer auto-population/default-state repo scenarios over generic checkbox-action scenarios
2. if no exact repo assertion exists, prefer explicit unresolved/generated marking over weak repo borrowing

### Priority 2: Fix recommendation-stage state movement
File:
- [src/casforge/generation/feature_assembler.py](../src/casforge/generation/feature_assembler.py)

Focus:
1. compose MTNS from correct recommendation-stage screen context
2. do not allow committee/credit-approval style chains to stand in for recommendation MTNS
3. if still weak, keep it omitted

### Priority 3: Fix recommended-limit targeting
Files:
- [src/casforge/generation/story_facts.py](../src/casforge/generation/story_facts.py)
- [src/casforge/generation/feature_assembler.py](../src/casforge/generation/feature_assembler.py)

Focus:
1. stronger exact recognition of `recommended limit`
2. stronger rejection of add-on-card and other limit-field lookalikes
3. consider explicit generated fallback if repo has no true match

## What Passed At End Of Latest Session
These commands passed:
```powershell
python -m unittest discover -s test -v
python tools/cli/evaluate_retrieval.py --threshold 85
python tools/cli/smoke_small_chunks.py
python tools/cli/validate_generated_features.py --dir workspace/generated/phase4_eval_patterns_v5
```

Results:
1. unit tests: `34 passed`
2. smoke: `PASS`
3. retrieval benchmark: `100%`
4. generated feature validation: `PASS`

## Suggested Next Debug Loop
1. Inspect the latest sample:
   - [../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature](../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature)
2. Compare the weak kept scenario and omitted intents against the best reference files the user already supplied.
3. Improve only one weak behavior at a time:
   - default checked
   - recommended limit disabled
   - recommendation MTNS
4. Run the fast loop first:
```powershell
python -m unittest discover -s test -v
python tools/cli/smoke_small_chunks.py
```
5. Then rerun the real sample:
```powershell
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/committee.csv --story CAS-264757 --flow-type unordered --output workspace/generated/phase4_eval_patterns_v6
python tools/cli/validate_generated_features.py --dir workspace/generated/phase4_eval_patterns_v6
```

## Important Cautions For The Next Session
1. Do not redesign the embedding layer.
2. Do not break ingestion flow or DB schema.
3. Do not remove `NEW_STEP_NOT_IN_REPO` behavior.
4. Do not guess ordered/unordered flow.
5. Do not bulk-load the full repo.
6. Do not increase scenario count by allowing weak relaxed-scope borrowing again.

## Short Status Snapshot
- reorg: done
- path rewiring: done
- templates wired: done
- story-facts layer: done
- deterministic planner: done
- section-aware planning: added
- section-aware anchor scoring: added
- matrix-aware scoring: added
- conservative confidence gating: stronger now
- tests: passing
- retrieval: 100 percent
- latest sample: better structured, still below target, now more conservative and honest
