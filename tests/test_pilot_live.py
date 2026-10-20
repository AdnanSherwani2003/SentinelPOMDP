from __future__ import annotations

from uuid import uuid4

import pytest

from sentinel_pomdp.calibration import build_candidate_domain_pack, estimate_categorical_model, evaluate_predictions
from sentinel_pomdp.domains import DomainPackService
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.repository import Neo4jGraphRepository
from sentinel_pomdp.ingestion import DatasetConfiguration, EnterpriseDataService, LocalDocumentStore, ReviewAction
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService
from sentinel_pomdp.pilot import PilotSplit, chronological_group_split
from sentinel_pomdp.pilot.fixtures import representative_shipment_fixture
from sentinel_pomdp.pilot.replay import ReplayPolicy, replay_logged_policy


_manager = Neo4jConnectionManager()
pytestmark = [pytest.mark.live_pilot,
              pytest.mark.skipif(not _manager.ping(), reason="live Neo4j is unavailable")]


def test_live_calibrated_pack_drives_tenant_scoped_graph_investigation(tmp_path):
    tenant = f"pilot-live-{uuid4().hex}"
    repository = Neo4jGraphRepository(_manager)
    store = LocalDocumentStore(tmp_path / "pilot-live")
    dataset = representative_shipment_fixture(60)
    manifest = chronological_group_split(dataset)
    estimate = estimate_categorical_model(dataset, manifest)
    labels = {case.case_id: case.ground_truth_label for case in dataset.cases
              if manifest.assignments[case.case_id] == PilotSplit.TEST}
    metrics = evaluate_predictions(
        replay_logged_policy(dataset, manifest, estimate, ReplayPolicy("logged", True, .8)), labels)
    candidate = build_candidate_domain_pack(
        estimate=estimate, domain_id="shipment-timeliness", name="Live shipment pilot",
        claim_type="shipment_timeliness", model_version="live-cal-v1",
        relation_hypotheses={"EXPERIENCED_DELAY": "delayed"},
        action_costs={"inspect_delivery": .08}, answer_threshold=.8,
        minimum_independent_sources=2, holdout_metrics=metrics)
    packs = DomainPackService(store, repository)
    packs.save(tenant, candidate)
    packs.approve(tenant, candidate.domain_id, candidate.model_version, "live-reviewer")

    ingestion = EnterpriseDataService(store, repository)
    ingestion.configure_dataset(tenant, DatasetConfiguration(
        dataset_id=dataset.dataset_id, name="Pilot deliveries",
        field_mapping={"purchase_order": "po", "expected_date": "expected",
                       "actual_date": "actual"}))
    ingestion.upload(tenant, dataset_id=dataset.dataset_id, filename="expected.csv",
                     content=b"po,expected,actual\nPO-PILOT-LIVE,2026-01-01,\n",
                     source_group="erp")
    ingestion.upload(tenant, dataset_id=dataset.dataset_id, filename="actual.csv",
                     content=b"po,expected,actual\nPO-PILOT-LIVE,,2026-01-05\n",
                     source_group="warehouse")
    fact = store.list_candidates(tenant)[0]
    ingestion.review(tenant, fact.candidate_id, ReviewAction.APPROVE, "live-reviewer")
    scenario = packs.build_scenario(
        tenant, candidate.domain_id, "Was PO-PILOT-LIVE delivered late?")
    response = InvestigationIntelligenceService(
        repository, DeterministicFakeLLM()).investigate_scenario(
            "Was PO-PILOT-LIVE delivered late?", tenant, scenario)
    assert response.decision == "ANSWER"
    assert response.investigation["metadata"]["domain_model_version"] == "live-cal-v1"
    assert repository.get_provenance_chain(fact.graph_fact_id, "other-tenant") is None
