import pytest

from sentinel_pomdp.operations import (
    DurableWorker,
    JobState,
    NewOperationJob,
    OperationType,
    RetryableOperationError,
    SQLiteOperationRepository,
    UncertainOperationError,
)


def enqueue(repo, *, key="key", retries=2, replay_safe=True):
    return repo.create_job(NewOperationJob(
        tenant_id="tenant-a", principal_id="operator-a",
        operation_type=OperationType.EVALUATION, correlation_id="corr-a",
        payload={"evaluation_id": "eval-a"}, idempotency_key=key,
        max_retries=retries, replay_safe=replay_safe,
    ))[0]


def test_worker_completes_and_persists_result(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "ops.db")
    job = enqueue(repo)
    worker = DurableWorker(repo, {
        OperationType.EVALUATION: lambda context, payload: {"id": payload["evaluation_id"]}
    }, retry_backoff_seconds=0)
    assert worker.run_once()
    restored = repo.get_job("tenant-a", job.job_id)
    assert restored.state is JobState.COMPLETED
    assert restored.result == {"id": "eval-a"}


def test_retry_is_bounded_and_only_for_replay_safe_job(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "ops.db")
    safe = enqueue(repo, key="safe", retries=1)

    def transient(_context, _payload):
        raise RetryableOperationError("TEMPORARY", "try later")

    worker = DurableWorker(repo, {OperationType.EVALUATION: transient}, retry_backoff_seconds=0)
    worker.run_once()
    assert repo.get_job("tenant-a", safe.job_id).state is JobState.RETRY_WAIT
    worker.run_once()
    assert repo.get_job("tenant-a", safe.job_id).state is JobState.FAILED

    unsafe = enqueue(repo, key="unsafe", replay_safe=False)
    worker.run_once()
    assert repo.get_job("tenant-a", unsafe.job_id).state is JobState.FAILED


def test_uncertain_failure_never_blindly_retries(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "ops.db")
    job = enqueue(repo)

    def uncertain(_context, _payload):
        raise UncertainOperationError("REMOTE_RESULT_UNKNOWN", "timeout after submit")

    DurableWorker(repo, {OperationType.EVALUATION: uncertain}).run_once()
    assert repo.get_job("tenant-a", job.job_id).state is JobState.NEEDS_RECONCILIATION


def test_journal_replays_completed_side_effect(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "ops.db")
    job = enqueue(repo)
    calls = []

    def handler(context, payload):
        first = context.journaled_step(
            "publish", payload,
            lambda: calls.append("called") or {"publication_id": "pub-1"},
        )
        second = context.journaled_step(
            "publish", payload,
            lambda: calls.append("called-again") or {"publication_id": "pub-2"},
        )
        assert first == second
        return first

    DurableWorker(repo, {OperationType.EVALUATION: handler}).run_once()
    assert calls == ["called"]
    assert repo.get_job("tenant-a", job.job_id).result == {"publication_id": "pub-1"}


def test_started_journal_requires_reconciliation(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "ops.db")
    job = enqueue(repo)

    def handler(context, payload):
        from hashlib import sha256
        import json
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint = sha256(encoded.encode()).hexdigest()
        context.repository.journal_put(context.claim, "publish", "STARTED", fingerprint)
        return context.journaled_step("publish", payload, lambda: {})

    DurableWorker(repo, {OperationType.EVALUATION: handler}).run_once()
    assert repo.get_job("tenant-a", job.job_id).state is JobState.NEEDS_RECONCILIATION


def test_queued_cancellation_is_not_claimed(tmp_path):
    repo = SQLiteOperationRepository(tmp_path / "ops.db")
    job = enqueue(repo)
    repo.request_cancel("tenant-a", job.job_id)
    assert not DurableWorker(repo, {OperationType.EVALUATION: lambda *_: {}}).run_once()
