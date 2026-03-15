"""
api/models.py
-------------
Pydantic request/response models for the CASForge API.
"""

from __future__ import annotations
from typing import Any, List, Optional, Literal, Union
from pydantic import BaseModel, Field


class StoryRef(BaseModel):
    csv_path:  str
    story_key: str
    story_scope_defaults: Optional["StoryScopeDefaults"] = None


class StoryInfo(BaseModel):
    issue_key:           str
    summary:             str
    issue_type:          str
    description:         str
    new_process:         str
    current_process:     str
    business_scenarios:  str
    impacted_areas:      str
    key_ui_steps:        str
    acceptance_criteria: str
    supplemental_comments: str = ""


class StorySummary(BaseModel):
    key:     str
    summary: str
    type:    str


class IntentsResponse(BaseModel):
    story_key:            str
    summary:              str
    story_scope_defaults: "StoryScopeDefaults"
    intents:              List["IntentItem"]
    legacy_intents:       List[str] = Field(default_factory=list)


class ScopeSelection(BaseModel):
    mode: Literal["all", "specific"] = "all"
    values: List[str] = Field(default_factory=list)


class StoryScopeDefaults(BaseModel):
    lob_scope: ScopeSelection = Field(default_factory=ScopeSelection)
    stage_scope: ScopeSelection = Field(default_factory=ScopeSelection)


class IntentItem(BaseModel):
    id: str
    text: str
    family: str = "core"
    inherit_story_scope: bool = True
    lob_scope: Optional[ScopeSelection] = None
    stage_scope: Optional[ScopeSelection] = None
    action_target: Optional[str] = None
    screen_hint: Optional[str] = None
    expected_outcome: Optional[str] = None
    entity: Optional[str] = None
    target_field: Optional[str] = None
    expected_state: Optional[str] = None
    polarity: Optional[str] = None
    must_anchor_terms: List[str] = Field(default_factory=list)
    must_assert_terms: List[str] = Field(default_factory=list)
    forbidden_terms: List[str] = Field(default_factory=list)
    matrix_signature: Optional[str] = None
    allow_expansion: bool = False


class GenerateRequest(BaseModel):
    csv_path:  str
    story_key: str
    flow_type: Literal["ordered", "unordered"]
    story_scope_defaults: Optional[StoryScopeDefaults] = None
    intents: Optional[List[Union[str, IntentItem]]] = None   # backward-compatible


class GenerateResponse(BaseModel):
    story_key:      str
    summary:        str
    flow_type:      Literal["ordered", "unordered"]
    story_scope_defaults: StoryScopeDefaults
    intents:        List[IntentItem]
    legacy_intents: List[str] = Field(default_factory=list)
    feature_text:   str
    file_path:      str
    stage:          Optional[str] = None
    sub_tags:       List[str] = Field(default_factory=list)
    quality:        dict[str, Any] = Field(default_factory=dict)
    unresolved_steps: List[dict[str, Any]] = Field(default_factory=list)
    scenario_debug: List[dict[str, Any]] = Field(default_factory=list)
    coverage_gaps: List[dict[str, Any]] = Field(default_factory=list)
    omitted_plan_items: List[dict[str, Any]] = Field(default_factory=list)


class DirectForgeRequest(BaseModel):
    title: str = ""
    intents_text: str
    flow_type: Literal["ordered", "unordered"] = "unordered"


class UploadCsvRequest(BaseModel):
    filename: str
    content: str


class UploadCsvResponse(BaseModel):
    filename: str
    stored_path: str


class SearchRequest(BaseModel):
    query:          str
    top_k:          int   = 5
    screen_filter:  Optional[str] = None
    keyword_filter: Optional[str] = None


class StepResult(BaseModel):
    step_id:        int
    keyword:        str
    step_text:      str
    score:          float
    screen_context: Optional[str]
    scenario_title: Optional[str]
    file_name:      Optional[str]
    scenario_steps: List[dict] = []


class OutputFile(BaseModel):
    filename: str
    story_key: str
    content:  str


StoryRef.model_rebuild()
IntentsResponse.model_rebuild()
GenerateRequest.model_rebuild()
GenerateResponse.model_rebuild()
