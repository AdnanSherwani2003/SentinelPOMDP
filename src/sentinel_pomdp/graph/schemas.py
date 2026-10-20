"""Domain-adaptable Knowledge Graph Schemas and Pydantic Models.

Defines typed representations for entities, documents, relation facts, evidence,
and verifiable provenance chains with strict tenant isolation metadata.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of text content for integrity and duplicate detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EvidenceType(str, Enum):
    """Semantic relation between an evidence item and a claim/fact."""
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"


class Entity(BaseModel):
    """Domain-adaptable identifiable entity in the knowledge graph.

    Represents suppliers, components, products, operational facilities,
    or incident cases across enterprise domains.
    """
    entity_id: str = Field(..., description="Unique entity identifier within tenant scope")
    tenant_id: str = Field(..., description="Tenant authorization and ownership boundary")
    entity_type: str = Field(..., description="Domain category: e.g. supplier, product, component, incident")
    canonical_name: str = Field(..., description="Human-readable canonical name")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary domain attributes")
    created_at: str = Field(default_factory=_utc_now_iso)
    updated_at: str = Field(default_factory=_utc_now_iso)

    @field_validator("entity_id", "tenant_id", "entity_type", "canonical_name")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string")
        return v.strip()


class Document(BaseModel):
    """Source record from which evidence is extracted.

    Preserves source metadata, URI, classification, and content hash for integrity.
    """
    document_id: str = Field(..., description="Unique document identifier")
    tenant_id: str = Field(..., description="Tenant authorization boundary")
    title: str = Field(..., description="Descriptive title of the source record")
    source_uri: str = Field(..., description="URI or path where original document is located")
    source_type: str = Field(..., description="Type of document: receiving_log, shipping_manifest, invoice, etc.")
    classification: str = Field(default="internal", description="Data sensitivity classification")
    raw_content: str = Field(default="", description="Raw textual content (treated strictly as inert data)")
    content_hash: str = Field(default="", description="SHA-256 digest of document content")
    created_at: str = Field(default_factory=_utc_now_iso)
    ingested_at: str = Field(default_factory=_utc_now_iso)
    version: int = Field(default=1, ge=1)
    review_status: str = "APPROVED"
    active: bool = True

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            data_to_hash = self.raw_content if self.raw_content else f"{self.title}:{self.source_uri}"
            object.__setattr__(self, "content_hash", compute_content_hash(data_to_hash))

    @field_validator("document_id", "tenant_id", "title", "source_uri", "source_type")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string")
        return v.strip()


class Evidence(BaseModel):
    """Specific evidence item extracted from a source document.

    Links back to a source document. extraction_confidence represents parser / OCR
    extraction quality in [0, 1], explicitly distinct from POMDP belief probabilities.
    """
    evidence_id: str = Field(..., description="Unique evidence snippet identifier")
    tenant_id: str = Field(..., description="Tenant authorization boundary")
    document_id: str = Field(..., description="Foreign key referencing source Document")
    chunk_ref: str = Field(..., description="Reference to location in document: e.g. section_3, line_45, row_2")
    content: str = Field(..., description="Extracted textual or tabular evidence snippet (inert data)")
    extraction_method: str = Field(default="structured_parser", description="Parser/extractor used")
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Extraction quality score in [0.0, 1.0]")
    observed_at: str = Field(default_factory=_utc_now_iso)
    created_at: str = Field(default_factory=_utc_now_iso)
    source_group: str = ""
    review_status: str = "APPROVED"
    active: bool = True

    @field_validator("evidence_id", "tenant_id", "document_id", "chunk_ref", "content")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string")
        return v.strip()


class RelationFact(BaseModel):
    """Reified claim or relationship between two entities.

    Reifying facts as nodes allows multiple independent pieces of evidence to
    SUPPORT or CONTRADICT the same claim, creating auditable, traceable evidence graphs.
    """
    fact_id: str = Field(..., description="Unique fact identifier")
    tenant_id: str = Field(..., description="Tenant authorization boundary")
    relation_type: str = Field(..., description="Semantic relationship: SUPPLIES, DELIVERED, EXPERIENCED_DELAY, etc.")
    subject_id: str = Field(..., description="Foreign key to subject Entity")
    object_id: str = Field(..., description="Foreign key to object Entity")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Metadata associated with the fact")
    observed_at: str = Field(default_factory=_utc_now_iso)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now_iso)
    review_status: str = "APPROVED"
    active: bool = True

    @field_validator("fact_id", "tenant_id", "relation_type", "subject_id", "object_id")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string")
        return v.strip()


class EvidenceLink(BaseModel):
    """Association linking an Evidence item to a RelationFact."""
    link_id: str
    tenant_id: str
    evidence_id: str
    fact_id: str
    link_type: EvidenceType
    created_at: str = Field(default_factory=_utc_now_iso)


class ProvenanceRecord(BaseModel):
    """Detailed audit representation of evidence and its source document."""
    evidence_id: str
    chunk_ref: str
    content: str
    extraction_method: str
    extraction_confidence: float
    observed_at: str
    document_id: str
    document_title: str
    source_uri: str
    source_type: str
    classification: str
    content_hash: str
    source_group: str = ""
    document_version: int = 1


class FactProvenanceStatus(str, Enum):
    """Audit status of a fact's evidence support."""
    SUPPORTED = "SUPPORTED"          # Only supporting evidence present
    CONFLICTED = "CONFLICTED"        # Both supporting and contradictory evidence present
    CONTRADICTED = "CONTRADICTED"    # Only contradictory evidence present
    UNEVIDENCED = "UNEVIDENCED"      # No evidence attached to this fact


class ProvenanceChain(BaseModel):
    """Full auditable provenance chain for a relation fact."""
    fact: RelationFact
    subject: Optional[Entity] = None
    object: Optional[Entity] = None
    supporting_evidence: List[ProvenanceRecord] = Field(default_factory=list)
    contradicting_evidence: List[ProvenanceRecord] = Field(default_factory=list)
    status: FactProvenanceStatus = FactProvenanceStatus.UNEVIDENCED
    summary: str = ""

    def model_post_init(self, __context: Any) -> None:
        has_sup = len(self.supporting_evidence) > 0
        has_con = len(self.contradicting_evidence) > 0
        if has_sup and has_con:
            stat = FactProvenanceStatus.CONFLICTED
            summ = f"Conflicting evidence: {len(self.supporting_evidence)} supporting vs {len(self.contradicting_evidence)} contradicting records."
        elif has_sup:
            stat = FactProvenanceStatus.SUPPORTED
            summ = f"Supported by {len(self.supporting_evidence)} independent evidence records."
        elif has_con:
            stat = FactProvenanceStatus.CONTRADICTED
            summ = f"Contradicted by {len(self.contradicting_evidence)} evidence records."
        else:
            stat = FactProvenanceStatus.UNEVIDENCED
            summ = "Missing evidence: no supporting or contradicting records attached."
        object.__setattr__(self, "status", stat)
        if not self.summary:
            object.__setattr__(self, "summary", summ)


class TraversalPath(BaseModel):
    """Consistent, typed representation of a multi-hop graph traversal.

    Represents an ordered path through domain entities and reified relation facts.
    Supports both attribute access (.path, .hops) and subscript access (['path'], ['hops']).
    """
    path: List[Dict[str, Any]] = Field(
        ...,
        description="Ordered sequence of nodes along the traversal path (each with id, type, name, labels)",
    )
    hops: int = Field(default=1, description="Number of entity-to-entity hops")

    def __getitem__(self, key: str) -> Any:
        """Allow subscript access (e.g., p['path'], p['hops']) for backward compatibility."""
        if key == "path":
            return self.path
        elif key == "hops":
            return self.hops
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return key in ("path", "hops")

    def get(self, key: str, default: Any = None) -> Any:
        if key == "path":
            return self.path
        elif key == "hops":
            return self.hops
        return default

    def to_dict(self) -> Dict[str, Any]:
        """Convert to standard dictionary."""
        return {"path": self.path, "hops": self.hops}
