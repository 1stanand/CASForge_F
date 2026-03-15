# Codex Patch Summary

Files changed:

- src/casforge/generation/heuristic_config.py
- src/casforge/shared/paths.py
- src/casforge/generation/feature_assembler.py
- src/casforge/generation/scenario_planner.py
- src/casforge/generation/story_facts.py
- assets/generation/domain_knowledge.json
- assets/generation/planner_hints.json
- assets/generation/assembler_hints.json
- test/test_generation_planning.py
- README.md
- agent/Continuation_Guide.md
- agent/reports/gemini_root_cause_review.md
- agent/reports/claude_pickup_handoff_2026-03-15.md
- agent/diagnostics/accuracy_tracker.md
- agent/diagnostics/codex_change_log.md
- agent/diagnostics/codex_patch_summary.md

Key behavior changes:

- Gemini finding #1: weak fallback scenario generation is disabled in the active planning path
- Gemini finding #1: low-confidence or no-anchor intents now remain explicit coverage gaps instead of becoming invented scenarios
- Gemini finding #2: post-render step replacement is disabled in the active grounding path
- Gemini finding #2: unresolved generated steps retain their original text and continue to be marked through `NEW_STEP_NOT_IN_REPO`
- Gemini recommended fix #3: assertion fallback no longer performs an extra loose `Then` search after local and direct retrieval fail
- Gemini recommended fix #3: unresolved `Then` steps now render as explicit `NEW_STEP_NOT_IN_REPO:` assertions instead of generic placeholder expectations
- Gemini finding #3: recommendation-stage mentions no longer create `state_movement` signals or `state_move` effects without actual transition language
- Gemini finding #3: heuristic movement coverage no longer fires from bare stage-name phrases like `Recommendation`
- Gemini finding #4: planner synthetic backfill now only fills uncovered families instead of adding generic duplicates for already-covered families
- Gemini finding #4: synthetic planning now prefers specific business/control entities and omits filler when only generic context entities are available
- Gemini finding #3: heuristic fact extraction now drops ambiguous container/action targets instead of turning them into generic rules
- Gemini finding #3: precision seed rules no longer infer `credit approval stage` from generic `next stage` wording alone
- Gemini finding #3: story-fact normalization now prunes unsupported coverage/matrix signals and reclassifies mis-labeled derive rules more conservatively
- codex overfitting audit follow-up: planner titles now come from deterministic structural templates instead of exact sample-family phrases
- codex overfitting audit follow-up: planner tests now validate semantic target/effect/section behavior rather than exact OMNI recommendation wording
- codex overfitting audit follow-up: planner no longer promotes generic targets into sample-family controls purely from recommendation-stage context or condition substrings
- codex overfitting audit follow-up: planner no longer infers sample UI screens from control names alone
- codex overfitting audit follow-up: planner entity selection now prefers rule-backed specificity over a hand-picked business noun shortlist
- codex overfitting audit follow-up: `story_facts.py` seed rules now operate on explicit sentence evidence in a smaller rescue path instead of broad whole-story sample matching
- codex overfitting audit follow-up: generic target inference no longer upgrades `application level decision` into a recommendation dropdown purely from stage context
- codex overfitting audit follow-up: the `selected as recommended` seed no longer invents a disable rule unless disable/read-only text is explicit
- codex overfitting audit follow-up: assembler domain gating no longer hard-rejects candidates based on one sparse leftover path/domain noun
- codex overfitting audit follow-up: same-screen assertion/domain comparisons now outrank weak path-family mismatches
- diagnostics tracking now includes a short-form accuracy/test tracker and an implementation-status section attached to the Gemini root-cause report
- repository documentation now includes a root README and a Mermaid dependency graph generated from real Python import relationships
- CASForge-owned generation config files now exist under `assets/generation/` with a strict loader that rejects rule-engine style sample hacks instead of migrating them out of Python verbatim
- `story_facts.py` now reads stable domain aliases from `domain_knowledge.json` and no longer contains the old `_seed_precision_rules(...)` sample rescue path
- `scenario_planner.py` now reads section vocabulary, matrix hints, target aliases, synthetic blocklists, and neutral synthetic templates from config instead of keeping those buckets in Python
- `feature_assembler.py` now reads LOB aliases, specificity conflicts, family/section/matrix term buckets, and path-domain stopwords from config instead of keeping those business vocabularies in code
- the regression suite now covers strict config loading, malformed/missing config degradation, behavior changes from config changes, and the absence of hidden Python heuristic fallbacks
- Claude now has a current handoff doc with read order, remaining risks, and exact files to inspect instead of relying on the stale continuation guide

Expected impact:
- higher precision from omitting weakly grounded scenarios
- lower risk of late semantic drift from step rewrites
- fewer incorrect scenarios at the cost of more visible coverage gaps
- more honest assertion gaps when repository evidence is weak or missing
- fewer false movement plans caused by stage-name-only text in story facts
- fewer generic synthetic scenarios when rules already provide family-level coverage
- fewer low-value fallback intents such as generic screen/list validation
- fewer weak story facts with generic targets that distort later planning
- less planner overfitting to OMNI recommendation sample wording
- less downstream assembler coupling to planner intents shaped around `Recommendation Decisions` / `Product Type Decision List`
- less story-understanding dependence on one OMNI recommendation sentence family
- less assembler dependence on repo path naming conventions as a proxy for semantic domain
- more stable future test behavior because planner semantics are checked independently of one exact title style
- easier tracking of which findings are fixed, partially fixed, or still open without re-running the full investigation
- easier audit of heuristic-heavy modules and entrypoint wiring during future cleanup work
- a clean ownership boundary now exists between read-only ATDD workflow config (`order.json`) and CASForge-owned generation heuristics (`assets/generation/*.json`)
- story-fact extraction now prefers omission when a movement target is generic or when a checkbox target cannot be justified from configured aliases plus story context
- planner synthetic filler now degrades to omission if generic templates are missing rather than restoring hardcoded sample-shaped wording
- assembler domain/family/matrix gating now degrades to overlap-and-scope behavior if config buckets are missing instead of restoring hidden Python phrase banks
- planner synthetic filler omission on missing config is now enforced in tests

Overfit removed so far:
- exact planner titles tied to one sample family
- planner synthetic filler for generic context-only entities
- planner duplicate family backfill driven by weak synthetic coverage
- planner stage-name-only movement inference and generic movement targets
- planner target/screen/entity shaping based on recommendation-story shortcuts
- stage-only story-facts target promotion for `application level decision`
- whole-story seed-rule pattern matching for several recommendation-story rescues
- single-term path/domain-family rejection in assembler anchor/assertion gating
- post-render repo step replacement that could corrupt valid generated steps
- weak fallback scenario generation and loose fallback assertion invention

Remaining overfit risks:
- `story_facts.py` still relies on phrase dictionaries and target inference tuned to a small set of business nouns
- retrieval tests are still concentrated around one OMNI recommendation fixture family
- broader non-OMNI retrieval fixtures are still missing even though config-missing degradation is now covered
- some older historical docs may still describe pre-cleanup behavior, but `claude_pickup_handoff_2026-03-15.md` and the current diagnostics files are now the intended source of truth

Latest validation:
- `python -m unittest discover -s test`: `64/64`
- `python -m unittest discover -s test -p "test_generation_planning.py"`: `48/48`
- `python tools/cli/smoke_small_chunks.py`: `PASS`

Residual weaknesses:
- some valid stories may now omit scenarios rather than receiving a guessed target/screen interpretation
- `story_facts.py` remains the biggest source of sample-family semantics entering the stack, even after reducing the seed surface
- `feature_assembler.py` still inherits planner metadata and can amplify narrow entity/screen assumptions that remain upstream

What may need Claude-level architectural review later:
- replacing or shrinking `_seed_precision_rules(...)` without collapsing story understanding quality
- simplifying `feature_assembler.py` scoring/gating so repo-faithful selection depends less on hand-built phrase buckets
- broadening regression coverage beyond the OMNI recommendation family without rebuilding the test strategy from scratch
