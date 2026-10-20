from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel_pomdp.investigation.schemas import ObservationToken

IDENTIFIER_PATTERN = r"^[A-Za-z0-9_.-]+$"
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
REGISTERED_DOMAIN_TOOLS = {
    "fetch_order", "fetch_delivery_events", "fetch_source_provenance",
    "fetch_invoice", "fetch_purchase_order", "fetch_invoice_lines",
    "fetch_goods_receipt", "check_source_version",
    "investigate_fact_evidence", "investigate_entity_relationships",
    "investigate_competing_claims",
}


class DomainPackStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REVIEW_PENDING = "REVIEW_PENDING"
    PROVISIONAL = "PROVISIONAL"  # compatibility with calibrated Implementation 15 packs
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class InvestigationMode(str, Enum):
    FACTUAL = "FACTUAL"
    PROBABILISTIC = "PROBABILISTIC"


class ParameterSource(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REVIEWER_ASSUMED = "REVIEWER_ASSUMED"
    EMPIRICALLY_ESTIMATED = "EMPIRICALLY_ESTIMATED"


class CalibrationStatus(str, Enum):
    REVIEWER_ASSUMED = "REVIEWER_ASSUMED"
    EMPIRICALLY_ESTIMATED = "EMPIRICALLY_ESTIMATED"
    VALIDATED_ON_HOLDOUT = "VALIDATED_ON_HOLDOUT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    REJECTED = "REJECTED"
    APPROVED_FOR_PILOT = "APPROVED_FOR_PILOT"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DomainAction(StrictModel):
    action_id: str = Field(pattern=IDENTIFIER_PATTERN, max_length=128)
    relation_hypotheses: dict[str, str] = Field(default_factory=dict)
    cost: float = Field(gt=0, le=10)


class EvidenceRequirement(StrictModel):
    evidence_type: str = Field(pattern=IDENTIFIER_PATTERN, max_length=128)
    required: bool = True
    minimum_independent_sources: int = Field(default=1, ge=1, le=10)
    accepted_source_groups: list[str] = Field(default_factory=list, max_length=20)


class DataMapping(StrictModel):
    source_field: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(pattern=IDENTIFIER_PATTERN, max_length=128)
    relationship_type: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN, max_length=128)
    data_type: str = Field(pattern=r"^(string|integer|decimal|date|datetime|boolean)$")
    validation_rule: str = Field(pattern=r"^(required|optional|identifier|nonnegative|iso_date|iso_datetime|money)$")
    source_row_field: str = Field(min_length=1, max_length=200)
    available_at_field: str | None = Field(default=None, max_length=200)
    source_group: str = Field(min_length=1, max_length=200)


class FactualPolicy(StrictModel):
    outcomes: list[str] = Field(min_length=2, max_length=20)
    required_record_types: list[str] = Field(default_factory=list, max_length=20)
    require_goods_receipt: bool = False
    currency_must_match: bool = True
    quantity_tolerance: str = "0"
    unit_price_tolerance: str = "0.00"
    total_tolerance: str = "0.01"
    rounding: str = Field(default="ROUND_HALF_UP", pattern=r"^ROUND_(HALF_UP|HALF_EVEN|DOWN|UP)$")

    @field_validator("quantity_tolerance", "unit_price_tolerance", "total_tolerance")
    @classmethod
    def valid_decimal(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("tolerances must be decimal strings") from exc
        if parsed < 0 or not parsed.is_finite():
            raise ValueError("tolerances must be finite and nonnegative")
        return value


class GovernanceMetadata(StrictModel):
    author: str = Field(min_length=1, max_length=200)
    reviewer: str | None = Field(default=None, max_length=200)
    dataset_provenance: list[str] = Field(default_factory=list, max_length=50)
    source_dependencies: list[str] = Field(default_factory=list, max_length=50)
    validation_findings: list[str] = Field(default_factory=list, max_length=100)
    created_at: datetime
    approved_at: datetime | None = None
    retired_at: datetime | None = None
    retirement_reason: str | None = Field(default=None, max_length=1000)
    supersedes_version: str | None = Field(default=None, max_length=100)


class CalibrationMetadata(StrictModel):
    training_dataset_id: str
    training_dataset_version: str
    split_manifest_strategy: str
    method: str
    sample_counts: dict[str, int]
    validation_results: dict[str, float] = Field(default_factory=dict)
    status: CalibrationStatus
    estimated_at: datetime
    effective_at: datetime | None = None
    limitations: list[str] = Field(default_factory=list)


class DomainPack(StrictModel):
    domain_id: str = Field(pattern=IDENTIFIER_PATTERN, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    tenant_owner: str | None = Field(default=None, max_length=200)
    schema_version: str = "1.0"
    claim_type: str = Field(min_length=1, max_length=100)
    supported_question_types: list[str] = Field(default_factory=list, max_length=30)
    investigation_mode: InvestigationMode = InvestigationMode.PROBABILISTIC
    hypotheses: list[str] = Field(default_factory=list, max_length=20)
    entity_types: list[str] = Field(default_factory=list, max_length=50)
    relationship_types: list[str] = Field(default_factory=list, max_length=50)
    required_evidence: list[EvidenceRequirement] = Field(default_factory=list, max_length=30)
    optional_evidence: list[EvidenceRequirement] = Field(default_factory=list, max_length=30)
    expected_observation_tokens: list[str] = Field(default_factory=list, max_length=20)
    registered_tools: list[str] = Field(default_factory=list, max_length=30)
    mappings: list[DataMapping] = Field(default_factory=list, max_length=100)
    factual_policy: FactualPolicy | None = None
    prior: dict[str, float] = Field(default_factory=dict)
    actions: list[DomainAction] = Field(default_factory=list, max_length=20)
    observation_model: dict[str, dict[str, dict[str, float]]] = Field(default_factory=dict)
    answer_threshold: float | None = Field(default=None, gt=.5, lt=1)
    minimum_independent_sources: int = Field(default=1, ge=1, le=10)
    discount_factor: float = Field(default=.95, gt=0, le=1)
    planning_horizon: int = Field(default=2, ge=0, le=2)
    rewards: dict[str, float] = Field(default_factory=dict)
    abstention_behavior: str = Field(default="ABSTAIN", pattern=r"^ABSTAIN$")
    status: DomainPackStatus = DomainPackStatus.DRAFT
    model_version: str = Field(min_length=1, max_length=100, pattern=IDENTIFIER_PATTERN)
    calibration_note: str = Field(min_length=1, max_length=1000)
    approved_by: str | None = None
    parameter_source: ParameterSource = ParameterSource.REVIEWER_ASSUMED
    calibration: CalibrationMetadata | None = None
    governance: GovernanceMetadata | None = None
    evaluation_status: str = Field(default="NOT_EVALUATED", max_length=100)

    @property
    def immutable_version_id(self) -> str:
        payload = self.semantic_payload()
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @model_validator(mode="after")
    def validate_contract(self) -> "DomainPack":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported domain-pack schema version")
        if self.tenant_owner is not None and not self.tenant_owner.strip():
            raise ValueError("tenant owner cannot be blank")
        if len(set(self.registered_tools)) != len(self.registered_tools):
            raise ValueError("registered tools must be unique")
        unknown_tools = set(self.registered_tools) - REGISTERED_DOMAIN_TOOLS
        if unknown_tools:
            raise ValueError("unknown registered tool identifiers: " + ", ".join(sorted(unknown_tools)))
        mapping_keys = {(item.source_field, item.entity_type, item.relationship_type) for item in self.mappings}
        if len(mapping_keys) != len(self.mappings):
            raise ValueError("duplicate data mappings are not allowed")
        if self.investigation_mode == InvestigationMode.FACTUAL:
            if self.factual_policy is None:
                raise ValueError("factual packs require a factual policy")
            if self.prior or self.observation_model or self.actions:
                raise ValueError("factual packs cannot define probabilistic parameters")
            if self.parameter_source != ParameterSource.NOT_APPLICABLE:
                raise ValueError("factual packs must use NOT_APPLICABLE parameter source")
        else:
            self._validate_probability_model()
        if self.status in {DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE} and not self.approved_by:
            raise ValueError("approved domain packs require approved_by")
        if self.parameter_source == ParameterSource.EMPIRICALLY_ESTIMATED and self.calibration is None:
            raise ValueError("empirically estimated packs require calibration metadata")
        if (self.status in {DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE}
                and self.parameter_source == ParameterSource.EMPIRICALLY_ESTIMATED
                and (self.calibration is None
                     or self.calibration.status != CalibrationStatus.APPROVED_FOR_PILOT)):
            raise ValueError("empirical packs require explicit pilot approval before activation")
        return self

    def _validate_probability_model(self) -> None:
        states = set(self.hypotheses)
        if len(states) < 2 or len(states) != len(self.hypotheses):
            raise ValueError("probabilistic packs require at least two unique hypotheses")
        if set(self.prior) != states or abs(sum(self.prior.values()) - 1) > 1e-9:
            raise ValueError("prior must define every hypothesis and sum to 1")
        if any(value < 0 or value > 1 for value in self.prior.values()):
            raise ValueError("prior probabilities must be in [0, 1]")
        if self.answer_threshold is None:
            raise ValueError("probabilistic packs require an answer threshold")
        action_ids = {action.action_id for action in self.actions}
        if not action_ids or len(action_ids) != len(self.actions) or set(self.observation_model) != action_ids:
            raise ValueError("observation model must define every action exactly once")
        valid_observations = {item.value for item in ObservationToken}
        for action in self.actions:
            if not action.relation_hypotheses or not set(action.relation_hypotheses.values()) <= states:
                raise ValueError("action relation mappings must target configured hypotheses")
            rows = self.observation_model[action.action_id]
            if set(rows) != states:
                raise ValueError("every action must define likelihoods for every hypothesis")
            outcomes: set[str] | None = None
            for row in rows.values():
                if not row or not set(row) <= valid_observations:
                    raise ValueError("likelihoods contain an unsupported observation")
                if outcomes is None:
                    outcomes = set(row)
                if set(row) != outcomes or abs(sum(row.values()) - 1) > 1e-9:
                    raise ValueError("likelihood rows must share outcomes and sum to 1")
                if any(value < 0 or value > 1 for value in row.values()):
                    raise ValueError("likelihoods must be in [0, 1]")
        if self.expected_observation_tokens:
            configured = {token for rows in self.observation_model.values()
                          for row in rows.values() for token in row}
            if set(self.expected_observation_tokens) != configured:
                raise ValueError("expected observation tokens must match the observation model")
        if set(self.rewards) - {"correct_answer_reward", "incorrect_answer_penalty", "abstain_reward"}:
            raise ValueError("rewards contain unsupported engine parameters")
        if self.rewards.get("incorrect_answer_penalty", 0) < 0:
            raise ValueError("incorrect-answer penalty must be nonnegative")

    def semantic_payload(self) -> dict[str, Any]:
        """Fields that cannot change after a version is approved."""
        payload = self.model_dump(mode="json", exclude={"status", "approved_by", "governance"})
        calibration = payload.get("calibration")
        if calibration is not None:
            # Review state and withdrawal findings are lifecycle metadata; the
            # training identity, method, counts and measured results stay immutable.
            for key in ("status", "effective_at", "limitations"):
                calibration.pop(key, None)
        return payload
