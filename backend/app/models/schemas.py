"""Pydantic schemas for API request/response and internal data contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Product hierarchy ────────────────────────────────────────────────────────

class ProductModelSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    model_number: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class ProductFamilySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str = ""
    products: list[ProductModelSchema] = Field(default_factory=list)


class ProductCategorySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str = ""
    families: list[ProductFamilySchema] = Field(default_factory=list)


# ── SOP Flow JSON schema ────────────────────────────────────────────────────

class StepSchema(BaseModel):
    id: str
    type: Literal["instruction", "question", "check", "decision", "terminal", "escalation"]
    customer_message: str
    agent_notes: str = ""
    expected_responses: list[str] = Field(default_factory=list)
    response_buttons: list[str] = Field(default_factory=list)
    on_done: Optional[str] = None
    on_yes: Optional[str] = None
    on_no: Optional[str] = None
    on_not_sure: Optional[str] = None
    on_failed: Optional[str] = None
    on_other: Optional[str] = None
    retry_limit: int = 1
    safety_note: str = ""
    requires_attachment: bool = False


class TerminalStateSchema(BaseModel):
    id: str
    type: Literal["resolved", "escalation", "abandoned"]
    message: str


class ProductInfoSchema(BaseModel):
    name: str = ""
    category: str = ""
    family: str = ""
    model_aliases: list[str] = Field(default_factory=list)


class IssueInfoSchema(BaseModel):
    name: str = ""
    category: str = ""
    symptom_phrases: list[str] = Field(default_factory=list)
    negative_phrases: list[str] = Field(default_factory=list)


class SopFlowSchema(BaseModel):
    sop_id: str
    title: str
    # Scope controls runtime SOP selection priority: model > family > category > generic
    scope: Literal["generic", "category", "family", "model"] = "model"
    product: ProductInfoSchema = Field(default_factory=ProductInfoSchema)
    issue: IssueInfoSchema = Field(default_factory=IssueInfoSchema)
    prerequisites: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)
    steps: list[StepSchema] = Field(default_factory=list)
    terminal_states: list[TerminalStateSchema] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    version: int = 1
    status: Literal["draft", "reviewed", "published"] = "draft"
    source_file: str = ""
    created_at: str = ""
    inferred_structure: bool = False

    @model_validator(mode="after")
    def ensure_terminal_states(self) -> "SopFlowSchema":
        ids = {t.id for t in self.terminal_states}
        if "resolved" not in ids:
            self.terminal_states.append(
                TerminalStateSchema(id="resolved", type="resolved",
                                    message="I am glad we could resolve this! Is there anything else I can assist you with today?")
            )
        if "escalated" not in ids:
            self.terminal_states.append(
                TerminalStateSchema(id="escalated", type="escalation",
                                    message="I understand your concern and I am here to help. Allow me to connect you with our support team who will be able to assist you further.")
            )
        return self


# ── Chat API ────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    customer_id: str
    channel: str = "web"
    message: str


class BotMessage(BaseModel):
    type: Literal["text", "buttons", "info"]
    text: str
    buttons: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    conversation_id: str
    messages: list[BotMessage]
    state: str
    debug: Optional[dict] = None


# ── Streaming ───────────────────────────────────────────────────────────────

class StreamChunk(BaseModel):
    """Single SSE payload chunk."""
    type: Literal["text", "buttons", "done", "error"]
    text: str = ""
    buttons: list[str] = Field(default_factory=list)
    state: str = ""
    conversation_id: str = ""


# ── Search ──────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    product_text: str = ""
    issue_text: str = ""
    customer_message: str = ""
    product_id: Optional[str] = None
    category_id: Optional[str] = None
    family_id: Optional[str] = None


class SopCandidate(BaseModel):
    sop_flow_id: str
    product: str
    issue: str
    title: str
    score: float
    scope: str = "model"
    match_reasons: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    candidates: list[SopCandidate]
    needs_clarification: bool
    clarification_question: str = ""


# ── Ingestion ───────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    file_path: str
    auto_publish: bool = False


class ParsedSopOutput(BaseModel):
    sop: SopFlowSchema
    review_report: dict[str, Any]
    raw_text_preview: str = ""


# ── Admin ───────────────────────────────────────────────────────────────────

class SopListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sop_slug: str
    title: str
    status: str
    scope: str = "model"
    product: Optional[str] = None
    issue: Optional[str] = None
    version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_id: str
    status: str
    product_id: Optional[str] = None
    issue_id: Optional[str] = None
    sop_flow_id: Optional[str] = None
    current_step_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EscalationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: Optional[str] = None
    customer_id: str
    product_name: Optional[str] = None
    issue_name: Optional[str] = None
    sop_title: Optional[str] = None
    last_completed_step: Optional[str] = None
    failed_step: Optional[str] = None
    summary: Optional[str] = None
    recommended_action: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None


# ── Analytics ───────────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    total_conversations: int
    resolved_count: int
    escalated_count: int
    abandoned_count: int
    top_products: list[dict]
    top_issues: list[dict]
    sop_resolution_rate: list[dict]
    step_dropoff: list[dict]


# ── LLM internal contracts ───────────────────────────────────────────────────

class ClassifyResult(BaseModel):
    detected_product: str = ""
    detected_issue: str = ""
    detected_category: str = ""    # NEW: category hint
    detected_family: str = ""      # NEW: family hint
    symptoms: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str = ""   # NEW: combined into single call
    confidence: float = 0.0
    reason: str = ""


class InterpretResult(BaseModel):
    mapped_response: Literal[
        "yes", "no", "done", "not_sure", "failed",
        "help_needed", "wants_human", "unrelated", "other", "skip"
    ] = "other"
    confidence: float = 0.0
    extracted_observation: str = ""
    should_escalate: bool = False
    reason: str = ""
