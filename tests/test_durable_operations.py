from datetime import timedelta
from threading import Barrier, Thread

import pytest

from sentinel_pomdp.operations import (
    IdempotencyConflict,
    JobState,
    LeaseLost,
    NewOperationJob,
    OperationError,
    OperationType,
    SQLiteOperationRepository,
)
from sentinel_pomdp.operations.models import utc_now


def request(**overrides):
    values = dict(
        tenant_id="tenant-a",
        principal_id="reviewer-a",
        operation_type=OperationType.DOCUMENT_INGESTION,
        correlation_id="corr-1",
        payload={"document_id": "doc-1"},
        idempotency_key="idem-1",
        max_retries=2,
        replay_safe=True,
    )
    values.update(overrides)
    return NewOperationJob(**values)


def test_job_and_audit_survive_restart(tmp_path):
    path = tmp_path / "operations.db"
    first = SQLiteOperationRepository(path)
    created, is_new = first.create_job(request())
    assert is_new and created.state is JobState.QUEUED
    first.close()

    second = SQLiteOperationRepository(path)
    restored = second.get_job("tenant-a", created.job_id)
    assert restored is not None and restored.payload == {"document_id": "doc-1"}
    assert second.list_audit("tenant-a")[0]["operation"] == "job.created"
    second.close()


def test_idempotency_replays_identical_request_and_rejects_conflict(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    original, created = repo.create_job(request())
    replay, replay_created = repo.create_job(request(correlation_id="corr-2"))
    assert created is True and replay_created is False
    assert replay.job_id == original.job_id
    with pytest.raises(IdempotencyConflict):
        repo.create_job(request(payload={"document_id": "doc-2"}))


def test_tenant_scope_and_secret_payload_are_fail_closed(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    job, _ = repo.create_job(request())
    assert repo.get_job("tenant-b", job.job_id) is None
    assert repo.list_jobs("tenant-b") == []
    with pytest.raises(OperationError, match="not permitted"):
        repo.create_job(request(idempotency_key="secret", payload={"api_key": "never-store-me"}))


def test_concurrent_claim_has_one_winner(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    repo.create_job(request())
    barrier = Barrier(3)
    claims = []

    def claim(worker):
        barrier.wait()
        claims.append(repo.claim(worker))

    threads = [Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sum(item is not None for item in claims) == 1


def test_expired_replay_safe_lease_retries_and_fences_stale_worker(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    job, _ = repo.create_job(request())
    old_claim = repo.claim("worker-old", lease_seconds=1)
    assert old_claim is not None
    with repo._transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE operation_jobs SET lease_expires_at=? WHERE job_id=?",
            ((utc_now() - timedelta(seconds=2)).isoformat(), job.job_id),
        )
    new_claim = repo.claim("worker-new", lease_seconds=30)
    assert new_claim is not None
    assert new_claim.fencing_token > old_claim.fencing_token
    with pytest.raises(LeaseLost):
        repo.complete(old_claim, {"unsafe": True})
    completed = repo.complete(new_claim, {"ok": True})
    assert completed.state is JobState.COMPLETED


def test_expired_uncertain_lease_requires_reconciliation(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    job, _ = repo.create_job(request(replay_safe=False))
    claim = repo.claim("worker-old", lease_seconds=1)
    assert claim is not None
    with repo._transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE operation_jobs SET lease_expires_at=? WHERE job_id=?",
            ((utc_now() - timedelta(seconds=2)).isoformat(), job.job_id),
        )
    assert repo.claim("worker-new") is None
    restored = repo.get_job("tenant-a", job.job_id)
    assert restored is not None
    assert restored.state is JobState.NEEDS_RECONCILIATION


def test_cancellation_is_immediate_when_queued_and_cooperative_when_running(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    queued, _ = repo.create_job(request())
    assert repo.request_cancel("tenant-a", queued.job_id).state is JobState.CANCELLED

    running, _ = repo.create_job(request(idempotency_key="idem-2"))
    claim = repo.claim("worker")
    assert claim is not None and claim.job.job_id == running.job_id
    requested = repo.request_cancel("tenant-a", running.job_id)
    assert requested.state is JobState.CANCEL_REQUESTED
    assert repo.cancellation_requested(claim)
    assert repo.cancel_claim(claim).state is JobState.CANCELLED


def test_checkpoint_is_tenant_scoped_and_integrity_stamped(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    repo.put_checkpoint(
        workflow_id="wf-1", tenant_id="tenant-a", principal_id="principal-a",
        scenario_id="scenario-a", model_version="v1", sequence=1,
        phase="evidence_verified", state={"observation_ids": ["obs-1"]},
    )
    assert repo.latest_checkpoint("tenant-b", "wf-1") is None
    restored = repo.latest_checkpoint("tenant-a", "wf-1")
    assert restored["state"] == {"observation_ids": ["obs-1"]}
    assert len(restored["state_fingerprint"]) == 64


def test_summary_reports_queue_and_worker_health(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "operations.db")
    repo.create_job(request())
    repo.heartbeat_worker("worker-1", {"version": "test"})
    summary = repo.summary("tenant-a")
    assert summary["counts"] == {"QUEUED": 1}
    assert summary["fresh_workers"] == 1
    assert summary["multi_worker_supported"] is False
