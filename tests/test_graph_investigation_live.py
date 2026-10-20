from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.investigation.schemas import GraphInvestigationRequest, InvestigationAction
from sentinel_pomdp.investigation import build_scenario_planner, run_graph_investigation, supplier_shipment_delay_scenario
from sentinel_pomdp.investigation.observations import adapt_result
from sentinel_pomdp.investigation.tools import GraphInvestigationTools


_manager = Neo4jConnectionManager()
pytestmark = pytest.mark.skipif(not _manager.ping(), reason="live Neo4j is unavailable")


def test_live_and_memory_tool_contract_equivalence():
    live = Neo4jGraphRepository(_manager)
    memory = InMemoryGraphRepository()
    data = generate_supplier_delay_dataset()
    assert KnowledgeGraphIngestionPipeline(live).ingest_dataset(data).is_success
    assert KnowledgeGraphIngestionPipeline(memory).ingest_dataset(data).is_success
    request = GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id="fact_sup_a_caused_delay")
    actual = GraphInvestigationTools(live).execute(request, authorized_tenant_id="tenant_alpha")
    expected = GraphInvestigationTools(memory).execute(request, authorized_tenant_id="tenant_alpha")
    assert actual.status == expected.status
    assert [f.fact_id for f in actual.facts] == [f.fact_id for f in expected.facts]
    assert actual.evidence_ids == expected.evidence_ids
    assert actual.document_ids == expected.document_ids
    assert actual.provenance_verified == expected.provenance_verified
    live_observation = adapt_result("inspect", actual, seen_evidence_ids=set(), seen_document_ids=set())
    memory_observation = adapt_result("inspect", expected, seen_evidence_ids=set(), seen_document_ids=set())
    assert live_observation.model_dump(exclude={"action_name"}) == memory_observation.model_dump(exclude={"action_name"})


def test_live_graph_result_drives_bayes_and_answer_gate():
    live = Neo4jGraphRepository(_manager)
    assert KnowledgeGraphIngestionPipeline(live).ingest_dataset(generate_supplier_delay_dataset()).is_success
    scenario = supplier_shipment_delay_scenario()
    outcome = run_graph_investigation(live, scenario, build_scenario_planner(scenario, horizon=2),
                                      "tenant_alpha")
    assert outcome.steps[0].belief_after["shipment_delayed"] > scenario.prior["shipment_delayed"]
    assert outcome.decision == "ANSWER"
    assert outcome.evidence_verdict.sufficient
