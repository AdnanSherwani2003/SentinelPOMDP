"""Opt-in-by-availability security checks against the local Neo4j service."""
from __future__ import annotations

import pytest

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import Neo4jGraphRepository
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService
from sentinel_pomdp.security import (
    AuthenticatedPrincipal, AuthorizationError, LocalAPIKeyAuthenticator, Permission,
    ProtectedInvestigationService,
)


_manager = Neo4jConnectionManager()
pytestmark = [
    pytest.mark.live_security,
    pytest.mark.skipif(not _manager.ping(), reason="live Neo4j is unavailable"),
]


def test_live_protected_service_enforces_tenant_and_preserves_decision():
    repo = Neo4jGraphRepository(_manager)
    assert KnowledgeGraphIngestionPipeline(repo).ingest_dataset(
        generate_supplier_delay_dataset()).is_success
    auth = LocalAPIKeyAuthenticator()
    permissions = frozenset({
        Permission.INVESTIGATION_EXECUTE, Permission.EVIDENCE_READ,
        Permission.PROVENANCE_READ, Permission.TRACE_READ, Permission.WORKFLOW_RESUME,
    })
    _, alpha_key = auth.issue(AuthenticatedPrincipal(
        "live-alpha", "tenant_alpha", permissions=permissions))
    _, beta_key = auth.issue(AuthenticatedPrincipal(
        "live-beta", "tenant_beta", permissions=permissions))
    boundary = ProtectedInvestigationService(
        auth, InvestigationIntelligenceService(repo, DeterministicFakeLLM()))

    answer = boundary.investigate(
        alpha_key, "Was Supplier A's shipment late?").response
    assert answer.decision == "ANSWER"
    assert answer.final_belief["shipment_delayed"] == pytest.approx(.8869109947643979)
    assert all(repo.get_document(doc_id, "tenant_alpha") for doc_id in answer.document_ids)
    assert boundary.read_document(beta_key, "doc_beta_cert_001").tenant_id == "tenant_beta"
    with pytest.raises(AuthorizationError):
        boundary.read_document(alpha_key, "doc_beta_cert_001")
    with pytest.raises(AuthorizationError):
        boundary.read_trace(beta_key, answer.trace_id)
    with pytest.raises(AuthorizationError):
        boundary.resume_completed(beta_key, answer.trace_id)
