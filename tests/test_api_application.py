from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sentinel_pomdp.api.app import ApplicationDependencies, create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService
from sentinel_pomdp.intelligence.clients import LLMClientError
from sentinel_pomdp.observability import MetricsStore
from sentinel_pomdp.security import (
    AuthenticatedPrincipal, LocalAPIKeyAuthenticator, Permission,
    ProtectedInvestigationService, ProviderDataPolicy,
)


BASE_PERMISSIONS = frozenset({
    Permission.INVESTIGATION_EXECUTE, Permission.EVIDENCE_READ,
    Permission.PROVENANCE_READ, Permission.TRACE_READ, Permission.WORKFLOW_RESUME,
})


@pytest.fixture()
def api():
    credential = secrets.token_urlsafe(32)
    settings = AppSettings(api_key=credential)
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, credential, app.state.dependencies


def headers(credential: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {credential}"}


def investigate(client, credential, question="Was Supplier A's shipment late?"):
    return client.post("/api/v1/investigations", headers=headers(credential),
                       json={"question": question})


def custom_app(*, permissions=BASE_PERMISSIONS, client=None, policy=None,
               readiness=lambda: True, backend="memory", settings=None):
    credential = secrets.token_urlsafe(32)
    repo = InMemoryGraphRepository()
    assert KnowledgeGraphIngestionPipeline(repo).ingest_dataset(
        generate_supplier_delay_dataset()).is_success
    llm = client or DeterministicFakeLLM()
    auth = LocalAPIKeyAuthenticator()
    auth.register(credential, AuthenticatedPrincipal(
        "test-alpha", "tenant_alpha", permissions=frozenset(permissions)))
    service = ProtectedInvestigationService(
        auth, InvestigationIntelligenceService(repo, llm),
        data_policy=policy or ProviderDataPolicy())
    deps = ApplicationDependencies(
        service, auth, MetricsStore(), backend, llm.provider, readiness)
    settings = settings or AppSettings(api_key=credential, permissions=frozenset(permissions))
    return create_app(settings, deps), credential, deps, repo


def test_liveness_readiness_and_security_headers(api):
    client, _, _ = api
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == ready.status_code == 200
    assert live.json()["status"] == "live"
    assert ready.json() == {"status": "ready", "backend": "memory",
                            "provider": "fake", "details": []}
    assert "frame-ancestors 'none'" in ready.headers["content-security-policy"]
    assert "access-control-allow-origin" not in ready.headers
    assert ready.headers["x-correlation-id"]


def test_frontend_and_assets_load_without_persisting_credentials(api):
    client, _, _ = api
    page = client.get("/")
    script = client.get("/assets/app.js")
    style = client.get("/assets/styles.css")
    assert page.status_code == script.status_code == style.status_code == 200
    assert "Investigation timeline" in page.text
    assert "Posterior probabilities" in page.text
    assert "localStorage" not in script.text
    assert "sessionStorage" not in script.text
    assert "Authorization" in script.text


@pytest.mark.parametrize("authorization", [None, "Bearer invalid-credential", "Basic ignored"])
def test_missing_invalid_and_wrong_scheme_credentials_are_rejected(api, authorization):
    client, _, _ = api
    request_headers = {"Authorization": authorization} if authorization else {}
    response = client.post("/api/v1/investigations", headers=request_headers,
                           json={"question": "Was Supplier A late?"})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_FAILED"
    assert "credential" not in response.text.lower()


def test_session_reports_safe_principal_context(api):
    client, credential, _ = api
    response = client.get("/api/v1/session", headers=headers(credential))
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant_alpha"
    assert credential not in response.text


def test_supported_answer_serializes_authoritative_math_and_timeline(api):
    client, credential, _ = api
    response = investigate(client, credential)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == body["decision"] == "ANSWER"
    assert body["scenario_id"] == "supplier_a_shipment_delay"
    assert body["selected_hypothesis"] == "shipment_delayed"
    assert body["posterior"]["shipment_delayed"] == pytest.approx(.8869109947643979)
    assert body["supporting_evidence_ids"] == [
        "ev_telematics_truck_customs", "ev_wh_log_apx101_late"]
    assert body["contradicting_evidence_ids"] == []
    assert body["timeline"][0]["action"] == "inspect_supplier_a_delivery"
    assert body["timeline"][0]["observation"] == "EVIDENCE_SUPPORTED"
    assert body["investigation_cost"] == .08
    assert body["explanation_fallback_used"] is False
    assert body["provider"] == "deterministic-fake"


@pytest.mark.parametrize("question,decision,provenance", [
    ("Did Supplier A cause the entire production delay?", "ABSTAIN", "IRRELEVANT_SUPPORT"),
    ("Did Supplier B deliver on time?", "ABSTAIN", "CONFLICTED"),
    ("Is Component A certified?", "ABSTAIN", "INSUFFICIENT"),
])
def test_abstention_scenarios_are_not_http_errors(api, question, decision, provenance):
    client, credential, _ = api
    response = investigate(client, credential, question)
    assert response.status_code == 200
    assert response.json()["decision"] == decision
    assert response.json()["provenance_status"] == provenance


def test_unsupported_and_clarification_statuses_are_distinct(api):
    client, credential, _ = api
    unsupported = investigate(client, credential, "Write a weather poem")
    ambiguous = investigate(client, credential, "Did the supplier do it?")
    assert unsupported.status_code == ambiguous.status_code == 200
    assert unsupported.json()["status"] == "UNSUPPORTED_REQUEST"
    assert ambiguous.json()["status"] == "CLARIFICATION_REQUIRED"
    assert not unsupported.json()["trace_available"]


def test_validation_error_is_safe_and_does_not_echo_input(api):
    client, credential, _ = api
    marker = "sensitive-marker-" + "x" * 2000
    response = client.post("/api/v1/investigations", headers=headers(credential),
                           json={"question": marker})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    assert marker not in response.text


def test_investigation_detail_trace_evidence_and_provenance(api):
    client, credential, _ = api
    result = investigate(client, credential).json()
    investigation_id = result["investigation_id"]
    detail = client.get(f"/api/v1/investigations/{investigation_id}",
                        headers=headers(credential))
    trace = client.get(f"/api/v1/investigations/{investigation_id}/trace",
                       headers=headers(credential))
    evidence = client.get("/api/v1/evidence/ev_wh_log_apx101_late",
                          headers=headers(credential))
    provenance = client.get("/api/v1/provenance/fact_sup_a_caused_delay",
                            headers=headers(credential))
    assert detail.status_code == trace.status_code == evidence.status_code == provenance.status_code == 200
    assert detail.json()["posterior"] == result["posterior"]
    assert trace.json()["timeline"] == result["timeline"]
    assert any(item["node"] == "bayesian_update" for item in trace.json()["phases"])
    assert evidence.json()["document_id"] == "doc_wh_log_001"
    assert provenance.json()["status"] == "SUPPORTED"


def test_cross_tenant_evidence_trace_and_resume_are_denied(api):
    client, alpha_key, deps = api
    result = investigate(client, alpha_key).json()
    beta_key = secrets.token_urlsafe(32)
    deps.authenticator.register(beta_key, AuthenticatedPrincipal(
        "beta-user", "tenant_beta", permissions=BASE_PERMISSIONS))
    evidence = client.get("/api/v1/evidence/ev_wh_log_apx101_late", headers=headers(beta_key))
    trace = client.get(f"/api/v1/investigations/{result['investigation_id']}/trace",
                       headers=headers(beta_key))
    assert evidence.status_code == trace.status_code == 403
    assert evidence.json()["message"] == trace.json()["message"] == "Resource unavailable or access denied"
    with pytest.raises(Exception):
        deps.service.resume_completed(beta_key, result["investigation_id"])


def test_insufficient_permission_and_restricted_audit():
    app, credential, _, _ = custom_app(
        permissions=BASE_PERMISSIONS - {Permission.INVESTIGATION_EXECUTE})
    with TestClient(app) as client:
        denied = investigate(client, credential)
        audit = client.get("/api/v1/audit", headers=headers(credential))
    assert denied.status_code == audit.status_code == 403
    assert denied.json()["code"] == audit.json()["code"] == "ACCESS_DENIED"


def test_authorized_audit_is_tenant_scoped():
    app, credential, _, _ = custom_app(permissions=BASE_PERMISSIONS | {Permission.AUDIT_READ})
    with TestClient(app) as client:
        investigate(client, credential)
        response = client.get("/api/v1/audit", headers=headers(credential))
    assert response.status_code == 200
    assert all(item["tenant_id"] == "tenant_alpha" for item in response.json())
    assert credential not in response.text


class RecordingExternalLLM(DeterministicFakeLLM):
    provider = "groq"


def test_external_provider_privacy_denial_has_no_model_call():
    llm = RecordingExternalLLM()
    app, credential, _, _ = custom_app(client=llm)
    with TestClient(app) as client:
        response = investigate(client, credential)
    assert response.status_code == 403
    assert response.json()["code"] == "EXTERNAL_PROCESSING_DENIED"
    assert llm.calls == []


def test_explicit_backend_unavailability_is_503_without_fallback():
    app, credential, _, _ = custom_app(readiness=lambda: False, backend="neo4j")
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        result = investigate(client, credential)
    assert live.status_code == 200
    assert ready.status_code == result.status_code == 503
    assert result.json()["code"] == "NOT_READY"
    assert live.json()["backend"] == "neo4j"


def test_database_failure_is_503_not_a_bayesian_observation():
    app, credential, _, repository = custom_app()

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("private driver detail")

    repository.get_fact_evidence = unavailable
    with TestClient(app) as client:
        response = investigate(client, credential)
    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert "private driver" not in response.text


class FailingExternalLLM:
    provider = "groq"
    model = "test-unavailable"

    def generate_structured(self, **_kwargs):
        raise LLMClientError("provider detail must not leak")


def test_provider_failure_is_controlled_and_does_not_leak_detail():
    app, credential, _, _ = custom_app(
        client=FailingExternalLLM(), policy=ProviderDataPolicy(True, frozenset({"groq"})))
    with TestClient(app) as client:
        response = investigate(client, credential)
    assert response.status_code == 502
    assert response.json()["code"] == "PROVIDER_FAILURE"
    assert "provider detail" not in response.text


class SlowExternalLLM(FailingExternalLLM):
    def generate_structured(self, **_kwargs):
        time.sleep(.05)
        return super().generate_structured(**_kwargs)


def test_request_timeout_is_explicit():
    key = secrets.token_urlsafe(32)
    settings = AppSettings(api_key=key, request_timeout_seconds=.01)
    app, credential, _, _ = custom_app(
        client=SlowExternalLLM(), policy=ProviderDataPolicy(True, frozenset({"groq"})),
        settings=settings)
    with TestClient(app) as client:
        response = investigate(client, credential)
    assert response.status_code == 504
    assert response.json()["code"] == "INVESTIGATION_TIMEOUT"


def test_metrics_are_tenant_scoped_and_distinguish_outcomes(api):
    client, credential, _ = api
    investigate(client, credential)
    investigate(client, credential, "Did Supplier B deliver on time?")
    metrics = client.get("/api/v1/metrics/summary", headers=headers(credential))
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["tenant_id"] == "tenant_alpha"
    assert body["metrics"]["requests"] == 2
    assert body["metrics"]["statuses"] == {"ANSWER": 1, "ABSTAIN": 1}
    assert body["metrics"]["investigation_cost_total"] > 0


def test_api_path_matches_direct_and_protected_results(api):
    client, credential, deps = api
    direct = InvestigationIntelligenceService(
        deps.service.intelligence.repository, DeterministicFakeLLM()).investigate(
            "Was Supplier A's shipment late?", "tenant_alpha")
    protected = deps.service.investigate(
        credential, "Was Supplier A's shipment late?", correlation_id="protected-parity").response
    http = investigate(client, credential).json()
    for result in (protected,):
        assert result.scenario_id == direct.scenario_id
        assert result.decision == direct.decision
        assert result.final_belief == direct.final_belief
        assert result.supporting_evidence_ids == direct.supporting_evidence_ids
        assert result.investigation["total_cost"] == direct.investigation["total_cost"]
    assert http["scenario_id"] == direct.scenario_id
    assert http["decision"] == direct.decision
    assert http["posterior"] == direct.final_belief
    assert http["supporting_evidence_ids"] == direct.supporting_evidence_ids
    assert http["investigation_cost"] == direct.investigation["total_cost"]


def test_revoked_and_expired_api_keys_are_rejected(api):
    client, _, deps = api
    principal = AuthenticatedPrincipal("temp", "tenant_alpha", permissions=BASE_PERMISSIONS)
    revoked_id, revoked_key = deps.authenticator.issue(principal)
    deps.authenticator.revoke(revoked_id)
    _, expired_key = deps.authenticator.issue(AuthenticatedPrincipal(
        "expired", "tenant_alpha", permissions=BASE_PERMISSIONS,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert investigate(client, revoked_key).status_code == 401
    assert investigate(client, expired_key).status_code == 401


def test_logs_and_responses_exclude_question_and_api_key(api, caplog):
    client, credential, _ = api
    caplog.set_level(logging.INFO, logger="sentinel_pomdp.api")
    sensitive_question = "Was Supplier A late? private-reference-741"
    response = investigate(client, credential, sensitive_question)
    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert credential not in response.text and credential not in rendered_logs
    assert sensitive_question not in rendered_logs


def test_route_table_has_one_investigation_entrypoint(api):
    _, _, deps = api
    app = create_app(AppSettings(api_key=secrets.token_urlsafe(32)), deps)
    paths = [(route.path, tuple(sorted(getattr(route, "methods", None) or [])))
             for route in app.routes]
    post_paths = [path for path, methods in paths
                  if "POST" in methods and path.startswith("/api/v1/investigations")]
    assert post_paths == ["/api/v1/investigations"]
    assert not any("cypher" in path.lower() or "internal" in path.lower() for path, _ in paths)


def test_unknown_route_is_404(api):
    client, _, _ = api
    assert client.get("/api/v1/not-a-route").status_code == 404
