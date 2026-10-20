"""Transactional durable-operation repositories."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Iterator
from uuid import uuid4

from .models import (
    IdempotencyConflict, JobClaim, JobState, LeaseLost, NewOperationJob,
    OperationAuditEvent, OperationJob, OperationType, canonical_payload, utc_now,
)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value,datetime): return value
    parsed=datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class OperationRepository(ABC):
    supports_multi_worker: bool = False

    @abstractmethod
    def create_job(self, request: NewOperationJob) -> tuple[OperationJob,bool]: ...
    @abstractmethod
    def get_job(self, tenant_id: str, job_id: str) -> OperationJob | None: ...
    @abstractmethod
    def list_jobs(self, tenant_id: str, *, limit: int=100) -> list[OperationJob]: ...
    @abstractmethod
    def claim(self, worker_id: str, *, lease_seconds: float=30) -> JobClaim | None: ...
    @abstractmethod
    def heartbeat(self, claim: JobClaim, *, lease_seconds: float=30) -> OperationJob: ...
    @abstractmethod
    def update_progress(self, claim: JobClaim, progress: dict[str,Any]) -> OperationJob: ...
    @abstractmethod
    def complete(self, claim: JobClaim, result: dict[str,Any]) -> OperationJob: ...
    @abstractmethod
    def fail(self, claim: JobClaim, code: str, *, retryable: bool,
             uncertain: bool=False, backoff_seconds: float=1) -> OperationJob: ...
    @abstractmethod
    def request_cancel(self, tenant_id: str, job_id: str) -> OperationJob | None: ...
    @abstractmethod
    def emit_audit(self,event:OperationAuditEvent) -> None: ...
    @abstractmethod
    def summary(self, tenant_id: str, *, stale_worker_seconds: float=60) -> dict[str,Any]: ...
    @abstractmethod
    def close(self) -> None: ...


class SQLiteOperationRepository(OperationRepository):
    """Durable local backend. Serialized claims make this a single-worker mode."""
    supports_multi_worker=False

    def __init__(self,path: str | Path) -> None:
        self.path=Path(path).resolve()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self._lock=RLock()
        self._connection=sqlite3.connect(str(self.path),check_same_thread=False,isolation_level=None)
        self._connection.row_factory=sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    @contextmanager
    def _transaction(self, *, immediate: bool=False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback(); raise
            else:
                self._connection.commit()

    def migrate(self) -> None:
        migration=Path(__file__).with_name("migrations")/"001_initial_sqlite.sql"
        with self._lock:
            self._connection.executescript(migration.read_text(encoding="utf-8"))
            self._connection.execute(
                "INSERT OR IGNORE INTO operation_schema_version(version,applied_at) VALUES(1,?)",
                (_iso(utc_now()),))

    @staticmethod
    def _job(row: sqlite3.Row) -> OperationJob:
        return OperationJob(job_id=row["job_id"],tenant_id=row["tenant_id"],
            principal_id=row["principal_id"],operation_type=OperationType(row["operation_type"]),
            state=JobState(row["state"]),created_at=_dt(row["created_at"]),updated_at=_dt(row["updated_at"]),
            attempt_count=row["attempt_count"],correlation_id=row["correlation_id"],
            idempotency_key=row["idempotency_key"],input_fingerprint=row["input_fingerprint"],
            payload=json.loads(row["payload_json"]),progress=json.loads(row["progress_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_code=row["error_code"],lease_owner=row["lease_owner"],
            lease_expires_at=_dt(row["lease_expires_at"]),fencing_token=row["fencing_token"],
            max_retries=row["max_retries"],replay_safe=bool(row["replay_safe"]),
            cancellation_requested=bool(row["cancellation_requested"]),not_before=_dt(row["not_before"]))

    def _audit(self,conn:sqlite3.Connection, *, operation:str,outcome:str,reason:str,
               correlation_id:str,tenant_id:str|None=None,principal_id:str|None=None,
               resource_id:str|None=None) -> None:
        conn.execute("""INSERT OR IGNORE INTO operation_audit
            (event_id,occurred_at,operation,outcome,reason_code,correlation_id,tenant_id,principal_id,resource_id)
            VALUES(?,?,?,?,?,?,?,?,?)""",(str(uuid4()),_iso(utc_now()),operation,outcome,reason,
                correlation_id,tenant_id,principal_id,resource_id))

    def create_job(self,request:NewOperationJob) -> tuple[OperationJob,bool]:
        request.validate(); payload,fingerprint=canonical_payload(request.payload); now=utc_now()
        with self._transaction(immediate=True) as conn:
            if request.idempotency_key:
                existing=conn.execute("""SELECT * FROM operation_jobs WHERE tenant_id=? AND principal_id=?
                    AND operation_type=? AND idempotency_key=?""",(request.tenant_id,request.principal_id,
                    request.operation_type.value,request.idempotency_key)).fetchone()
                if existing:
                    if existing["input_fingerprint"]!=fingerprint: raise IdempotencyConflict()
                    return self._job(existing),False
            job_id=str(uuid4())
            conn.execute("""INSERT INTO operation_jobs
                (job_id,tenant_id,principal_id,operation_type,state,created_at,updated_at,attempt_count,
                 correlation_id,idempotency_key,input_fingerprint,payload_json,progress_json,max_retries,replay_safe)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(job_id,request.tenant_id,request.principal_id,
                request.operation_type.value,JobState.QUEUED.value,_iso(now),_iso(now),0,
                request.correlation_id,request.idempotency_key,fingerprint,payload,"{}",
                request.max_retries,int(request.replay_safe)))
            self._audit(conn,operation="job.created",outcome="ACCEPTED",reason="QUEUED",
                correlation_id=request.correlation_id,tenant_id=request.tenant_id,
                principal_id=request.principal_id,resource_id=job_id)
            return self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",(job_id,)).fetchone()),True

    def get_job(self,tenant_id:str,job_id:str) -> OperationJob|None:
        with self._lock:
            row=self._connection.execute("SELECT * FROM operation_jobs WHERE tenant_id=? AND job_id=?",
                (tenant_id,job_id)).fetchone()
            return self._job(row) if row else None

    def list_jobs(self,tenant_id:str,*,limit:int=100) -> list[OperationJob]:
        limit=max(1,min(limit,500))
        with self._lock:
            rows=self._connection.execute("SELECT * FROM operation_jobs WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
                (tenant_id,limit)).fetchall()
            return [self._job(row) for row in rows]

    def _recover_expired(self,conn:sqlite3.Connection,now:datetime) -> None:
        rows=conn.execute("""SELECT * FROM operation_jobs WHERE state IN (?,?)
            AND lease_expires_at IS NOT NULL AND lease_expires_at < ?""",
            (JobState.RUNNING.value,JobState.CANCEL_REQUESTED.value,_iso(now))).fetchall()
        for row in rows:
            job=self._job(row)
            if job.state is JobState.CANCEL_REQUESTED:
                state=JobState.NEEDS_RECONCILIATION; code="CANCELLED_WORKER_LOST"
            elif job.replay_safe and job.attempt_count<=job.max_retries:
                state=JobState.RETRY_WAIT; code="LEASE_EXPIRED"
            else:
                state=JobState.NEEDS_RECONCILIATION; code="LEASE_EXPIRED_UNCERTAIN"
            conn.execute("""UPDATE operation_jobs SET state=?,updated_at=?,error_code=?,lease_owner=NULL,
                lease_expires_at=NULL,not_before=? WHERE job_id=?""",(state.value,_iso(now),code,
                _iso(now) if state is JobState.RETRY_WAIT else None,job.job_id))
            self._audit(conn,operation="job.lease_expired",outcome=state.value,reason=code,
                correlation_id=job.correlation_id,tenant_id=job.tenant_id,
                principal_id=job.principal_id,resource_id=job.job_id)

    def claim(self,worker_id:str,*,lease_seconds:float=30) -> JobClaim|None:
        if not worker_id.strip() or not 1<=lease_seconds<=3600: raise ValueError("invalid worker lease")
        now=utc_now(); expires=now+timedelta(seconds=lease_seconds)
        with self._transaction(immediate=True) as conn:
            self._recover_expired(conn,now)
            row=conn.execute("""SELECT * FROM operation_jobs WHERE state IN (?,?)
                AND (not_before IS NULL OR not_before<=?) ORDER BY created_at LIMIT 1""",
                (JobState.QUEUED.value,JobState.RETRY_WAIT.value,_iso(now))).fetchone()
            if not row: return None
            token=row["fencing_token"]+1
            changed=conn.execute("""UPDATE operation_jobs SET state=?,updated_at=?,attempt_count=attempt_count+1,
                lease_owner=?,lease_expires_at=?,fencing_token=?,error_code=NULL,not_before=NULL
                WHERE job_id=? AND fencing_token=? AND state IN (?,?)""",(JobState.RUNNING.value,_iso(now),
                worker_id,_iso(expires),token,row["job_id"],row["fencing_token"],
                JobState.QUEUED.value,JobState.RETRY_WAIT.value)).rowcount
            if changed!=1: return None
            claimed=self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",(row["job_id"],)).fetchone())
            self._audit(conn,operation="job.claimed",outcome="RUNNING",reason="CLAIMED",
                correlation_id=claimed.correlation_id,tenant_id=claimed.tenant_id,
                principal_id=claimed.principal_id,resource_id=claimed.job_id)
            return JobClaim(claimed,worker_id,token)

    def _owned_update(self,claim:JobClaim,sql:str,parameters:tuple[Any,...]) -> OperationJob:
        with self._transaction(immediate=True) as conn:
            changed=conn.execute(sql,parameters+(claim.job.job_id,claim.worker_id,claim.fencing_token)).rowcount
            if changed!=1: raise LeaseLost()
            return self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",
                (claim.job.job_id,)).fetchone())

    def heartbeat(self,claim:JobClaim,*,lease_seconds:float=30) -> OperationJob:
        now=utc_now(); return self._owned_update(claim,"""UPDATE operation_jobs SET updated_at=?,lease_expires_at=?
            WHERE job_id=? AND lease_owner=? AND fencing_token=? AND state IN ('RUNNING','CANCEL_REQUESTED')""",
            (_iso(now),_iso(now+timedelta(seconds=lease_seconds))))

    def update_progress(self,claim:JobClaim,progress:dict[str,Any]) -> OperationJob:
        payload,_=canonical_payload(progress)
        return self._owned_update(claim,"""UPDATE operation_jobs SET updated_at=?,progress_json=?
            WHERE job_id=? AND lease_owner=? AND fencing_token=? AND state IN ('RUNNING','CANCEL_REQUESTED')""",
            (_iso(utc_now()),payload))

    def complete(self,claim:JobClaim,result:dict[str,Any]) -> OperationJob:
        payload,_=canonical_payload(result); now=utc_now()
        with self._transaction(immediate=True) as conn:
            changed=conn.execute("""UPDATE operation_jobs SET state=?,updated_at=?,result_json=?,error_code=NULL,
                lease_owner=NULL,lease_expires_at=NULL,cancellation_requested=0 WHERE job_id=? AND lease_owner=?
                AND fencing_token=? AND state IN ('RUNNING','CANCEL_REQUESTED')""",
                (JobState.COMPLETED.value,_iso(now),payload,claim.job.job_id,claim.worker_id,claim.fencing_token)).rowcount
            if changed!=1: raise LeaseLost()
            job=self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",(claim.job.job_id,)).fetchone())
            self._audit(conn,operation="job.completed",outcome="COMPLETED",reason="RESULT_PERSISTED",
                correlation_id=job.correlation_id,tenant_id=job.tenant_id,principal_id=job.principal_id,resource_id=job.job_id)
            return job

    def fail(self,claim:JobClaim,code:str,*,retryable:bool,uncertain:bool=False,
             backoff_seconds:float=1) -> OperationJob:
        now=utc_now(); current=self.get_job(claim.job.tenant_id,claim.job.job_id)
        if current is None: raise LeaseLost()
        if uncertain: state=JobState.NEEDS_RECONCILIATION
        elif retryable and current.replay_safe and current.attempt_count<=current.max_retries:
            state=JobState.RETRY_WAIT
        else: state=JobState.FAILED
        not_before=now+timedelta(seconds=max(0,min(backoff_seconds,3600))) if state is JobState.RETRY_WAIT else None
        with self._transaction(immediate=True) as conn:
            changed=conn.execute("""UPDATE operation_jobs SET state=?,updated_at=?,error_code=?,lease_owner=NULL,
                lease_expires_at=NULL,not_before=? WHERE job_id=? AND lease_owner=? AND fencing_token=?
                AND state IN ('RUNNING','CANCEL_REQUESTED')""",(state.value,_iso(now),code,_iso(not_before),
                claim.job.job_id,claim.worker_id,claim.fencing_token)).rowcount
            if changed!=1: raise LeaseLost()
            job=self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",(claim.job.job_id,)).fetchone())
            self._audit(conn,operation="job.failed",outcome=state.value,reason=code,
                correlation_id=job.correlation_id,tenant_id=job.tenant_id,principal_id=job.principal_id,resource_id=job.job_id)
            return job

    def request_cancel(self,tenant_id:str,job_id:str) -> OperationJob|None:
        now=utc_now()
        with self._transaction(immediate=True) as conn:
            row=conn.execute("SELECT * FROM operation_jobs WHERE tenant_id=? AND job_id=?",
                (tenant_id,job_id)).fetchone()
            if not row:return None
            job=self._job(row)
            if job.state in {JobState.QUEUED,JobState.RETRY_WAIT}:
                state=JobState.CANCELLED
            elif job.state is JobState.RUNNING:
                state=JobState.CANCEL_REQUESTED
            else:return job
            conn.execute("UPDATE operation_jobs SET state=?,updated_at=?,cancellation_requested=1 WHERE job_id=?",
                (state.value,_iso(now),job_id))
            self._audit(conn,operation="job.cancel_requested",outcome=state.value,reason="USER_REQUEST",
                correlation_id=job.correlation_id,tenant_id=job.tenant_id,principal_id=job.principal_id,resource_id=job.job_id)
            return self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",(job_id,)).fetchone())

    def cancellation_requested(self,claim:JobClaim) -> bool:
        current=self.get_job(claim.job.tenant_id,claim.job.job_id)
        if current is None or current.fencing_token!=claim.fencing_token or current.lease_owner!=claim.worker_id:
            raise LeaseLost()
        return current.cancellation_requested or current.state is JobState.CANCEL_REQUESTED

    def cancel_claim(self,claim:JobClaim) -> OperationJob:
        now=utc_now()
        with self._transaction(immediate=True) as conn:
            changed=conn.execute("""UPDATE operation_jobs SET state='CANCELLED',updated_at=?,
                lease_owner=NULL,lease_expires_at=NULL,error_code='CANCELLED_AT_SAFE_BOUNDARY'
                WHERE job_id=? AND lease_owner=? AND fencing_token=? AND state='CANCEL_REQUESTED'""",
                (_iso(now),claim.job.job_id,claim.worker_id,claim.fencing_token)).rowcount
            if changed!=1: raise LeaseLost()
            job=self._job(conn.execute("SELECT * FROM operation_jobs WHERE job_id=?",
                (claim.job.job_id,)).fetchone())
            self._audit(conn,operation="job.cancelled",outcome="CANCELLED",
                reason="SAFE_BOUNDARY",correlation_id=job.correlation_id,
                tenant_id=job.tenant_id,principal_id=job.principal_id,resource_id=job.job_id)
            return job

    def journal_get(self,job_id:str,step_key:str) -> dict[str,Any]|None:
        with self._lock:
            row=self._connection.execute("SELECT * FROM operation_journal WHERE job_id=? AND step_key=?",
                (job_id,step_key)).fetchone()
            return dict(row) if row else None

    def journal_put(self,claim:JobClaim,step_key:str,state:str,input_fingerprint:str,
                    result:dict[str,Any]|None=None) -> None:
        current=self.get_job(claim.job.tenant_id,claim.job.job_id)
        if current is None or current.lease_owner!=claim.worker_id or current.fencing_token!=claim.fencing_token:
            raise LeaseLost()
        result_json=json.dumps(result,sort_keys=True,separators=(",",":")) if result is not None else None
        with self._transaction(immediate=True) as conn:
            conn.execute("""INSERT INTO operation_journal(job_id,step_key,state,input_fingerprint,result_json,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(job_id,step_key) DO UPDATE SET state=excluded.state,
                input_fingerprint=excluded.input_fingerprint,result_json=excluded.result_json,updated_at=excluded.updated_at""",
                (claim.job.job_id,step_key,state,input_fingerprint,result_json,_iso(utc_now())))

    def emit_audit(self,event:OperationAuditEvent) -> None:
        with self._transaction(immediate=True) as conn:
            conn.execute("""INSERT OR IGNORE INTO operation_audit
                (event_id,occurred_at,operation,outcome,reason_code,correlation_id,tenant_id,principal_id,resource_id)
                VALUES(?,?,?,?,?,?,?,?,?)""",(event.event_id,_iso(event.occurred_at),event.operation,event.outcome,
                event.reason_code,event.correlation_id,event.tenant_id,event.principal_id,event.resource_id))

    def list_audit(self,tenant_id:str,*,limit:int=100) -> list[dict[str,Any]]:
        with self._lock:
            return [dict(row) for row in self._connection.execute(
                "SELECT * FROM operation_audit WHERE tenant_id=? ORDER BY occurred_at DESC LIMIT ?",
                (tenant_id,max(1,min(limit,500)))).fetchall()]

    def heartbeat_worker(self,worker_id:str,metadata:dict[str,Any]|None=None) -> None:
        now=_iso(utc_now()); encoded,_=canonical_payload(metadata or {})
        with self._transaction(immediate=True) as conn:
            conn.execute("""INSERT INTO worker_heartbeats(worker_id,heartbeat_at,started_at,metadata_json)
                VALUES(?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at,
                metadata_json=excluded.metadata_json""",(worker_id,now,now,encoded))

    def put_checkpoint(self, *, workflow_id:str,tenant_id:str,principal_id:str,scenario_id:str,
                       model_version:str,sequence:int,phase:str,state:dict[str,Any]) -> None:
        encoded,fingerprint=canonical_payload(state)
        with self._transaction(immediate=True) as conn:
            conn.execute("""INSERT INTO workflow_checkpoints(workflow_id,tenant_id,principal_id,scenario_id,
                model_version,sequence,phase,state_json,state_fingerprint,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (workflow_id,tenant_id,principal_id,scenario_id,model_version,sequence,phase,encoded,
                fingerprint,_iso(utc_now())))

    def latest_checkpoint(self,tenant_id:str,workflow_id:str) -> dict[str,Any]|None:
        with self._lock:
            row=self._connection.execute("""SELECT * FROM workflow_checkpoints WHERE tenant_id=?
                AND workflow_id=? ORDER BY sequence DESC LIMIT 1""",(tenant_id,workflow_id)).fetchone()
            if not row:return None
            result=dict(row); result["state"]=json.loads(result.pop("state_json")); return result

    def summary(self,tenant_id:str,*,stale_worker_seconds:float=60) -> dict[str,Any]:
        now=utc_now(); stale=_iso(now-timedelta(seconds=stale_worker_seconds))
        with self._lock:
            counts={row["state"]:row["count"] for row in self._connection.execute(
                "SELECT state,count(*) AS count FROM operation_jobs WHERE tenant_id=? GROUP BY state",
                (tenant_id,)).fetchall()}
            oldest=self._connection.execute("SELECT MIN(created_at) AS value FROM operation_jobs WHERE tenant_id=? AND state='QUEUED'",
                (tenant_id,)).fetchone()["value"]
            expired=self._connection.execute("SELECT count(*) AS value FROM operation_jobs WHERE tenant_id=? AND state IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at<?",
                (tenant_id,_iso(now))).fetchone()["value"]
            workers=self._connection.execute("SELECT count(*) AS value FROM worker_heartbeats WHERE heartbeat_at>=?",
                (stale,)).fetchone()["value"]
            retry_count=self._connection.execute(
                "SELECT COALESCE(SUM(MAX(attempt_count-1,0)),0) AS value FROM operation_jobs WHERE tenant_id=?",
                (tenant_id,)).fetchone()["value"]
            terminal_rows=self._connection.execute("""SELECT created_at,updated_at,state FROM operation_jobs
                WHERE tenant_id=? AND state IN ('COMPLETED','FAILED','CANCELLED')""",
                (tenant_id,)).fetchall()
        oldest_age=(now-_dt(oldest)).total_seconds() if oldest else None
        durations=[(_dt(row["updated_at"])-_dt(row["created_at"])).total_seconds()
                   for row in terminal_rows]
        failures=sum(row["state"] == JobState.FAILED.value for row in terminal_rows)
        return {"tenant_id":tenant_id,"counts":counts,"oldest_queued_age_seconds":oldest_age,
            "lease_expired_jobs":expired,"fresh_workers":workers,"operational_database":"ready",
            "multi_worker_supported":self.supports_multi_worker,"retry_count":retry_count,
            "failure_rate":failures/len(terminal_rows) if terminal_rows else 0.0,
            "mean_terminal_latency_seconds":sum(durations)/len(durations) if durations else None,
            "reconciliation_backlog":counts.get(JobState.NEEDS_RECONCILIATION.value,0)}

    def ping(self) -> bool:
        try:
            with self._lock:self._connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:return False

    def close(self) -> None:
        with self._lock:self._connection.close()
