"""Opt-in domain acceptance against the explicitly disposable I19 Neo4j."""
import os
from uuid import uuid4

import pytest

from sentinel_pomdp.domains import (
    DomainInvestigationService, DomainPackService, ProcurementAdapter,
    procurement_demo_pack, seed_synthetic_procurement,
)
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.repository import Neo4jGraphRepository
from sentinel_pomdp.ingestion.storage import LocalDocumentStore


@pytest.mark.skipif(os.getenv("SENTINEL_I19_DISPOSABLE_NEO4J") != "1",
                    reason="requires explicitly disposable I19 Neo4j")
def test_live_procurement_provenance_and_withdrawal(tmp_path):
    assert os.environ.get("NEO4J_URI") == "bolt://127.0.0.1:17687"
    tenant = "i19-live-" + uuid4().hex
    manager = Neo4jConnectionManager()
    try:
        graph = Neo4jGraphRepository(manager)
        graph.init_schema_constraints()
        packs = DomainPackService(LocalDocumentStore(tmp_path), graph)
        pack = procurement_demo_pack(tenant)
        packs.save(tenant, packs.validate(tenant, pack))
        packs.submit_for_review(tenant, pack.domain_id, pack.model_version)
        packs.approve(tenant, pack.domain_id, pack.model_version, "i19-test-reviewer")
        packs.activate(tenant, pack.domain_id, pack.model_version)
        seed_synthetic_procurement(graph, tenant)
        seed_synthetic_procurement(graph, tenant)
        runtime = DomainInvestigationService(packs, [ProcurementAdapter(graph)])
        result = runtime.investigate(tenant, pack.domain_id, "Check INV-1001",
                                     version=pack.model_version)
        assert result.classification == "MATCH_SUPPORTED"
        assert len(result.fact_ids) == len(result.evidence_ids) == 2
        assert result.provenance_verified
        with pytest.raises(KeyError):
            runtime.investigate("other-tenant", pack.domain_id, "Check INV-1001")
        graph.deactivate_document("doc-PO-2001", tenant)
        result = runtime.investigate(tenant, pack.domain_id, "Check INV-1001")
        assert (result.decision, result.classification) == ("ABSTAIN", "INSUFFICIENT_EVIDENCE")
    finally:
        manager.close()
