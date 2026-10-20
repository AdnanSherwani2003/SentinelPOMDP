"""Typed contracts for read-only graph-backed investigations."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from sentinel_pomdp.graph.schemas import ProvenanceRecord, RelationFact, TraversalPath


class InvestigationAction(str, Enum):
    FACT_EVIDENCE = "investigate_fact_evidence"
    ENTITY_RELATIONSHIPS = "investigate_entity_relationships"
    COMPETING_CLAIMS = "investigate_competing_claims"


class ToolStatus(str, Enum):
    EVIDENCE_FOUND = "EVIDENCE_FOUND"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    NO_EVIDENCE = "NO_EVIDENCE"
    MISSING_RECORD = "MISSING_RECORD"
    UNAUTHORIZED = "UNAUTHORIZED"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"


class ObservationToken(str, Enum):
    SUPPORTED = "EVIDENCE_SUPPORTED"
    CONFLICTED = "EVIDENCE_CONFLICTED"
    CONTRADICTED = "EVIDENCE_CONTRADICTED"
    NOT_FOUND = "EVIDENCE_NOT_FOUND"
    DUPLICATE = "DUPLICATE_INFORMATION"
    HASH_MISMATCH = "SOURCE_HASH_MISMATCH"


class GraphInvestigationRequest(BaseModel):
    """One authorized operation; arbitrary Cypher is deliberately impossible."""

    tenant_id: str
    action_name: InvestigationAction
    target_id: str
    allowed_relation_types: tuple[str, ...] = ()
    max_depth: int = Field(default=1, ge=1, le=2)
    max_results: int = Field(default=50, ge=1, le=100)

    @field_validator("tenant_id", "target_id")
    @classmethod
    def nonempty_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError("identifier must contain 1-128 characters")
        if not all(c.isalnum() or c in "_-.:" for c in value):
            raise ValueError("identifier contains unsupported characters")
        return value

    @field_validator("allowed_relation_types")
    @classmethod
    def valid_relation_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 20 or any(not v or len(v) > 64 or not v.replace("_", "").isalnum() for v in values):
            raise ValueError("invalid allowed relation type")
        return tuple(dict.fromkeys(values))

    @model_validator(mode="after")
    def action_parameters_match(self) -> "GraphInvestigationRequest":
        if self.action_name == InvestigationAction.FACT_EVIDENCE and self.allowed_relation_types:
            raise ValueError("fact evidence requests do not accept relation filters")
        return self


class GraphInvestigationResult(BaseModel):
    action_name: InvestigationAction
    target_id: str
    status: ToolStatus
    facts: list[RelationFact] = Field(default_factory=list)
    supporting_evidence: list[ProvenanceRecord] = Field(default_factory=list)
    contradicting_evidence: list[ProvenanceRecord] = Field(default_factory=list)
    paths: list[TraversalPath] = Field(default_factory=list)
    provenance_verified: bool = False
    hash_mismatches: list[str] = Field(default_factory=list)
    cost: float = Field(ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    error: str | None = None

    @property
    def evidence_ids(self) -> list[str]:
        return sorted({e.evidence_id for e in self.supporting_evidence + self.contradicting_evidence})

    @property
    def document_ids(self) -> list[str]:
        return sorted({e.document_id for e in self.supporting_evidence + self.contradicting_evidence})


class EvidenceObservation(BaseModel):
    action_name: str
    observation_token: ObservationToken
    source_fact_ids: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    source_signal_groups: list[str] = Field(default_factory=list)
    evidence_status: ToolStatus
    provenance_verified: bool
    is_duplicate: bool = False


class EvidenceVerdict(BaseModel):
    sufficient: bool
    hypothesis: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    independent_source_groups: list[str] = Field(default_factory=list)
    provenance_status: str
    reason: str


class InvestigationStep(BaseModel):
    step_number: int
    belief_before: dict[str, float]
    chosen_action: str
    planner_horizon: int
    expected_action_utility: float
    action_scores: dict[str, float]
    tool_invoked: str | None = None
    tool_status: ToolStatus | None = None
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    observation_token: ObservationToken | None = None
    belief_after: dict[str, float]
    investigation_cost: float = 0.0
    latency_ms: float | None = None
    evidence_support: str


class InvestigationOutcome(BaseModel):
    decision: str
    selected_hypothesis: str | None = None
    final_belief: dict[str, float]
    evidence_verdict: EvidenceVerdict
    steps: list[InvestigationStep]
    total_cost: float
    termination_reason: str
    planning_runtime_ms: float
    tool_runtime_ms: float
    metadata: dict[str, Any] = Field(default_factory=dict)
