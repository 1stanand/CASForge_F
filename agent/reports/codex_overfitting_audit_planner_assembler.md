# Planner / Assembler Overfitting Audit

No explicit story-ID handling was found in either file. The overfit pattern is mostly phrase-level and test-coupled: fixed canonical titles, narrow entity rewrites, sample-family screen mappings, and retrieval gates that assume a small set of known repo domains.

## `src/casforge/generation/scenario_planner.py`

### 1. Exact sample-shaped title generation
File: `src/casforge/generation/scenario_planner.py:499-543`

Suspicious logic:
- `_title_from_rule(...)`
- Fixed outputs such as:
  - `Display Decision column in Product Type Decision List`
  - `Keep Decision checkboxes checked by default`
  - `Display Decision checkbox for sub products`
  - `Keep Recommendation Decision dropdown disabled`
  - `Disable Recommended Limit when any subloan is not recommended`
  - `Move application to Credit Approval from Recommendation`

Why this looks overfit:
- These are not generic title templates. They are exact, repo-style titles for one narrow recommendation/subloan family.
- The function is shaping planner output toward known expected wording, not just normalizing extracted facts.
- The `state_move` branch hardwires `Credit Approval` from `Recommendation`, which is a specific business flow, not a general planner behavior.

What should happen:
- Generalize.
- Keep deterministic title generation, but derive titles from canonical target/effect/scope instead of returning story-family-specific phrases.
- Stage movement should only name a specific destination when the extracted rule explicitly names it.

Current tests reinforcing it:
- `test/test_generation_planning.py:96-99`
- Those assertions lock exact titles instead of validating intent structure, effect, scope, and section.

### 2. Narrow canonical rewrites for one story family
File: `src/casforge/generation/scenario_planner.py:565-583`

Suspicious logic:
- `_canonical_plan_target(...)`
- Rewrites:
  - `application level decision` -> `Recommendation Decision dropdown` only at `Recommendation`
  - `decision checkbox` -> card-grid or sub-loan-grid variants from condition text
  - direct special-casing of `credit approval stage`

Why this looks overfit:
- These rewrites assume the extracted text belongs to the OMNI recommendation/sub-product UI family.
- The planner is not just canonicalizing generic controls; it is injecting business-screen semantics from a few known story patterns.
- This can mis-shape plans for future stories that use similar words differently.

What should happen:
- Gate or generalize.
- Keep only canonical rewrites that are valid across many stories.
- Narrow stage/screen-specific rewrites should require explicit entity evidence from facts, not just a condition substring.

Current tests reinforcing it:
- `test/test_generation_planning.py:475-497`
- `test/test_generation_planning.py:607-677`

### 3. Hardcoded screen mapping to sample UI nouns
File: `src/casforge/generation/scenario_planner.py:587-595`

Suspicious logic:
- `_screen_hint_for_rule(...)`
- Returns `Recommendation Decisions` and `Product Type Decision List` from target names alone.

Why this looks overfit:
- The planner is inferring exact screen labels from a small fixed set of control names.
- This works for the current sample family because those screen names are stable in the reference repo.
- It is not a general mechanism for arbitrary Jira stories.

What should happen:
- Generalize.
- Prefer explicit `screen_hint` from extracted facts or story UI path.
- Only infer a screen from a target if the target-to-screen mapping is repo-wide and stable, not sample-family-specific.

Current tests reinforcing it:
- `test/test_generation_planning.py:459-497`
- `test/test_generation_planning.py:521-534`

### 4. Synthetic plan templates still assume sub-product style behavior
File: `src/casforge/generation/scenario_planner.py:270-307`

Suspicious logic:
- `_synthetic_items_from_signals(...)`
- Sample-shaped templates:
  - `Resolve {primary_entity} enablement from sub selection`
  - `Derive {primary_entity} from selected sub products`
  - `Move application with {primary_entity} to next stage`
  - `Handle mixed {primary_entity} combinations correctly`

Why this looks overfit:
- These are not neutral fallbacks. They assume dependency and derivation usually come from sub-product selection.
- They fit the current sample family well, but they are weak for committee flows, process-state stories, or non-grid logic.
- Even after recent conservative tightening, the phrase templates still carry sample-family semantics.

What should happen:
- Generalize or gate harder.
- Synthetic items should stay generic unless the relevant source signals explicitly mention sub products, matrix behavior, or stage movement.
- If that evidence is absent, omission is safer than emitting a shaped synthetic intent.

Current tests reinforcing it:
- `test/test_generation_planning.py:117-131`
- `test/test_generation_planning.py:151-185`

### 5. Entity ranking is biased toward a hand-picked sample shortlist
File: `src/casforge/generation/scenario_planner.py:606-636`

Suspicious logic:
- `_best_entity(...)`
- `_best_entity_from_facts(...)`
- Ranking seed string:
  - `decision checkbox recommendation decision dropdown recommended limit recommended amount committee verdict decision column`

Why this looks overfit:
- The shortlist is a small hand-authored set of entities taken from current story families.
- This means planner prioritization quality depends on whether a future story resembles those exact entities.
- It is a strong signal that entity preference was tuned from sample outputs and tests.

What should happen:
- Generalize.
- Rank by specificity, overlap with extracted rules, and explicit story evidence rather than a baked-in preferred-entity phrase bank.
- If a shortlist remains, it should be framed as a minimal repo-wide allowlist and tested across several families.

Current tests reinforcing it:
- `test/test_generation_planning.py:151-160`
- `test/test_generation_planning.py:178-185`

### 6. Section classification still contains one narrow screen-specific shortcut
File: `src/casforge/generation/scenario_planner.py:707-744`

Suspicious logic:
- `_section_for_plan(...)`
- Shortcut:
  - if `"decision"` in target and `"product type decision list"` in screen -> `decision_logic`

Why this looks overfit:
- That shortcut is tied to one known UI container from the sample recommendation flow.
- It bypasses more general effect/family-based sectioning.

What should happen:
- Remove or gate.
- Sectioning should prefer generic effect/family evidence.
- Screen-name shortcuts should only exist if they represent a cross-repo convention, not one screen family.

Current tests reinforcing it:
- Indirectly reinforced by exact title/section assertions in `test/test_generation_planning.py:96-99`

### 7. Sample-grown blocklists for synthetic entities
File: `src/casforge/generation/scenario_planner.py:102-109` and `src/casforge/generation/scenario_planner.py:820-829`

Suspicious logic:
- `_SYNTHETIC_ENTITY_BLOCKLIST`
- `_synthetic_entity_specific_enough(...)`

Why this looks overfit:
- The blocklist names concrete entities from current story families: `product type decision list`, `credit approval stage`, `mtns`, `application stage movement`.
- This is conservative and safer than forcing output, but it is still a sample-grown fix list.

What should happen:
- Gate, not remove.
- This is one of the safer heuristics in the file, but it should stop growing ad hoc.
- Tests should validate the principle “generic containers do not produce synthetic intents” rather than locking specific blocked entity strings.

Current tests reinforcing it:
- `test/test_generation_planning.py:151-185`
- `test/test_generation_planning.py:311-338`

## `src/casforge/generation/feature_assembler.py`

### 1. Hardcoded specificity conflicts for a few known entity families
File: `src/casforge/generation/feature_assembler.py:126-129` and `src/casforge/generation/feature_assembler.py:1740-1752`

Suspicious logic:
- `_SPECIFICITY_CONFLICTS`
- `_has_specificity_conflict(...)`
- Explicit marker families for:
  - credit card / primary card / add-on card
  - sub loan / subloan
  - checkbox variants

Why this looks overfit:
- These are narrow domain families encoded as global rejection rules.
- The logic is useful for the current sample retrieval path, but it does not scale well to other domains unless each family gets its own handcrafted conflict set.
- This is the same anti-pattern seen in `story_facts.py`: a small set of learned business nouns becomes infrastructure logic.

What should happen:
- Gate or generalize.
- Keep conflict checks only where there is broad repo evidence they prevent real false positives.
- Prefer explicit entity hierarchy metadata when available; until then, this logic should stay minimal and test-backed across multiple families.

Current tests reinforcing it:
- `test/test_generation_planning.py:653-677`
- `test/test_generation_planning.py:683-691`

### 2. Domain gating depends heavily on leftover repo-path nouns
File: `src/casforge/generation/feature_assembler.py:774-820` and `src/casforge/generation/feature_assembler.py:1782-1790`

Suspicious logic:
- `_scenario_domain_ok(...)`
- `_domain_specific_terms(...)`
- The generic-token filter removes most common workflow words, so the surviving domain evidence is often a small set of nouns like `omni`, `subloan`, `committee`, `viewer`.

Why this looks overfit:
- This works because the current repo and tests expose clear path/screen nouns for the sample families.
- It is less a semantic match than a “do the leftover repo nouns match?” gate.
- Stories whose valid anchors do not share those surviving nouns can be unfairly rejected.

What should happen:
- Generalize.
- Domain gating should rely more on extracted target/screen evidence and scope tags, less on path-derived residual nouns.
- If kept, this should be a soft score bonus before rejection, not a strong hard gate for multiple sections.

Current tests reinforcing it:
- `test/test_generation_planning.py:407-449`
- `test/test_generation_planning.py:737-777`
- The repeated OMNI-vs-property-viewer setup strongly trains the code toward path-family discrimination.

### 3. Assertion retrieval “same domain family” check is tied to repo naming conventions
File: `src/casforge/generation/feature_assembler.py:1566-1588`

Suspicious logic:
- `_same_domain_family(...)`
- `_path_domain_terms(...)`

Why this looks overfit:
- Assertions are kept or rejected partly by file path terms and screen-label overlap.
- That is pragmatic, but it assumes reference-repo directories and scenario screens cleanly encode domain boundaries.
- It is especially shaped around the current sample contrast between OMNI features and “property viewer” negatives.

What should happen:
- Gate, not remove.
- As a conservative safety check this is understandable, but it should be treated as a weak domain hint rather than a strict family identity rule when explicit scope data is sparse.
- Tests should include several unrelated positive families, not only one positive family plus one negative family.

Current tests reinforcing it:
- `test/test_generation_planning.py:539-601`
- `test/test_generation_planning.py:737-777`

### 4. Family / section / matrix matching are still tuned to a small set of business phrases
File: `src/casforge/generation/feature_assembler.py:909-1017`

Suspicious logic:
- `_family_matches_context(...)`
- `_section_alignment_bonus(...)`
- `_matrix_alignment_bonus(...)`
- Narrow marker sets include:
  - `credit`, `recommendation`, `approval`, `reconsideration`
  - `dependent_card`
  - `credit_card`
  - `subloan`

Why this looks overfit:
- These gates and bonuses are effective for the current story families, but they are still phrase buckets learned from a narrow corpus.
- The `matrix_signature` bonuses especially encode known subloan/card patterns rather than a general matrix framework.
- This is not explicit sample cheating, but it is clearly shaped around a few business areas.

What should happen:
- Generalize and test differently.
- Keep section/family scoring, but reduce business-phrase dependence.
- Future tests should verify behavior across multiple unrelated feature families before adding new marker sets.

Current tests reinforcing it:
- `test/test_generation_planning.py:459-497`
- `test/test_generation_planning.py:521-677`

### 5. Planner-output coupling is stronger than raw-story generalization
File: `src/casforge/generation/feature_assembler.py:455-500`, `src/casforge/generation/feature_assembler.py:822-834`

Suspicious logic:
- `_intent_anchor_context(...)`
- `_candidate_rejection_reason(...)`

Why this looks overfit:
- The assembler relies on planner-provided fields such as `section_key`, `pattern_terms`, `entity`, `target_field`, and exact expected outcomes.
- Because the planner is already sample-shaped in several places, the assembler inherits those assumptions and turns them into hard retrieval gates.
- This is less direct overfit in the assembler and more downstream amplification of planner overfit.

What should happen:
- Test differently and generalize upstream first.
- Tightening assembler gates further will not fix the underlying issue if planner intents remain narrowly canonicalized.
- Broader tests should validate that different phrasings of the same behavior still assemble correctly.

Current tests reinforcing it:
- Most retrieval tests in `test/test_generation_planning.py:407-991` use planner-shaped intents rather than raw-story-derived variety.

## Tests Most Clearly Reinforcing Overfit

### Strongest test-coupled overfit in planner
File: `test/test_generation_planning.py:96-99`

Why:
- This locks exact scenario titles for one sample family.
- It encourages future code changes to preserve those titles verbatim rather than preserve the underlying semantics.

Recommended change:
- Test section classification, target/effect preservation, and specificity instead of exact phrasing.

### Retrieval tests rely heavily on one OMNI recommendation family
File: `test/test_generation_planning.py:407-777`

Why:
- The positive fixtures repeatedly use:
  - `OMNI`
  - `Recommendation`
  - `Product Type Decision List`
  - `Recommendation Decisions`
  - `SeparateDecision...feature`
- The negative fixture is frequently `property viewer`.
- That is useful as one regression pack, but it does not prove generalization.

Recommended change:
- Keep these tests, but add parallel fixtures from at least two unrelated domains before trusting the heuristics.

### Conservative anti-hallucination tests are good and should stay
File: `test/test_generation_planning.py:782-991`

Why:
- These tests enforce desirable behavior:
  - no weak scaffold plan
  - no weak fallback plan
  - preserve `NEW_STEP_NOT_IN_REPO`
  - do not silently replace unresolved steps
- These are not overfit problems; they are safety rails.

Recommended change:
- Keep as-is.

## Bottom Line

1. The heavier overfit is in `scenario_planner.py`, especially exact-title shaping, narrow canonical rewrites, screen inference, and entity ranking.
2. `feature_assembler.py` is less obviously sample-cheating, but several retrieval gates are still tuned to a small set of known business nouns and repo naming conventions.
3. The test suite currently reinforces planner overfit most strongly through exact expected titles and a retrieval fixture set dominated by one OMNI recommendation family.
4. The safest cleanup order would be:
   - generalize planner title / target / screen shaping first
   - then soften or rebalance assembler domain-family gates
   - then broaden tests so they validate general behavior, not one sample family
