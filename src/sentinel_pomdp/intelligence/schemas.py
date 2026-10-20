"""Strict contracts at both sides of the untrusted LLM boundary."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentType(str, Enum):
    INVESTIGATE = "INVESTIGATE"
    CLARIFY = "CLARIFY"
    UNSUPPORTED = "UNSUPPORTED"


class ClaimType(str, Enum):
    NONE = "NONE"
    SHIPMENT_TIMELINESS = "SHIPMENT_TIMELINESS"
    CAUSAL_ATTRIBUTION = "CAUSAL_ATTRIBUTION"
    DELIVERY_TIMELINESS = "DELIVERY_TIMELINESS"
    CERTIFICATION_STATUS = "CERTIFICATION_STATUS"
    DELAY_SIGNAL_SCREENING = "DELAY_SIGNAL_SCREENING"


class ResponseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    INTERPRETATION_FAILED = "INTERPRETATION_FAILED"


class ParsedInvestigationIntent(StrictModel):
    intent_type: IntentType
    scenario_id: str = ""
    subject_id: str = ""
    claim_type: ClaimType = ClaimType.NONE
    clarification_question: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def consistent_shape(self) -> "ParsedInvestigationIntent":
        populated = bool(self.scenario_id and self.subject_id and self.claim_type != ClaimType.NONE)
        if self.intent_type == IntentType.INVESTIGATE and not populated:
            raise ValueError("investigation intent requires scenario, subject, and claim type")
        if self.intent_type == IntentType.CLARIFY and not self.clarification_question:
            raise ValueError("clarification intent requires a question")
        return self


class BeliefEntry(StrictModel):
    hypothesis: str
    probability: float = Field(ge=0, le=1)


class GroundedExplanationDraft(StrictModel):
    decision: Literal["ANSWER", "ABSTAIN"]
    selected_hypothesis: str = ""
    final_belief: list[BeliefEntry]
    summary: str = Field(min_length=1, max_length=1200)
    fact_ids: list[str]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    document_ids: list[str]
    provenance_status: str
    limitation: str = Field(default="", max_length=500)


class LLMUsage(StrictModel):
    provider: str
    model: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0)


class InvestigationResponse(StrictModel):
    status: ResponseStatus
    question: str
    scenario_id: str | None = None
    subject_id: str | None = None
    claim_type: ClaimType | None = None
    decision: Literal["ANSWER", "ABSTAIN"] | None = None
    selected_hypothesis: str | None = None
    final_belief: dict[str, float] = Field(default_factory=dict)
    explanation: str
    fact_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    provenance_status: str | None = None
    limitation: str | None = None
    interpretation_fallback_used: bool = False
    explanation_fallback_used: bool = False
    grounding_valid: bool | None = None
    trace_id: str
    investigation: dict[str, Any] | None = None
    llm_usage: list[LLMUsage] = Field(default_factory=list)
