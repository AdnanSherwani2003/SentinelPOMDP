"""Validated public HTTP contracts. Internal workflow state is never returned raw."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sentinel_pomdp.pilot import PilotDataset


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationRequest(APIModel):
    question: str = Field(min_length=1, max_length=2_000)
    planning_horizon: int | None = Field(default=None, ge=0, le=2)
    mode: Literal["registered_pomdp", "document_lookup", "domain_pomdp"] = "registered_pomdp"
    domain_pack_id: str | None = Field(default=None, max_length=128)


class ReviewRequest(APIModel):
    action: Literal["APPROVE", "REJECT"]
    note: str | None = Field(default=None, max_length=2_000)


class JobSubmitRequest(APIModel):
    operation_type: Literal[
        "DOCUMENT_INGESTION", "OLIST_BATCH", "INVESTIGATION", "EVALUATION",
        "DOMAIN_VALIDATION", "DOMAIN_INVESTIGATION"]
    payload: dict[str, Any]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class DocumentLookupResponse(APIModel):
    mode: Literal["DOCUMENT_LOOKUP"] = "DOCUMENT_LOOKUP"
    status: str
    purchase_order: str
    records: list[dict[str, Any]]
    calibrated: Literal[False] = False


class PilotCalibrationRequest(APIModel):
    dataset: PilotDataset
    model_version: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    claim_type: str = Field(min_length=1, max_length=100)
    relation_hypotheses: dict[str, str]
    action_costs: dict[str, float]
    answer_threshold: float = Field(gt=.5, lt=1)
    minimum_independent_sources: int = Field(default=1, ge=1, le=10)
    minimum_state_samples: int = Field(default=5, ge=1)
    minimum_action_state_samples: int = Field(default=3, ge=1)


class ModelReviewRequest(APIModel):
    action: Literal["APPROVE", "REJECT", "ROLLBACK"]


class DomainLifecycleRequest(APIModel):
    action: Literal["SUBMIT", "APPROVE", "REJECT", "ACTIVATE", "RETIRE", "REVALIDATE"]
    reason: str | None = Field(default=None, max_length=1_000)


class DomainInvestigationRequest(APIModel):
    question: str = Field(min_length=1, max_length=2_000)
    version: str | None = Field(default=None, min_length=1, max_length=100)

class OlistImportRequest(APIModel):
    limit: int = Field(default=100, ge=1, le=10_000)
    offset: int = Field(default=0, ge=0)
    expected_archive_sha256: str = Field(min_length=64,max_length=64,pattern=r"^[a-f0-9]{64}$")
    review_action: Literal["APPROVE", "REJECT"]

class OlistPredictionRequest(APIModel):
    order_id: str = Field(min_length=1, max_length=64)
    decision_time: Literal["PURCHASE", "APPROVAL", "CARRIER_HANDOFF"] = "CARRIER_HANDOFF"


class BeliefChange(APIModel):
    hypothesis: str
    initial: float = Field(ge=0, le=1)
    final: float = Field(ge=0, le=1)


class TimelineStep(APIModel):
    step_number: int
    action: str
    observation: str | None = None
    tool_status: str | None = None
    belief_before: dict[str, float]
    belief_after: dict[str, float]
    evidence_ids: list[str]
    document_ids: list[str]
    expected_utility: float
    investigation_cost: float
    latency_ms: float | None = None
    evidence_support: str


class TimingSummary(APIModel):
    planning_ms: float = 0
    graph_ms: float = 0
    model_ms: float = 0
    request_ms: float = 0


class InvestigationAPIResponse(APIModel):
    investigation_id: str
    correlation_id: str
    status: str
    original_question: str
    scenario_id: str | None = None
    decision: Literal["ANSWER", "ABSTAIN"] | None = None
    selected_hypothesis: str | None = None
    posterior: dict[str, float] = Field(default_factory=dict)
    belief_changes: list[BeliefChange] = Field(default_factory=list)
    explanation: str
    fact_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    provenance_status: str | None = None
    limitation: str | None = None
    timeline: list[TimelineStep] = Field(default_factory=list)
    investigation_cost: float = 0
    provider: str
    model: str
    explanation_fallback_used: bool
    grounding_valid: bool | None = None
    trace_available: bool
    timings: TimingSummary


class TracePhase(APIModel):
    node: str
    route: str | None = None
    tool_status: str | None = None
    observation: str | None = None
    duration_ms: float | None = None
    termination_reason: str | None = None


class TraceResponse(APIModel):
    investigation_id: str
    scenario_id: str | None
    decision: str | None
    timeline: list[TimelineStep]
    phases: list[TracePhase]


class SessionResponse(APIModel):
    authenticated: bool
    principal_id: str
    tenant_id: str
    permissions: list[str]


class HealthResponse(APIModel):
    status: str
    backend: str
    provider: str
    details: list[str] = Field(default_factory=list)


class MetricsResponse(APIModel):
    tenant_id: str
    metrics: dict[str, Any]


class ErrorBody(APIModel):
    code: str
    message: str
    correlation_id: str
