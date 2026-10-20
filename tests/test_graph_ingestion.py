"""Unit tests for Knowledge Graph Ingestion Pipeline."""
from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import (
    SupplierDelayDataset,
    generate_supplier_delay_dataset,
)
from sentinel_pomdp.graph.ingestion import (
    KnowledgeGraphIngestionPipeline,
)
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.graph.schemas import (
    Document,
    Entity,
    Evidence,
    EvidenceLink,
    EvidenceType,
    RelationFact,
)


def test_clean_dataset_ingestion():
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repository=repo)
    dataset = generate_supplier_delay_dataset()

    report = pipeline.ingest_dataset(dataset)
    assert report.is_success
    assert report.entities_upserted == len(dataset.entities)
    assert report.documents_upserted == len(dataset.documents)
    assert report.facts_upserted == len(dataset.facts)
    assert report.evidence_upserted == len(dataset.evidence)
    assert report.links_created == len(dataset.links)
    assert len(report.errors) == 0


def test_idempotent_repeated_ingestion():
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repository=repo)
    dataset = generate_supplier_delay_dataset()

    # First run
    rep1 = pipeline.ingest_dataset(dataset)
    assert rep1.is_success

    # Second run with exact same dataset
    rep2 = pipeline.ingest_dataset(dataset)
    assert rep2.is_success
    assert rep2.errors == []

    # Verify counts in repository didn't duplicate
    entities = repo.list_entities("tenant_alpha")
    assert len(entities) == 10  # 10 unique entities for tenant_alpha


def test_ingestion_rejects_unsupported_entity_type():
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repository=repo, enforce_type_allowlists=True)

    invalid_entity = Entity(
        entity_id="bad_001",
        tenant_id="tenant_alpha",
        entity_type="magical_unicorns",  # Not in allowlist
        canonical_name="Invalid Entity",
    )
    dataset = SupplierDelayDataset(entities=[invalid_entity])

    report = pipeline.ingest_dataset(dataset)
    assert not report.is_success
    assert any("Unsupported entity_type 'magical_unicorns'" in err for err in report.errors)


def test_ingestion_rejects_unsupported_relation_type():
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repository=repo, enforce_type_allowlists=True)

    e1 = Entity(entity_id="e1", tenant_id="t1", entity_type="supplier", canonical_name="E1")
    e2 = Entity(entity_id="e2", tenant_id="t1", entity_type="component", canonical_name="E2")
    bad_fact = RelationFact(
        fact_id="f1",
        tenant_id="t1",
        relation_type="TELEPORTS_TO",  # Not in allowlist
        subject_id="e1",
        object_id="e2",
    )
    dataset = SupplierDelayDataset(entities=[e1, e2], facts=[bad_fact])

    report = pipeline.ingest_dataset(dataset)
    assert not report.is_success
    assert any("Unsupported relation_type 'TELEPORTS_TO'" in err for err in report.errors)


def test_ingestion_rejects_missing_foreign_key_subject():
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repository=repo)

    e2 = Entity(entity_id="e2", tenant_id="t1", entity_type="component", canonical_name="E2")
    orphan_fact = RelationFact(
        fact_id="f1",
        tenant_id="t1",
        relation_type="SUPPLIES",
        subject_id="missing_e1",
        object_id="e2",
    )
    dataset = SupplierDelayDataset(entities=[e2], facts=[orphan_fact])

    report = pipeline.ingest_dataset(dataset)
    assert not report.is_success
    assert any("references unknown subject entity 'missing_e1'" in err for err in report.errors)


def test_ingestion_rejects_missing_evidence_source_document():
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repository=repo)

    ev = Evidence(
        evidence_id="ev_orphan",
        tenant_id="t1",
        document_id="doc_missing_999",
        chunk_ref="sec_1",
        content="Some unreferenced statement",
    )
    dataset = SupplierDelayDataset(evidence=[ev])

    report = pipeline.ingest_dataset(dataset)
    assert not report.is_success
    assert any("references unknown document 'doc_missing_999'" in err for err in report.errors)
