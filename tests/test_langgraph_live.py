from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.investigation import build_scenario_planner, supplier_shipment_delay_scenario
from sentinel_pomdp.orchestration import run_langgraph_investigation


manager = Neo4jConnectionManager()
pytestmark = pytest.mark.skipif(not manager.ping(), reason="live Neo4j is unavailable")


def test_live_and_memory_langgraph_logical_equivalence():
    live = Neo4jGraphRepository(manager)
    memory = InMemoryGraphRepository()
    dataset = generate_supplier_delay_dataset()
    assert KnowledgeGraphIngestionPipeline(live).ingest_dataset(dataset).is_success
    assert KnowledgeGraphIngestionPipeline(memory).ingest_dataset(dataset).is_success
    scenario = supplier_shipment_delay_scenario()
    live_outcome = run_langgraph_investigation(
        live, scenario, build_scenario_planner(scenario), "tenant_alpha")
    memory_outcome = run_langgraph_investigation(
        memory, scenario, build_scenario_planner(scenario), "tenant_alpha")
    assert live_outcome.decision == memory_outcome.decision == "ANSWER"
    assert live_outcome.final_belief == pytest.approx(memory_outcome.final_belief)
    assert live_outcome.evidence_verdict.evidence_ids == memory_outcome.evidence_verdict.evidence_ids
    assert live_outcome.evidence_verdict.document_ids == memory_outcome.evidence_verdict.document_ids
    assert live_outcome.total_cost == memory_outcome.total_cost


def test_optional_temporal_properties_remain_none_live():
    live = Neo4jGraphRepository(manager)
    assert KnowledgeGraphIngestionPipeline(live).ingest_dataset(generate_supplier_delay_dataset()).is_success
    fact = live.get_relation_fact("fact_sup_a_caused_delay", "tenant_alpha")
    assert fact is not None
    assert fact.valid_from is None
    assert fact.valid_to is None
