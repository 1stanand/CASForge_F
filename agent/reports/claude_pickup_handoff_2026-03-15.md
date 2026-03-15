# Claude Pickup Handoff

## Purpose
This is the current Codex-to-Claude handoff after the config-driven heuristic cleanup.

Read this first if Claude is taking over from the current branch state.

## Read Order
1. [README.md](../../README.md)
2. [agent/AGENT_OPERATING_RULES.md](../AGENT_OPERATING_RULES.md)
3. [.agent/PROJECT_STATUS.md](../../.agent/PROJECT_STATUS.md)
4. [.agent/PIPELINE_OVERVIEW.md](../../.agent/PIPELINE_OVERVIEW.md)
5. [agent/reports/gemini_root_cause_review.md](./gemini_root_cause_review.md)
6. [agent/reports/codex_overfitting_audit_planner_assembler.md](./codex_overfitting_audit_planner_assembler.md)
7. [agent/diagnostics/codex_patch_summary.md](../diagnostics/codex_patch_summary.md)
8. [agent/diagnostics/codex_change_log.md](../diagnostics/codex_change_log.md)
9. [agent/diagnostics/accuracy_tracker.md](../diagnostics/accuracy_tracker.md)
10. [agent/reports/accuracychecks/accuracy_progress.md](./accuracychecks/accuracy_progress.md)

## Files Claude Should Inspect In Code
1. [src/casforge/generation/story_facts.py](../../src/casforge/generation/story_facts.py)
2. [src/casforge/generation/scenario_planner.py](../../src/casforge/generation/scenario_planner.py)
3. [src/casforge/generation/feature_assembler.py](../../src/casforge/generation/feature_assembler.py)
4. [src/casforge/generation/heuristic_config.py](../../src/casforge/generation/heuristic_config.py)
5. [assets/generation/domain_knowledge.json](../../assets/generation/domain_knowledge.json)
6. [assets/generation/planner_hints.json](../../assets/generation/planner_hints.json)
7. [assets/generation/assembler_hints.json](../../assets/generation/assembler_hints.json)
8. [test/test_generation_planning.py](../../test/test_generation_planning.py)

## What Was Completed
1. Weak fallback scenario generation was disabled/restricted in the active assembler path.
2. Post-render step replacement was disabled/restricted, preserving `NEW_STEP_NOT_IN_REPO`.
3. Weak fallback assertion behavior was hardened to keep unresolved `Then` steps explicit.
4. Planner titles were generalized away from exact sample-family wording.
5. Story-fact movement extraction and ambiguous target handling were tightened.
6. Remaining `story_facts` seed rescue logic was removed instead of being moved into config.
7. Stable CAS/domain knowledge and generic planner/assembler hint buckets were externalized into CASForge-owned JSON.
8. Strict config loading now rejects rule-engine style keys and degrades conservatively on missing/malformed files.
9. Regression coverage now includes config-loading, config-driven behavior, and missing-config degradation.

## Validation Baseline
Latest verified commands:

```powershell
python -m unittest discover -s test
python -m unittest discover -s test -p "test_generation_planning.py"
python tools/cli/smoke_small_chunks.py
```

Latest verified results:
- full unit suite: `64/64` passed
- targeted planning/config suite: `48/48` passed
- small-chunk smoke: `PASS`

## Important Ownership Boundary
1. `assets/workflow/order.json` is not CASForge-owned.
2. `order.json` remains a read-only ATDD/workflow dependency.
3. CASForge-owned generation config now lives under:
   - [assets/generation/domain_knowledge.json](../../assets/generation/domain_knowledge.json)
   - [assets/generation/planner_hints.json](../../assets/generation/planner_hints.json)
   - [assets/generation/assembler_hints.json](../../assets/generation/assembler_hints.json)
4. Sample-specific rescue logic should not be added to either Python or these JSON files.

## Main Problems Claude Needs To Solve
1. `feature_assembler.py` is still the primary quality bottleneck.
   - It remains heuristic-heavy even after bucket externalization.
   - The likely next work is simplifying anchor/assertion selection logic without weakening conservative gating.
2. `story_facts.py` still relies on regex-heavy lexical inference.
   - Stable vocab moved to config, but target/effect/polarity extraction is still brittle on mixed business sentences.
   - The likely next work is reducing false positives and improving clause-level semantic separation without reintroducing rescue rules.
3. Real accuracy is still not broadly proven.
   - The tracked improvement exists, but evaluation is still based on a small number of stories.
   - The likely next work is broader, real-sample validation rather than tuning to a single Jira family.
4. Retrieval/planning tests are still too OMNI-heavy.
   - The suite is better semantically, but fixtures are still concentrated around one recommendation family.
   - The likely next work is adding unrelated domains before trusting more heuristic tuning.

## What Claude Should Not Redo
1. Do not reintroduce weak fallback scenario generation.
2. Do not re-enable post-render step replacement.
3. Do not hide unresolved assertions or remove `NEW_STEP_NOT_IN_REPO`.
4. Do not move sample hacks into JSON.
5. Do not modify retrieval, ingestion, embeddings, or DB schema unless a broader design decision is explicitly made.

## Best Current Framing
The system is now cleaner and less sample-shaped than before, but not finished.

The code no longer keeps the main stable business vocabularies hardcoded inside the three scoped generation modules. The remaining problems are mostly:
- heuristic complexity in assembler selection
- brittle lexical parsing in story facts
- insufficiently broad evaluation coverage

Gemini's review is still the right root-cause anchor. The handoff for Claude is not "start from zero"; it is "continue from a cleaned conservative baseline and attack the remaining semantic bottlenecks".
