# Gemini Root Cause Review - CASForge

## 1. Executive Summary

The CASForge system's inability to surpass ~40% manual effort reduction is not due to a single failed component but a systemic issue rooted in a flawed design philosophy: it prioritizes generating a complete feature file over a semantically accurate one. The pipeline is built on a cascade of brittle, heuristic-based modules that amplify uncertainty rather than resolving it. When faced with ambiguity—a common occurrence with complex business stories—the system falls back to generating syntactically valid but logically incorrect scenarios, leading to low-quality, untrustworthy output that requires significant manual correction.

## 2. Most Likely Primary Bottleneck

**`src/casforge/generation/feature_assembler.py` is the primary bottleneck.**

This module is the epicenter of the quality issues. It receives ambiguous and often low-quality "plans" from the upstream `scenario_planner.py`. Instead of flagging this ambiguity, it employs an extremely complex and fragile set of heuristics, fallbacks, and post-processing steps to force the creation of a complete feature file at all costs. This includes selecting poorly-matched "anchor" scenarios, retrieving irrelevant assertions, and generating generic, incorrect steps.

## 3. Top 5 Root-Cause Findings

1.  **Aggressive Fallback Mechanisms Invent Bad Scenarios:** When the assembler cannot find a high-confidence anchor scenario from the repository, it enters `_build_scaffold_plan_from_related_hits` and `_build_fallback_plan`. This creates scenarios from weak or tangentially related data, which is a primary source of business logic errors. The system invents work instead of admitting a gap.
2.  **Dangerous Post-Render "Grounding" Corrupts Good Steps:** The `_ground_steps_to_repo` function performs a final pass to replace generated steps with existing repository steps. Its matching thresholds are too loose, causing it to swap correctly generated (but new) steps for existing, semantically different ones based on superficial text similarity. This silently corrupts the logic of an otherwise correct scenario.
3.  **Initial Story Understanding is Brittle and Overfit:** `story_facts.py` relies on hardcoded, regex-heavy heuristics (`_seed_precision_rules`, `_heuristic_rule`) that are overfitted to specific story formats. When these fail, the system either works with sparse, incorrect "facts" or falls back to an LLM call with insufficient context, leading to a poor foundational understanding of the story's requirements.
4.  **Synthetic Plan Generation Fills Gaps with Generic Tests:** When `story_facts.py` provides insufficient data, `scenario_planner.py` resorts to creating generic scenarios (`_synthetic_items_from_signals`) based on broad "coverage signals." This results in low-value, generic tests (e.g., "Validate {primary_entity}") that do not reflect the specific, nuanced requirements of the business story.
5.  **Overly Complex and Fragile Heuristics:** The entire generation pipeline, particularly `feature_assembler.py`, is a tower of interdependent heuristics for scoring, ranking, filtering, and selection. Functions like `_select_scenario_anchor` and `_is_assertion_relevant` involve dozens of calculations and magic numbers. This extreme complexity makes the system unpredictable and highly sensitive to small variations in input text, causing a cascade of failures.

## 4. File-level Inspection Priority

The investigation should be laser-focused. The problem is well-defined and contained within the generation logic.

1.  **`src/casforge/generation/feature_assembler.py`**: This is the #1 priority. The logic within `_plan_scenarios`, `_select_anchor_variants`, and especially `_ground_steps_to_repo` must be inspected and refactored.
2.  **`src/casforge/generation/story_facts.py`**: The second priority. The heuristic-based extraction in `infer_story_facts_heuristically` and `_seed_precision_rules` should be reviewed to understand the source of the low-quality input fed into the rest of the system.
3.  **`src/casforge/generation/scenario_planner.py`**: The third priority. The `_synthetic_items_from_signals` function is the key area to inspect to see how generic scenarios are being created.

## 5. Recommended Fixes in Order

1.  **Disable and Refactor the "Grounding" Pass:** Immediately modify `_ground_steps_to_repo`. Instead of replacing steps, it should only *report* steps that do not exist in the repository. The "NEW_STEP_NOT_IN_REPO" marker is the correct behavior; auto-replacement is too dangerous and must be removed. This is the single most impactful change to stop the system from corrupting its own output.
2.  **Remove Fallback Scenario Generation:** Disable the fallback mechanisms in `feature_assembler.py` (`_build_fallback_plan`, `_build_scaffold_plan_from_related_hits`). If no high-confidence anchor can be found, the system should treat it as a "coverage gap" and omit the scenario, as the documentation suggests. This will increase the honesty and accuracy of the output, even if it means generating fewer scenarios initially.
3.  **Simplify and Harden Assertion Retrieval:** The logic for finding `Then` steps (`_retrieve_assertions`, `_fallback_then_step`) should be simplified. If a high-confidence assertion cannot be found from the local anchor or a direct retrieval, the step should be explicitly marked as unresolved (e.g., `Then Then NEW_STEP_NOT_IN_REPO: <expected outcome>`), not replaced with a generic fallback like "expected behaviour should be observed".
4.  **Deprecate Heuristic Fact/Plan Generation:** The long-term solution is to move away from the brittle heuristics in `story_facts.py` and `scenario_planner.py`. The system should lean more heavily on a properly-prompted LLM to produce a structured plan directly from the Jira story, which the assembler can then execute. The current heuristic-first approach is the architectural source of the problem.
5.  **Refactor `feature_assembler.py` for Simplicity:** As recommended in `agent/NextSteps.md`, this monolithic file should be broken into smaller, more focused modules (e.g., `anchor_selection`, `assertion_resolution`, `feature_renderer`). This will make the logic easier to understand, debug, and safely modify.

## 6. Risks / Possible Misreads in Current Docs

The project documentation is surprisingly self-aware and accurate, but some parts might inspire overconfidence:

-   **`Continuation_Guide.md`**: It states "Retrieval remains a core strength." While true for finding *documents*, the assembler's ability to select the *correct* anchor from those retrieved documents is the issue. The strength in retrieval doesn't translate to strength in generation.
-   **`PIPELINE_OVERVIEW.md`**: It says "planning is deterministic." This is true, but it's deterministically processing flawed inputs, which consistently leads to flawed outputs.
-   **General Tone**: The documents correctly identify many of the symptoms (e.g., weak fallback, issues with default-state handling). However, they frame them as small, incremental "next steps" (`Fix default-state behavior`). My analysis suggests the problem is more fundamental to the generation philosophy and requires more significant architectural changes than just tweaking individual behaviors. The core issue is the system's aversion to admitting when it doesn't know what to do.

## 7. Implementation Status (Codex, 2026-03-15)

This section tracks which findings have already been addressed in the current branch.

1. **Finding #1: Aggressive fallback mechanisms invent bad scenarios**
   Status: partially addressed
   - weak fallback scenario generation in `feature_assembler.py` has been disabled/restricted
   - low-confidence or no-anchor cases now prefer coverage gaps and omitted items over invented scenarios

2. **Finding #2: Dangerous post-render grounding corrupts good steps**
   Status: addressed
   - post-render step replacement in `_ground_steps_to_repo` has been disabled/restricted
   - unresolved generated steps now stay visible through `NEW_STEP_NOT_IN_REPO`

3. **Finding #3: Initial story understanding is brittle and overfit**
   Status: partially addressed
   - stage-name-only movement extraction was reduced
   - ambiguous target/effect facts are now dropped more often
   - noisy `default_state`, `validation`, and related family labels are pruned more conservatively
   - stage-only promotion of `application level decision` into `recommendation decision dropdown` has been removed from generic target inference
   - stable LOB/entity/stage/family/matrix vocabularies are now loaded from `assets/generation/domain_knowledge.json`
   - `_seed_precision_rules(...)` has been removed instead of being migrated into config

4. **Finding #4: Synthetic plan generation fills gaps with generic tests**
   Status: partially addressed
   - synthetic backfill now prefers uncovered families only
   - generic context entities are blocked from creating weak filler intents
   - planner target/screen/entity shaping has been reduced so synthetic and rule-backed plans depend less on sample-family shortcuts
   - planner section vocabulary, matrix hints, target aliases, synthetic blocklists, and neutral synthetic templates are now loaded from CASForge-owned config

5. **Finding #5: Overly complex and fragile heuristics**
   Status: partially addressed
   - planner title generation, canonical target shaping, screen inference, and entity ranking have been made less sample-coupled
   - assembler domain-family gating now depends less on sparse path/domain nouns alone
   - generic assembler LOB aliases, specificity conflicts, family/section/matrix buckets, and path-domain stopwords are now loaded from CASForge-owned config
   - the system is still heavily heuristic-driven, especially in `feature_assembler.py`, and the remaining cleanup likely needs broader design work plus more diverse fixtures

Measured effect so far:
- real-sample comparison `run1 -> run2` improved aggregate grounding rate from `66.1%` to `71.8%`
- total `NEW_STEP_NOT_IN_REPO` markers across the tracked samples improved from `33` to `24`
- the gain came primarily from reducing weak speculative planning on the weaker committee-style sample while leaving the stronger omni sample stable
- latest validation after config migration:
  - `python -m unittest discover -s test`: `64/64` passed
  - `python -m unittest discover -s test -p "test_generation_planning.py"`: `48/48` passed
  - `python tools/cli/smoke_small_chunks.py`: `PASS`
