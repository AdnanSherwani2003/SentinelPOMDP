"""PostgreSQL operations store for concurrent API and worker processes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .models import (
    IdempotencyConflict, JobClaim, JobState, LeaseLost, NewOperationJob,
    OperationAuditEvent, OperationJob, OperationType, canonical_payload, utc_now,
)
from .repository import OperationRepository


def _job(row: dict[str, Any]) -> OperationJob:
    def object_value(value):
        return json.loads(value) if isinstance(value, str) else value
    return OperationJob(
        job_id=str(row["job_id"]), tenant_id=row["tenant_id"],
        principal_id=row["principal_id"], operation_type=OperationType(row["operation_type"]),
        state=JobState(row["state"]), created_at=row["created_at"], updated_at=row["updated_at"],
        attempt_count=row["attempt_count"], correlation_id=row["correlation_id"],
        idempotency_key=row["idempotency_key"], input_fingerprint=row["input_fingerprint"],
        payload=object_value(row["payload_json"]), progress=object_value(row["progress_json"]),
        result=object_value(row["result_json"]) if row["result_json"] is not None else None,
        error_code=row["error_code"], lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"], fencing_token=row["fencing_token"],
        max_retries=row["max_retries"], replay_safe=row["replay_safe"],
        cancellation_requested=row["cancellation_requested"], not_before=row["not_before"],
    )


class PostgresOperationRepository(OperationRepository):
    supports_multi_worker = True

    def __init__(self, connection_string: str, *, min_size: int = 1, max_size: int = 10) -> None:
        if not connection_string:
            raise ValueError("PostgreSQL connection string is required")
        self._pool = ConnectionPool(
            connection_string, min_size=min_size, max_size=max_size,
            kwargs={"row_factory": dict_row}, open=True,
        )
        self._pool.wait(timeout=10)
        self.migrate()

    def migrate(self) -> None:
        source = (Path(__file__).with_name("migrations") / "001_initial_postgres.sql").read_text("utf-8")
        with self._pool.connection() as connection:
            with connection.transaction():
                for statement in source.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO operation_schema_version(version,applied_at) VALUES(1,%s) ON CONFLICT DO NOTHING",
                    (utc_now(),),
                )

    @staticmethod
    def _audit(cursor, *, operation: str, outcome: str, reason: str,
               correlation_id: str, tenant_id: str | None = None,
               principal_id: str | None = None, resource_id: str | None = None) -> None:
        cursor.execute("""INSERT INTO operation_audit
            (event_id,occurred_at,operation,outcome,reason_code,correlation_id,tenant_id,principal_id,resource_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
            str(uuid4()), utc_now(), operation, outcome, reason, correlation_id,
            tenant_id, principal_id, resource_id))

    def create_job(self, request: NewOperationJob) -> tuple[OperationJob, bool]:
        request.validate(); payload, fingerprint = canonical_payload(request.payload); now = utc_now()
        with self._pool.connection() as connection, connection.transaction():
            job_id = str(uuid4())
            inserted = connection.execute("""INSERT INTO operation_jobs
                (job_id,tenant_id,principal_id,operation_type,state,created_at,updated_at,attempt_count,
                 correlation_id,idempotency_key,input_fingerprint,payload_json,progress_json,max_retries,replay_safe)
                VALUES(%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,principal_id,operation_type,idempotency_key)
                WHERE idempotency_key IS NOT NULL DO NOTHING RETURNING *""", (
                job_id, request.tenant_id, request.principal_id, request.operation_type.value,
                JobState.QUEUED.value, now, now, request.correlation_id, request.idempotency_key,
                fingerprint, Jsonb(json.loads(payload)), Jsonb({}), request.max_retries,
                request.replay_safe)).fetchone()
            if not inserted:
                existing = connection.execute("""SELECT * FROM operation_jobs
                    WHERE tenant_id=%s AND principal_id=%s AND operation_type=%s AND idempotency_key=%s""",
                    (request.tenant_id, request.principal_id, request.operation_type.value,
                     request.idempotency_key)).fetchone()
                if existing is None or existing["input_fingerprint"] != fingerprint:
                    raise IdempotencyConflict()
                return _job(existing), False
            self._audit(connection, operation="job.created", outcome="ACCEPTED", reason="QUEUED",
                correlation_id=request.correlation_id, tenant_id=request.tenant_id,
                principal_id=request.principal_id, resource_id=job_id)
            return _job(inserted), True

    def get_job(self, tenant_id: str, job_id: str) -> OperationJob | None:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM operation_jobs WHERE tenant_id=%s AND job_id=%s",
                (tenant_id, job_id)).fetchone()
            return _job(row) if row else None

    def list_jobs(self, tenant_id: str, *, limit: int = 100) -> list[OperationJob]:
        with self._pool.connection() as connection:
            rows = connection.execute("""SELECT * FROM operation_jobs WHERE tenant_id=%s
                ORDER BY created_at DESC LIMIT %s""", (tenant_id, max(1, min(limit, 500)))).fetchall()
            return [_job(row) for row in rows]

    def _recover_expired(self, connection, now: datetime) -> None:
        rows = connection.execute("""SELECT * FROM operation_jobs
            WHERE state IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at < %s
            FOR UPDATE SKIP LOCKED""", (now,)).fetchall()
        for row in rows:
            job = _job(row)
            if job.state is JobState.CANCEL_REQUESTED:
                state, code = JobState.NEEDS_RECONCILIATION, "CANCELLED_WORKER_LOST"
            elif job.replay_safe and job.attempt_count <= job.max_retries:
                state, code = JobState.RETRY_WAIT, "LEASE_EXPIRED"
            else:
                state, code = JobState.NEEDS_RECONCILIATION, "LEASE_EXPIRED_UNCERTAIN"
            connection.execute("""UPDATE operation_jobs SET state=%s,updated_at=%s,error_code=%s,
                lease_owner=NULL,lease_expires_at=NULL,not_before=%s WHERE job_id=%s""", (
                state.value, now, code, now if state is JobState.RETRY_WAIT else None, job.job_id))
            self._audit(connection, operation="job.lease_expired", outcome=state.value, reason=code,
                correlation_id=job.correlation_id, tenant_id=job.tenant_id,
                principal_id=job.principal_id, resource_id=job.job_id)

    def claim(self, worker_id: str, *, lease_seconds: float = 30) -> JobClaim | None:
        if not worker_id.strip() or not 1 <= lease_seconds <= 3600:
            raise ValueError("invalid worker lease")
        now = utc_now()
        with self._pool.connection() as connection, connection.transaction():
            self._recover_expired(connection, now)
            row = connection.execute("""SELECT * FROM operation_jobs
                WHERE state IN ('QUEUED','RETRY_WAIT') AND (not_before IS NULL OR not_before<=%s)
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""", (now,)).fetchone()
            if not row:
                return None
            token = row["fencing_token"] + 1
            claimed = connection.execute("""UPDATE operation_jobs SET state='RUNNING',updated_at=%s,
                attempt_count=attempt_count+1,lease_owner=%s,lease_expires_at=%s,
                fencing_token=%s,error_code=NULL,not_before=NULL WHERE job_id=%s RETURNING *""", (
                now, worker_id, now + timedelta(seconds=lease_seconds), token, row["job_id"])).fetchone()
            job = _job(claimed)
            self._audit(connection, operation="job.claimed", outcome="RUNNING", reason="CLAIMED",
                correlation_id=job.correlation_id, tenant_id=job.tenant_id,
                principal_id=job.principal_id, resource_id=job.job_id)
            return JobClaim(job, worker_id, token)

    def _owned_update(self, claim: JobClaim, assignments: str, values: tuple[Any, ...],
                      *, states: str = "('RUNNING','CANCEL_REQUESTED')") -> OperationJob:
        with self._pool.connection() as connection, connection.transaction():
            row = connection.execute(f"""UPDATE operation_jobs SET {assignments}
                WHERE job_id=%s AND lease_owner=%s AND fencing_token=%s AND state IN {states}
                RETURNING *""", values + (claim.job.job_id, claim.worker_id, claim.fencing_token)).fetchone()
            if not row:
                raise LeaseLost()
            return _job(row)

    def heartbeat(self, claim: JobClaim, *, lease_seconds: float = 30) -> OperationJob:
        now = utc_now()
        return self._owned_update(claim, "updated_at=%s,lease_expires_at=%s",
            (now, now + timedelta(seconds=lease_seconds)))

    def update_progress(self, claim: JobClaim, progress: dict[str, Any]) -> OperationJob:
        canonical_payload(progress)
        return self._owned_update(claim, "updated_at=%s,progress_json=%s",
            (utc_now(), Jsonb(progress)))

    def complete(self, claim: JobClaim, result: dict[str, Any]) -> OperationJob:
        canonical_payload(result); now = utc_now()
        with self._pool.connection() as connection, connection.transaction():
            row = connection.execute("""UPDATE operation_jobs SET state='COMPLETED',updated_at=%s,
                result_json=%s,error_code=NULL,lease_owner=NULL,lease_expires_at=NULL,
                cancellation_requested=FALSE WHERE job_id=%s AND lease_owner=%s AND fencing_token=%s
                AND state='RUNNING' RETURNING *""", (
                now, Jsonb(result), claim.job.job_id, claim.worker_id, claim.fencing_token)).fetchone()
            if not row: raise LeaseLost()
            job = _job(row)
            self._audit(connection, operation="job.completed", outcome="COMPLETED",
                reason="RESULT_PERSISTED", correlation_id=job.correlation_id,
                tenant_id=job.tenant_id, principal_id=job.principal_id, resource_id=job.job_id)
            return job

    def fail(self, claim: JobClaim, code: str, *, retryable: bool,
             uncertain: bool = False, backoff_seconds: float = 1) -> OperationJob:
        current = self.get_job(claim.job.tenant_id, claim.job.job_id)
        if current is None: raise LeaseLost()
        if uncertain: state = JobState.NEEDS_RECONCILIATION
        elif retryable and current.replay_safe and current.attempt_count <= current.max_retries:
            state = JobState.RETRY_WAIT
        else: state = JobState.FAILED
        now = utc_now(); not_before = (
            now + timedelta(seconds=max(0, min(backoff_seconds, 3600)))
            if state is JobState.RETRY_WAIT else None)
        with self._pool.connection() as connection, connection.transaction():
            row = connection.execute("""UPDATE operation_jobs SET state=%s,updated_at=%s,error_code=%s,
                lease_owner=NULL,lease_expires_at=NULL,not_before=%s WHERE job_id=%s AND lease_owner=%s
                AND fencing_token=%s AND state IN ('RUNNING','CANCEL_REQUESTED') RETURNING *""", (
                state.value, now, code, not_before, claim.job.job_id,
                claim.worker_id, claim.fencing_token)).fetchone()
            if not row: raise LeaseLost()
            job = _job(row)
            self._audit(connection, operation="job.failed", outcome=state.value, reason=code,
                correlation_id=job.correlation_id, tenant_id=job.tenant_id,
                principal_id=job.principal_id, resource_id=job.job_id)
            return job

    def request_cancel(self, tenant_id: str, job_id: str) -> OperationJob | None:
        with self._pool.connection() as connection, connection.transaction():
            row = connection.execute("""SELECT * FROM operation_jobs WHERE tenant_id=%s AND job_id=%s
                FOR UPDATE""", (tenant_id, job_id)).fetchone()
            if not row: return None
            job = _job(row)
            if job.state in {JobState.QUEUED, JobState.RETRY_WAIT}: state = JobState.CANCELLED
            elif job.state is JobState.RUNNING: state = JobState.CANCEL_REQUESTED
            else: return job
            updated = _job(connection.execute("""UPDATE operation_jobs SET state=%s,updated_at=%s,
                cancellation_requested=TRUE WHERE job_id=%s RETURNING *""",
                (state.value, utc_now(), job_id)).fetchone())
            self._audit(connection, operation="job.cancel_requested", outcome=state.value,
                reason="USER_REQUEST", correlation_id=job.correlation_id, tenant_id=job.tenant_id,
                principal_id=job.principal_id, resource_id=job.job_id)
            return updated

    def cancellation_requested(self, claim: JobClaim) -> bool:
        current = self.get_job(claim.job.tenant_id, claim.job.job_id)
        if current is None or current.fencing_token != claim.fencing_token or current.lease_owner != claim.worker_id:
            raise LeaseLost()
        return current.cancellation_requested or current.state is JobState.CANCEL_REQUESTED

    def cancel_claim(self, claim: JobClaim) -> OperationJob:
        return self._owned_update(claim,
            "state='CANCELLED',updated_at=%s,lease_owner=NULL,lease_expires_at=NULL,error_code='CANCELLED_AT_SAFE_BOUNDARY'",
            (utc_now(),), states="('CANCEL_REQUESTED')")

    def journal_get(self, job_id: str, step_key: str) -> dict[str, Any] | None:
        with self._pool.connection() as connection:
            row = connection.execute("SELECT * FROM operation_journal WHERE job_id=%s AND step_key=%s",
                (job_id, step_key)).fetchone()
            if row and isinstance(row.get("result_json"), dict):
                row["result_json"] = json.dumps(row["result_json"], sort_keys=True, separators=(",", ":"))
            return row

    def journal_put(self, claim: JobClaim, step_key: str, state: str, input_fingerprint: str,
                    result: dict[str, Any] | None = None) -> None:
        current = self.get_job(claim.job.tenant_id, claim.job.job_id)
        if current is None or current.lease_owner != claim.worker_id or current.fencing_token != claim.fencing_token:
            raise LeaseLost()
        with self._pool.connection() as connection, connection.transaction():
            connection.execute("""INSERT INTO operation_journal
                (job_id,step_key,state,input_fingerprint,result_json,updated_at) VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(job_id,step_key) DO UPDATE SET state=excluded.state,
                input_fingerprint=excluded.input_fingerprint,result_json=excluded.result_json,
                updated_at=excluded.updated_at""", (claim.job.job_id, step_key, state,
                input_fingerprint, Jsonb(result) if result is not None else None, utc_now()))

    def emit_audit(self, event: OperationAuditEvent) -> None:
        with self._pool.connection() as connection, connection.transaction():
            connection.execute("""INSERT INTO operation_audit
                (event_id,occurred_at,operation,outcome,reason_code,correlation_id,tenant_id,principal_id,resource_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (
                event.event_id, event.occurred_at, event.operation, event.outcome,
                event.reason_code, event.correlation_id, event.tenant_id,
                event.principal_id, event.resource_id))

    def list_audit(self, tenant_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._pool.connection() as connection:
            return connection.execute("""SELECT * FROM operation_audit WHERE tenant_id=%s
                ORDER BY occurred_at DESC LIMIT %s""", (tenant_id, max(1, min(limit, 500)))).fetchall()

    def heartbeat_worker(self, worker_id: str, metadata: dict[str, Any] | None = None) -> None:
        canonical_payload(metadata or {}); now = utc_now()
        with self._pool.connection() as connection, connection.transaction():
            connection.execute("""INSERT INTO worker_heartbeats(worker_id,heartbeat_at,started_at,metadata_json)
                VALUES(%s,%s,%s,%s) ON CONFLICT(worker_id) DO UPDATE SET
                heartbeat_at=excluded.heartbeat_at,metadata_json=excluded.metadata_json""",
                (worker_id, now, now, Jsonb(metadata or {})))

    def put_checkpoint(self, *, workflow_id: str, tenant_id: str, principal_id: str,
                       scenario_id: str, model_version: str, sequence: int, phase: str,
                       state: dict[str, Any]) -> None:
        _, fingerprint = canonical_payload(state)
        with self._pool.connection() as connection, connection.transaction():
            connection.execute("""INSERT INTO workflow_checkpoints(workflow_id,tenant_id,principal_id,
                scenario_id,model_version,sequence,phase,state_json,state_fingerprint,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (workflow_id, tenant_id,
                principal_id, scenario_id, model_version, sequence, phase, Jsonb(state), fingerprint, utc_now()))

    def latest_checkpoint(self, tenant_id: str, workflow_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as connection:
            row = connection.execute("""SELECT * FROM workflow_checkpoints WHERE tenant_id=%s
                AND workflow_id=%s ORDER BY sequence DESC LIMIT 1""", (tenant_id, workflow_id)).fetchone()
            if not row: return None
            row["state"] = row.pop("state_json")
            return row

    def summary(self, tenant_id: str, *, stale_worker_seconds: float = 60) -> dict[str, Any]:
        now = utc_now()
        with self._pool.connection() as connection:
            counts = {row["state"]: row["count"] for row in connection.execute(
                "SELECT state,count(*) AS count FROM operation_jobs WHERE tenant_id=%s GROUP BY state",
                (tenant_id,)).fetchall()}
            oldest = connection.execute("""SELECT MIN(created_at) AS value FROM operation_jobs
                WHERE tenant_id=%s AND state='QUEUED'""", (tenant_id,)).fetchone()["value"]
            expired = connection.execute("""SELECT count(*) AS value FROM operation_jobs WHERE tenant_id=%s
                AND state IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at<%s""",
                (tenant_id, now)).fetchone()["value"]
            workers = connection.execute("SELECT count(*) AS value FROM worker_heartbeats WHERE heartbeat_at>=%s",
                (now - timedelta(seconds=stale_worker_seconds),)).fetchone()["value"]
            retry_count = connection.execute("""SELECT COALESCE(SUM(GREATEST(attempt_count-1,0)),0) AS value
                FROM operation_jobs WHERE tenant_id=%s""", (tenant_id,)).fetchone()["value"]
            terminal_rows = connection.execute("""SELECT created_at,updated_at,state FROM operation_jobs
                WHERE tenant_id=%s AND state IN ('COMPLETED','FAILED','CANCELLED')""",
                (tenant_id,)).fetchall()
        durations = [(row["updated_at"] - row["created_at"]).total_seconds() for row in terminal_rows]
        failures = sum(row["state"] == JobState.FAILED.value for row in terminal_rows)
        return {"tenant_id": tenant_id, "counts": counts,
            "oldest_queued_age_seconds": (now - oldest).total_seconds() if oldest else None,
            "lease_expired_jobs": expired, "fresh_workers": workers,
            "operational_database": "ready", "multi_worker_supported": True,
            "retry_count": retry_count,
            "failure_rate": failures / len(terminal_rows) if terminal_rows else 0.0,
            "mean_terminal_latency_seconds": sum(durations) / len(durations) if durations else None,
            "reconciliation_backlog": counts.get(JobState.NEEDS_RECONCILIATION.value, 0)}

    def ping(self) -> bool:
        try:
            with self._pool.connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._pool.close()
