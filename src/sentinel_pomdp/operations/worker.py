"""Cooperative durable job worker with leases, fencing, and replay journals."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import logging
from threading import Event
from time import monotonic
from typing import Any, Callable, Mapping
from uuid import uuid4

from .models import (
    CancellationRequested, JobClaim, LeaseLost, OperationError, OperationType,
    RetryableOperationError, UncertainOperationError,
)
from .repository import OperationRepository

logger = logging.getLogger(__name__)
JobHandler = Callable[["OperationContext", dict[str, Any]], dict[str, Any]]


@dataclass
class OperationContext:
    repository: OperationRepository
    claim: JobClaim
    lease_seconds: float

    def safe_boundary(self, progress: dict[str, Any] | None = None) -> None:
        """Renew ownership and honor cancellation between atomic side effects."""
        if self.repository.cancellation_requested(self.claim):
            raise CancellationRequested()
        if progress is not None:
            self.repository.update_progress(self.claim, progress)
        self.repository.heartbeat(self.claim, lease_seconds=self.lease_seconds)

    def journaled_step(
        self,
        step_key: str,
        input_value: dict[str, Any],
        action: Callable[[], dict[str, Any]],
        *,
        resume_started: bool = False,
    ) -> dict[str, Any]:
        """Replay a completed step or record a new one under the current fence."""
        encoded = json.dumps(input_value, sort_keys=True, separators=(",", ":"))
        fingerprint = sha256(encoded.encode("utf-8")).hexdigest()
        existing = self.repository.journal_get(self.claim.job.job_id, step_key)
        if existing:
            if existing["input_fingerprint"] != fingerprint:
                raise UncertainOperationError(
                    "JOURNAL_INPUT_CONFLICT", "step input changed during recovery")
            if existing["state"] == "COMPLETED":
                return json.loads(existing["result_json"] or "{}")
            if not resume_started:
                # STARTED means an external side effect may have happened.
                raise UncertainOperationError(
                    "STEP_OUTCOME_UNCERTAIN", "an interrupted side effect needs reconciliation")
        self.safe_boundary()
        self.repository.journal_put(
            self.claim, step_key, "STARTED", fingerprint, None)
        result = action()
        self.repository.journal_put(
            self.claim, step_key, "COMPLETED", fingerprint, result)
        self.safe_boundary()
        return result


class DurableWorker:
    def __init__(
        self,
        repository: OperationRepository,
        handlers: Mapping[OperationType, JobHandler],
        *,
        worker_id: str | None = None,
        lease_seconds: float = 30,
        retry_backoff_seconds: float = 1,
    ) -> None:
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        self.repository = repository
        self.handlers = dict(handlers)
        self.worker_id = worker_id or f"worker-{uuid4()}"
        self.lease_seconds = lease_seconds
        self.retry_backoff_seconds = retry_backoff_seconds

    def run_once(self) -> bool:
        self.repository.heartbeat_worker(self.worker_id, {"mode": "durable"})
        claim = self.repository.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if claim is None:
            return False
        context = OperationContext(self.repository, claim, self.lease_seconds)
        handler = self.handlers.get(claim.job.operation_type)
        if handler is None:
            self.repository.fail(claim, "HANDLER_NOT_CONFIGURED", retryable=False)
            return True
        try:
            context.safe_boundary({"phase": "started"})
            result = handler(context, claim.job.payload)
            context.safe_boundary({"phase": "finalizing"})
            self.repository.complete(claim, result)
        except CancellationRequested:
            self.repository.cancel_claim(claim)
        except RetryableOperationError as exc:
            self.repository.fail(
                claim, exc.code, retryable=True,
                backoff_seconds=self.retry_backoff_seconds)
        except UncertainOperationError as exc:
            self.repository.fail(claim, exc.code, retryable=False, uncertain=True)
        except LeaseLost:
            # A newer fencing token owns the job. The stale worker must not write.
            logger.warning("worker lease lost", extra={"job_id": claim.job.job_id})
        except OperationError as exc:
            self.repository.fail(claim, exc.code, retryable=False)
        except Exception:
            logger.exception("durable job failed", extra={"job_id": claim.job.job_id})
            self.repository.fail(claim, "UNHANDLED_OPERATION_FAILURE", retryable=False)
        return True

    def run(self, stop: Event, *, poll_seconds: float = .25) -> None:
        if poll_seconds < .01:
            raise ValueError("poll_seconds must be at least 0.01")
        while not stop.is_set():
            started = monotonic()
            worked = self.run_once()
            if not worked:
                stop.wait(max(.01, poll_seconds - (monotonic() - started)))
