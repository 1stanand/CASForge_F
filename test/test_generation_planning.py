import unittest
from unittest.mock import patch

from casforge.generation import feature_assembler as fa
from casforge.generation.intent_extractor import _parse_intent_records, _assign_ids_and_scope, infer_story_scope_defaults
from casforge.generation.scenario_planner import build_scenario_plan_items
from casforge.generation.story_facts import extract_story_facts, infer_story_facts_heuristically
from casforge.parsing.jira_parser import JiraStory


class IntentPlanningHintTests(unittest.TestCase):
    def test_parse_intent_records_keeps_planning_hints(self):
        raw = (
            '[{"text":"Display committee decision for omni sub products",'
            '"family":"positive",'
            '"action_target":"committee decision",'
            '"screen_hint":"Committee Decision",'
            '"expected_outcome":"display"}]'
        )
        records = _parse_intent_records(raw)
        assigned = _assign_ids_and_scope(records, None)
        self.assertEqual(assigned[0]["action_target"], "committee decision")
        self.assertEqual(assigned[0]["screen_hint"], "Committee Decision")
        self.assertEqual(assigned[0]["expected_outcome"], "display")


class StoryScopeInferenceTests(unittest.TestCase):
    def test_infer_story_scope_defaults_prefers_heading_stage_and_omni_lob(self):
        story = JiraStory(
            issue_key='CAS-264757',
            summary='Separate Credit Approval decision at the sub loan level under OMNI Loan - Recommendation',
            issue_type='Story',
            description='',
            current_process='',
            new_process='RECOMMENDATION\n* A new column decision is required for omni loan sub products.',
            business_scenarios='',
            impacted_areas='',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        defaults = infer_story_scope_defaults(story)
        self.assertEqual(defaults['lob_scope'], {'mode': 'specific', 'values': ['OMNI']})
        self.assertEqual(defaults['stage_scope'], {'mode': 'specific', 'values': ['Recommendation']})


class StoryFactsAndPlannerTests(unittest.TestCase):
    def _story(self) -> JiraStory:
        return JiraStory(
            issue_key='CAS-264757',
            summary='Separate Credit Approval decision at the sub loan level under OMNI Loan - Recommendation',
            issue_type='Story',
            description='',
            current_process='',
            new_process=(
                'RECOMMENDATION\n'
                '* A new column decision is required in product type decision list for all the sub loans.\n'
                '* By default all the checkboxes will come checked when user lands on recommendation stage.\n'
                '* If any subloan is not recommended then recommended limit field will be disabled and application will move to credit approval.'
            ),
            business_scenarios='Zero recommended amount should not be allowed for not recommended subloan.',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='Display decision checkbox for sub loans and move application with all subloans to credit approval.',
            story_description='',
        )

    def test_story_facts_detect_entities_rules_and_matrix(self):
        facts = infer_story_facts_heuristically(self._story())
        self.assertIn('decision checkbox', facts['entities'])
        self.assertIn('recommended limit', facts['entities'])
        self.assertTrue(any(rule['effect'] == 'disable' for rule in facts['rules']))
        self.assertIn('field_enablement', facts['coverage_signals'])
        self.assertIn('state_movement', facts['coverage_signals'])
        self.assertIn('any', facts['matrix_signals'])

    def test_planner_builds_short_structured_items(self):
        defaults = infer_story_scope_defaults(self._story())
        facts = infer_story_facts_heuristically(self._story(), defaults)
        plan_items = build_scenario_plan_items(self._story(), story_scope_defaults=defaults, story_facts=facts)
        self.assertGreaterEqual(len(plan_items), 4)
        self.assertTrue(any(item['family'] == 'dependency' for item in plan_items))
        self.assertTrue(any(item['family'] == 'state_movement' for item in plan_items))
        for item in plan_items:
            self.assertLessEqual(len(item['text'].split()), 14)
            self.assertTrue(item['must_anchor_terms'])
            self.assertNotIn('user logs in', item['text'].lower())

    def test_planner_assigns_repo_style_sections(self):
        defaults = infer_story_scope_defaults(self._story())
        facts = infer_story_facts_heuristically(self._story(), defaults)
        plan_items = build_scenario_plan_items(self._story(), story_scope_defaults=defaults, story_facts=facts)
        sections = {item['text']: item.get('section_title') for item in plan_items}
        self.assertEqual(sections.get('Display Decision column in Product Type Decision List'), 'UI Structure Validation')
        self.assertEqual(sections.get('Keep Decision checkboxes checked by default'), 'Checkbox Availability & Default State')
        self.assertEqual(sections.get('Disable Recommended Limit when any subloan is not recommended'), 'Field Enablement Behaviour')
        self.assertEqual(sections.get('Move application to Credit Approval from Recommendation'), 'Move To Next Stage Validations')

    @patch("casforge.generation.story_facts.llm_client.chat")
    def test_extract_story_facts_skips_llm_for_strong_heuristic_story(self, mock_chat):
        defaults = infer_story_scope_defaults(self._story())
        facts = extract_story_facts(self._story(), story_scope_defaults=defaults)
        self.assertGreaterEqual(len(facts["rules"]), 6)
        mock_chat.assert_not_called()

    @patch("casforge.generation.story_facts.llm_client.chat")
    def test_extract_story_facts_preserves_specific_scope_over_overlay(self, mock_chat):
        mock_chat.return_value = (
            '{'
            '"story_scope_defaults":{'
            '"lob_scope":{"mode":"specific","values":["HL"]},'
            '"stage_scope":{"mode":"specific","values":["Credit Approval"]}'
            '},'
            '"entities":["decision checkbox"],'
            '"rules":[]'
            '}'
        )
        defaults = {
            "lob_scope": {"mode": "specific", "values": ["OMNI"]},
            "stage_scope": {"mode": "specific", "values": ["Recommendation"]},
        }
        weak_story = JiraStory(
            issue_key="CAS-000001",
            summary="Decision column support",
            issue_type="Story",
            description="",
            current_process="",
            new_process="A new decision support is required.",
            business_scenarios="",
            impacted_areas="",
            key_ui_steps="",
            acceptance_criteria="",
            story_description="",
        )
        facts = extract_story_facts(weak_story, story_scope_defaults=defaults)
        self.assertEqual(facts["story_scope_defaults"]["lob_scope"], defaults["lob_scope"])
        self.assertEqual(facts["story_scope_defaults"]["stage_scope"], defaults["stage_scope"])
        mock_chat.assert_called_once()


class RetrievalFirstAssemblyTests(unittest.TestCase):
    def _hit(
        self,
        *,
        step_text: str,
        keyword: str = "When",
        score: float = 0.75,
        file_path: str,
        scenario_title: str,
        screen_context: str,
        then_text: str,
        stage: str = "Recommendation",
        product: str = "OMNI",
    ) -> dict:
        scenario_steps = [
            {"keyword": "Given", "step_text": f'user is on {screen_context} screen', "screen_context": screen_context},
            {"keyword": "And", "step_text": 'relevant setup data is available', "screen_context": screen_context},
            {"keyword": keyword, "step_text": step_text, "screen_context": screen_context},
            {"keyword": "Then", "step_text": then_text, "screen_context": screen_context},
        ]
        return {
            "step_id": abs(hash((file_path, scenario_title, step_text))) % 100000,
            "step_text": step_text,
            "keyword": keyword,
            "score": score,
            "screen_context": screen_context,
            "scenario_title": scenario_title,
            "file_path": file_path,
            "file_name": file_path.split("/")[-1],
            "scenario_steps": scenario_steps,
            "scope_stage_tags": ["@Recommendation" if stage.lower() == "recommendation" else f"@{stage.replace(' ', '')}"],
            "scope_sub_tags": ["@CommitteeDecision"],
            "scope_product_types": [product],
            "scope_application_stages": [stage],
        }

    @patch("casforge.generation.feature_assembler.search")
    def test_anchor_selection_prefers_same_domain_scenario(self, mock_search):
        mock_search.return_value = [
            self._hit(
                step_text='user confirms separate decision for omni sub products',
                score=0.81,
                file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
                scenario_title='Separate decision at recommendation',
                screen_context='Committee Decision',
                then_text='separate decision should be displayed for selected sub products',
            ),
            self._hit(
                step_text='user confirms separate decision for omni sub products',
                score=0.96,
                file_path='workspace/reference_repo/Features/collateral/property/Viewer.feature',
                scenario_title='Property viewer decision check',
                screen_context='Property Viewer',
                then_text='property viewer details should be displayed',
            ),
        ]
        intent = {
            "id": "intent_001",
            "text": "Display separate decision for omni sub products",
            "family": "positive",
            "action_target": "separate decision",
            "screen_hint": "Committee Decision",
            "expected_outcome": "display",
            "entity": "sub product decision",
            "target_field": "decision column",
            "expected_state": "display",
            "polarity": "positive",
            "must_anchor_terms": ["separate decision", "omni sub products"],
            "must_assert_terms": ["display", "decision"],
            "forbidden_terms": ["property viewer"],
            "section_key": "decision_logic",
            "section_title": "Decision Logic Behaviour",
            "pattern_terms": ["decision", "recommended", "dropdown"],
        }
        scope = {
            "lob_scope": {"mode": "specific", "values": ["OMNI"]},
            "stage_scope": {"mode": "specific", "values": ["Recommendation"]},
        }

        anchors, removed, relaxed, rejected = fa._select_anchor_variants(intent, scope, "@Recommendation", 1)
        self.assertEqual(relaxed, 0)
        self.assertEqual(len(anchors), 1)
        self.assertIn('/omni/', anchors[0]["file_path"].lower())
        self.assertEqual(anchors[0]["screen_context"], "Committee Decision")
        self.assertIsInstance(rejected, dict)

    @patch("casforge.generation.feature_assembler.search")
    def test_section_aware_anchor_scoring_prefers_ui_structure_scenario(self, mock_search):
        mock_search.return_value = [
            self._hit(
                step_text='user clicks on Product Type Decision List accordion to expand it',
                score=0.82,
                file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
                scenario_title='Availability of New Column In Product Type Decision List in Omni Loan at Recommendation Stage',
                screen_context='Product Type Decision List',
                then_text='user should be able to see the new column "Decision"',
            ),
            self._hit(
                step_text='user clicks on Product Type Decision List accordion to expand it',
                score=0.86,
                file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
                scenario_title='Availability of Enabled Checkbox in Decision Column of Product Type Decision List for Sub Product Types of Omni Loan',
                screen_context='Product Type Decision List',
                then_text='user should be able to see a CheckBox type input field in Decision Column for sub product',
            ),
        ]
        intent = {
            "id": "intent_001",
            "text": "Display Decision column in Product Type Decision List",
            "family": "positive",
            "action_target": "decision column",
            "screen_hint": "Product Type Decision List",
            "expected_outcome": "display",
            "entity": "decision column",
            "target_field": "decision column",
            "expected_state": "display",
            "polarity": "positive",
            "must_anchor_terms": ["decision column", "product type decision list"],
            "must_assert_terms": ["display", "column"],
            "forbidden_terms": ["checkbox"],
            "section_key": "ui_structure",
            "section_title": "UI Structure Validation",
            "pattern_terms": ["new column", "availability", "display"],
        }
        scope = {
            "lob_scope": {"mode": "specific", "values": ["OMNI"]},
            "stage_scope": {"mode": "specific", "values": ["Recommendation"]},
        }

        anchors, _, _, _ = fa._select_anchor_variants(intent, scope, "@Recommendation", 1)
        self.assertEqual(len(anchors), 1)
        self.assertIn('new column', anchors[0]['scenario_title'].lower())

    def test_scope_gate_accepts_unordered_title_context_without_explicit_metadata(self):
        hit = self._hit(
            step_text='user clicks on Product Type Decision List accordion to expand it',
            score=0.88,
            file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
            scenario_title='Availability of New Column In Product Type Decision List in Omni Loan at Recommendation Stage',
            screen_context='Recommendation Decisions',
            then_text='user should be able to see the new column "Decision"',
        )
        hit['scope_stage_tags'] = []
        hit['scope_application_stages'] = []
        hit['scope_product_types'] = []
        scope = {
            'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
            'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
        }
        self.assertTrue(fa._hit_in_scope(hit, scope))

    def test_synthetic_action_anchor_recovers_when_only_then_hit_is_retrieved(self):
        then_hit = self._hit(
            keyword='Then',
            step_text='Recommendation Decision dropdown for Recommendation Decisions should be "<isEnabled>"',
            score=0.84,
            file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
            scenario_title='Recommendation Decision Dropdown should be Disabled for Omni Loan at Recommendation Stage',
            screen_context='Recommendation Decisions',
            then_text='Recommendation Decision dropdown for Recommendation Decisions should be "<isEnabled>"',
        )
        then_hit['scenario_steps'] = [
            {'keyword': 'When', 'step_text': 'user scrolls down to Recommendation Decisions', 'screen_context': 'Recommendation Decisions'},
            {'keyword': 'Then', 'step_text': 'Recommendation Decision dropdown for Recommendation Decisions should be "<isEnabled>"', 'screen_context': 'Recommendation Decisions'},
        ]
        anchor = fa._pick_group_anchor_step([then_hit], 'Disable application level decision if any subloan is selected as recommended')
        self.assertEqual(anchor['keyword'], 'When')
        self.assertEqual(anchor['step_text'], 'user scrolls down to Recommendation Decisions')

    @patch("casforge.generation.feature_assembler.search")
    def test_assertion_retrieval_stays_in_anchor_domain(self, mock_search):
        anchor = self._hit(
            step_text='user confirms separate decision for omni sub products',
            score=0.81,
            file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
            scenario_title='Separate decision at recommendation',
            screen_context='Committee Decision',
            then_text='separate decision should be displayed for selected sub products',
        )
        same_domain_then = self._hit(
            keyword='Then',
            step_text='separate decision should be displayed for selected sub products',
            score=0.72,
            file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
            scenario_title='Separate decision at recommendation',
            screen_context='Committee Decision',
            then_text='separate decision should be displayed for selected sub products',
        )
        wrong_domain_then = self._hit(
            keyword='Then',
            step_text='separate decision should be displayed for selected sub products',
            score=0.94,
            file_path='workspace/reference_repo/Features/collateral/property/Viewer.feature',
            scenario_title='Property viewer decision check',
            screen_context='Property Viewer',
            then_text='property viewer details should be displayed',
        )
        same_domain_and = self._hit(
            keyword='And',
            step_text='selected sub product rows should remain visible',
            score=0.64,
            file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
            scenario_title='Separate decision at recommendation',
            screen_context='Committee Decision',
            then_text='selected sub product rows should remain visible',
        )

        def _search_side_effect(query, top_k=20, screen_filter=None, keyword_filter=None):
            if keyword_filter == 'Then':
                return [wrong_domain_then, same_domain_then]
            if keyword_filter == 'And':
                return [same_domain_and]
            return []

        mock_search.side_effect = _search_side_effect
        intent = {
            "id": "intent_001",
            "text": "Display separate decision for omni sub products",
            "family": "positive",
            "action_target": "separate decision",
            "screen_hint": "Committee Decision",
            "expected_outcome": "display",
            "entity": "sub product decision",
            "target_field": "decision column",
            "expected_state": "display",
            "polarity": "positive",
            "must_anchor_terms": ["separate decision"],
            "must_assert_terms": ["display", "decision"],
        }
        scope = {
            "lob_scope": {"mode": "specific", "values": ["OMNI"]},
            "stage_scope": {"mode": "specific", "values": ["Recommendation"]},
        }

        then_text, and_text = fa._retrieve_assertions(intent, anchor, scope, "@Recommendation")
        self.assertEqual(then_text, 'separate decision should be displayed for selected sub products')
        self.assertEqual(and_text, 'selected sub product rows should remain visible')

    def test_polarity_guard_rejects_opposite_candidate(self):
        hit = self._hit(
            step_text='user scrolls down to Recommendation Decisions',
            score=0.84,
            file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
            scenario_title='Recommendation Decision Dropdown should be Enabled for Omni Loan at Recommendation Stage',
            screen_context='Recommendation Decisions',
            then_text='Recommendation Decision dropdown for Recommendation Decisions should be enabled',
        )
        context = {
            'search_text': 'Disable application level decision if any subloan is not recommended',
            'screen_hint': 'Recommendation Decisions',
            'action_target': 'application level decision',
            'expected_outcome': 'disabled',
            'entity': 'application level decision',
            'target_field': 'recommendation decision dropdown',
            'expected_state': 'disabled',
            'polarity': 'disabled',
            'must_anchor_terms': ['application level decision', 'recommendation decision'],
            'must_assert_terms': ['disabled'],
            'forbidden_terms': ['enabled'],
            'family': 'dependency',
        }
        scope = {
            'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
            'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
        }
        self.assertEqual(fa._candidate_rejection_reason(hit, context, scope), 'polarity_mismatch')

    def test_checked_assertion_requires_checked_signal(self):
        context = {
            'expected_outcome': 'checked',
            'must_assert_terms': ['checked'],
        }
        then_text = 'user should be able to see a "CheckBox" type input field in "Decision" Column for "<SubProductType>" sub product'
        self.assertFalse(
            fa._is_assertion_relevant(
                then_text,
                'Keep Decision checkboxes checked by default',
                'user clicks on Product Type Decision List accordion to expand it',
                context,
            )
        )

    def test_generic_sub_product_intent_rejects_card_specific_candidate(self):
        hit = self._hit(
            step_text='user clicks on Product Type Decision List accordion to expand it',
            score=0.89,
            file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
            scenario_title='Availability of <isEnabled> Checkbox in Decision Column of Product Type Decision List for <CardType> of Omni Loan at Recommendation Stage',
            screen_context='Product Type Decision List',
            then_text='user should be able to see a "CheckBox" type input field in "<ColumnName>" Column for Credit Card Sub Product',
        )
        context = {
            'text': 'Display Decision checkbox for sub products',
            'search_text': 'Display Decision checkbox for sub products Product Type Decision List at Recommendation',
            'screen_hint': 'Product Type Decision List',
            'action_target': 'decision checkbox',
            'expected_outcome': 'display',
            'entity': 'decision checkbox',
            'target_field': 'decision checkbox',
            'expected_state': 'display',
            'polarity': 'enabled',
            'must_anchor_terms': ['decision checkbox', 'sub products'],
            'must_assert_terms': ['display', 'decision'],
            'forbidden_terms': [],
            'family': 'positive',
        }
        scope = {
            'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
            'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
        }
        self.assertEqual(fa._candidate_rejection_reason(hit, context, scope), 'entity_mismatch')

    def test_disabled_assertion_requires_matching_target_field(self):
        context = {
            'expected_outcome': 'disabled',
            'must_assert_terms': ['disabled'],
            'target_field': 'recommended limit field',
            'entity': 'recommended limit',
        }
        then_text = 'Recommended Amount field should be "<isEnabled>" for following sub products'
        self.assertFalse(
            fa._is_assertion_relevant(
                then_text,
                'Disable Recommended Limit when any subloan is not recommended',
                'user sets recommended checkbox for following sub products',
                context,
            )
        )

    def test_anchor_picker_prefers_user_action_over_assertion_and(self):
        group = [
            self._hit(
                keyword='And',
                step_text='checkbox should be "<isEnabled>" for "<SubProductType>"',
                score=0.91,
                file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
                scenario_title='Availability of <isEnabled> Checkbox in Decision Column of Product Type Decision List for <SubProductType> of Omni Loan at Recommendation Stage',
                screen_context='Product Type Decision List',
                then_text='user should be able to see a "CheckBox" type input field in "Decision" Column for "<SubProductType>" sub product',
            ),
            self._hit(
                keyword='When',
                step_text='user clicks on Product Type Decision List accordion to expand it',
                score=0.82,
                file_path='workspace/reference_repo/Features/omni/SeparateDecisionForOmniSubProductsAtRecommendation.feature',
                scenario_title='Availability of <isEnabled> Checkbox in Decision Column of Product Type Decision List for <SubProductType> of Omni Loan at Recommendation Stage',
                screen_context='Product Type Decision List',
                then_text='user should be able to see a "CheckBox" type input field in "Decision" Column for "<SubProductType>" sub product',
            ),
        ]
        anchor = fa._pick_group_anchor_step(group, 'Display Decision checkbox for sub products')
        self.assertEqual(anchor['keyword'], 'When')
        self.assertEqual(anchor['step_text'], 'user clicks on Product Type Decision List accordion to expand it')

    @patch('casforge.generation.feature_assembler.search')
    def test_best_replacement_rejects_weak_match(self, mock_search):
        mock_search.side_effect = [
            [{'step_text': 'the RCU checkbox is enabled'}],
            [{'step_text': 'the RCU checkbox is enabled'}],
        ]
        self.assertIsNone(fa._best_replacement('checkbox should be "<isEnabled>" for "<SubProductType>"', 'When'))

    @patch('casforge.generation.feature_assembler.search')
    def test_low_confidence_plan_becomes_coverage_gap(self, mock_search):
        wrong_domain = self._hit(
            step_text='user views property details in viewer screen',
            score=0.61,
            file_path='workspace/reference_repo/Features/collateral/property/Viewer.feature',
            scenario_title='Property viewer check',
            screen_context='Property Viewer',
            then_text='property viewer details should be displayed',
            product='HL',
        )
        mock_search.return_value = [wrong_domain]
        intents = [{
            'id': 'intent_001',
            'text': 'Disable recommended limit when any subloan is not recommended',
            'family': 'dependency',
            'inherit_story_scope': True,
            'lob_scope': None,
            'stage_scope': None,
            'action_target': 'recommended limit',
            'screen_hint': 'Recommendation Decisions',
            'expected_outcome': 'disabled',
            'entity': 'recommended limit',
            'target_field': 'recommended limit field',
            'expected_state': 'disabled',
            'polarity': 'disabled',
            'must_anchor_terms': ['recommended limit', 'subloan'],
            'must_assert_terms': ['disabled'],
            'forbidden_terms': ['enabled', 'property viewer'],
            'matrix_signature': 'any',
            'allow_expansion': True,
        }]
        quality = {
            'removed_out_of_scope_candidates': 0,
            'scope_relaxations': 0,
        }
        plans, scenario_debug, coverage_gaps, omitted = fa._plan_scenarios(
            intents=intents,
            flow_type='unordered',
            detected_stage='@Recommendation',
            detected_sub_tags=['@CommitteeDecision'],
            story_scope_defaults={
                'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
                'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
            },
            quality=quality,
        )
        self.assertEqual(plans, [])
        self.assertTrue(coverage_gaps)
        self.assertEqual(coverage_gaps[0]['reason'], 'no_eligible_anchor')
        self.assertTrue(omitted)
        self.assertTrue(scenario_debug)


if __name__ == "__main__":
    unittest.main()
