# Agent Handoff Index

Start here before touching code.

## Read Order
1. [agent.md](./agent.md)
2. [agnet.md](./agnet.md)
3. [skills.md](./skills.md)
4. [../docs/cas_context/ATDD_Repo_CONTEXT.md](../docs/cas_context/ATDD_Repo_CONTEXT.md)
5. [../docs/cas_context/CAS_Overview.md](../docs/cas_context/CAS_Overview.md)
6. [../docs/FrontEnd_Expectations/approach.md](../docs/FrontEnd_Expectations/approach.md)
7. [../docs/FrontEnd_Expectations/UI_Expectation.md](../docs/FrontEnd_Expectations/UI_Expectation.md)
8. [../docs/HOW_TO_RUN.md](../docs/HOW_TO_RUN.md)

## Current Challenge
### What has been done
1. Project reorg and path rewiring are complete.
2. Story-facts extraction, deterministic scenario planning, and retrieval-first assembly are all in place.
3. Planner now assigns repo-style section families instead of only flat generic families.
4. Assembler now uses section-aware and matrix-aware anchor scoring.
5. LOB-aware query expansion and stronger target specificity checks were added.
6. Wrong low-confidence scenarios are now omitted more often instead of being forced into output.
7. Tests, smoke checks, retrieval benchmark, and generated-feature validation are all passing.

### What is fine
1. Retrieval remains strong at 100 percent on the benchmark.
2. Ordered and unordered template rendering is stable.
3. Repo-authentic grounding is still working.
4. Sectioned output now looks closer to real CAS files.
5. Coverage gaps are surfaced honestly instead of hidden.

### What is not fine
1. Actual business quality is still below the 85-90 percent goal on hard stories.
2. `CAS-264757` still has one weak kept scenario:
   - `Keep Decision checkboxes checked by default`
3. Two unique weak intents are currently omitted instead of solved:
   - `Disable Recommended Limit when any subloan is not recommended`
   - `Move application to Credit Approval from Recommendation`
4. Recommendation-stage state movement is still not being composed well enough from repo material.
5. Exact default-state and recommended-limit patterns are still underrepresented in current matching.

### What needs to be done next
1. Fix default-state scenario resolution for recommendation-stage checkbox behavior.
2. Add a safer state-movement composer for recommendation to credit-approval transitions.
3. Improve exact matching for `recommended limit` vs other limit/amount fields.
4. Keep the conservative gating rule: omit weak scenarios rather than borrow wrong repo chains.

## Current Best Reference Run
Latest generated sample:
- [../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature](../workspace/generated/phase4_eval_patterns_v5/CAS_264757.feature)

Use this as the current baseline.

## Core Files For The Next Session
- [story_facts.py](../src/casforge/generation/story_facts.py)
- [scenario_planner.py](../src/casforge/generation/scenario_planner.py)
- [intent_extractor.py](../src/casforge/generation/intent_extractor.py)
- [feature_assembler.py](../src/casforge/generation/feature_assembler.py)
- [test_generation_planning.py](../test/test_generation_planning.py)
- [smoke_small_chunks.py](../tools/cli/smoke_small_chunks.py)

## Quick Commands
```powershell
python -m unittest discover -s test -v
python tools/cli/evaluate_retrieval.py --threshold 85
python tools/cli/smoke_small_chunks.py
python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/committee.csv --story CAS-264757 --flow-type unordered --output workspace/generated/phase4_eval_patterns_v5
python tools/cli/validate_generated_features.py --dir workspace/generated/phase4_eval_patterns_v5
```
