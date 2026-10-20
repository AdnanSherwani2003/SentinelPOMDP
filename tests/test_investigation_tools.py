from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.investigation.schemas import (
    GraphInvestigationRequest, InvestigationAction, ToolStatus,
)
from sentinel_pomdp.investigation.tools import GraphInvestigationTools


@pytest.fixture()
def repository():
    repo = InMemoryGraphRepository()
    assert KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset()).is_success
    return repo


def test_fact_tool_returns_typed_provenance(repository):
    request = GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id="fact_sup_a_caused_delay")
    result = GraphInvestigationTools(repository).execute(request, authorized_tenant_id="tenant_alpha")
    assert result.status == ToolStatus.EVIDENCE_FOUND
    assert result.evidence_ids == ["ev_telematics_truck_customs", "ev_wh_log_apx101_late"]
    assert result.document_ids == ["doc_telematics_002", "doc_wh_log_001"]
    assert result.provenance_verified


def test_conflict_missing_tenant_and_authorization_are_distinct(repository):
    tools = GraphInvestigationTools(repository)
    conflict = tools.execute(GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id="fact_sup_b_delivered_ontime"), authorized_tenant_id="tenant_alpha")
    missing = tools.execute(GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id="not_here"), authorized_tenant_id="tenant_alpha")
    denied = tools.execute(GraphInvestigationRequest(
        tenant_id="tenant_beta", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id="fact_beta_sup_gamma_supplies_comp_z"), authorized_tenant_id="tenant_alpha")
    assert conflict.status == ToolStatus.CONFLICTING_EVIDENCE
    assert missing.status == ToolStatus.MISSING_RECORD
    assert denied.status == ToolStatus.UNAUTHORIZED
    assert denied.facts == []


def test_relationship_tool_bounds_and_filters_paths(repository):
    result = GraphInvestigationTools(repository).execute(GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.ENTITY_RELATIONSHIPS,
        target_id="sup_a", allowed_relation_types=("SUPPLIES",), max_depth=2, max_results=1,
    ), authorized_tenant_id="tenant_alpha")
    assert result.status == ToolStatus.EVIDENCE_FOUND
    assert len(result.paths) == 1
    assert result.paths[0].hops == 1


def test_invalid_identifiers_and_relation_types_fail_closed(repository):
    with pytest.raises(ValidationError):
        GraphInvestigationRequest(tenant_id="tenant alpha", action_name="investigate_fact_evidence",
                                  target_id="fact")
    result = GraphInvestigationTools(repository).execute(GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.ENTITY_RELATIONSHIPS,
        target_id="sup_a", allowed_relation_types=("DROP_ALL",)),
        authorized_tenant_id="tenant_alpha")
    assert result.status == ToolStatus.INVALID_REQUEST


def test_repository_exception_is_operational_failure_not_negative_evidence(repository, monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("database timed out")
    monkeypatch.setattr(repository, "get_provenance_chain", fail)
    result = GraphInvestigationTools(repository).execute(GraphInvestigationRequest(
        tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
        target_id="fact_sup_a_caused_delay"), authorized_tenant_id="tenant_alpha")
    assert result.status == ToolStatus.DATABASE_UNAVAILABLE
    assert not result.facts
