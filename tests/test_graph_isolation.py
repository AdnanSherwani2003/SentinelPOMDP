"""Unit tests for Knowledge Graph Multi-Tenant Isolation Boundaries."""
from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository


@pytest.fixture
def multi_tenant_repository() -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    pipeline = KnowledgeGraphIngestionPipeline(repo)
    dataset = generate_supplier_delay_dataset(
        primary_tenant="tenant_alpha",
        secondary_tenant="tenant_beta",
    )
    report = pipeline.ingest_dataset(dataset)
    assert report.is_success
    return repo


def test_entity_tenant_isolation(multi_tenant_repository: InMemoryGraphRepository):
    # Primary tenant entity exists in primary tenant
    sup_a = multi_tenant_repository.get_entity("sup_a", "tenant_alpha")
    assert sup_a is not None
    assert sup_a.canonical_name.startswith("Supplier A")

    # Primary tenant cannot see secondary tenant entity
    leaked_sup = multi_tenant_repository.get_entity("sup_gamma", "tenant_alpha")
    assert leaked_sup is None

    # Secondary tenant can see its own entity
    sup_gamma = multi_tenant_repository.get_entity("sup_gamma", "tenant_beta")
    assert sup_gamma is not None
    assert sup_gamma.canonical_name.startswith("Supplier Gamma")


def test_document_tenant_isolation(multi_tenant_repository: InMemoryGraphRepository):
    # Primary tenant document exists in primary tenant
    doc_a = multi_tenant_repository.get_document("doc_wh_log_001", "tenant_alpha")
    assert doc_a is not None

    # Secondary tenant document cannot be read by primary tenant
    leaked_doc = multi_tenant_repository.get_document("doc_beta_cert_001", "tenant_alpha")
    assert leaked_doc is None

    # Secondary tenant can read its own document
    doc_b = multi_tenant_repository.get_document("doc_beta_cert_001", "tenant_beta")
    assert doc_b is not None


def test_relation_fact_tenant_isolation(multi_tenant_repository: InMemoryGraphRepository):
    # Primary tenant facts
    facts_a = multi_tenant_repository.find_facts("tenant_alpha")
    assert len(facts_a) == 12
    for f in facts_a:
        assert f.tenant_id == "tenant_alpha"

    # Secondary tenant facts
    facts_b = multi_tenant_repository.find_facts("tenant_beta")
    assert len(facts_b) == 1
    assert facts_b[0].fact_id == "fact_beta_sup_gamma_supplies_comp_z"

    # Primary tenant cannot retrieve secondary tenant fact by ID
    leaked_fact = multi_tenant_repository.get_relation_fact(
        "fact_beta_sup_gamma_supplies_comp_z", "tenant_alpha"
    )
    assert leaked_fact is None


def test_multi_hop_traversal_tenant_boundary(multi_tenant_repository: InMemoryGraphRepository):
    # Multi-hop paths in tenant_alpha should never traverse nodes from tenant_beta
    paths = multi_tenant_repository.get_multi_hop_relationships("sup_a", "tenant_alpha", max_hops=2)
    assert len(paths) > 0
    for p in paths:
        for node in p["path"]:
            # Check that none of the nodes belong to tenant_beta
            assert node["id"] not in {"sup_gamma", "comp_z", "prod_y", "fact_beta_sup_gamma_supplies_comp_z"}
