from __future__ import annotations

from uuid import uuid4

import pytest

from sentinel_pomdp.domains import DomainAction, DomainPack, DomainPackService, DomainPackStatus
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.repository import Neo4jGraphRepository
from sentinel_pomdp.ingestion import DatasetConfiguration, EnterpriseDataService, LocalDocumentStore, ReviewAction
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService


_manager = Neo4jConnectionManager()
pytestmark = [
    pytest.mark.live_company_data,
    pytest.mark.skipif(not _manager.ping(), reason="live Neo4j is unavailable"),
]


def test_live_neo4j_company_document_to_authoritative_decision(tmp_path):
    tenant = f"company-live-{uuid4().hex}"
    repository = Neo4jGraphRepository(_manager)
    store = LocalDocumentStore(tmp_path / "live-company")
    ingestion = EnterpriseDataService(store, repository)
    ingestion.configure_dataset(tenant, DatasetConfiguration(
        dataset_id="delivery", name="Delivery",
        field_mapping={"purchase_order": "po", "expected_date": "expected",
                       "actual_date": "actual"}))
    ingestion.upload(tenant, dataset_id="delivery", filename="expected.csv",
                     content=b"po,expected,actual\nPO-LIVE-14,2026-10-01,\n")
    ingestion.upload(tenant, dataset_id="delivery", filename="actual.csv",
                     content=b"po,expected,actual\nPO-LIVE-14,,2026-10-05\n")
    candidate = store.list_candidates(tenant)[0]
    ingestion.review(tenant, candidate.candidate_id, ReviewAction.APPROVE, "live-reviewer")

    supported = {
        "EVIDENCE_SUPPORTED": .90, "EVIDENCE_CONFLICTED": .02,
        "EVIDENCE_CONTRADICTED": .02, "EVIDENCE_NOT_FOUND": .04,
        "DUPLICATE_INFORMATION": .01, "SOURCE_HASH_MISMATCH": .01}
    alternate = {
        "EVIDENCE_SUPPORTED": .10, "EVIDENCE_CONFLICTED": .05,
        "EVIDENCE_CONTRADICTED": .60, "EVIDENCE_NOT_FOUND": .23,
        "DUPLICATE_INFORMATION": .01, "SOURCE_HASH_MISMATCH": .01}
    packs = DomainPackService(store, repository)
    packs.save(tenant, DomainPack(
        domain_id="delivery", name="Delivery delay", claim_type="shipment_timeliness",
        hypotheses=["delayed", "on_time"], prior={"delayed": .55, "on_time": .45},
        actions=[DomainAction(action_id="inspect", cost=.08,
                              relation_hypotheses={"EXPERIENCED_DELAY": "delayed"})],
        observation_model={"inspect": {"delayed": supported, "on_time": alternate}},
        answer_threshold=.7, minimum_independent_sources=2,
        status=DomainPackStatus.APPROVED, model_version="live-review-v1",
        calibration_note="Live integration fixture only.", approved_by="live-reviewer"))
    scenario = packs.build_scenario(tenant, "delivery", "Was PO-LIVE-14 delayed?")
    result = InvestigationIntelligenceService(
        repository, DeterministicFakeLLM()).investigate_scenario(
            "Was PO-LIVE-14 delayed?", tenant, scenario)
    assert result.decision == "ANSWER"
    assert result.selected_hypothesis == "delayed"
    assert len(result.document_ids) == 2
    assert repository.get_provenance_chain(candidate.graph_fact_id, "another-tenant") is None
