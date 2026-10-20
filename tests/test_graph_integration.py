"""Integration tests executing against a live Neo4j database service.

These tests execute against a real Neo4j container/service if running.
If Neo4j is offline, tests are skipped with a clear, informative message explaining
the Docker Compose setup command.
"""
from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.provenance import validate_evidence_chain
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.graph.schemas import (
    Entity,
    FactProvenanceStatus,
    TraversalPath,
)

# Test connectivity at module load time
_cm = Neo4jConnectionManager()
NEO4J_AVAILABLE = _cm.ping()

skip_if_no_neo4j = pytest.mark.skipif(
    not NEO4J_AVAILABLE,
    reason=(
        "Live Neo4j instance not reachable at configured URI. "
        "Start Neo4j via 'docker compose -f infra/compose.yaml up -d' to execute live integration tests."
    ),
)


@skip_if_no_neo4j
class TestNeo4jLiveIntegration:
    """Live database integration tests against Neo4j."""

    @pytest.fixture(scope="class")
    @classmethod
    def live_repo(cls):
        cm = Neo4jConnectionManager()
        repo = Neo4jGraphRepository(cm)
        # Initialize schema constraints
        repo.init_schema_constraints()
        return repo

    def test_live_connection_and_constraints(self, live_repo: Neo4jGraphRepository):
        assert live_repo.conn.ping()

    def test_live_dataset_ingestion_and_idempotence(self, live_repo: Neo4jGraphRepository):
        pipeline = KnowledgeGraphIngestionPipeline(repository=live_repo)
        dataset = generate_supplier_delay_dataset()

        # Ingest once
        rep1 = pipeline.ingest_dataset(dataset)
        assert rep1.is_success
        assert rep1.entities_upserted == len(dataset.entities)

        # Ingest again (idempotent upsert verification)
        rep2 = pipeline.ingest_dataset(dataset)
        assert rep2.is_success
        assert len(rep2.errors) == 0

    def test_live_entity_retrieval(self, live_repo: Neo4jGraphRepository):
        entity = live_repo.get_entity("sup_a", "tenant_alpha")
        assert entity is not None
        assert entity.entity_id == "sup_a"
        assert entity.canonical_name == "Supplier A (Apex Microelectronics)"

    def test_live_tenant_isolation(self, live_repo: Neo4jGraphRepository):
        # Query tenant_beta entity from tenant_alpha scope - must return None
        cross_tenant_entity = live_repo.get_entity("sup_gamma", "tenant_alpha")
        assert cross_tenant_entity is None

        # Query within proper tenant_beta scope
        proper_entity = live_repo.get_entity("sup_gamma", "tenant_beta")
        assert proper_entity is not None

    def test_live_provenance_scenarios(self, live_repo: Neo4jGraphRepository):
        # Scenario A: Strong corroboration
        res_a = validate_evidence_chain(live_repo, "fact_sup_a_caused_delay", "tenant_alpha")
        assert res_a.status == FactProvenanceStatus.SUPPORTED
        assert res_a.supporting_count == 2
        assert res_a.contradicting_count == 0

        # Scenario B: Contradictory evidence
        res_b = validate_evidence_chain(live_repo, "fact_sup_b_delivered_ontime", "tenant_alpha")
        assert res_b.status == FactProvenanceStatus.CONFLICTED
        assert res_b.supporting_count == 1
        assert res_b.contradicting_count == 1

        # Scenario C: Unevidenced claim
        res_c = validate_evidence_chain(live_repo, "fact_comp_a_qa_certified", "tenant_alpha")
        assert res_c.status == FactProvenanceStatus.UNEVIDENCED

    def test_live_multi_hop_traversal(self, live_repo: Neo4jGraphRepository):
        paths = live_repo.get_multi_hop_relationships("sup_a", "tenant_alpha", max_hops=2)
        assert len(paths) == 6
        for p in paths:
            assert isinstance(p, TraversalPath)
            # Test subscript access
            assert isinstance(p["path"], list)
            assert isinstance(p["hops"], int)
            # Test attribute access
            assert isinstance(p.path, list)
            assert isinstance(p.hops, int)
            for node in p["path"]:
                assert "id" in node
                assert "type" in node
                assert "name" in node
                assert "labels" in node

    def test_multi_hop_backend_shape_parity(self, live_repo: Neo4jGraphRepository):
        """Regression test validating identical path results from live Neo4j and InMemory repositories."""
        in_memory_repo = InMemoryGraphRepository()
        dataset = generate_supplier_delay_dataset()
        KnowledgeGraphIngestionPipeline(in_memory_repo).ingest_dataset(dataset)

        neo_paths = live_repo.get_multi_hop_relationships("sup_a", "tenant_alpha", max_hops=2)
        mem_paths = in_memory_repo.get_multi_hop_relationships("sup_a", "tenant_alpha", max_hops=2)

        assert len(neo_paths) == len(mem_paths) == 6

        for n_path, m_path in zip(neo_paths, mem_paths):
            assert isinstance(n_path, TraversalPath)
            assert isinstance(m_path, TraversalPath)
            assert n_path.hops == m_path.hops
            assert n_path["hops"] == m_path["hops"]
            assert len(n_path.path) == len(m_path.path)
            assert len(n_path["path"]) == len(m_path["path"])

            # Verify identical node IDs, types, names, and labels
            for n_node, m_node in zip(n_path.path, m_path.path):
                assert n_node["id"] == m_node["id"]
                assert n_node["type"] == m_node["type"]
                assert n_node["name"] == m_node["name"]
                assert set(n_node["labels"]) == set(m_node["labels"])
