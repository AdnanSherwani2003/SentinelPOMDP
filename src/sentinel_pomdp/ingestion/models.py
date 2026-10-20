"""Canonical source, parsing, extraction, and review contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PARSED = "PARSED"
    NEEDS_OCR = "NEEDS_OCR"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class CandidateStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class SourceLocation(StrictModel):
    document_id: str
    version: int = Field(ge=1)
    locator: str
    page: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)
    column: str | None = None
    line: int | None = Field(default=None, ge=1)
    source_text: str = Field(min_length=1, max_length=8_000)
    source_group: str = Field(min_length=1, max_length=256)


class NormalizedRecord(StrictModel):
    record_id: str
    location: SourceLocation
    fields: dict[str, str]


class NormalizedSegment(StrictModel):
    segment_id: str
    location: SourceLocation
    text: str = Field(min_length=1, max_length=100_000)


class NormalizedDocument(StrictModel):
    document_id: str
    tenant_id: str
    source_type: Literal["csv", "xlsx", "pdf", "docx", "txt"]
    segments: list[NormalizedSegment] = Field(default_factory=list, max_length=10_000)
    records: list[NormalizedRecord] = Field(default_factory=list, max_length=10_000)
    warnings: list[str] = Field(default_factory=list)


class CompanyDocument(StrictModel):
    document_id: str
    tenant_id: str
    dataset_id: str
    source_name: str
    source_type: str
    media_type: str
    source_hash: str
    version: int = Field(ge=1)
    ingestion_id: str
    status: DocumentStatus
    classification: str = "confidential"
    byte_size: int = Field(ge=0)
    imported_at: str = Field(default_factory=utc_now)
    supersedes_document_id: str | None = None
    parser_warnings: list[str] = Field(default_factory=list)
    failure_code: str | None = None
    active: bool = True


class DatasetConfiguration(StrictModel):
    dataset_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    field_mapping: dict[str, str]
    date_format: str = "%Y-%m-%d"
    timezone: str = "UTC"
    review_required: bool = True
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    allowed_source_types: set[str] = Field(default_factory=lambda: {"csv", "xlsx", "pdf", "docx", "txt"})
    created_at: str = Field(default_factory=utc_now)

    @field_validator("field_mapping")
    @classmethod
    def required_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        if "purchase_order" not in value:
            raise ValueError("field_mapping requires purchase_order")
        if not ({"expected_date", "actual_date"} & set(value)):
            raise ValueError("field_mapping requires expected_date or actual_date")
        if any(not key.strip() or not column.strip() for key, column in value.items()):
            raise ValueError("field mappings must be non-empty")
        return value


class CandidateSource(StrictModel):
    location: SourceLocation
    extraction_method: str
    extraction_confidence: float = Field(ge=0, le=1)
    direct_statement: bool


class FactCandidate(StrictModel):
    candidate_id: str
    tenant_id: str
    dataset_id: str
    subject_id: str
    subject_name: str
    object_id: str
    object_name: str
    relation_type: Literal["EXPERIENCED_DELAY", "DELIVERED_ON_TIME", "OLIST_DELIVERY_OUTCOME",
                           "CUSTOMER_PLACED_ORDER", "ORDER_CONTAINS_ITEM",
                           "ITEM_SOLD_BY_SELLER", "ITEM_REFERENCES_PRODUCT"]
    attributes: dict[str, Any]
    sources: list[CandidateSource] = Field(min_length=1)
    status: CandidateStatus = CandidateStatus.NEEDS_REVIEW
    extraction_method: str = "deterministic_delivery_comparison"
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    graph_fact_id: str | None = None


class IngestionResult(StrictModel):
    ingestion_id: str
    document: CompanyDocument
    duplicate: bool = False
    candidates_created: int = 0
