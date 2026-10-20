"""Durable operational records; payloads contain references, never credentials."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class OperationType(str, Enum):
    DOCUMENT_INGESTION = "DOCUMENT_INGESTION"
    OLIST_BATCH = "OLIST_BATCH"
    INVESTIGATION = "INVESTIGATION"
    EVALUATION = "EVALUATION"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    DOMAIN_INVESTIGATION = "DOMAIN_INVESTIGATION"


TERMINAL_STATES = frozenset({
    JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED,
})

FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "api_key", "authorization", "credential", "credentials", "password",
    "secret", "token", "openai_api_key", "groq_api_key", "neo4j_password",
})


class OperationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IdempotencyConflict(OperationError):
    def __init__(self) -> None:
        super().__init__("IDEMPOTENCY_CONFLICT",
            "the idempotency key is already bound to a different request")


class LeaseLost(OperationError):
    def __init__(self) -> None:
        super().__init__("LEASE_LOST", "worker lease or fencing token is no longer current")


class CancellationRequested(OperationError):
    def __init__(self) -> None:
        super().__init__("CANCEL_REQUESTED", "cooperative cancellation was requested")


class RetryableOperationError(OperationError):
    """A bounded transient failure whose handler is explicitly replay-safe."""


class UncertainOperationError(OperationError):
    """A failure after a side effect whose outcome must be reconciled by an operator."""


def _validate_value(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized=str(key).strip().lower()
            if normalized in FORBIDDEN_PAYLOAD_KEYS or normalized.endswith("_password"):
                raise OperationError("SECRET_IN_PAYLOAD", f"{path}.{key} is not permitted")
            _validate_value(child,f"{path}.{key}")
    elif isinstance(value, (list,tuple)):
        for index,child in enumerate(value): _validate_value(child,f"{path}[{index}]")


def canonical_payload(payload: dict[str, Any]) -> tuple[str,str]:
    _validate_value(payload)
    encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 256_000:
        raise OperationError("PAYLOAD_TOO_LARGE","job payload exceeds 256000 bytes")
    return encoded,sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NewOperationJob:
    tenant_id: str
    principal_id: str
    operation_type: OperationType
    correlation_id: str
    payload: dict[str, Any]
    idempotency_key: str | None = None
    max_retries: int = 2
    replay_safe: bool = False

    def validate(self) -> None:
        if not self.tenant_id.strip() or not self.principal_id.strip():
            raise OperationError("INVALID_SCOPE","tenant and principal are required")
        if self.idempotency_key is not None and not 1 <= len(self.idempotency_key) <= 200:
            raise OperationError("INVALID_IDEMPOTENCY_KEY","idempotency key must contain 1-200 characters")
        if not 0 <= self.max_retries <= 10:
            raise OperationError("INVALID_RETRY_LIMIT","max_retries must be between 0 and 10")
        canonical_payload(self.payload)


@dataclass(frozen=True)
class OperationJob:
    job_id: str
    tenant_id: str
    principal_id: str
    operation_type: OperationType
    state: JobState
    created_at: datetime
    updated_at: datetime
    attempt_count: int
    correlation_id: str
    idempotency_key: str | None
    input_fingerprint: str
    payload: dict[str, Any]
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_code: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    fencing_token: int = 0
    max_retries: int = 2
    replay_safe: bool = False
    cancellation_requested: bool = False
    not_before: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id":self.job_id,"tenant_id":self.tenant_id,
            "principal_id":self.principal_id,"operation_type":self.operation_type.value,
            "state":self.state.value,"created_at":self.created_at.isoformat(),
            "updated_at":self.updated_at.isoformat(),"attempt_count":self.attempt_count,
            "correlation_id":self.correlation_id,"progress":self.progress,
            "result":self.result,"error_code":self.error_code,
            "lease_expires_at":self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "max_retries":self.max_retries,"cancellation_requested":self.cancellation_requested,
        }


@dataclass(frozen=True)
class JobClaim:
    job: OperationJob
    worker_id: str
    fencing_token: int


@dataclass(frozen=True)
class OperationAuditEvent:
    event_id: str
    occurred_at: datetime
    operation: str
    outcome: str
    reason_code: str
    correlation_id: str
    tenant_id: str | None = None
    principal_id: str | None = None
    resource_id: str | None = None
