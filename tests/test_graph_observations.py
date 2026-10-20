from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.graph.schemas import Document
from sentinel_pomdp.investigation.observations import UnsafeToolResult, adapt_result
from sentinel_pomdp.investigation.schemas import (
    GraphInvestigationRequest, GraphInvestigationResult, InvestigationAction,
    ObservationToken, ToolStatus,
)
from sentinel_pomdp.investigation.tools import GraphInvestigationTools


@pytest.fixture()
def setup():
    repo = InMemoryGraphRepository()
    KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
    return repo, GraphInvestigationTools(repo)


def execute(setup, fact):
    repo, tools = setup
    return tools.execute(GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id=fact), authorized_tenant_id="tenant_alpha")


@pytest.mark.parametrize(("fact", "token"), [
    ("fact_sup_a_caused_delay", ObservationToken.SUPPORTED),
    ("fact_sup_b_delivered_ontime", ObservationToken.CONFLICTED),
    ("fact_comp_a_qa_certified", ObservationToken.NOT_FOUND),
    ("missing", ObservationToken.NOT_FOUND),
])
def test_registered_evidence_mapping(setup, fact, token):
    observation = adapt_result("inspect", execute(setup, fact),
                               seen_evidence_ids=set(), seen_document_ids=set())
    assert observation.observation_token == token


def test_duplicate_document_is_not_counted_as_independent_confirmation(setup):
    first = adapt_result("one", execute(setup, "fact_sup_a_caused_delay"),
                         seen_evidence_ids=set(), seen_document_ids=set())
    second = adapt_result("two", execute(setup, "fact_incident_attributed_sup_a"),
                          seen_evidence_ids=set(first.source_evidence_ids),
                          seen_document_ids=set(first.source_document_ids))
    assert second.observation_token == ObservationToken.DUPLICATE
    assert second.is_duplicate


def test_hash_mismatch_is_explicit(setup):
    repo, _ = setup
    old = repo.get_document("doc_wh_log_001", "tenant_alpha")
    repo.upsert_document(Document(**{**old.model_dump(), "raw_content": "tampered"}))
    observation = adapt_result("inspect", execute(setup, "fact_sup_a_caused_delay"),
                               seen_evidence_ids=set(), seen_document_ids=set())
    assert observation.observation_token == ObservationToken.HASH_MISMATCH


def test_operational_error_never_reaches_bayes():
    result = GraphInvestigationResult(
        action_name=InvestigationAction.FACT_EVIDENCE, target_id="x",
        status=ToolStatus.DATABASE_UNAVAILABLE, cost=.1, error="timeout")
    with pytest.raises(UnsafeToolResult, match="timeout"):
        adapt_result("inspect", result, seen_evidence_ids=set(), seen_document_ids=set())
