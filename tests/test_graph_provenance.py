"""Unit tests for Evidence Provenance Validation and Auditing."""
from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.provenance import (
    audit_tenant_provenance,
    format_provenance_trace,
    validate_evidence_chain,
)
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.graph.schemas import (
    Document,
    FactProvenanceStatus,
)


@pytest.fixture
def populated_repository() -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repo)
    dataset = generate_supplier_delay_dataset()
    report = pipeline.ingest_dataset(dataset)
    assert report.is_success
    return repo


def test_provenance_scenario_a_strong_support(populated_repository: InMemoryGraphRepository):
    # Supplier A delayed Component A - supported by warehouse log and telematics
    res = validate_evidence_chain(populated_repository, "fact_sup_a_caused_delay", "tenant_alpha")
    assert res.status == FactProvenanceStatus.SUPPORTED
    assert res.supporting_count == 2
    assert res.contradicting_count == 0
    assert res.all_documents_verified
    assert res.is_reliable
    assert len(res.hash_mismatches) == 0

    trace = format_provenance_trace(res.chain)
    assert "SUPPORTED" in trace
    assert "ev_wh_log_apx101_late" in trace
    assert "ev_telematics_truck_customs" in trace


def test_provenance_scenario_b_conflicting_evidence(populated_repository: InMemoryGraphRepository):
    # Supplier B on-time claim - contradicted by receiving inspection log
    res = validate_evidence_chain(populated_repository, "fact_sup_b_delivered_ontime", "tenant_alpha")
    assert res.status == FactProvenanceStatus.CONFLICTED
    assert res.supporting_count == 1
    assert res.contradicting_count == 1
    assert not res.is_reliable

    trace = format_provenance_trace(res.chain)
    assert "CONFLICTED" in trace
    assert "ev_sup_b_claimed_ontime" in trace
    assert "ev_dock_b_late_damaged" in trace


def test_provenance_scenario_c_unevidenced_claim(populated_repository: InMemoryGraphRepository):
    # Component A QA certification - zero evidence attached
    res = validate_evidence_chain(populated_repository, "fact_comp_a_qa_certified", "tenant_alpha")
    assert res.status == FactProvenanceStatus.UNEVIDENCED
    assert res.supporting_count == 0
    assert res.contradicting_count == 0
    assert not res.is_reliable

    trace = format_provenance_trace(res.chain)
    assert "UNEVIDENCED" in trace
    assert "Missing evidence" in trace


def test_provenance_hash_integrity_detection(populated_repository: InMemoryGraphRepository):
    # Tamper with the raw content of a document after ingestion to verify hash mismatch detection
    tampered_doc = Document(
        document_id="doc_wh_log_001",
        tenant_id="tenant_alpha",
        title="Tampered Warehouse Log",
        source_uri="synthetic://warehouse/logs/wh01_2026_04.pdf",
        source_type="receiving_log",
        raw_content="MALICIOUS ALTERATION: Everything arrived on time!",
        content_hash="6e65e071a36a33cf1234567890abcdef1234567890abcdef1234567890abcdef",  # Old hash
    )
    populated_repository.upsert_document(tampered_doc)

    res = validate_evidence_chain(populated_repository, "fact_sup_a_caused_delay", "tenant_alpha")
    assert not res.all_documents_verified
    assert len(res.hash_mismatches) > 0
    assert not res.is_reliable


def test_tenant_provenance_audit_summary(populated_repository: InMemoryGraphRepository):
    audit = audit_tenant_provenance(populated_repository, "tenant_alpha")
    assert audit["tenant_id"] == "tenant_alpha"
    assert audit["total_facts"] == 12
    assert "fact_sup_a_caused_delay" in audit["supported_facts"]
    assert "fact_sup_b_delivered_ontime" in audit["conflicted_facts"]
    assert "fact_comp_a_qa_certified" in audit["unevidenced_facts"]
    assert len(audit["abstention_recommended_facts"]) >= 2
