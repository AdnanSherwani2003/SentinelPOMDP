from fastapi.testclient import TestClient

from sentinel_pomdp.api.app import ApplicationDependencies, create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.observability import MetricsStore
from sentinel_pomdp.operations import OperationService, SQLiteOperationRepository
from sentinel_pomdp.security import (
    AuthenticatedPrincipal, LocalAPIKeyAuthenticator, Permission,
)


class UnusedInvestigationService:
    pass


def client(tmp_path, *, tenant="tenant-a", permissions=None):
    key = "k" * 32
    auth = LocalAPIKeyAuthenticator()
    auth.register(key, AuthenticatedPrincipal(
        "operator-a", tenant,
        permissions=frozenset(permissions or {
            Permission.JOB_SUBMIT, Permission.JOB_READ, Permission.JOB_CANCEL,
            Permission.OPERATIONS_READ, Permission.CALIBRATION_RUN,
        })))
    repo = SQLiteOperationRepository(tmp_path / f"{tenant}.db")
    deps = ApplicationDependencies(
        UnusedInvestigationService(), auth, MetricsStore(), "memory", "fake",
        lambda: True, operations=OperationService(repo))
    app = create_app(AppSettings(
        api_key=key, operations_database_path=str(tmp_path / "unused.db")), deps)
    return TestClient(app), {"Authorization": f"Bearer {key}"}, repo


def test_submit_replay_list_summary_and_cancel(tmp_path):
    api, headers, _repo = client(tmp_path)
    body = {
        "operation_type": "EVALUATION",
        "payload": {"evaluation_id": "eval-1"},
        "idempotency_key": "request-1",
    }
    with api:
        created = api.post("/api/v1/jobs", headers=headers, json=body)
        assert created.status_code == 202 and created.json()["created"] is True
        replay = api.post("/api/v1/jobs", headers=headers, json=body)
        assert replay.status_code == 202 and replay.json()["created"] is False
        assert replay.json()["job_id"] == created.json()["job_id"]
        assert api.get("/api/v1/jobs", headers=headers).json()[0]["job_id"] == created.json()["job_id"]
        assert api.get("/api/v1/operations/summary", headers=headers).json()["counts"] == {"QUEUED": 1}
        cancelled = api.post(
            f"/api/v1/jobs/{created.json()['job_id']}/cancel", headers=headers)
        assert cancelled.json()["state"] == "CANCELLED"


def test_api_idempotency_conflict_and_secret_rejection(tmp_path):
    api, headers, _repo = client(tmp_path)
    first = {"operation_type": "EVALUATION", "payload": {"id": 1}, "idempotency_key": "same"}
    second = {"operation_type": "EVALUATION", "payload": {"id": 2}, "idempotency_key": "same"}
    with api:
        assert api.post("/api/v1/jobs", headers=headers, json=first).status_code == 202
        conflict = api.post("/api/v1/jobs", headers=headers, json=second)
        assert conflict.status_code == 409
        secret = api.post("/api/v1/jobs", headers=headers, json={
            "operation_type": "EVALUATION", "payload": {"password": "forbidden-test-credential-value"}})
        assert secret.status_code == 422
        assert "forbidden-test-credential-value" not in secret.text


def test_job_lookup_does_not_cross_tenant(tmp_path):
    first_api, first_headers, repo = client(tmp_path, tenant="tenant-a")
    with first_api:
        job_id = first_api.post("/api/v1/jobs", headers=first_headers, json={
            "operation_type": "EVALUATION", "payload": {"id": 1}}).json()["job_id"]

    key = "b" * 32
    auth = LocalAPIKeyAuthenticator()
    auth.register(key, AuthenticatedPrincipal(
        "operator-b", "tenant-b", permissions=frozenset({Permission.JOB_READ})))
    deps = ApplicationDependencies(
        UnusedInvestigationService(), auth, MetricsStore(), "memory", "fake",
        lambda: True, operations=OperationService(repo))
    second_api = TestClient(create_app(AppSettings(api_key=key), deps))
    with second_api:
        response = second_api.get(
            f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 404


def test_job_endpoints_enforce_permissions(tmp_path):
    api, headers, repo = client(tmp_path, permissions={Permission.EVIDENCE_READ})
    with api:
        response = api.post("/api/v1/jobs", headers=headers, json={
            "operation_type": "EVALUATION", "payload": {"id": 1}})
    assert response.status_code == 403
    events = repo.list_audit("tenant-a")
    assert events[0]["operation"] == "job.submit"
    assert events[0]["outcome"] == "DENY"
    repo.close()
    reopened = SQLiteOperationRepository(tmp_path / "tenant-a.db")
    assert reopened.list_audit("tenant-a")[0]["reason_code"] == "AUTHORIZATION_FAILED"
