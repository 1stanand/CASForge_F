from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from casforge.generation import heuristic_config as hc
from casforge.generation import feature_assembler as fa
from casforge.generation import scenario_planner as sp
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
        self.assertIn('recommended limit field', facts['entities'])
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

    def test_planner_assigns_sections_from_semantic_fields(self):
        defaults = infer_story_scope_defaults(self._story())
        facts = infer_story_facts_heuristically(self._story(), defaults)
        plan_items = build_scenario_plan_items(self._story(), story_scope_defaults=defaults, story_facts=facts)
        by_target_and_outcome = {
            (item.get('target_field'), item.get('expected_outcome')): item
            for item in plan_items
        }

        display_item = by_target_and_outcome.get(('Decision column', 'display'))
        checkbox_item = by_target_and_outcome.get(('Decision checkbox', 'checked'))
        disable_item = by_target_and_outcome.get(('Recommended Limit field', 'disabled'))
        state_move_item = by_target_and_outcome.get(('Credit Approval stage', 'state_change'))

        self.assertIsNotNone(display_item)
        self.assertIsNotNone(checkbox_item)
        self.assertIsNotNone(disable_item)
        self.assertIsNotNone(state_move_item)

        self.assertEqual(display_item.get('section_title'), 'UI Structure Validation')
        self.assertEqual(checkbox_item.get('section_title'), 'Checkbox Availability & Default State')
        self.assertEqual(disable_item.get('section_title'), 'Field Enablement Behaviour')
        self.assertEqual(state_move_item.get('section_title'), 'Move To Next Stage Validations')

        self.assertNotIn('Product Type Decision List', display_item.get('text', ''))
        self.assertNotEqual(disable_item.get('text'), 'Disable Recommended Limit when any subloan is not recommended')
        self.assertNotEqual(state_move_item.get('text'), 'Move application to Credit Approval from Recommendation')

    def test_title_from_rule_uses_neutral_structural_templates(self):
        move_title = sp._title_from_rule(
            'Credit Approval stage',
            'state_move',
            'positive',
            'on MTNS from recommendation stage',
            {'stage_scope': {'mode': 'specific', 'values': ['Recommendation']}},
        )
        disable_title = sp._title_from_rule(
            'Recommended Limit field',
            'disable',
            'disabled',
            'if any subloan is not recommended',
        )
        display_title = sp._title_from_rule('Decision column', 'display', 'positive', '')

        self.assertTrue(display_title.startswith('Display Decision column'))
        self.assertNotIn('Product Type Decision List', display_title)

        self.assertTrue(disable_title.startswith('Disable Recommended Limit field'))
        self.assertIn('subloan', disable_title.lower())

        self.assertTrue(move_title.startswith('Move application to Credit Approval stage'))
        self.assertNotEqual(move_title, 'Move application to Credit Approval from Recommendation')

    def test_canonical_plan_target_does_not_promote_stage_specific_family_terms(self):
        target = sp._canonical_plan_target(
            'application level decision',
            'when user edits the application level decision',
            'derive',
            {'stage_scope': {'mode': 'specific', 'values': ['Recommendation']}},
        )
        self.assertEqual(target, 'Application level decision')

    def test_screen_hint_for_rule_uses_explicit_or_default_context_only(self):
        explicit = sp._screen_hint_for_rule(
            {'screen_hint': 'Decision Drawer'},
            'Decision column',
            None,
            'Recommendation Decisions',
        )
        defaulted = sp._screen_hint_for_rule(
            {},
            'Decision column',
            None,
            'Recommendation Decisions',
        )
        missing = sp._screen_hint_for_rule({}, 'Decision column', None, None)

        self.assertEqual(explicit, 'Decision Drawer')
        self.assertEqual(defaulted, 'Recommendation Decisions')
        self.assertIsNone(missing)

    def test_best_entity_from_facts_prefers_rule_backed_specific_entity(self):
        facts = {
            'entities': ['committee verdict', 'committee', 'member'],
            'rules': [{
                'condition': 'when majority is reached',
                'target': 'committee verdict',
                'effect': 'derive',
                'polarity': 'positive',
            }],
        }

        self.assertEqual(sp._best_entity_from_facts(facts), 'committee verdict')

    def test_planner_does_not_add_synthetic_duplicate_family_when_rule_already_exists(self):
        story = JiraStory(
            issue_key='TINY-1',
            summary='Committee decision majority update',
            issue_type='Story',
            description='',
            current_process='',
            new_process='system finalizes verdict as soon as majority is mathematically reached.',
            business_scenarios='If vote split remains tied then verdict should stay mixed.',
            impacted_areas='Committee Approval',
            key_ui_steps='CAS >> Committee Approval >> Decision Drawer',
            acceptance_criteria='System should finalize verdict when majority is reached.',
            story_description='',
        )
        facts = {
            'story_scope_defaults': {'lob_scope': {'mode': 'all', 'values': []}, 'stage_scope': {'mode': 'all', 'values': []}},
            'entities': ['committee verdict'],
            'rules': [{
                'condition': 'when majority is mathematically reached',
                'target': 'committee verdict',
                'effect': 'selection_dependency',
                'polarity': 'positive',
                'family_hint': 'dependency',
                'screen_hint': 'Decision Drawer',
            }],
            'coverage_signals': ['dependency', 'validation', 'data_combination', 'edge'],
            'matrix_signals': ['mixed'],
        }
        plan_items = build_scenario_plan_items(story, story_facts=facts)
        dependency_items = [item for item in plan_items if item['family'] == 'dependency']

        self.assertEqual(len(dependency_items), 1)
        self.assertFalse(any('enablement from sub selection' in item['text'].lower() for item in plan_items))

    def test_planner_prefers_specific_entity_for_synthetic_items(self):
        story = JiraStory(
            issue_key='CAS-000003',
            summary='Decision checkbox support',
            issue_type='Story',
            description='',
            current_process='',
            new_process='',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='',
            story_description='',
        )
        facts = {
            'story_scope_defaults': {'lob_scope': {'mode': 'all', 'values': []}, 'stage_scope': {'mode': 'all', 'values': []}},
            'entities': ['product type decision list', 'decision checkbox'],
            'rules': [],
            'coverage_signals': ['ui_structure', 'default_state'],
            'matrix_signals': [],
        }
        plan_items = build_scenario_plan_items(story, story_facts=facts)

        self.assertTrue(plan_items)
        self.assertTrue(all('decision checkbox' in item['text'].lower() for item in plan_items))
        self.assertFalse(any('product type decision list' in item['text'].lower() for item in plan_items))

    def test_planner_skips_synthetic_items_for_generic_entity_only(self):
        story = JiraStory(
            issue_key='CAS-000004',
            summary='Generic screen support',
            issue_type='Story',
            description='',
            current_process='',
            new_process='',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='',
            story_description='',
        )
        facts = {
            'story_scope_defaults': {'lob_scope': {'mode': 'all', 'values': []}, 'stage_scope': {'mode': 'all', 'values': []}},
            'entities': ['product type decision list'],
            'rules': [],
            'coverage_signals': ['ui_structure', 'validation'],
            'matrix_signals': [],
        }

        self.assertEqual(build_scenario_plan_items(story, story_facts=facts), [])
        self.assertFalse(sp._synthetic_entity_specific_enough('product type decision list'))

    @patch("casforge.generation.story_facts.llm_client.chat")
    def test_extract_story_facts_skips_llm_for_strong_heuristic_story(self, mock_chat):
        defaults = infer_story_scope_defaults(self._story())
        facts = extract_story_facts(self._story(), story_scope_defaults=defaults)
        targets_and_effects = {
            (rule['target'], rule['effect'])
            for rule in facts['rules']
        }
        self.assertIn(('decision column', 'display'), targets_and_effects)
        self.assertIn(('decision checkbox', 'default_state'), targets_and_effects)
        self.assertIn(('recommended limit field', 'disable'), targets_and_effects)
        self.assertIn(('recommended amount field', 'zero_validation'), targets_and_effects)
        self.assertIn(('credit approval stage', 'state_move'), targets_and_effects)
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

    def test_recommendation_stage_mention_does_not_create_state_move_rule(self):
        story = JiraStory(
            issue_key='CAS-000002',
            summary='Decision column support at Recommendation stage',
            issue_type='Story',
            description='',
            current_process='',
            new_process='A new column decision is required in product type decision list at recommendation stage.',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='Display decision column for sub loans.',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        self.assertFalse(any(rule['effect'] == 'state_move' for rule in facts['rules']))
        self.assertNotIn('state_movement', facts['coverage_signals'])

    def test_application_level_decision_target_is_not_promoted_by_stage_alone(self):
        story = JiraStory(
            issue_key='CAS-000008',
            summary='Application decision disabled at recommendation stage',
            issue_type='Story',
            description='',
            current_process='',
            new_process='Application level decision should be disabled at recommendation stage.',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        targets = {rule['target'] for rule in facts['rules']}

        self.assertIn('application level decision', targets)
        self.assertNotIn('recommendation decision dropdown', targets)

    def test_selected_as_recommended_rule_does_not_invent_disable_rule_without_disable_text(self):
        story = JiraStory(
            issue_key='CAS-000009',
            summary='Application decision derive behavior',
            issue_type='Story',
            description='',
            current_process='',
            new_process='Application level decision is selected as recommended when any matching rule applies.',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        dropdown_rules = [
            rule for rule in facts['rules']
            if rule['target'] in {'application level decision', 'recommendation decision dropdown'}
        ]

        self.assertTrue(any(rule['effect'] == 'derive' for rule in dropdown_rules))
        self.assertFalse(any(rule['effect'] == 'disable' for rule in dropdown_rules))

    def test_by_default_nature_text_does_not_trigger_default_state_signal(self):
        story = JiraStory(
            issue_key='CAS-000007',
            summary='Committee logic configuration',
            issue_type='Story',
            description='',
            current_process='',
            new_process='It needs to be build in configurable manner so as existing implementation do not get impacted, with by default nature to be as is working.',
            business_scenarios='',
            impacted_areas='',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)

        self.assertNotIn('default_state', facts['coverage_signals'])

    @patch("casforge.generation.story_facts.llm_client.chat")
    def test_extract_story_facts_prunes_noisy_overlay_signals_and_families(self, mock_chat):
        mock_chat.return_value = (
            '{'
            '"entities":["committee verdict","Committee","Member"],'
            '"rules":['
            '{"condition":"Minimum Approval Committee","target":"Final Verdict","effect":"derive","polarity":"positive","family_hint":"validation"},'
            '{"condition":"All member decisions are captured","target":"Committee Status","effect":"state_move","polarity":"positive","family_hint":"state_movement"}'
            '],'
            '"coverage_signals":["default_state","validation","edge","field_enablement","dependency","derived_decision","state_movement"],'
            '"matrix_signals":["mixed","dependent_card","zero_value","multi_grid"]'
            '}'
        )
        story = JiraStory(
            issue_key='CAS-270826',
            summary='ATDD - Committee Decision Logic Change',
            issue_type='Story',
            description='',
            current_process='',
            new_process=(
                'Final verdict is derived post minimum approval but 100% member participation shall be ensured.\n'
                'Committee Status remains open until all member decisions are captured.\n'
                'Any split should follow majority view.\n'
                'It needs to be configurable with by default nature to be as is working.'
            ),
            business_scenarios='',
            impacted_areas='',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        facts = extract_story_facts(story)

        self.assertIn('dependency', facts['coverage_signals'])
        self.assertIn('derived_decision', facts['coverage_signals'])
        self.assertIn('state_movement', facts['coverage_signals'])
        self.assertNotIn('default_state', facts['coverage_signals'])
        self.assertNotIn('field_enablement', facts['coverage_signals'])
        self.assertNotIn('edge', facts['coverage_signals'])
        self.assertEqual(facts['matrix_signals'], ['mixed'])
        derive_rules = [rule for rule in facts['rules'] if rule['effect'] == 'derive']
        self.assertTrue(derive_rules)
        self.assertTrue(all(rule['family_hint'] == 'dependency' for rule in derive_rules))

    def test_generic_container_target_is_dropped_from_heuristic_rules(self):
        story = JiraStory(
            issue_key='CAS-000005',
            summary='Display product type decision list',
            issue_type='Story',
            description='',
            current_process='',
            new_process='Product type decision list should be displayed at recommendation stage.',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='Display product type decision list.',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)

        self.assertFalse(any(rule['target'] == 'product type decision list' for rule in facts['rules']))
        self.assertEqual(facts['rules'], [])

    def test_generic_next_stage_target_is_dropped_without_explicit_stage(self):
        story = JiraStory(
            issue_key='CAS-000006',
            summary='Move application to next stage',
            issue_type='Story',
            description='',
            current_process='',
            new_process='Application should move to next stage when committee verdict is finalized.',
            business_scenarios='',
            impacted_areas='Committee Approval',
            key_ui_steps='CAS >> Committee Approval >> Decision Drawer',
            acceptance_criteria='Move application to next stage.',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)

        self.assertFalse(any(rule['target'] == 'application stage movement' for rule in facts['rules']))
        self.assertFalse(any(rule['effect'] == 'state_move' for rule in facts['rules']))

    def test_story_facts_can_extract_rules_from_supplemental_comments(self):
        story = JiraStory(
            issue_key='CAS-COMMENT',
            summary='Decision logic shared in comments',
            issue_type='Story',
            description='',
            current_process='',
            new_process='',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='',
            story_description='',
            supplemental_comments='Final approach: Recommended limit field should be disabled when any subloan is not recommended.',
        )
        facts = infer_story_facts_heuristically(story)

        self.assertTrue(any(rule['target'] == 'recommended limit field' and rule['effect'] == 'disable' for rule in facts['rules']))
        self.assertIn('field_enablement', facts['coverage_signals'])

    def test_heuristic_extracts_display_section_rule(self):
        """Sentences with 'section should be displayed' (no 'field'/'column')
        must now be extracted by the heuristic trigger token 'display'."""
        story = JiraStory(
            issue_key='CAS-DISP-001',
            summary='Display collateral section at credit approval',
            issue_type='Story',
            description='',
            current_process='',
            new_process='The collateral section should be displayed for secured loan applications.',
            business_scenarios='',
            impacted_areas='Collateral Details',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        display_rules = [r for r in facts.get('rules', []) if r.get('effect') == 'display']
        self.assertTrue(
            any('collateral' in str(r.get('target', '')).lower() for r in display_rules),
            f"Expected a display rule for 'collateral section', got: {facts.get('rules', [])}"
        )

    def test_heuristic_infers_negative_display_polarity(self):
        """'X should not be visible' must produce effect=display, polarity=negative."""
        story = JiraStory(
            issue_key='CAS-NEG-DISP-001',
            summary='Hide collateral section when not secured',
            issue_type='Story',
            description='',
            current_process='',
            new_process='The collateral section should not be visible for unsecured loan applications.',
            business_scenarios='',
            impacted_areas='Collateral Details',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        neg_display = [
            r for r in facts.get('rules', [])
            if r.get('effect') == 'display' and r.get('polarity') == 'negative'
        ]
        self.assertTrue(
            len(neg_display) > 0,
            f"Expected a display/negative rule, got: {facts.get('rules', [])}"
        )

    def test_heuristic_infers_shown_as_display_effect(self):
        """'X should be shown' should produce effect=display, not None."""
        story = JiraStory(
            issue_key='CAS-SHOWN-001',
            summary='Show approval decision section',
            issue_type='Story',
            description='',
            current_process='',
            new_process='The approval decision section should be shown when status is final.',
            business_scenarios='',
            impacted_areas='Approval',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        display_rules = [r for r in facts.get('rules', []) if r.get('effect') == 'display']
        self.assertTrue(
            any('section' in str(r.get('target', '')).lower() for r in display_rules),
            f"Expected a display rule with 'section' target, got: {facts.get('rules', [])}"
        )

    def test_positional_placement_sentence_skipped_by_heuristic(self):
        """'column added before X field' must not produce a display rule for X field.
        The mentioned field is a spatial anchor, not the rule subject."""
        story = JiraStory(
            issue_key='CAS-POS-001',
            summary='Add decision checkbox before recommended amount field',
            issue_type='Story',
            description='',
            current_process='',
            new_process='This column will be added before recommended amount field.',
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        facts = infer_story_facts_heuristically(story)
        targets = {r.get('target', '') for r in facts.get('rules', [])}
        self.assertNotIn('recommended amount field', targets,
            "Positional anchor 'recommended amount field' must not become a display rule target")

    @patch("casforge.generation.story_facts.llm_client.chat")
    def test_contradictory_heuristic_rules_force_llm_call(self, mock_chat):
        """When heuristic extracts two rules with same (target, effect) but different
        polarity (e.g. derive/recommended vs derive/not_recommended), the heuristic is
        NOT authoritative and the LLM must be called."""
        mock_chat.return_value = (
            '{"story_scope_defaults":{"lob_scope":{"mode":"all","values":[]},'
            '"stage_scope":{"mode":"all","values":[]}},'
            '"entities":[],"rules":[],"coverage_signals":[],"matrix_signals":[]}'
        )
        story = JiraStory(
            issue_key='CAS-CONTRA-001',
            summary='Application decision derives from sub-loan recommendation',
            issue_type='Story',
            description='',
            current_process='',
            new_process=(
                'If even one of the sub loan is selected as recommended then '
                'application level decision will change to recommended. '
                'If all the subloans are marked not recommended then '
                'application decision will be updated to not recommended. '
                'If any subloan is not recommended then recommended limit field will be disabled.'
            ),
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='CAS >> Omni Loan >> Recommendation Decisions',
            acceptance_criteria='',
            story_description='',
        )
        extract_story_facts(story)
        mock_chat.assert_called_once()

    def test_financial_value_sentences_do_not_make_heuristic_authoritative(self):
        """A story with only financial-value sentences must NOT be declared authoritative
        by the heuristic — the LLM must be called to handle the ambiguity.

        Regression for C7: 'amount'/'rate'/'limit' in the trigger gate caused financial
        sentences to inflate heuristic rule counts, sometimes reaching the authoritative
        threshold and bypassing the LLM.
        """
        story = JiraStory(
            issue_key='CAS-REG-C7-001',
            summary='Recommended amount and limit field enablement under OMNI',
            issue_type='Story',
            description='',
            current_process='',
            new_process=(
                'The recommended amount field should reflect the derived value. '
                'The recommended limit field should be disabled when sub-loan count is zero. '
                'If no sub-loan is recommended the recommended amount should show zero.'
            ),
            business_scenarios='',
            impacted_areas='Recommendation Decisions',
            key_ui_steps='',
            acceptance_criteria='',
            story_description='',
        )
        from casforge.generation.story_facts import _heuristic_facts_are_authoritative
        facts = infer_story_facts_heuristically(story)
        # A story with only 2-3 field-enablement rules must not reach the authoritative
        # threshold (requires >= 5 rules across >= 3 families).
        self.assertFalse(
            _heuristic_facts_are_authoritative(facts),
            f"Heuristic must not be authoritative for a story with only financial-value sentences. "
            f"Got rules: {facts.get('rules', [])}"
        )

    def test_target_is_specific_rejects_generic_words(self):
        """Single generic words like 'field', 'amount', 'limit' must not be specific targets."""
        from casforge.generation.story_facts import _target_is_specific
        for generic in ('field', 'amount', 'limit', 'rate', 'value', 'item', 'section'):
            self.assertFalse(_target_is_specific(generic), f"'{generic}' should not be specific")

    def test_target_is_specific_accepts_compound_targets(self):
        """Multi-word targets like 'decision checkbox' or 'recommended amount field' must be specific."""
        from casforge.generation.story_facts import _target_is_specific
        for specific in ('decision checkbox', 'recommended amount field', 'credit approval stage',
                         'sub loan recommendation', 'committee verdict dropdown'):
            self.assertTrue(_target_is_specific(specific), f"'{specific}' should be specific")


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

    def test_same_domain_family_allows_same_screen_when_only_path_terms_differ(self):
        anchor = self._hit(
            step_text='user opens decision details',
            score=0.81,
            file_path='workspace/reference_repo/Features/shared/Decision.feature',
            scenario_title='Decision availability',
            screen_context='Recommendation Decisions',
            then_text='decision details should be displayed',
        )
        candidate = self._hit(
            keyword='Then',
            step_text='decision details should be displayed',
            score=0.77,
            file_path='workspace/reference_repo/Features/manual/Checklist.feature',
            scenario_title='Decision display',
            screen_context='Recommendation Decisions',
            then_text='decision details should be displayed',
        )

        self.assertTrue(fa._same_domain_family(candidate, anchor))

    def test_scenario_domain_ok_does_not_require_single_leftover_domain_term_match(self):
        hit = self._hit(
            step_text='user clicks on decision checkbox',
            score=0.83,
            file_path='workspace/reference_repo/Features/manual/Checklist.feature',
            scenario_title='Decision checkbox display',
            screen_context='Recommendation Decisions',
            then_text='decision checkbox should be displayed',
        )
        context = {
            'search_text': 'Display decision checkbox for omni users',
            'screen_hint': 'Recommendation Decisions',
            'action_target': 'decision checkbox',
            'entity': 'decision checkbox',
            'target_field': 'decision checkbox',
            'section_key': 'checkbox_state',
            'pattern_terms': [],
        }

        self.assertTrue(fa._scenario_domain_ok(hit, context))

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

    def test_no_anchor_does_not_build_scaffold_plan(self):
        intent = {
            'id': 'intent_001',
            'text': 'Display decision checkbox for sub loans',
            'family': 'positive',
        }
        quality = {
            'removed_out_of_scope_candidates': 0,
            'scope_relaxations': 0,
        }
        with patch(
            'casforge.generation.feature_assembler._select_anchor_variants',
            return_value=([], 0, 0, {'no_anchor': 1}),
        ), patch(
            'casforge.generation.feature_assembler._build_scaffold_plan_from_related_hits'
        ) as mock_scaffold:
            plans, scenario_debug, coverage_gaps, omitted = fa._plan_scenarios(
                intents=[intent],
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
        self.assertEqual(coverage_gaps[0]['reason'], 'no_eligible_anchor')
        self.assertTrue(omitted)
        self.assertTrue(scenario_debug)
        mock_scaffold.assert_not_called()

    def test_low_confidence_anchor_does_not_build_fallback_plan(self):
        intent = {
            'id': 'intent_001',
            'text': 'Display decision checkbox for sub loans',
            'family': 'positive',
        }
        low_confidence_plan = fa.ScenarioPlan(
            intent_id='intent_001',
            intent=intent['text'],
            family='positive',
            section_key='core_flow',
            section='Core Flow Coverage',
            title='Display decision checkbox for sub loans',
            given_steps=['user is on Committee Decision screen'],
            when_steps=['user opens Product Type Decision List'],
            then_step='decision checkbox should be displayed',
            then_and_step=None,
            placeholders=[],
            tags=['@Recommendation'],
            effective_scope={
                'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
                'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
            },
            unresolved_assertion=True,
            confidence=0.4,
            anchor_file='workspace/reference_repo/Features/omni/Decision.feature',
            anchor_title='Decision checkbox display',
            assertion_source='fallback',
            debug={'anchor_score': 0.91},
        )
        quality = {
            'removed_out_of_scope_candidates': 0,
            'scope_relaxations': 0,
        }
        with patch(
            'casforge.generation.feature_assembler._select_anchor_variants',
            return_value=([{'anchor_scenario_score': 0.91}], 0, 0, {}),
        ), patch(
            'casforge.generation.feature_assembler._build_plan_from_anchor',
            return_value=low_confidence_plan,
        ), patch(
            'casforge.generation.feature_assembler._build_fallback_plan'
        ) as mock_fallback:
            plans, scenario_debug, coverage_gaps, omitted = fa._plan_scenarios(
                intents=[intent],
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
        self.assertIn('low_confidence', [item['reason'] for item in coverage_gaps])
        self.assertEqual(coverage_gaps[-1]['reason'], 'omitted_after_confidence_gate')
        self.assertTrue(omitted)
        self.assertTrue(scenario_debug)
        mock_fallback.assert_not_called()

    def test_ground_steps_to_repo_keeps_unresolved_step_text(self):
        conn = MagicMock()
        cur = MagicMock()
        feature_text = (
            'Feature: Demo feature\n\n'
            '  Scenario Outline: Keep generated step\n'
            '    When user performs a brand new action\n'
        )
        with patch(
            'casforge.generation.feature_assembler.get_conn',
            return_value=conn,
        ), patch(
            'casforge.generation.feature_assembler.get_cursor',
            return_value=nullcontext(cur),
        ), patch(
            'casforge.generation.feature_assembler._step_exists',
            return_value=False,
        ), patch(
            'casforge.generation.feature_assembler._best_replacement',
            return_value='repo replacement should not be used',
        ) as mock_replacement:
            grounded_text, unresolved, total, grounded = fa._ground_steps_to_repo(feature_text)

        self.assertIn('When user performs a brand new action', grounded_text)
        self.assertIn('# [NEW_STEP_NOT_IN_REPO] When user performs a brand new action', grounded_text)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]['marker'], 'NEW_STEP_NOT_IN_REPO')
        self.assertEqual(total, 1)
        self.assertEqual(grounded, 0)
        mock_replacement.assert_not_called()
        conn.close.assert_called_once()

    @patch('casforge.generation.feature_assembler.search')
    def test_fallback_then_step_marks_missing_assertion_without_search(self, mock_search):
        intent = {
            'id': 'intent_001',
            'text': 'Disable Recommended Limit when any subloan is not recommended',
            'family': 'dependency',
            'expected_outcome': 'disabled',
            'entity': 'recommended limit',
            'target_field': 'recommended limit field',
            'expected_state': 'disabled',
            'polarity': 'disabled',
            'must_anchor_terms': ['recommended limit', 'subloan'],
            'must_assert_terms': ['disabled'],
        }
        anchor = self._hit(
            step_text='user sets recommended checkbox for following sub products',
            score=0.86,
            file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
            scenario_title='Disable Recommended Limit for Omni Loan at Recommendation Stage',
            screen_context='Recommendation Decisions',
            then_text='Recommended Limit field should be disabled',
        )

        then_step = fa._fallback_then_step(intent, anchor)

        self.assertEqual(then_step, 'NEW_STEP_NOT_IN_REPO: recommended limit field should be disabled')
        mock_search.assert_not_called()

    @patch('casforge.generation.feature_assembler._retrieve_assertions', return_value=(None, None))
    def test_build_plan_uses_explicit_unresolved_then_when_assertion_missing(self, mock_retrieve):
        intent = {
            'id': 'intent_001',
            'text': 'Disable Recommended Limit when any subloan is not recommended',
            'family': 'dependency',
            'action_target': 'recommended limit',
            'screen_hint': 'Recommendation Decisions',
            'expected_outcome': 'disabled',
            'entity': 'recommended limit',
            'target_field': 'recommended limit field',
            'expected_state': 'disabled',
            'polarity': 'disabled',
            'must_anchor_terms': ['recommended limit', 'subloan'],
            'must_assert_terms': ['disabled'],
            'section_key': 'field_enablement',
            'section_title': 'Field Enablement Behaviour',
        }
        anchor = self._hit(
            step_text='user sets recommended checkbox for following sub products',
            score=0.86,
            file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
            scenario_title='Disable Recommended Limit for Omni Loan at Recommendation Stage',
            screen_context='Recommendation Decisions',
            then_text='Recommended Limit field should be disabled',
        )
        anchor['scenario_steps'] = [
            {'keyword': 'Given', 'step_text': 'user is on Recommendation Decisions screen', 'screen_context': 'Recommendation Decisions'},
            {'keyword': 'When', 'step_text': 'user sets recommended checkbox for following sub products', 'screen_context': 'Recommendation Decisions'},
        ]
        anchor['anchor_scenario_score'] = 0.91
        scope = {
            'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
            'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
        }

        plan = fa._build_plan_from_anchor(
            intent=intent,
            flow_type='unordered',
            family='dependency',
            section_key='field_enablement',
            section='Field Enablement Behaviour',
            anchor=anchor,
            variant_idx=1,
            detected_stage='@Recommendation',
            detected_sub_tags=['@CommitteeDecision'],
            effective_scope=scope,
            ordinal=1,
        )

        self.assertIsNotNone(plan)
        self.assertTrue(plan.unresolved_assertion)
        self.assertEqual(plan.assertion_source, 'fallback')
        self.assertTrue(plan.then_step.startswith('NEW_STEP_NOT_IN_REPO: '))
        mock_retrieve.assert_called_once()

    @patch('casforge.generation.feature_assembler.search')
    def test_retrieve_assertions_falls_back_to_no_screen_filter_when_filtered_returns_nothing(self, mock_search):
        """When screen-filtered assertion search returns nothing, the retrieval should
        retry without the screen filter and accept a valid same-domain result."""
        def _side_effect(query, top_k=20, screen_filter=None, keyword_filter=None):
            if screen_filter:
                return []  # Filtered search finds nothing
            if keyword_filter == 'Then':
                return [self._hit(
                    keyword='Then',
                    step_text='Recommended Limit field should be disabled',
                    score=0.88,
                    file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
                    scenario_title='Disable Recommended Limit for Omni Loan at Recommendation Stage',
                    screen_context='Recommendation Decisions',
                    then_text='Recommended Limit field should be disabled',
                )]
            return []

        mock_search.side_effect = _side_effect
        intent = {
            'id': 'intent_001',
            'text': 'Disable Recommended Limit when any subloan is not recommended',
            'family': 'dependency',
            'action_target': 'recommended limit',
            'screen_hint': 'Recommendation Decisions',
            'expected_outcome': 'disabled',
            'entity': 'recommended limit',
            'target_field': 'recommended limit field',
            'expected_state': 'disabled',
            'polarity': 'disabled',
            'must_anchor_terms': ['recommended limit', 'subloan'],
            'must_assert_terms': ['disabled'],
        }
        anchor = self._hit(
            step_text='user sets recommended checkbox for following sub products',
            score=0.86,
            file_path='workspace/reference_repo/Features/omni/SeparateDecision.feature',
            scenario_title='Disable Recommended Limit for Omni Loan at Recommendation Stage',
            screen_context='Recommendation Decisions',
            then_text='Recommended Limit field should be disabled',
        )
        scope = {
            'lob_scope': {'mode': 'specific', 'values': ['OMNI']},
            'stage_scope': {'mode': 'specific', 'values': ['Recommendation']},
        }
        then_text, _ = fa._retrieve_assertions(intent, anchor, scope, '@Recommendation')
        self.assertIsNotNone(then_text, "Should recover a Then assertion via screen-filter fallback")
        self.assertIn('disabled', then_text.lower())

    def test_is_assertion_relevant_rejects_cross_entity_via_generic_words(self):
        """The non-strict generic-word fallback must NOT accept an assertion about a
        different field purely because it contains 'enabled'/'disabled'."""
        context = {
            'expected_outcome': 'disabled',
            'target_field': 'recommended limit field',
            'entity': 'recommended limit',
            'must_assert_terms': ['disabled'],
        }
        # 'application level decision should be disabled' has 'disabled' but wrong entity
        result = fa._is_assertion_relevant(
            'application level decision should be disabled',
            'Disable Recommended Limit when any subloan is not recommended',
            'user sets recommended checkbox for following sub products',
            context,
        )
        self.assertFalse(result, "Cross-entity assertion must be rejected even with matching generic word")

    def test_is_assertion_relevant_accepts_correct_target_via_generic_words(self):
        """The non-strict path should still accept an assertion that shares specific
        target tokens with the context, even if overlap with intent is modest."""
        context = {
            'expected_outcome': 'disabled',
            'target_field': 'recommended limit field',
            'entity': 'recommended limit',
            'must_assert_terms': ['disabled'],
        }
        # 'Recommended Limit field should be disabled' has 'recommended'+'limit'+'disabled'
        result = fa._is_assertion_relevant(
            'Recommended Limit field should be disabled',
            'Disable Recommended Limit when any subloan is not recommended',
            'user sets recommended checkbox for following sub products',
            context,
        )
        self.assertTrue(result, "Correct-target assertion must still be accepted")


class HeuristicConfigTests(unittest.TestCase):
    def tearDown(self):
        hc.reload_heuristic_configs()

    def _domain_payload(self) -> dict:
        return {
            "lob_aliases": [{"canonical": "OMNI", "phrases": ["omni"]}],
            "entities": [{
                "canonical": "committee outcome",
                "aliases": ["committee outcome"],
                "family": "decision_logic",
                "screens": ["Decision Drawer"],
            }],
            "stages": [{"canonical": "Committee Approval", "aliases": ["committee approval"]}],
            "families": [{"key": "ui_structure", "terms": ["display"]}],
            "sections": [{
                "key": "ui_structure",
                "display_name": "UI Structure Validation",
                "terms": ["display", "screen"],
            }],
            "matrix_terms": [{"key": "mixed", "terms": ["mixed"]}],
            "state_transition_terms": ["stage", "committee approval"],
        }

    def _planner_payload(self) -> dict:
        return {
            "target_aliases": [{"match": "committee outcome", "canonical": "Committee outcome", "scope": "global"}],
            "synthetic_entity_blocklist": ["generic behavior"],
            "synthetic_templates": {"generic_visibility": ["Display {target}"]},
        }

    def _assembler_payload(self) -> dict:
        return {
            "specificity_conflicts": [{
                "candidate_markers": ["credit card"],
                "intent_markers": ["credit card"],
            }],
            "family_terms": {"dependency": ["derived"]},
            "section_terms": {"ui_structure": ["display", "screen"]},
            "matrix_terms": {"mixed": ["mixed"]},
            "path_domain_stopwords": ["feature", "generated"],
        }

    def _write_json(self, root: Path, name: str, payload: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_generation_config_loads_and_normalizes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            domain = self._write_json(root, "domain_knowledge.json", self._domain_payload())
            planner = self._write_json(root, "planner_hints.json", self._planner_payload())
            assembler = self._write_json(root, "assembler_hints.json", self._assembler_payload())
            with patch.object(hc, "DOMAIN_KNOWLEDGE_PATH", domain), patch.object(hc, "PLANNER_HINTS_PATH", planner), patch.object(hc, "ASSEMBLER_HINTS_PATH", assembler):
                hc.reload_heuristic_configs()
                self.assertEqual(hc.load_domain_knowledge()["entities"][0]["canonical"], "committee outcome")
                self.assertEqual(hc.load_planner_hints()["target_aliases"][0]["canonical"], "Committee outcome")
                self.assertEqual(hc.load_assembler_hints()["section_terms"]["ui_structure"], {"display", "screen"})

    def test_malformed_config_warns_and_returns_empty_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "domain_knowledge.json"
            path.write_text("{bad", encoding="utf-8")
            with patch.object(hc, "DOMAIN_KNOWLEDGE_PATH", path), self.assertLogs("casforge.generation.heuristic_config", level="WARNING") as logs:
                hc.reload_heuristic_configs()
                loaded = hc.load_domain_knowledge()
            self.assertEqual(loaded["entities"], ())
            self.assertTrue(any("invalid JSON" in line for line in logs.output))

    def test_missing_config_warns_and_returns_empty_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "planner_hints.json"
            with patch.object(hc, "PLANNER_HINTS_PATH", missing), self.assertLogs("casforge.generation.heuristic_config", level="WARNING") as logs:
                hc.reload_heuristic_configs()
                loaded = hc.load_planner_hints()
            self.assertEqual(loaded["synthetic_templates"], {})
            self.assertTrue(any("missing" in line.lower() for line in logs.output))

    def test_unknown_or_disallowed_keys_reject_config(self):
        payload = dict(self._assembler_payload())
        payload["rescue_rules"] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_json(Path(tmpdir), "assembler_hints.json", payload)
            with patch.object(hc, "ASSEMBLER_HINTS_PATH", path), self.assertLogs("casforge.generation.heuristic_config", level="WARNING") as logs:
                hc.reload_heuristic_configs()
                loaded = hc.load_assembler_hints()
            self.assertEqual(loaded["family_terms"], {})
            self.assertTrue(any("unsupported keys" in line for line in logs.output))

    def test_domain_config_change_changes_story_fact_entity_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            domain = self._write_json(Path(tmpdir), "domain_knowledge.json", self._domain_payload())
            with patch.object(hc, "DOMAIN_KNOWLEDGE_PATH", domain):
                hc.reload_heuristic_configs()
                story = JiraStory(
                    issue_key="CAS-CONFIG",
                    summary="Committee outcome display",
                    issue_type="Story",
                    description="",
                    current_process="",
                    new_process="Committee outcome should be displayed on the decision drawer screen.",
                    business_scenarios="",
                    impacted_areas="Decision Drawer",
                    key_ui_steps="",
                    acceptance_criteria="",
                    story_description="",
                )
                facts = infer_story_facts_heuristically(story)
            self.assertIn("committee outcome", facts["entities"])

    def test_missing_planner_config_omits_synthetic_filler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "planner_hints.json"
            with patch.object(hc, "PLANNER_HINTS_PATH", missing):
                hc.reload_heuristic_configs()
                story = JiraStory(
                    issue_key="CAS-SYNTH",
                    summary="Committee outcome support",
                    issue_type="Story",
                    description="",
                    current_process="",
                    new_process="",
                    business_scenarios="",
                    impacted_areas="Decision Drawer",
                    key_ui_steps="",
                    acceptance_criteria="",
                    story_description="",
                )
                facts = {
                    "story_scope_defaults": {"lob_scope": {"mode": "all", "values": []}, "stage_scope": {"mode": "all", "values": []}},
                    "entities": ["committee verdict"],
                    "rules": [],
                    "coverage_signals": ["ui_structure", "validation"],
                    "matrix_signals": [],
                }
                self.assertEqual(build_scenario_plan_items(story, story_facts=facts), [])

    def test_missing_assembler_config_removes_hidden_specificity_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "assembler_hints.json"
            with patch.object(hc, "ASSEMBLER_HINTS_PATH", missing):
                hc.reload_heuristic_configs()
                context = {
                    "text": "generic checkbox behaviour",
                    "search_text": "generic checkbox behaviour",
                    "entity": "checkbox",
                    "target_field": "checkbox",
                    "must_anchor_terms": ["checkbox"],
                }
                self.assertFalse(fa._has_specificity_conflict("credit card checkbox should be visible", context))


class UnrelatedDomainGeneralizationTests(unittest.TestCase):
    """
    Tests that assembler/planner/story_facts work for a domain that shares
    NO vocabulary with the OMNI recommendation fixture family.
    Domain: collateral valuation at Credit Approval stage (Home Loan).
    Purpose: confirm heuristics generalise instead of being OMNI-tuned.
    """

    def _val_hit(
        self,
        *,
        step_text: str,
        keyword: str = "When",
        score: float = 0.75,
        scenario_title: str,
        then_text: str,
        file_path: str = "workspace/reference_repo/Features/creditapproval/collateral/ValuationFlow.feature",
        screen_context: str = "Collateral Details",
        stage: str = "CreditApproval",
        product: str = "HL",
    ) -> dict:
        scenario_steps = [
            {"keyword": "Given", "step_text": f"user is on {screen_context} screen", "screen_context": screen_context},
            {"keyword": "And", "step_text": "collateral data is available", "screen_context": screen_context},
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
            "scope_stage_tags": [f"@{stage}"],
            "scope_sub_tags": [],
            "scope_product_types": [product],
            "scope_application_stages": [stage],
        }

    def _val_scope(self) -> dict:
        return {
            "lob_scope": {"mode": "specific", "values": ["HL"]},
            "stage_scope": {"mode": "specific", "values": ["CreditApproval"]},
        }

    def _val_intent(self) -> dict:
        return {
            "id": "intent_val_001",
            "text": "Display valuation report when assessor confirms collateral value",
            "family": "positive",
            "action_target": "valuation report",
            "screen_hint": "Collateral Details",
            "expected_outcome": "display",
            "entity": "valuation report",
            "target_field": "collateral value field",
            "expected_state": "display",
            "polarity": "positive",
            "must_anchor_terms": ["valuation report", "collateral value"],
            "must_assert_terms": ["display", "valuation"],
            "forbidden_terms": ["subloan", "recommendation", "omni"],
            "section_key": "ui_structure",
            "section_title": "UI Structure Validation",
            "pattern_terms": ["valuation", "collateral", "display"],
        }

    def _omni_hit(self) -> dict:
        """A high-scoring OMNI/Recommendation fixture that should NOT win for a valuation intent."""
        scenario_steps = [
            {"keyword": "Given", "step_text": "user is on Recommendation Decisions screen", "screen_context": "Recommendation Decisions"},
            {"keyword": "When", "step_text": "user confirms separate decision for omni sub products", "screen_context": "Recommendation Decisions"},
            {"keyword": "Then", "step_text": "separate decision should be displayed for selected sub products", "screen_context": "Recommendation Decisions"},
        ]
        return {
            "step_id": 99001,
            "step_text": "user confirms separate decision for omni sub products",
            "keyword": "When",
            "score": 0.92,
            "screen_context": "Recommendation Decisions",
            "scenario_title": "Separate decision at recommendation for OMNI sub products",
            "file_path": "workspace/reference_repo/Features/omni/SeparateDecision.feature",
            "file_name": "SeparateDecision.feature",
            "scenario_steps": scenario_steps,
            "scope_stage_tags": ["@Recommendation"],
            "scope_sub_tags": ["@CommitteeDecision"],
            "scope_product_types": ["OMNI"],
            "scope_application_stages": ["Recommendation"],
        }

    def test_domain_gate_accepts_valuation_fixture_for_valuation_intent(self):
        """A collateral/valuation fixture should pass _scenario_domain_ok for a valuation intent."""
        hit = self._val_hit(
            step_text="user uploads valuation report for collateral assessment",
            score=0.83,
            scenario_title="Display Collateral Valuation Report at Credit Approval",
            then_text="collateral value field should be displayed with valuation report details",
        )
        context = {
            "search_text": "Display valuation report when assessor confirms collateral value Collateral Details at CreditApproval",
            "screen_hint": "Collateral Details",
            "action_target": "valuation report",
            "entity": "valuation report",
            "target_field": "collateral value field",
            "section_key": "ui_structure",
            "pattern_terms": ["valuation", "collateral", "display"],
        }
        self.assertTrue(fa._scenario_domain_ok(hit, context))

    def test_domain_gate_rejects_omni_fixture_for_valuation_intent(self):
        """An OMNI/Recommendation fixture should NOT pass _scenario_domain_ok for a valuation intent
        when screen and domain evidence are clearly different."""
        hit = self._omni_hit()
        context = {
            "search_text": "Display valuation report when assessor confirms collateral value Collateral Details",
            "screen_hint": "Collateral Details",
            "action_target": "valuation report",
            "entity": "valuation report",
            "target_field": "collateral value field",
            "section_key": "ui_structure",
            "pattern_terms": ["valuation", "collateral", "display"],
        }
        self.assertFalse(fa._scenario_domain_ok(hit, context))

    def test_same_domain_family_rejects_cross_domain_assertion(self):
        """_same_domain_family should reject an OMNI assertion for a valuation anchor."""
        anchor = self._val_hit(
            step_text="user uploads valuation report",
            score=0.85,
            scenario_title="Display Collateral Valuation at Credit Approval",
            then_text="collateral value should be displayed",
        )
        omni_assertion = {
            "step_text": "separate decision should be displayed for selected sub products",
            "keyword": "Then",
            "score": 0.80,
            "screen_context": "Recommendation Decisions",
            "file_path": "workspace/reference_repo/Features/omni/SeparateDecision.feature",
            "scenario_title": "Separate decision at Recommendation",
            "scope_sub_tags": [],
            "scope_stage_tags": ["@Recommendation"],
        }
        self.assertFalse(fa._same_domain_family(omni_assertion, anchor))

    def test_same_domain_family_accepts_same_screen_valuation_assertion(self):
        """_same_domain_family should accept a valuation assertion for a valuation anchor
        even if the file path differs, as long as screen context matches."""
        anchor = self._val_hit(
            step_text="user uploads valuation report",
            score=0.85,
            scenario_title="Display Collateral Valuation at Credit Approval",
            then_text="collateral value should be displayed",
        )
        same_screen_assertion = {
            "step_text": "collateral value should be shown",
            "keyword": "Then",
            "score": 0.79,
            "screen_context": "Collateral Details",
            "file_path": "workspace/reference_repo/Features/creditapproval/collateral/Approval.feature",
            "scenario_title": "Collateral value display",
            "scope_sub_tags": [],
            "scope_stage_tags": ["@CreditApproval"],
        }
        self.assertTrue(fa._same_domain_family(same_screen_assertion, anchor))

    @patch("casforge.generation.feature_assembler.search")
    def test_anchor_selection_prefers_valuation_domain_over_omni(self, mock_search):
        """Given both OMNI and valuation hits, anchor selection must prefer valuation for a valuation intent."""
        omni = self._omni_hit()
        valuation = self._val_hit(
            step_text="user uploads valuation report for collateral assessment",
            score=0.78,
            scenario_title="Display Collateral Valuation Report at Credit Approval",
            then_text="collateral value field should be displayed",
        )
        mock_search.return_value = [omni, valuation]
        intent = self._val_intent()
        scope = self._val_scope()

        anchors, removed, relaxed, rejected = fa._select_anchor_variants(intent, scope, "@CreditApproval", 1)

        self.assertGreaterEqual(len(anchors), 1, "Should select at least one anchor")
        if anchors:
            self.assertIn("collateral", anchors[0]["file_path"].lower(),
                         "Anchor must come from collateral domain, not OMNI")
            self.assertNotIn("omni", anchors[0]["file_path"].lower())

    def test_polarity_mismatch_rejects_approval_enabled_for_disabled_intent(self):
        """For a 'disabled' intent in valuation domain, an 'enabled' candidate should be rejected."""
        hit = self._val_hit(
            step_text="user sets valuation status to approved",
            score=0.85,
            scenario_title="Approval decision enabled when collateral is valued",
            then_text="approval decision field should be enabled",
        )
        context = {
            "text": "Disable approval decision when collateral is not valued",
            "search_text": "Disable approval decision when collateral is not valued Collateral Details",
            "screen_hint": "Collateral Details",
            "action_target": "approval decision",
            "expected_outcome": "disabled",
            "entity": "approval decision",
            "target_field": "approval decision field",
            "expected_state": "disabled",
            "polarity": "disabled",
            "must_anchor_terms": ["approval decision", "collateral"],
            "must_assert_terms": ["disabled"],
            "forbidden_terms": ["enabled"],
            "family": "dependency",
        }
        scope = self._val_scope()
        rejection = fa._candidate_rejection_reason(hit, context, scope)
        self.assertEqual(rejection, "polarity_mismatch")

    def test_story_facts_extracts_rules_from_credit_approval_domain_story(self):
        """story_facts correctly extracts rules from a Credit Approval domain story
        that shares no vocabulary with the OMNI recommendation family."""
        story = JiraStory(
            issue_key="CAS-COLL-001",
            summary="Display Collateral Valuation at Credit Approval",
            issue_type="Story",
            description="",
            current_process="",
            new_process=(
                "CREDIT APPROVAL\n"
                "* Collateral value field should be displayed when valuation report is uploaded.\n"
                "* If any collateral is not valued, the approval decision field will be disabled.\n"
                "* Valuation status field should be enabled once assessor confirms the valuation."
            ),
            business_scenarios="",
            impacted_areas="Collateral Details",
            key_ui_steps="CAS >> Credit Approval >> Collateral Details",
            acceptance_criteria="Display collateral value field and disable approval decision when collateral is not valued.",
            story_description="",
        )
        facts = infer_story_facts_heuristically(story)

        self.assertTrue(facts["rules"], "Should extract at least one rule")
        effects = {rule["effect"] for rule in facts["rules"]}
        self.assertTrue(effects & {"display", "disable", "enable"},
                        f"Expected display/disable/enable rules, got effects: {effects}")
        self.assertTrue(
            any(rule.get("effect") == "disable" for rule in facts["rules"]),
            "Should have a disable rule for approval decision"
        )

    def test_planner_builds_items_for_credit_approval_domain(self):
        """Planner produces structured items for Credit Approval domain,
        not just coverage_gaps or empty output."""
        from casforge.generation.intent_extractor import infer_story_scope_defaults
        story = JiraStory(
            issue_key="CAS-COLL-001",
            summary="Display Collateral Valuation at Credit Approval",
            issue_type="Story",
            description="",
            current_process="",
            new_process=(
                "CREDIT APPROVAL\n"
                "* Collateral value field should be displayed when valuation report is uploaded.\n"
                "* If any collateral is not valued, the approval decision field will be disabled.\n"
                "* Valuation status field should be enabled once assessor confirms the valuation."
            ),
            business_scenarios="",
            impacted_areas="Collateral Details",
            key_ui_steps="CAS >> Credit Approval >> Collateral Details",
            acceptance_criteria="Display collateral value and disable approval decision when not valued.",
            story_description="",
        )
        defaults = infer_story_scope_defaults(story)
        facts = infer_story_facts_heuristically(story, defaults)
        plan_items = build_scenario_plan_items(story, story_scope_defaults=defaults, story_facts=facts)

        self.assertGreaterEqual(len(plan_items), 2, "Should build at least 2 plan items for this story")
        for item in plan_items:
            self.assertTrue(item.get("must_anchor_terms"), f"Item missing must_anchor_terms: {item}")
            self.assertLessEqual(len(item["text"].split()), 14,
                                 f"Plan item title too long: {item['text']}")
        families = {item["family"] for item in plan_items}
        self.assertTrue(families & {"positive", "dependency"},
                        f"Expected positive/dependency families, got: {families}")

    def test_no_cross_domain_leakage_in_retrieval_assertions(self):
        """_assertion_candidate_ok must reject a cross-domain assertion
        (different screen, different path) even when the step score is high."""
        anchor = self._val_hit(
            step_text="user confirms collateral valuation",
            score=0.88,
            scenario_title="Collateral valuation confirmation at Credit Approval",
            then_text="collateral value field should be displayed",
        )
        cross_domain = {
            "step_text": "Recommendation Decision dropdown should be disabled",
            "keyword": "Then",
            "score": 0.93,
            "screen_context": "Recommendation Decisions",
            "file_path": "workspace/reference_repo/Features/omni/SeparateDecision.feature",
            "scenario_title": "Disable Recommendation Decision Dropdown at Recommendation Stage",
            "scope_sub_tags": [],
            "scope_stage_tags": ["@Recommendation"],
            "scope_product_types": ["OMNI"],
            "scope_application_stages": ["Recommendation"],
            "scenario_steps": [],
        }
        context = {
            "search_text": "Display collateral value field at Credit Approval Collateral Details",
            "screen_hint": "Collateral Details",
            "action_target": "collateral value",
            "entity": "collateral value",
            "target_field": "collateral value field",
            "expected_outcome": "display",
            "must_assert_terms": ["display", "collateral"],
        }
        scope = self._val_scope()
        result = fa._assertion_candidate_ok(cross_domain, context, anchor, scope)
        self.assertFalse(result, "Cross-domain assertion should be rejected even with high score")


if __name__ == "__main__":
    unittest.main()
