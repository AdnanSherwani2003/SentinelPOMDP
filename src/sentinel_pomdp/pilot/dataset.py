from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataClassification(str, Enum):
    SYNTHETIC_REPRESENTATIVE = "SYNTHETIC_REPRESENTATIVE"
    AUTHORIZED_ORGANIZATIONAL = "AUTHORIZED_ORGANIZATIONAL"


class ClaimType(str, Enum):
    DELIVERY_TIMELINESS = "DELIVERY_TIMELINESS"
    CAUSAL_ATTRIBUTION = "CAUSAL_ATTRIBUTION"


class LabelStatus(str, Enum):
    UNLABELED = "UNLABELED"
    IN_REVIEW = "IN_REVIEW"
    DISPUTED = "DISPUTED"
    ADJUDICATED = "ADJUDICATED"
    APPROVED = "APPROVED"
    UNKNOWN = "UNKNOWN"


class PilotSplit(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class SelectionMechanism(str, Enum):
    ROUTINE = "ROUTINE"
    SUSPECTED_PROBLEM = "SUSPECTED_PROBLEM"
    UNKNOWN = "UNKNOWN"


class LabelReview(StrictModel):
    reviewer_ref: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=128)
    reviewed_at: datetime
    method: str = Field(min_length=1, max_length=300)
    source_ids: list[str] = Field(default_factory=list)


class PilotCase(StrictModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    domain_id: str = Field(min_length=1, max_length=128)
    dataset_version: str = Field(min_length=1, max_length=100)
    event_time: datetime
    entity_id: str = Field(min_length=1, max_length=128)
    leakage_group_id: str = Field(min_length=1, max_length=128)
    source_family_ids: list[str] = Field(default_factory=list)
    subgroup: dict[str, str] = Field(default_factory=dict)
    claim_type: ClaimType
    ground_truth_label: str | None = Field(default=None, max_length=128)
    ground_truth_source_ids: list[str] = Field(default_factory=list)
    independent_ground_truth: bool = False
    label_status: LabelStatus = LabelStatus.UNLABELED
    label_method: str | None = Field(default=None, max_length=500)
    reviews: list[LabelReview] = Field(default_factory=list)
    split: PilotSplit | None = None
    business_costs: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def label_consistency(self) -> "PilotCase":
        definitive = self.label_status in {LabelStatus.ADJUDICATED, LabelStatus.APPROVED}
        if definitive and (not self.ground_truth_label or not self.ground_truth_source_ids
                           or not self.independent_ground_truth):
            raise ValueError("definitive labels require an independent label and source provenance")
        if self.label_status == LabelStatus.DISPUTED and len({r.label for r in self.reviews}) < 2:
            raise ValueError("disputed labels require disagreeing reviewer records")
        return self

    def evaluation_view(self) -> dict:
        """Return inputs visible to replay; deliberately excludes ground truth."""
        return {
            "case_id": self.case_id, "tenant_id": self.tenant_id,
            "domain_id": self.domain_id, "event_time": self.event_time.isoformat(),
            "entity_id": self.entity_id, "claim_type": self.claim_type.value,
            "subgroup": self.subgroup,
        }


class PilotObservation(StrictModel):
    case_id: str
    action_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=128)
    observation_token: str | None = Field(default=None, max_length=128)
    observed: bool
    source_document_id: str | None = None
    source_group_id: str | None = None
    upstream_source_id: str | None = None
    observation_time: datetime | None = None
    available_at_decision_time: bool = True
    selection_mechanism: SelectionMechanism = SelectionMechanism.UNKNOWN
    missing_reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def observed_shape(self) -> "PilotObservation":
        if self.observed and (not self.observation_token or not self.observation_time):
            raise ValueError("observed records require a token and observation time")
        if not self.observed and self.observation_token is not None:
            raise ValueError("unobserved records cannot contain a counterfactual token")
        return self


class PilotDataset(StrictModel):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=128)
    version: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=128)
    domain_id: str = Field(min_length=1, max_length=128)
    classification: DataClassification
    authorized_use: bool
    usage_basis: str = Field(min_length=1, max_length=1000)
    created_at: datetime
    cases: list[PilotCase]
    observations: list[PilotObservation]
    allowed_labels: list[str] = Field(min_length=2)
    allowed_observations: list[str] = Field(min_length=2)
    retention_note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def identity_consistency(self) -> "PilotDataset":
        if not self.authorized_use:
            raise ValueError("dataset use must be explicitly authorized")
        if len(set(self.allowed_labels)) != len(self.allowed_labels):
            raise ValueError("allowed labels must be unique")
        for case in self.cases:
            if (case.tenant_id != self.tenant_id or case.dataset_version != self.version
                    or case.domain_id != self.domain_id):
                raise ValueError("case scope or dataset version mismatch")
            if case.ground_truth_label and case.ground_truth_label not in self.allowed_labels:
                raise ValueError("case contains an invalid ground-truth label")
        return self
