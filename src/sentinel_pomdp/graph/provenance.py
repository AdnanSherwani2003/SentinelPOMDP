"""Verifiable Evidence Provenance Services and Audit Utilities.

Provides services to validate evidence chains, audit document hash integrity,
detect contradictions between sources, and format human-readable provenance traces.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.graph.schemas import (
    FactProvenanceStatus,
    ProvenanceChain,
    ProvenanceRecord,
    compute_content_hash,
)

logger = logging.getLogger(__name__)


@dataclass
class ProvenanceValidationResult:
    """Detailed audit verdict of a fact's evidence chain."""

    fact_id: str
    tenant_id: str
    status: FactProvenanceStatus
    supporting_count: int
    contradicting_count: int
    all_documents_verified: bool
    hash_mismatches: List[str] = field(default_factory=list)
    chain: Optional[ProvenanceChain] = None
    notes: List[str] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        """True if fact is SUPPORTED, has zero contradictions, and all doc hashes match."""
        return (
            self.status == FactProvenanceStatus.SUPPORTED
            and self.contradicting_count == 0
            and self.all_documents_verified
            and len(self.hash_mismatches) == 0
        )


def validate_evidence_chain(
    repo: BaseGraphRepository,
    fact_id: str,
    tenant_id: str,
) -> ProvenanceValidationResult:
    """Audit the complete provenance chain for a material claim.

    Verifies:
    1. The fact exists in the specified tenant boundary.
    2. Associated supporting and contradictory evidence are retrieved.
    3. Source documents exist and their SHA-256 content hashes match content.
    4. Evaluates whether the claim is SUPPORTED, CONFLICTED, CONTRADICTED, or UNEVIDENCED.
    """
    chain = repo.get_provenance_chain(fact_id=fact_id, tenant_id=tenant_id)
    if not chain:
        return ProvenanceValidationResult(
            fact_id=fact_id,
            tenant_id=tenant_id,
            status=FactProvenanceStatus.UNEVIDENCED,
            supporting_count=0,
            contradicting_count=0,
            all_documents_verified=False,
            notes=[f"Fact '{fact_id}' not found in tenant '{tenant_id}'"],
        )

    hash_mismatches: List[str] = []
    all_docs_verified = True
    notes: List[str] = []

    all_evidence: List[ProvenanceRecord] = chain.supporting_evidence + chain.contradicting_evidence

    for ev in all_evidence:
        doc = repo.get_document(ev.document_id, tenant_id)
        if not doc:
            all_docs_verified = False
            notes.append(f"Evidence {ev.evidence_id} references missing document {ev.document_id}")
            continue

        # If raw content is present, verify hash integrity
        if doc.raw_content:
            computed = compute_content_hash(doc.raw_content)
            if computed != doc.content_hash:
                hash_mismatches.append(
                    f"Hash mismatch on doc '{doc.document_id}': expected {doc.content_hash[:8]}.. got {computed[:8]}.."
                )
                all_docs_verified = False

    if chain.status == FactProvenanceStatus.CONFLICTED:
        notes.append("CONTRADICTION DETECTED: Independent sources disagree on this claim.")
    elif chain.status == FactProvenanceStatus.UNEVIDENCED:
        notes.append("MISSING EVIDENCE: Claim has zero supporting or contradicting evidence.")

    return ProvenanceValidationResult(
        fact_id=fact_id,
        tenant_id=tenant_id,
        status=chain.status,
        supporting_count=len(chain.supporting_evidence),
        contradicting_count=len(chain.contradicting_evidence),
        all_documents_verified=all_docs_verified,
        hash_mismatches=hash_mismatches,
        chain=chain,
        notes=notes,
    )


def audit_tenant_provenance(
    repo: BaseGraphRepository,
    tenant_id: str,
) -> Dict[str, Any]:
    """Produce an exhaustive provenance audit across all facts in a tenant.

    Identifies:
    - Total facts
    - Facts with strong support
    - Facts with contradictory records
    - Facts with zero evidence (candidates for agent abstention)
    """
    facts = repo.find_facts(tenant_id=tenant_id)
    supported: List[str] = []
    conflicted: List[str] = []
    contradicted: List[str] = []
    unevidenced: List[str] = []

    for f in facts:
        res = validate_evidence_chain(repo, f.fact_id, tenant_id)
        if res.status == FactProvenanceStatus.SUPPORTED:
            supported.append(f.fact_id)
        elif res.status == FactProvenanceStatus.CONFLICTED:
            conflicted.append(f.fact_id)
        elif res.status == FactProvenanceStatus.CONTRADICTED:
            contradicted.append(f.fact_id)
        elif res.status == FactProvenanceStatus.UNEVIDENCED:
            unevidenced.append(f.fact_id)

    return {
        "tenant_id": tenant_id,
        "total_facts": len(facts),
        "supported_facts": supported,
        "conflicted_facts": conflicted,
        "contradicted_facts": contradicted,
        "unevidenced_facts": unevidenced,
        "abstention_recommended_facts": conflicted + unevidenced,
    }


def format_provenance_trace(chain: ProvenanceChain) -> str:
    """Format an auditable, human-readable ASCII provenance trace."""
    lines: List[str] = []
    fact = chain.fact
    subj_name = chain.subject.canonical_name if chain.subject else fact.subject_id
    obj_name = chain.object.canonical_name if chain.object else fact.object_id

    lines.append("=" * 72)
    lines.append(f"CLAIM / FACT ID: {fact.fact_id}")
    lines.append(f"RELATION:        ({subj_name}) -[:{fact.relation_type}]-> ({obj_name})")
    lines.append(f"OBSERVED AT:     {fact.observed_at}")
    lines.append(f"STATUS:          {chain.status.value}")
    lines.append(f"SUMMARY:         {chain.summary}")
    lines.append("-" * 72)

    if chain.supporting_evidence:
        lines.append(f"SUPPORTING EVIDENCE ({len(chain.supporting_evidence)} records):")
        for idx, ev in enumerate(chain.supporting_evidence, 1):
            lines.append(f"  [{idx}] Evidence ID: {ev.evidence_id}")
            lines.append(f"      Extraction:  {ev.extraction_method} (Confidence: {ev.extraction_confidence:.2f})")
            lines.append(f"      Chunk Ref:   {ev.chunk_ref}")
            lines.append(f"      Excerpt:     \"{ev.content}\"")
            lines.append(f"      Source Doc:  {ev.document_title} (ID: {ev.document_id})")
            lines.append(f"      Source URI:  {ev.source_uri}")
            lines.append(f"      Hash:        {ev.content_hash[:16]}...")
    else:
        lines.append("SUPPORTING EVIDENCE: None")

    if chain.contradicting_evidence:
        lines.append("-" * 72)
        lines.append(f"CONTRADICTORY EVIDENCE ({len(chain.contradicting_evidence)} records):")
        for idx, ev in enumerate(chain.contradicting_evidence, 1):
            lines.append(f"  [{idx}] Evidence ID: {ev.evidence_id}")
            lines.append(f"      Extraction:  {ev.extraction_method} (Confidence: {ev.extraction_confidence:.2f})")
            lines.append(f"      Chunk Ref:   {ev.chunk_ref}")
            lines.append(f"      Excerpt:     \"{ev.content}\"")
            lines.append(f"      Source Doc:  {ev.document_title} (ID: {ev.document_id})")
            lines.append(f"      Source URI:  {ev.source_uri}")
            lines.append(f"      Hash:        {ev.content_hash[:16]}...")
    else:
        lines.append("CONTRADICTORY EVIDENCE: None")

    lines.append("=" * 72)
    return "\n".join(lines)
