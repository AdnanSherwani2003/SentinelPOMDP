from threading import Event
from time import sleep

from fastapi.testclient import TestClient

from sentinel_pomdp.api.app import ApplicationDependencies, create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.observability import MetricsStore
from sentinel_pomdp.security import (
    AuthenticatedPrincipal, LocalAPIKeyAuthenticator, Permission,
)


def test_http_timeout_is_safe_but_does_not_claim_thread_cancellation():
    """The current sync worker can finish after HTTP 504; this is a documented limitation."""
    completed = Event()

    class SlowService:
        def investigate(self, *_args, **_kwargs):
            sleep(.08)
            completed.set()
            raise RuntimeError("late result is deliberately ignored")

    key = "t" * 32
    auth = LocalAPIKeyAuthenticator()
    auth.register(key, AuthenticatedPrincipal(
        "timeout-user", "tenant_alpha",
        permissions=frozenset({Permission.INVESTIGATION_EXECUTE})))
    deps = ApplicationDependencies(
        SlowService(), auth, MetricsStore(), "memory", "fake", lambda: True)
    app = create_app(AppSettings(api_key=key, request_timeout_seconds=.01), deps)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/investigations", headers={"Authorization": f"Bearer {key}"},
            json={"question": "Was Supplier A's shipment late?"})
    assert response.status_code == 504
    assert response.json()["code"] == "INVESTIGATION_TIMEOUT"
    assert completed.wait(.5), "worker-thread continuation semantics changed; reassess cancellation"


def test_failed_neo4j_readiness_never_falls_back_to_memory(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://127.0.0.1:1")
    monkeypatch.setenv("NEO4J_PASSWORD", "placeholder-not-a-real-secret")
    key = "n" * 32
    app = create_app(AppSettings(
        api_key=key, backend="neo4j", request_timeout_seconds=1))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/investigations", headers={"Authorization": f"Bearer {key}"},
            json={"question": "Was Supplier A's shipment late?"})
    assert response.status_code == 503
    assert response.json()["code"] == "NOT_READY"
    assert app.state.dependencies.backend_name == "neo4j"
