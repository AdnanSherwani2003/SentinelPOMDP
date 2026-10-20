"""Unit tests for Knowledge Graph Pydantic schemas."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel_pomdp.graph.schemas import (
    Document,
    Entity,
    Evidence,
    EvidenceType,
    FactProvenanceStatus,
    ProvenanceChain,
    ProvenanceRecord,
    RelationFact,
    compute_content_hash,
)


def test_entity_creation_valid():
    entity = Entity(
        entity_id="sup_a",
        tenant_id="tenant_alpha",
        entity_type="supplier",
        canonical_name="Supplier A",
        attributes={"country": "DE", "tier": 1},
    )
    assert entity.entity_id == "sup_a"
    assert entity.tenant_id == "tenant_alpha"
    assert entity.attributes["tier"] == 1
    assert entity.created_at is not None


def test_entity_empty_field_raises():
    with pytest.raises(ValidationError):
        Entity(
            entity_id="   ",
            tenant_id="tenant_alpha",
            entity_type="supplier",
            canonical_name="Supplier A",
        )


def test_document_content_hash_auto_generation():
    doc = Document(
        document_id="doc_001",
        tenant_id="tenant_alpha",
        title="Receiving Log 2026-04",
        source_uri="synthetic://warehouse/log_001",
        source_type="receiving_log",
        raw_content="Component shipment received 5 days late with dented crates.",
    )
    expected_hash = compute_content_hash("Component shipment received 5 days late with dented crates.")
    assert doc.content_hash == expected_hash
    assert len(doc.content_hash) == 64


def test_evidence_extraction_confidence_bounds():
    # Valid confidence
    ev = Evidence(
        evidence_id="ev_001",
        tenant_id="tenant_alpha",
        document_id="doc_001",
        chunk_ref="section_1",
        content="Delivery arrived on 2026-04-15",
        extraction_confidence=0.95,
    )
    assert ev.extraction_confidence == 0.95

    # Out of bounds (> 1.0)
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev_002",
            tenant_id="tenant_alpha",
            document_id="doc_001",
            chunk_ref="section_1",
            content="Invalid",
            extraction_confidence=1.5,
        )

    # Out of bounds (< 0.0)
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev_003",
            tenant_id="tenant_alpha",
            document_id="doc_001",
            chunk_ref="section_1",
            content="Invalid",
            extraction_confidence=-0.1,
        )


def test_relation_fact_valid():
    fact = RelationFact(
        fact_id="fact_001",
        tenant_id="tenant_alpha",
        relation_type="SUPPLIES",
        subject_id="sup_a",
        object_id="comp_a",
        attributes={"contract_year": 2026},
    )
    assert fact.fact_id == "fact_001"
    assert fact.relation_type == "SUPPLIES"
    assert fact.subject_id == "sup_a"
    assert fact.object_id == "comp_a"


def test_provenance_chain_status_determination():
    fact = RelationFact(
        fact_id="fact_delay",
        tenant_id="tenant_alpha",
        relation_type="EXPERIENCED_DELAY",
        subject_id="ship_a",
        object_id="incident_001",
    )
    record_sup = ProvenanceRecord(
        evidence_id="ev_1",
        chunk_ref="sec_1",
        content="Arrived 5 days late",
        extraction_method="parser",
        extraction_confidence=0.99,
        observed_at="2026-04-15T00:00:00Z",
        document_id="doc_1",
        document_title="Warehouse Log",
        source_uri="synthetic://log1",
        source_type="log",
        classification="internal",
        content_hash="abc",
    )
    record_con = ProvenanceRecord(
        evidence_id="ev_2",
        chunk_ref="sec_2",
        content="Carrier claims on-time delivery",
        extraction_method="parser",
        extraction_confidence=0.90,
        observed_at="2026-04-15T00:00:00Z",
        document_id="doc_2",
        document_title="Carrier Invoice",
        source_uri="synthetic://inv2",
        source_type="invoice",
        classification="internal",
        content_hash="def",
    )

    # Unevidenced
    chain_empty = ProvenanceChain(fact=fact)
    assert chain_empty.status == FactProvenanceStatus.UNEVIDENCED

    # Supported
    chain_sup = ProvenanceChain(fact=fact, supporting_evidence=[record_sup])
    assert chain_sup.status == FactProvenanceStatus.SUPPORTED

    # Contradicted
    chain_con = ProvenanceChain(fact=fact, contradicting_evidence=[record_con])
    assert chain_con.status == FactProvenanceStatus.CONTRADICTED

    # Conflicted
    chain_conf = ProvenanceChain(
        fact=fact,
        supporting_evidence=[record_sup],
        contradicting_evidence=[record_con],
    )
    assert chain_conf.status == FactProvenanceStatus.CONFLICTED
    assert "Conflicting evidence" in chain_conf.summary


def test_traversal_path_schema():
    from sentinel_pomdp.graph.schemas import TraversalPath

    nodes = [
        {"id": "e1", "type": "supplier", "name": "Supplier A", "labels": ["Entity"]},
        {"id": "f1", "type": "SUPPLIES", "name": "SUPPLIES", "labels": ["RelationFact"]},
        {"id": "e2", "type": "component", "name": "Component A", "labels": ["Entity"]},
    ]
    tp = TraversalPath(path=nodes, hops=1)

    # Subscript access
    assert tp["path"] == nodes
    assert tp["hops"] == 1
    assert "path" in tp
    assert "hops" in tp

    # Attribute access
    assert tp.path == nodes
    assert tp.hops == 1

    # Dictionary conversion
    d = tp.to_dict()
    assert d == {"path": nodes, "hops": 1}

    # Invalid subscript
    with pytest.raises(KeyError):
        _ = tp["invalid_key"]
