"""FastAPI-to-protected-service verification against configured local Neo4j."""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from sentinel_pomdp.api.app import ApplicationDependencies, create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import Neo4jGraphRepository
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService
from sentinel_pomdp.observability import MetricsStore
from sentinel_pomdp.security import (
    AuthenticatedPrincipal, LocalAPIKeyAuthenticator, Permission,
    ProtectedInvestigationService,
)


_manager = Neo4jConnectionManager()
pytestmark = [
    pytest.mark.live_api,
    pytest.mark.skipif(not _manager.ping(), reason="live Neo4j is unavailable"),
]


def test_live_browser_api_path_preserves_math_and_tenant_isolation():
    repository = Neo4jGraphRepository(_manager)
    assert KnowledgeGraphIngestionPipeline(repository).ingest_dataset(
        generate_supplier_delay_dataset()).is_success
    auth = LocalAPIKeyAuthenticator()
    permissions = frozenset({
        Permission.INVESTIGATION_EXECUTE, Permission.EVIDENCE_READ,
        Permission.PROVENANCE_READ, Permission.TRACE_READ, Permission.WORKFLOW_RESUME,
    })
    alpha_key = secrets.token_urlsafe(32)
    beta_key = secrets.token_urlsafe(32)
    auth.register(alpha_key, AuthenticatedPrincipal(
        "api-live-alpha", "tenant_alpha", permissions=permissions))
    auth.register(beta_key, AuthenticatedPrincipal(
        "api-live-beta", "tenant_beta", permissions=permissions))
    service = ProtectedInvestigationService(
        auth, InvestigationIntelligenceService(repository, DeterministicFakeLLM()))
    deps = ApplicationDependencies(
        service, auth, MetricsStore(), "neo4j", "fake", _manager.ping)
    app = create_app(AppSettings(api_key=alpha_key, backend="neo4j"), deps)

    with TestClient(app) as client:
        result = client.post(
            "/api/v1/investigations", headers={"Authorization": f"Bearer {alpha_key}"},
            json={"question": "Was Supplier A's shipment late?"})
        assert result.status_code == 200
        body = result.json()
        assert body["decision"] == "ANSWER"
        assert body["posterior"]["shipment_delayed"] == pytest.approx(.8869109947643979)
        denied = client.get(
            f"/api/v1/investigations/{body['investigation_id']}/trace",
            headers={"Authorization": f"Bearer {beta_key}"})
        assert denied.status_code == 403
        evidence = client.get(
            "/api/v1/evidence/ev_wh_log_apx101_late",
            headers={"Authorization": f"Bearer {alpha_key}"})
        assert evidence.status_code == 200
        assert evidence.json()["document_id"] == "doc_wh_log_001"
