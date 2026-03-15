# Codex Change Log

## Change 1

File:
src/casforge/generation/feature_assembler.py

Reason:
Disable fallback scenario generation (Gemini finding #1)

Change summary:
- Disabled weak scenario recovery in `_plan_scenarios` by preventing `_build_scaffold_plan_from_related_hits` and `_build_fallback_plan` from being used in the active path.
- If no high-confidence anchor is found, or anchor-backed plans fail the confidence gate, the assembler now records a coverage gap and omission instead of inventing a scenario.
- Preserved deterministic planning and existing honest omission behavior.

Risk:
low

## Change 2

File:
src/casforge/generation/feature_assembler.py

Reason:
Disable post-render step replacement (Gemini finding #2)

Change summary:
- Disabled the active post-render replacement path in `_ground_steps_to_repo`.
- Missing repo steps now remain as generated text and are surfaced only through the existing `NEW_STEP_NOT_IN_REPO` notice.
- Preserved honest gap signaling and avoided semantic corruption from late replacement.

Risk:
low

## Change 3
File:
src/casforge/generation/feature_assembler.py, test/test_generation_planning.py

Gemini finding addressed:
Gemini recommended fix #3: simplify and harden assertion retrieval

Change summary:
- Removed the loose secondary `Then` search from `_fallback_then_step` once local and direct assertion retrieval have already failed.
- Changed fallback assertion rendering to emit explicit unresolved `Then` text prefixed with `NEW_STEP_NOT_IN_REPO:` instead of generic phrases.
- Added regression coverage to ensure missing assertions stay visible and unresolved in assembled plans.

Reason:
Generic fallback assertions were hiding uncertainty and could invent incorrect expected outcomes after retrieval had already failed.

Risk level:
low-medium

## Change 4
File:
src/casforge/generation/story_facts.py, test/test_generation_planning.py

Gemini finding addressed:
Gemini finding #3: initial story understanding is brittle and overfit

Change summary:
- Tightened state-movement inference so stage mentions like `Recommendation` no longer create `state_move` effects by themselves.
- Added a shared `_looks_like_state_movement(...)` gate used by both heuristic effect inference and coverage-signal detection.
- Added regression coverage to ensure UI/display requirements at recommendation stage stay as display rules instead of movement rules.

Reason:
Bare stage names were being treated as movement evidence, which inflated `state_movement` signals and polluted downstream planning with incorrect movement coverage.

Risk level:
low

## Change 9
File:
src/casforge/generation/story_facts.py

Gemini finding addressed:
Gemini finding #3: initial story understanding is brittle and overfit

Change summary:
- Tightened the precision seed for `credit approval stage` so it only fires when both movement language and `credit approval` are explicitly present.
- Stopped converting generic `move to next stage` phrasing into a hardcoded `credit approval stage` fact.

Reason:
The seed rule was manufacturing a specific movement target from ambiguous text, which contradicted the conservative “drop ambiguous facts” goal.

Risk level:
low

## Change 10
File:
src/casforge/generation/story_facts.py, test/test_generation_planning.py

Gemini finding addressed:
Gemini finding #3: initial story understanding is brittle and overfit

Change summary:
- Hardened story-fact normalization so unsupported coverage and matrix signals from raw text or overlay facts are pruned conservatively.
- Tightened default-state, validation, and edge signal detection to require stronger evidence instead of single broad tokens.
- Corrected family normalization when overlay facts label `derive`/dependency-like rules as `validation` or `positive` without validation evidence.

Reason:
Noisy fact normalization was a direct source of generic downstream intents such as default-state, validation, edge, and enablement scenarios that were not actually grounded in the story.

Risk level:
low-medium

## Change 5
File:
src/casforge/generation/story_facts.py

Gemini finding addressed:
Gemini finding #3: initial story understanding is brittle and overfit

Change summary:
- Removed bare stage-name phrases from heuristic `state_movement` coverage patterns.
- `state_movement` coverage is now triggered by transition language or explicit movement rules rather than any mention of recommendation/approval stages.

Reason:
Coverage detection still over-reported movement for stage-name-only stories even after tightening effect inference.

Risk level:
low

## Change 6
File:
src/casforge/generation/scenario_planner.py, test/test_generation_planning.py

Gemini finding addressed:
Gemini finding #4: synthetic plan generation fills gaps with generic tests

Change summary:
- Changed planner backfill logic so synthetic items only cover families that are not already represented by concrete rule-derived items.
- Prevented generic synthetic duplicates from being added solely because they have a different matrix signature.
- Added regression coverage to keep rule-backed dependency plans from being supplemented with generic dependency filler.

Reason:
The planner was appending low-value synthetic items even when a real rule had already covered that family, which diluted precision without adding trustworthy coverage.

Risk level:
low

## Change 7
File:
src/casforge/generation/scenario_planner.py, test/test_generation_planning.py

Gemini finding addressed:
Gemini finding #4: synthetic plan generation fills gaps with generic tests

Change summary:
- Taught the planner to prefer specific control/business entities for synthetic items instead of blindly using the first detected entity.
- Added a conservative gate that skips synthetic item generation when the only available entity is generic context such as `product type decision list`.
- Added regression coverage for both “prefer the specific entity” and “omit generic synthetic filler” behavior.

Reason:
When facts were sparse, the planner could still emit low-value synthetic intents like `Display product type decision list`, which are not repo-faithful test objectives.

Risk level:
low-medium

## Change 8
File:
src/casforge/generation/story_facts.py, test/test_generation_planning.py

Gemini finding addressed:
Gemini finding #3: initial story understanding is brittle and overfit

Change summary:
- Added a conservative target/effect ambiguity gate for heuristic fact extraction.
- Dropped generic container targets like `product type decision list` and generic movement targets like `application stage movement` / `mtns` instead of converting them into rules.
- Added regression coverage to ensure ambiguous display/movement sentences are omitted rather than extracted as weak facts.

Reason:
These generic targets are context or action labels, not stable business facts. Keeping them produced overly generic or incorrect rules that polluted downstream planning.

Risk level:
low

## Change 11
File:
agent/diagnostics/accuracy_tracker.md, agent/reports/gemini_root_cause_review.md, agent/diagnostics/codex_change_log.md, agent/diagnostics/codex_patch_summary.md

Gemini finding addressed:
Tracking update across Gemini findings #1-#5

Change summary:
- Replaced the placeholder `accuracy_tracker.md` with a real short-form verification tracker that records the latest test status and run-to-run quality trend.
- Appended an implementation-status section to `gemini_root_cause_review.md` so the source findings stay mapped to what has already been implemented.
- Recorded the tracking update in the ongoing Codex diagnostics logs.

Reason:
The repo already had code-change diagnostics, but the quick test/accuracy tracker was not being maintained and the Gemini report did not show implementation status. This makes it harder to judge current state without re-reading multiple files.

Risk level:
low

## Change 12
File:
README.md, docs/architecture/repo_dependency_graph.md, agent/diagnostics/codex_change_log.md, agent/diagnostics/codex_patch_summary.md

Gemini finding addressed:
N/A - repository auditability and architecture visibility

Change summary:
- Added a root `README.md` with a practical description of the CASForge pipeline, operating philosophy, setup, and validation workflow.
- Added a Mermaid dependency graph under `docs/architecture/repo_dependency_graph.md` based on real Python import relationships across parsing, planning, assembly, retrieval, CLI entrypoints, web entrypoints, and tests.
- Recorded the documentation update in the diagnostics logs.

Reason:
The repo needed a concrete top-level map of how modules are wired together so future reviews can identify heuristic-heavy hotspots from actual dependencies instead of ad hoc browsing.

Risk level:
low

## Change 13
File:
src/casforge/generation/scenario_planner.py, test/test_generation_planning.py

Gemini finding addressed:
Codex overfitting audit: exact sample-shaped title generation in scenario_planner.py

Change summary:
- Replaced hardcoded sample-family title branches in `_title_from_rule(...)` with deterministic templates derived from target, effect, polarity, and condition.
- Added neutral derived-state title rendering such as `Set <target> to <state>` and neutral state-movement phrasing such as `Move application to <target> ...`.
- Updated planner tests so they validate target/effect/section semantics and verify the old sample-shaped phrases are no longer required.

Reason:
Planner titles were encoding one narrow recommendation/subloan story family and the tests were reinforcing that wording instead of the underlying behavior.

Risk level:
low-medium

## Change 14
Files:
src/casforge/generation/scenario_planner.py, test/test_generation_planning.py

Overfit issue addressed:
Narrow planner canonical rewrites, sample-family screen inference, and hand-picked entity ranking

Change summary:
- Removed stage/condition-driven target promotion in `_canonical_plan_target(...)` so generic inputs like `application level decision` are no longer rewritten into sample-family controls purely because the story is at recommendation stage.
- Removed target-name-only screen inference in `_screen_hint_for_rule(...)`; the planner now uses explicit rule screen hints or story/default context instead of assuming sample UI screens from control names.
- Replaced the hand-picked preferred-entity shortlist in `_best_entity_from_facts(...)` with rule-backed specificity ranking and generic target normalization.
- Added regression tests that validate semantic behavior instead of the previous sample-family assumptions.

Reason:
The planner was still shaping intents toward the known OMNI recommendation family even after title generation was generalized. That made downstream assembly inherit sample-specific targets, screens, and entity priorities.

Risk level:
medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`
- `python tools/cli/smoke_small_chunks.py`

Result:
- targeted planning suite passed: `37/37`
- small-chunk smoke passed: `PASS`

## Change 15
Files:
src/casforge/generation/story_facts.py, test/test_generation_planning.py

Overfit issue addressed:
Sample-family seed rules and stage-driven target promotion in `story_facts.py`

Change summary:
- Reduced `_seed_precision_rules(...)` to a smaller sentence-anchored rescue path instead of a blob-wide source of pre-authored recommendation-story rules.
- Removed stage-only promotion of `application level decision` into `recommendation decision dropdown` from generic target inference.
- Stopped the `selected as recommended` seed path from inventing a disable rule unless disable/read-only text is explicitly present.
- Updated tests so the strong-heuristic path is validated through semantic rules rather than a sample-driven minimum rule count.

Reason:
`story_facts.py` was still the strongest source of sample-family semantics entering the stack. The seed path was manufacturing narrow conditions and targets from whole-story matches instead of staying close to literal sentence evidence.

Risk level:
medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`
- `python tools/cli/smoke_small_chunks.py`

Result:
- targeted planning/story-facts suite passed: `39/39`
- small-chunk smoke passed: `PASS`

## Change 16
Files:
src/casforge/generation/feature_assembler.py, test/test_generation_planning.py

Overfit issue addressed:
Assembler domain-family gating that depended too heavily on sparse path nouns and single residual domain terms

Change summary:
- Softened `_scenario_domain_ok(...)` so domain-term mismatch is only a hard reject when both sides have richer domain evidence, not when the comparison reduces to one leftover noun.
- Softened `_same_domain_family(...)` so path-term mismatch no longer overrides clearly matching screen context by itself.
- Filtered generic repo scaffolding terms out of `_path_domain_terms(...)` and `_domain_specific_terms(...)`.
- Added regression tests for same-screen sparse-path cases and for `_scenario_domain_ok(...)` without a single residual domain-term match.

Reason:
The assembler was still carrying a sample-shaped assumption that repo family identity can be reliably inferred from leftover path nouns like `omni` vs `property`. That is too brittle for broader story families.

Risk level:
medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`
- `python tools/cli/smoke_small_chunks.py`

Result:
- targeted planning/assembler suite passed: `41/41`
- small-chunk smoke passed: `PASS`

## Change 17
Files:
src/casforge/shared/paths.py, src/casforge/generation/heuristic_config.py, assets/generation/domain_knowledge.json, assets/generation/planner_hints.json, assets/generation/assembler_hints.json

Overfit issue addressed:
Move stable CAS domain knowledge and generic hint buckets out of Python without migrating sample-specific rescue logic

Change summary:
- Added a strict cached config loader in `heuristic_config.py` for CASForge-owned generation config.
- Added `assets/generation/domain_knowledge.json`, `planner_hints.json`, and `assembler_hints.json`.
- Added `GENERATION_ASSETS_DIR` path wiring for the new config location.
- Enforced config separation by rejecting unsupported top-level keys and disallowed rule-engine style keys like `emit`, `condition`, `effect`, `polarity`, `family_hint`, `title`, `screen_hint`, and `query`.
- Config load failures now degrade conservatively to empty sections instead of restoring hidden Python business defaults.

Reason:
The remaining business/domain phrase banks needed to move out of Python, but the migration had to prevent sample-story rescue logic from simply reappearing in JSON.

Risk level:
medium

Validation run:
- pending

Result:
- pending wiring and behavior validation

## Change 18
Files:
src/casforge/generation/story_facts.py, test/test_generation_planning.py

Overfit issue addressed:
Stable story-facts domain knowledge externalization plus removal of the remaining sample rescue path

Change summary:
- Replaced Python LOB/entity/family/matrix/state-transition tables with reads from `domain_knowledge.json`.
- Removed `_seed_precision_rules(...)` instead of migrating it into config.
- Added generic story-level control inference for ambiguous checkbox sentences using configured entity aliases instead of hardcoded sample outcomes.
- Added compound-clause splitting for movement clauses, tightened state-move acceptance to explicit stage targets only, and kept default-state detection conservative.
- Updated tests to validate semantic derive behavior and canonical field naming after the target normalization cleanup.

Reason:
`story_facts.py` was still the strongest overfit source in the stack. The point of this cycle was to keep only config-backed stable aliases and generic extraction behavior, not preserve sample-family rescue facts.

Risk level:
medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`

Result:
- targeted planning/story-facts suite passed: `41/41`

## Change 19
Files:
src/casforge/generation/scenario_planner.py

Overfit issue addressed:
Planner section/matrix/alias/template buckets moved out of Python into generic config

Change summary:
- Replaced planner section specs, matrix hint terms, target aliases, synthetic entity blocklists, and synthetic templates with reads from `domain_knowledge.json` and `planner_hints.json`.
- Kept deterministic title generation, section selection logic, dedupe, and ranking in Python.
- Synthetic filler now depends on neutral config templates; if those templates are missing or invalid, the planner omits filler instead of restoring hardcoded wording.

Reason:
`scenario_planner.py` still had sample-grown vocabulary and synthetic text in code. This cycle moves only stable section vocabulary and generic planner hints into config while preserving conservative planning behavior.

Risk level:
medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`

Result:
- targeted planning suite passed: `41/41`

## Change 20
Files:
src/casforge/generation/feature_assembler.py

Overfit issue addressed:
Assembler generic retrieval buckets moved out of Python into config

Change summary:
- Replaced assembler LOB aliases, specificity conflicts, family-term buckets, section-term buckets, matrix-term buckets, and path-domain stopwords with reads from `domain_knowledge.json` and `assembler_hints.json`.
- Kept retrieval flow, scope gating, confidence gating, anchor/assertion selection, and `NEW_STEP_NOT_IN_REPO` behavior in Python.
- Simplified matrix alignment to use configured term buckets uniformly instead of keeping domain-specific marker branches in code.

Reason:
`feature_assembler.py` still held the largest remaining bank of business-term buckets in Python. This cycle moves those generic hints into config without reopening weak fallback generation or post-render replacement.

Risk level:
medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`

Result:
- targeted planning/assembler suite passed: `41/41`

## Change 21
Files:
test/test_generation_planning.py

Overfit issue addressed:
Config wiring and conservative degradation are now explicitly test-covered

Change summary:
- Added tests for valid generation-config loading and normalization.
- Added tests for malformed JSON, missing config files, and unknown/disallowed keys degrading to empty sections with warnings.
- Added tests showing that changing domain config changes story-fact behavior, that missing planner config omits synthetic filler, and that missing assembler config does not restore hidden specificity conflicts.

Reason:
The config migration is only trustworthy if the suite proves there are no hidden Python fallbacks and that config failures degrade conservatively instead of silently reviving old heuristics.

Risk level:
low-medium

Validation run:
- `python -m unittest discover -s test -p "test_generation_planning.py"`

Result:
- targeted planning/config suite passed: `48/48`

## Change 22
Files:
README.md, agent/reports/gemini_root_cause_review.md, agent/diagnostics/accuracy_tracker.md, agent/diagnostics/codex_change_log.md, agent/diagnostics/codex_patch_summary.md

Overfit issue addressed:
Documentation and tracker alignment for the config-driven heuristic cleanup

Change summary:
- Documented the ownership boundary between read-only `order.json` and CASForge-owned `assets/generation/*.json` in the repo README.
- Updated the Gemini implementation-status section to reflect that stable story/planner/assembler knowledge has moved into config and that the old story-facts seed rescue path is gone.
- Refreshed the short-form accuracy tracker with the latest validation counts from the config-migration branch.

Reason:
The code changes are only maintainable if future contributors can see where domain knowledge belongs, what remains heuristic, and what the latest validation baseline actually is.

Risk level:
low

Validation run:
- `python -m unittest discover -s test`
- `python -m unittest discover -s test -p "test_generation_planning.py"`
- `python tools/cli/smoke_small_chunks.py`

Result:
- full unit suite passed: `64/64`
- targeted planning/config suite passed: `48/48`
- small-chunk smoke passed: `PASS`

## Change 23
Files:
agent/reports/claude_pickup_handoff_2026-03-15.md, agent/Continuation_Guide.md

Overfit issue addressed:
Handoff/documentation drift after the config-driven cleanup

Change summary:
- Added a Claude-specific pickup handoff with read order, code files to inspect, implemented changes, current validation baseline, ownership boundaries, and remaining problems.
- Replaced the outdated `Continuation_Guide.md` body with a redirect to the current handoff set so future sessions do not restart from stale pre-cleanup assumptions.

Reason:
The branch state changed substantially during the cleanup. Claude needs one current, explicit handoff document instead of rediscovering context across stale guidance plus multiple diagnostics files.

Risk level:
low

Validation run:
- not run (documentation-only step)

Result:
- handoff docs updated for Claude pickup
